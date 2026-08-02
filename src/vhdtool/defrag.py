"""Disk defragmentation via copy to new image.

Creates a new image with all files laid out sequentially (defragmented).
This approach is safe - original image is preserved, no in-place modifications.
"""

import os
import struct
from typing import BinaryIO, Iterator, Optional, Callable

from .fat import BPB, DirEntry, FATType, _make_dos_datetime
from .image import VHDImage
from .utils import calculate_fat16_params, create_mbr, create_fat16_boot_sector


class DefragmentedImage:
    """Creates a defragmented copy of a FAT filesystem."""

    def __init__(self, source_path: str, dest_path: str,
                 new_size: Optional[int] = None,
                 progress_callback: Optional[Callable[[str, int, int], None]] = None):
        """
        Initialize defragmentation.

        Args:
            source_path: Path to source image
            dest_path: Path to destination image (will be created)
            new_size: Optional new size in bytes (None = same as source)
            progress_callback: Optional callback(phase, current, total)
        """
        self.source_path = source_path
        self.dest_path = dest_path
        self.new_size = new_size
        self.progress = progress_callback or (lambda *_: None)

        # State
        self.source: Optional[VHDImage] = None
        self.dest_file: Optional[BinaryIO] = None
        self.dest_bpb: Optional[BPB] = None
        self.next_cluster: int = 2
        self.files_copied: int = 0
        self.bytes_copied: int = 0

        # Buffering for fast sequential writes
        self.write_buffer: bytearray = bytearray()
        self.buffer_start_sector: int = 0
        self.buffer_size: int = 1024 * 1024  # 1MB buffer

    def defragment(self) -> dict:
        """
        Perform defragmentation.

        Returns dict with statistics:
            - files_copied: Number of files copied
            - bytes_copied: Total bytes copied
            - source_clusters: Clusters used in source
            - dest_clusters: Clusters used in destination
            - fragmentation_before: Fragmentation ratio (0-1) before
            - fragmentation_after: Fragmentation ratio (0-1) after (should be 0)
        """
        if os.path.exists(self.dest_path):
            raise FileExistsError(f"Destination already exists: {self.dest_path}")

        with VHDImage(self.source_path) as self.source:
            stats_before = self.source.get_filesystem_stats()
            frag_before = self._calculate_fragmentation()

            # Determine destination size
            source_size = os.path.getsize(self.source_path)
            if self.new_size is None:
                dest_size = source_size
            else:
                dest_size = (self.new_size // 512) * 512

            # Validate shrink is possible
            if dest_size < source_size:
                self._validate_shrink(dest_size, stats_before)

            # Create destination image
            self._create_destination(dest_size)

            try:
                # Copy boot sector (preserving bootability)
                self._copy_boot_sector()

                # Copy all files recursively
                self._copy_directory("/", is_root=True)

                # Flush any remaining buffer
                self._flush_buffer()

                # Finalize FAT tables
                self._finalize_fat()

            except Exception:
                # Clean up on failure
                if self.dest_file:
                    self.dest_file.close()
                if os.path.exists(self.dest_path):
                    os.remove(self.dest_path)
                raise

            finally:
                if self.dest_file:
                    self.dest_file.close()

        # Verify result
        with VHDImage(self.dest_path) as dest:
            stats_after = dest.get_filesystem_stats()

        return {
            'files_copied': self.files_copied,
            'bytes_copied': self.bytes_copied,
            'source_clusters': stats_before['used_clusters'],
            'dest_clusters': stats_after['used_clusters'],
            'fragmentation_before': frag_before,
            'fragmentation_after': 0.0,  # By construction
        }

    def _validate_shrink(self, dest_size: int, stats: dict) -> None:
        """Validate that shrinking to dest_size is possible."""
        from .utils import format_size, calculate_fat16_params

        source_size = os.path.getsize(self.source_path)
        dest_sectors = dest_size // 512
        part_start = 63  # Standard partition offset

        # Check minimum FAT16 size
        min_fat16_sectors = 4085 + part_start
        min_fat16_size = min_fat16_sectors * 512

        if dest_size < min_fat16_size:
            raise ValueError(
                f"Cannot shrink to {format_size(dest_size)}: "
                f"minimum FAT16 size is {format_size(min_fat16_size)}"
            )

        # Calculate space needed for data
        used_bytes = stats['used_bytes']
        # Add overhead: reserved sectors, FAT tables, root directory
        dest_part_sectors = dest_sectors - part_start
        try:
            params = calculate_fat16_params(dest_part_sectors)
        except ValueError as e:
            raise ValueError(f"Cannot shrink to {format_size(dest_size)}: {e}")

        overhead_sectors = (params['reserved_sectors'] +
                          params['num_fats'] * params['fat_size'] +
                          (params['root_entries'] * 32 + 511) // 512)
        available_data_sectors = dest_part_sectors - overhead_sectors
        available_bytes = available_data_sectors * 512

        if used_bytes > available_bytes:
            shortage = used_bytes - available_bytes
            raise ValueError(
                f"Cannot shrink to {format_size(dest_size)}: data would not fit.\n"
                f"  Current data size: {format_size(used_bytes)}\n"
                f"  Available in target: {format_size(available_bytes)}\n"
                f"  Shortage: {format_size(shortage)}\n"
                f"  Minimum target size: ~{format_size(dest_size + shortage + 1024*1024)}"
            )

    def _calculate_fragmentation(self) -> float:
        """Calculate fragmentation ratio (0 = defragmented, 1 = maximally fragmented)."""
        total_files = 0
        fragmented_files = 0

        for entry in self._walk_all_entries("/"):
            if not entry.is_directory and not entry.is_volume_label and entry.size > 0:
                total_files += 1
                chain = self.source._get_cluster_chain(entry.first_cluster)
                if len(chain) > 1:
                    # Check if clusters are sequential
                    for i in range(len(chain) - 1):
                        if chain[i+1] != chain[i] + 1:
                            fragmented_files += 1
                            break

        return fragmented_files / total_files if total_files > 0 else 0.0

    def _walk_all_entries(self, path: str) -> Iterator[DirEntry]:
        """Walk all directory entries recursively."""
        try:
            entries = self.source.list_dir(path)
        except Exception:
            return

        for entry in entries:
            if entry.name.startswith('.'):
                continue
            yield entry
            if entry.is_directory:
                subpath = f"{path.rstrip('/')}/{entry.full_name}"
                yield from self._walk_all_entries(subpath)

    def _create_destination(self, size: int):
        """Create destination image with formatted filesystem."""
        total_sectors = size // 512
        part_start = 63
        part_sectors = total_sectors - part_start

        # Calculate FAT parameters
        params = calculate_fat16_params(part_sectors)

        # Create and write MBR
        mbr = create_mbr(total_sectors, bootable=True)

        self.dest_file = open(self.dest_path, 'w+b')
        self.dest_file.write(mbr)

        # Write VBR (will be replaced with source's boot code)
        vbr = create_fat16_boot_sector(params, volume_label="DEFRAG", hidden_sectors=part_start)
        self.dest_file.seek(part_start * 512)
        self.dest_file.write(vbr)

        # Initialize FAT tables
        fat_start = part_start + params['reserved_sectors']
        fat_size = params['fat_size']

        # FAT with reserved entries
        fat = bytearray(fat_size * 512)
        fat[0:4] = b'\xF8\xFF\xFF\xFF'

        for i in range(params['num_fats']):
            self.dest_file.seek((fat_start + i * fat_size) * 512)
            self.dest_file.write(fat)

        # Initialize root directory
        root_start = fat_start + params['num_fats'] * fat_size
        root_sectors = (params['root_entries'] * 32 + 511) // 512
        self.dest_file.seek(root_start * 512)
        self.dest_file.write(b'\x00' * root_sectors * 512)

        # Extend file to full size
        self.dest_file.seek(size - 1)
        self.dest_file.write(b'\x00')

        # Store parameters for later use
        self.dest_params = params
        self.dest_part_start = part_start
        self.dest_fat_start = fat_start
        self.dest_fat_size = fat_size
        self.dest_num_fats = params['num_fats']
        self.dest_root_start = root_start
        self.dest_root_sectors = root_sectors
        self.dest_root_entries = params['root_entries']
        self.dest_sectors_per_cluster = params['sectors_per_cluster']
        self.dest_cluster_size = params['sectors_per_cluster'] * 512
        self.dest_data_start = root_start + root_sectors

        # FAT table in memory for fast updates
        self.dest_fat = bytearray(fat)

    def _copy_boot_sector(self):
        """Copy boot code from source, preserving bootability."""
        # Read source VBR
        source_vbr = self.source._read_sector(self.source.partition_offset)

        # Read destination VBR (has correct BPB for new size)
        self.dest_file.seek(self.dest_part_start * 512)
        dest_vbr = bytearray(self.dest_file.read(512))

        # Copy boot code from source (bytes 0-2 jump, 62-509 code)
        dest_vbr[0:3] = source_vbr[0:3]    # Jump instruction
        dest_vbr[62:510] = source_vbr[62:510]  # Boot code

        # Copy volume label if present
        if source_vbr[38] == 0x29:  # Extended boot signature
            dest_vbr[43:54] = source_vbr[43:54]  # Volume label

        # Write back
        self.dest_file.seek(self.dest_part_start * 512)
        self.dest_file.write(dest_vbr)

    def _copy_directory(self, path: str, is_root: bool = False):
        """Copy directory contents recursively."""
        try:
            entries = self.source.list_dir(path)
        except Exception:
            return

        dir_entries_data = []

        for entry in entries:
            if entry.name == '.' or entry.name == '..':
                continue

            self.progress("copying", self.files_copied, -1)

            if entry.is_directory:
                # Allocate cluster for subdirectory
                dir_cluster = self._allocate_cluster()

                # Create directory entry
                dir_entry = self._make_dir_entry(entry, dir_cluster)
                dir_entries_data.append(dir_entry)

                # Copy subdirectory contents
                subpath = f"{path.rstrip('/')}/{entry.full_name}"
                self._copy_subdirectory(subpath, dir_cluster)

            elif not entry.is_directory and not entry.is_volume_label:
                if entry.size == 0:
                    # Empty file - no clusters
                    file_entry = self._make_dir_entry(entry, 0)
                    dir_entries_data.append(file_entry)
                else:
                    # Copy file data
                    first_cluster = self._copy_file_data(path, entry)
                    file_entry = self._make_dir_entry(entry, first_cluster)
                    dir_entries_data.append(file_entry)

                self.files_copied += 1
                self.bytes_copied += entry.size

            else:
                # Volume label or other - copy entry as-is
                dir_entries_data.append(self._make_raw_entry(entry))

        # Write directory entries
        if is_root:
            self._write_root_entries(dir_entries_data)
        else:
            # For subdirectories, entries are written in _copy_subdirectory
            pass

    def _copy_subdirectory(self, path: str, dir_cluster: int):
        """Copy subdirectory to allocated cluster."""
        try:
            entries = self.source.list_dir(path)
        except Exception:
            return

        # Build directory entries
        dir_entries_data = []

        # Add . and .. entries
        dot_entry = self._make_dot_entry(dir_cluster)
        dotdot_entry = self._make_dotdot_entry(0)  # 0 for root parent
        dir_entries_data.append(dot_entry)
        dir_entries_data.append(dotdot_entry)

        for entry in entries:
            if entry.name == '.' or entry.name == '..':
                continue

            self.progress("copying", self.files_copied, -1)

            if entry.is_directory:
                # Allocate cluster for subdirectory
                subdir_cluster = self._allocate_cluster()
                subdir_entry = self._make_dir_entry(entry, subdir_cluster)
                dir_entries_data.append(subdir_entry)

                # Recursively copy
                subpath = f"{path.rstrip('/')}/{entry.full_name}"
                self._copy_subdirectory(subpath, subdir_cluster)

            elif not entry.is_directory and not entry.is_volume_label:
                if entry.size == 0:
                    file_entry = self._make_dir_entry(entry, 0)
                else:
                    first_cluster = self._copy_file_data(path, entry)
                    file_entry = self._make_dir_entry(entry, first_cluster)
                dir_entries_data.append(file_entry)

                self.files_copied += 1
                self.bytes_copied += entry.size
            else:
                dir_entries_data.append(self._make_raw_entry(entry))

        # Write entries to directory cluster
        self._write_dir_cluster(dir_cluster, dir_entries_data)

    def _copy_file_data(self, dir_path: str, entry: DirEntry) -> int:
        """Copy file data sequentially, return first cluster."""
        file_path = f"{dir_path.rstrip('/')}/{entry.full_name}"
        data = self.source.read_file(file_path)

        if len(data) == 0:
            return 0

        # Calculate clusters needed
        clusters_needed = (len(data) + self.dest_cluster_size - 1) // self.dest_cluster_size

        # Allocate sequential clusters
        first_cluster = self.next_cluster
        clusters = []
        for _ in range(clusters_needed):
            clusters.append(self._allocate_cluster())

        # Link clusters in chain and write data
        for i, cluster in enumerate(clusters):
            # Link to next cluster or mark as end
            if i < len(clusters) - 1:
                self._set_fat_entry(cluster, clusters[i + 1])
            else:
                self._set_fat_entry(cluster, 0xFFFF)  # End of chain

            start = i * self.dest_cluster_size
            end = min(start + self.dest_cluster_size, len(data))
            chunk = data[start:end]

            # Pad to cluster size
            if len(chunk) < self.dest_cluster_size:
                chunk = chunk + b'\x00' * (self.dest_cluster_size - len(chunk))

            self._write_cluster(cluster, chunk)

        return first_cluster

    def _allocate_cluster(self) -> int:
        """Allocate next sequential cluster."""
        cluster = self.next_cluster
        self.next_cluster += 1

        # Mark as end of chain (will be updated if more clusters follow)
        self._set_fat_entry(cluster, 0xFFFF)

        return cluster

    def _set_fat_entry(self, cluster: int, value: int):
        """Set FAT entry value."""
        offset = cluster * 2
        self.dest_fat[offset:offset+2] = struct.pack('<H', value)

    def _write_cluster(self, cluster: int, data: bytes):
        """Write data to cluster using buffered I/O."""
        sector = self.dest_data_start + (cluster - 2) * self.dest_sectors_per_cluster

        # Direct write for now (buffering can be added for optimization)
        self.dest_file.seek(sector * 512)
        self.dest_file.write(data)

    def _write_root_entries(self, entries: list[bytes]):
        """Write entries to root directory."""
        root_data = bytearray(self.dest_root_sectors * 512)

        offset = 0
        for entry in entries:
            if offset + 32 > len(root_data):
                break
            root_data[offset:offset+32] = entry
            offset += 32

        self.dest_file.seek(self.dest_root_start * 512)
        self.dest_file.write(root_data)

    def _write_dir_cluster(self, cluster: int, entries: list[bytes]):
        """Write entries to directory cluster."""
        cluster_data = bytearray(self.dest_cluster_size)

        offset = 0
        for entry in entries:
            if offset + 32 > len(cluster_data):
                break
            cluster_data[offset:offset+32] = entry
            offset += 32

        self._write_cluster(cluster, bytes(cluster_data))

    def _make_dir_entry(self, entry: DirEntry, first_cluster: int) -> bytes:
        """Create directory entry bytes."""
        from datetime import datetime

        data = bytearray(32)

        # Name and extension (8.3 format)
        name = entry.name.upper().ljust(8)[:8]
        ext = entry.ext.upper().ljust(3)[:3]
        data[0:8] = name.encode('ascii', errors='replace')
        data[8:11] = ext.encode('ascii', errors='replace')

        # Attributes
        data[11] = entry.attr

        # Reserved
        data[12] = 0
        data[13] = 0  # Creation time tenths

        # Convert datetime to DOS format or use defaults
        if entry.create_time:
            create_time_val, create_date_val = _make_dos_datetime(entry.create_time)
        else:
            create_time_val, create_date_val = 0, 0

        if entry.modify_time:
            modify_time_val, modify_date_val = _make_dos_datetime(entry.modify_time)
        else:
            modify_time_val, modify_date_val = create_time_val, create_date_val

        if entry.access_date:
            _, access_date_val = _make_dos_datetime(entry.access_date)
        else:
            access_date_val = create_date_val

        data[14:16] = struct.pack('<H', create_time_val)
        data[16:18] = struct.pack('<H', create_date_val)
        data[18:20] = struct.pack('<H', access_date_val)

        # High word of cluster (FAT32 only, 0 for FAT16)
        data[20:22] = b'\x00\x00'

        # Modification time/date
        data[22:24] = struct.pack('<H', modify_time_val)
        data[24:26] = struct.pack('<H', modify_date_val)

        # First cluster
        data[26:28] = struct.pack('<H', first_cluster & 0xFFFF)

        # File size
        data[28:32] = struct.pack('<I', entry.size)

        return bytes(data)

    def _make_raw_entry(self, entry: DirEntry) -> bytes:
        """Create raw entry bytes (for volume labels etc)."""
        return self._make_dir_entry(entry, entry.first_cluster)

    def _make_dot_entry(self, cluster: int) -> bytes:
        """Create '.' directory entry."""
        data = bytearray(32)
        data[0:11] = b'.          '
        data[11] = 0x10  # Directory attribute
        data[26:28] = struct.pack('<H', cluster & 0xFFFF)
        return bytes(data)

    def _make_dotdot_entry(self, parent_cluster: int) -> bytes:
        """Create '..' directory entry."""
        data = bytearray(32)
        data[0:11] = b'..         '
        data[11] = 0x10  # Directory attribute
        data[26:28] = struct.pack('<H', parent_cluster & 0xFFFF)
        return bytes(data)

    def _flush_buffer(self):
        """Flush write buffer to disk."""
        # Currently using direct writes, no buffer to flush
        pass

    def _finalize_fat(self):
        """Write FAT tables to disk."""
        # Build proper cluster chains from sequential allocation
        # (files are already sequential, so chains are simple)

        # Write FAT to all copies
        for i in range(self.dest_num_fats):
            self.dest_file.seek((self.dest_fat_start + i * self.dest_fat_size) * 512)
            self.dest_file.write(self.dest_fat)


def defragment_image(source: str, dest: str, new_size: Optional[int] = None,
                     progress: Optional[Callable[[str, int, int], None]] = None) -> dict:
    """
    Create a defragmented copy of a disk image.

    Args:
        source: Path to source image
        dest: Path to destination (must not exist)
        new_size: Optional new size in bytes
        progress: Optional progress callback(phase, current, total)

    Returns:
        Statistics dictionary
    """
    defrag = DefragmentedImage(source, dest, new_size, progress)
    return defrag.defragment()
