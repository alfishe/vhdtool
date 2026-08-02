"""VHD and raw disk image handling."""

import struct
from typing import BinaryIO, Iterator, Optional

from .fat import BPB, DirEntry, FATType
from .partition import PartitionEntry, parse_mbr_partitions


class VHDImage:
    """Handler for VHD and raw disk images with FAT filesystem support."""

    VHD_COOKIE = b"conectix"
    VHD_TYPE_FIXED = 2
    VHD_TYPE_DYNAMIC = 3
    VHD_TYPE_DIFFERENCING = 4

    def __init__(self, path: str, readonly: bool = True):
        self.path = path
        self.readonly = readonly
        self.file: Optional[BinaryIO] = None
        self.is_vhd = False
        self.is_dynamic = False
        self.disk_size = 0
        self.vhd_block_size = 0
        self.bat: list[int] = []
        self.bat_offset = 0
        self.data_offset = 0
        self.partition_offset = 0
        self.bpb: Optional[BPB] = None

    def __enter__(self):
        mode = "rb" if self.readonly else "r+b"
        self.file = open(self.path, mode)
        self._detect_format()
        return self

    def __exit__(self, *args):
        if self.file:
            self.file.close()

    def _detect_format(self):
        """Detect if this is a VHD or raw image."""
        self.file.seek(-512, 2)
        footer = self.file.read(512)

        if footer[:8] == self.VHD_COOKIE:
            self.is_vhd = True
            self._parse_vhd_footer(footer)
        else:
            self.file.seek(0, 2)
            self.disk_size = self.file.tell()

        self._find_partition()
        self._parse_bpb()

    def _parse_vhd_footer(self, footer: bytes):
        """Parse VHD footer structure."""
        disk_type = struct.unpack(">I", footer[60:64])[0]
        self.disk_size = struct.unpack(">Q", footer[48:56])[0]

        if disk_type == self.VHD_TYPE_DYNAMIC or disk_type == self.VHD_TYPE_DIFFERENCING:
            self.is_dynamic = True
            data_offset = struct.unpack(">Q", footer[16:24])[0]
            self._parse_dynamic_header(data_offset)
        elif disk_type == self.VHD_TYPE_FIXED:
            self.is_dynamic = False

    def _parse_dynamic_header(self, offset: int):
        """Parse dynamic VHD header."""
        self.file.seek(offset)
        header = self.file.read(1024)

        if header[:8] != b"cxsparse":
            raise ValueError("Invalid dynamic VHD header")

        self.bat_offset = struct.unpack(">Q", header[16:24])[0]
        max_bat_entries = struct.unpack(">I", header[28:32])[0]
        self.vhd_block_size = struct.unpack(">I", header[32:36])[0]

        self.file.seek(self.bat_offset)
        bat_data = self.file.read(max_bat_entries * 4)
        self.bat = list(struct.unpack(f">{max_bat_entries}I", bat_data))

        bitmap_sectors = (self.vhd_block_size // 512 + 7) // 8
        bitmap_sectors = (bitmap_sectors + 511) // 512
        self.data_offset = bitmap_sectors * 512

    def _read_sector(self, lba: int) -> bytes:
        """Read a single sector, handling VHD translation."""
        if self.is_vhd and self.is_dynamic:
            block_idx = (lba * 512) // self.vhd_block_size
            block_offset = (lba * 512) % self.vhd_block_size

            if block_idx >= len(self.bat) or self.bat[block_idx] == 0xFFFFFFFF:
                return b'\x00' * 512

            physical_offset = (self.bat[block_idx] * 512) + self.data_offset + block_offset
            self.file.seek(physical_offset)
        else:
            self.file.seek(lba * 512)

        return self.file.read(512)

    def _write_sector(self, lba: int, data: bytes):
        """Write a single sector."""
        if self.readonly:
            raise IOError("Image opened in readonly mode")
        if len(data) != 512:
            raise ValueError("Sector must be 512 bytes")

        if self.is_vhd and self.is_dynamic:
            raise NotImplementedError("Writing to dynamic VHD not yet supported")

        self.file.seek(lba * 512)
        self.file.write(data)

    def _read_sectors(self, start_lba: int, count: int) -> bytes:
        """Read multiple consecutive sectors."""
        if self.is_vhd and self.is_dynamic:
            return b''.join(self._read_sector(start_lba + i) for i in range(count))

        self.file.seek(start_lba * 512)
        return self.file.read(count * 512)

    def _write_sectors(self, start_lba: int, data: bytes):
        """Write multiple consecutive sectors."""
        if self.readonly:
            raise IOError("Image opened in readonly mode")
        if len(data) % 512 != 0:
            raise ValueError("Data must be multiple of 512 bytes")

        if self.is_vhd and self.is_dynamic:
            for i in range(len(data) // 512):
                self._write_sector(start_lba + i, data[i*512:(i+1)*512])
        else:
            self.file.seek(start_lba * 512)
            self.file.write(data)

    def _find_partition(self):
        """Find the first FAT partition."""
        mbr = self._read_sector(0)

        if mbr[510:512] != b'\x55\xAA':
            self.partition_offset = 0
            return

        # Check if this is a floppy/superfloppy (no partition table)
        if mbr[0] in (0xEB, 0xE9) and mbr[21] in (0xF0, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF):
            bytes_per_sector = struct.unpack("<H", mbr[11:13])[0]
            if bytes_per_sector in (512, 1024, 2048, 4096):
                self.partition_offset = 0
                return

        for i in range(4):
            entry_offset = 446 + (i * 16)
            entry = mbr[entry_offset:entry_offset + 16]

            type_code = entry[4]
            start_lba = struct.unpack("<I", entry[8:12])[0]

            if type_code in (0x01, 0x04, 0x06, 0x0B, 0x0C, 0x0E):
                self.partition_offset = start_lba
                return

        self.partition_offset = 0

    def _parse_bpb(self):
        """Parse the BIOS Parameter Block."""
        boot_sector = self._read_sector(self.partition_offset)

        if boot_sector[510:512] != b'\x55\xAA':
            raise ValueError("Invalid boot sector signature")

        self.bpb = BPB.from_bytes(boot_sector)

    def is_floppy(self) -> bool:
        """Check if this is a floppy/superfloppy image (no partition table)."""
        return self.partition_offset == 0 and self.bpb is not None

    def get_partitions(self) -> list[PartitionEntry]:
        """Read MBR partition table."""
        mbr = self._read_sector(0)
        return parse_mbr_partitions(mbr)

    def _cluster_to_sector(self, cluster: int) -> int:
        """Convert cluster number to sector number."""
        return self.partition_offset + self.bpb.first_data_sector + \
               (cluster - 2) * self.bpb.sectors_per_cluster

    def _read_cluster(self, cluster: int) -> bytes:
        """Read a single cluster."""
        sector = self._cluster_to_sector(cluster)
        return self._read_sectors(sector, self.bpb.sectors_per_cluster)

    def _write_cluster(self, cluster: int, data: bytes):
        """Write a single cluster."""
        if len(data) != self.bpb.cluster_size:
            raise ValueError(f"Data must be {self.bpb.cluster_size} bytes")
        sector = self._cluster_to_sector(cluster)
        self._write_sectors(sector, data)

    def _read_fat_entry(self, cluster: int) -> int:
        """Read FAT entry for a cluster."""
        fat_offset = self.partition_offset + self.bpb.reserved_sectors

        if self.bpb.fat_type == FATType.FAT12:
            offset = cluster + (cluster // 2)
            sector = fat_offset + (offset // 512)
            pos = offset % 512

            data = self._read_sectors(sector, 2)
            value = struct.unpack("<H", data[pos:pos+2])[0]

            if cluster & 1:
                return value >> 4
            else:
                return value & 0x0FFF

        elif self.bpb.fat_type == FATType.FAT16:
            sector = fat_offset + (cluster * 2 // 512)
            pos = (cluster * 2) % 512
            data = self._read_sector(sector)
            return struct.unpack("<H", data[pos:pos+2])[0]

        else:  # FAT32
            sector = fat_offset + (cluster * 4 // 512)
            pos = (cluster * 4) % 512
            data = self._read_sector(sector)
            return struct.unpack("<I", data[pos:pos+4])[0] & 0x0FFFFFFF

    def _write_fat_entry(self, cluster: int, value: int):
        """Write FAT entry for a cluster."""
        fat_offset = self.partition_offset + self.bpb.reserved_sectors

        if self.bpb.fat_type == FATType.FAT12:
            raise NotImplementedError("FAT12 write not supported")

        elif self.bpb.fat_type == FATType.FAT16:
            sector = fat_offset + (cluster * 2 // 512)
            pos = (cluster * 2) % 512
            data = bytearray(self._read_sector(sector))
            struct.pack_into("<H", data, pos, value)
            self._write_sector(sector, bytes(data))

            if self.bpb.num_fats > 1:
                sector2 = sector + self.bpb.fat_size
                self._write_sector(sector2, bytes(data))

        else:  # FAT32
            sector = fat_offset + (cluster * 4 // 512)
            pos = (cluster * 4) % 512
            data = bytearray(self._read_sector(sector))
            old = struct.unpack("<I", data[pos:pos+4])[0]
            new_value = (old & 0xF0000000) | (value & 0x0FFFFFFF)
            struct.pack_into("<I", data, pos, new_value)
            self._write_sector(sector, bytes(data))

            if self.bpb.num_fats > 1:
                sector2 = sector + self.bpb.fat_size
                self._write_sector(sector2, bytes(data))

    def _is_end_of_chain(self, value: int) -> bool:
        """Check if FAT entry indicates end of cluster chain."""
        if self.bpb.fat_type == FATType.FAT12:
            return value >= 0x0FF8
        elif self.bpb.fat_type == FATType.FAT16:
            return value >= 0xFFF8
        else:
            return value >= 0x0FFFFFF8

    def _get_cluster_chain(self, start_cluster: int) -> list[int]:
        """Get the full cluster chain starting from a cluster."""
        chain = []
        cluster = start_cluster

        while cluster >= 2 and not self._is_end_of_chain(cluster):
            chain.append(cluster)
            cluster = self._read_fat_entry(cluster)
            if len(chain) > 1000000:
                raise ValueError("Cluster chain too long (possible corruption)")

        return chain

    def _find_free_cluster(self) -> int:
        """Find a free cluster."""
        for cluster in range(2, self.bpb.cluster_count + 2):
            if self._read_fat_entry(cluster) == 0:
                return cluster
        raise IOError("No free clusters available")

    def _allocate_clusters(self, count: int) -> list[int]:
        """Allocate a chain of clusters."""
        clusters = []
        end_marker = 0xFFFF if self.bpb.fat_type == FATType.FAT16 else 0x0FFFFFFF

        for _ in range(count):
            cluster = self._find_free_cluster()
            self._write_fat_entry(cluster, end_marker)
            if clusters:
                self._write_fat_entry(clusters[-1], cluster)
            clusters.append(cluster)

        return clusters

    def _parse_dir_entry(self, data: bytes) -> Optional[DirEntry]:
        """Parse a 32-byte directory entry."""
        return DirEntry.from_bytes(data)

    def _make_dir_entry(self, name: str, ext: str, attr: int,
                        cluster: int, size: int) -> bytes:
        """Create a 32-byte directory entry."""
        entry = DirEntry(
            name=name,
            ext=ext,
            attr=attr,
            create_time=None,
            modify_time=None,
            access_date=None,
            first_cluster=cluster,
            size=size,
        )
        return entry.to_bytes()

    def _read_root_dir(self) -> Iterator[DirEntry]:
        """Read root directory entries."""
        if self.bpb.fat_type == FATType.FAT32:
            yield from self._read_dir_cluster(self.bpb.root_cluster)
        else:
            root_start = self.partition_offset + self.bpb.reserved_sectors + \
                        (self.bpb.num_fats * self.bpb.fat_size)

            for i in range(self.bpb.root_entries):
                sector = root_start + (i * 32 // 512)
                offset = (i * 32) % 512
                data = self._read_sector(sector)
                entry = self._parse_dir_entry(data[offset:offset+32])
                if entry is None and data[offset] == 0x00:
                    break
                if entry:
                    yield entry

    def _read_dir_cluster(self, start_cluster: int) -> Iterator[DirEntry]:
        """Read directory entries from cluster chain."""
        chain = self._get_cluster_chain(start_cluster)

        for cluster in chain:
            data = self._read_cluster(cluster)
            entries_per_cluster = self.bpb.cluster_size // 32

            for i in range(entries_per_cluster):
                entry_data = data[i*32:(i+1)*32]
                if entry_data[0] == 0x00:
                    return
                entry = self._parse_dir_entry(entry_data)
                if entry:
                    yield entry

    def _resolve_path(self, path: str) -> tuple[Optional[DirEntry], list[DirEntry]]:
        """Resolve a path to a directory entry and its contents."""
        parts = [p for p in path.replace('\\', '/').split('/') if p]

        if not parts:
            return None, list(self._read_root_dir())

        current_entries = list(self._read_root_dir())
        current_entry = None

        for part in parts:
            found = False
            part_upper = part.upper()

            for entry in current_entries:
                entry_name = entry.full_name.upper()
                if entry_name == part_upper:
                    current_entry = entry
                    if entry.is_directory:
                        current_entries = list(self._read_dir_cluster(entry.first_cluster))
                    found = True
                    break

            if not found:
                raise FileNotFoundError(f"Path not found: {path}")

        if current_entry and current_entry.is_directory:
            return current_entry, current_entries
        else:
            return current_entry, []

    def list_dir(self, path: str = "/") -> list[DirEntry]:
        """List directory contents."""
        entry, contents = self._resolve_path(path)
        if entry and not entry.is_directory:
            return [entry]
        return [e for e in contents if not e.is_volume_label and e.name not in ('.', '..')]

    def read_file(self, path: str) -> bytes:
        """Read a file from the image."""
        entry, _ = self._resolve_path(path)
        if entry is None:
            raise FileNotFoundError(f"File not found: {path}")
        if entry.is_directory:
            raise IsADirectoryError(f"Is a directory: {path}")

        if entry.size == 0 or entry.first_cluster < 2:
            return b''

        chain = self._get_cluster_chain(entry.first_cluster)
        data = b''.join(self._read_cluster(c) for c in chain)
        return data[:entry.size]

    def write_file(self, path: str, data: bytes):
        """Write a file to the image."""
        parts = [p for p in path.replace('\\', '/').split('/') if p]
        if not parts:
            raise ValueError("Invalid path")

        filename = parts[-1]
        dir_path = '/'.join(parts[:-1]) if len(parts) > 1 else '/'

        if '.' in filename:
            name, ext = filename.rsplit('.', 1)
        else:
            name, ext = filename, ''

        if len(name) > 8 or len(ext) > 3:
            raise ValueError("Filename must be 8.3 format")

        clusters_needed = (len(data) + self.bpb.cluster_size - 1) // self.bpb.cluster_size
        if clusters_needed == 0:
            clusters_needed = 1

        allocated = self._allocate_clusters(clusters_needed)

        padded_data = data + b'\x00' * (clusters_needed * self.bpb.cluster_size - len(data))
        for i, cluster in enumerate(allocated):
            chunk = padded_data[i * self.bpb.cluster_size:(i + 1) * self.bpb.cluster_size]
            self._write_cluster(cluster, chunk)

        dir_entry = self._make_dir_entry(name, ext, DirEntry.ATTR_ARCHIVE,
                                         allocated[0], len(data))
        self._add_dir_entry(dir_path, dir_entry)

    def _add_dir_entry(self, dir_path: str, entry: bytes):
        """Add a directory entry to a directory."""
        if dir_path == '/' or not dir_path:
            if self.bpb.fat_type == FATType.FAT32:
                self._add_entry_to_cluster(self.bpb.root_cluster, entry)
            else:
                root_start = self.partition_offset + self.bpb.reserved_sectors + \
                            (self.bpb.num_fats * self.bpb.fat_size)

                for i in range(self.bpb.root_entries):
                    sector = root_start + (i * 32 // 512)
                    offset = (i * 32) % 512
                    data = bytearray(self._read_sector(sector))

                    if data[offset] == 0x00 or data[offset] == 0xE5:
                        data[offset:offset+32] = entry
                        self._write_sector(sector, bytes(data))
                        return

                raise IOError("Root directory full")
        else:
            parent, _ = self._resolve_path(dir_path)
            if parent is None or not parent.is_directory:
                raise FileNotFoundError(f"Directory not found: {dir_path}")
            self._add_entry_to_cluster(parent.first_cluster, entry)

    def _add_entry_to_cluster(self, start_cluster: int, entry: bytes):
        """Add a directory entry to a cluster chain."""
        chain = self._get_cluster_chain(start_cluster)

        for cluster in chain:
            data = bytearray(self._read_cluster(cluster))
            entries_per_cluster = self.bpb.cluster_size // 32

            for i in range(entries_per_cluster):
                if data[i*32] == 0x00 or data[i*32] == 0xE5:
                    data[i*32:(i+1)*32] = entry
                    self._write_cluster(cluster, bytes(data))
                    return

        new_cluster = self._find_free_cluster()
        self._write_fat_entry(chain[-1], new_cluster)
        end_marker = 0xFFFF if self.bpb.fat_type == FATType.FAT16 else 0x0FFFFFFF
        self._write_fat_entry(new_cluster, end_marker)

        new_data = entry + b'\x00' * (self.bpb.cluster_size - 32)
        self._write_cluster(new_cluster, new_data)

    def mkdir(self, path: str):
        """Create a directory."""
        parts = [p for p in path.replace('\\', '/').split('/') if p]
        if not parts:
            raise ValueError("Invalid path")

        dirname = parts[-1]
        parent_path = '/'.join(parts[:-1]) if len(parts) > 1 else '/'

        if len(dirname) > 8:
            raise ValueError("Directory name must be 8 characters or less")

        cluster = self._find_free_cluster()
        end_marker = 0xFFFF if self.bpb.fat_type == FATType.FAT16 else 0x0FFFFFFF
        self._write_fat_entry(cluster, end_marker)

        if parent_path == '/' or not parent_path:
            parent_cluster = 0
        else:
            parent, _ = self._resolve_path(parent_path)
            parent_cluster = parent.first_cluster if parent else 0

        dir_data = bytearray(self.bpb.cluster_size)

        dot_entry = self._make_dir_entry('.', '', DirEntry.ATTR_DIRECTORY, cluster, 0)
        dotdot_entry = self._make_dir_entry('..', '', DirEntry.ATTR_DIRECTORY, parent_cluster, 0)
        dir_data[0:32] = dot_entry
        dir_data[32:64] = dotdot_entry

        self._write_cluster(cluster, bytes(dir_data))

        entry = self._make_dir_entry(dirname, '', DirEntry.ATTR_DIRECTORY, cluster, 0)
        self._add_dir_entry(parent_path, entry)

    def remove(self, path: str):
        """Remove a file or empty directory."""
        entry, contents = self._resolve_path(path)
        if entry is None:
            raise FileNotFoundError(f"Not found: {path}")

        if entry.is_directory:
            real_contents = [e for e in contents if e.name not in ('.', '..')]
            if real_contents:
                raise OSError(f"Directory not empty: {path}")

        if entry.first_cluster >= 2:
            chain = self._get_cluster_chain(entry.first_cluster)
            for cluster in chain:
                self._write_fat_entry(cluster, 0)

        parts = [p for p in path.replace('\\', '/').split('/') if p]
        parent_path = '/'.join(parts[:-1]) if len(parts) > 1 else '/'
        self._mark_entry_deleted(parent_path, entry.full_name)

    def _mark_entry_deleted(self, dir_path: str, name: str):
        """Mark a directory entry as deleted."""
        name_upper = name.upper()

        if dir_path == '/' or not dir_path:
            if self.bpb.fat_type != FATType.FAT32:
                root_start = self.partition_offset + self.bpb.reserved_sectors + \
                            (self.bpb.num_fats * self.bpb.fat_size)

                for i in range(self.bpb.root_entries):
                    sector = root_start + (i * 32 // 512)
                    offset = (i * 32) % 512
                    data = bytearray(self._read_sector(sector))

                    entry = self._parse_dir_entry(data[offset:offset+32])
                    if entry and entry.full_name.upper() == name_upper:
                        data[offset] = 0xE5
                        self._write_sector(sector, bytes(data))
                        return
                return
            start_cluster = self.bpb.root_cluster
        else:
            parent, _ = self._resolve_path(dir_path)
            start_cluster = parent.first_cluster

        chain = self._get_cluster_chain(start_cluster)
        for cluster in chain:
            data = bytearray(self._read_cluster(cluster))
            entries_per_cluster = self.bpb.cluster_size // 32

            for i in range(entries_per_cluster):
                entry = self._parse_dir_entry(data[i*32:(i+1)*32])
                if entry and entry.full_name.upper() == name_upper:
                    data[i*32] = 0xE5
                    self._write_cluster(cluster, bytes(data))
                    return

    def get_highest_used_cluster(self) -> int:
        """Find the highest cluster number that is in use."""
        highest = 1  # Clusters start at 2, so 1 means none used
        for cluster in range(2, self.bpb.cluster_count + 2):
            entry = self._read_fat_entry(cluster)
            if entry != 0:  # Not free
                highest = cluster
        return highest

    def get_used_cluster_count(self) -> int:
        """Count the number of clusters in use."""
        count = 0
        for cluster in range(2, self.bpb.cluster_count + 2):
            if self._read_fat_entry(cluster) != 0:
                count += 1
        return count

    def get_free_cluster_count(self) -> int:
        """Count the number of free clusters."""
        count = 0
        for cluster in range(2, self.bpb.cluster_count + 2):
            if self._read_fat_entry(cluster) == 0:
                count += 1
        return count

    def get_filesystem_stats(self) -> dict:
        """Get filesystem statistics."""
        used = self.get_used_cluster_count()
        total = self.bpb.cluster_count
        cluster_size = self.bpb.cluster_size
        return {
            'total_clusters': total,
            'used_clusters': used,
            'free_clusters': total - used,
            'cluster_size': cluster_size,
            'total_bytes': total * cluster_size,
            'used_bytes': used * cluster_size,
            'free_bytes': (total - used) * cluster_size,
            'highest_used_cluster': self.get_highest_used_cluster(),
        }
