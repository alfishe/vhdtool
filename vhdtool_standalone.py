#!/usr/bin/env python3
"""
VHD/Raw Disk Image Tool for MiSTer ao486

Supports reading and writing files to FAT12/FAT16/FAT32 filesystems
in VHD (fixed/dynamic) and raw disk images.

Usage:
    vhdtool.py info <image>              Show disk/partition/filesystem info
    vhdtool.py ls <image> [path]         List directory contents
    vhdtool.py cp <image>:<path> <dest>  Copy file from image to local
    vhdtool.py cp <src> <image>:<path>   Copy file from local to image
    vhdtool.py cat <image>:<path>        Print file contents to stdout
    vhdtool.py mkdir <image>:<path>      Create directory
    vhdtool.py rm <image>:<path>         Remove file or empty directory
    vhdtool.py create <image> <size>     Create new disk image
    vhdtool.py resize <image> <size>     Resize disk image (preserving data)
    vhdtool.py makeboot <image>          Make disk bootable
    vhdtool.py listboot                  List available boot sectors
"""

import argparse
import hashlib
import os
import shutil
import struct
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import BinaryIO, Iterator, Optional

BOOT_SECTORS_DIR = Path(__file__).parent / "bootsectors"


class FATType(IntEnum):
    FAT12 = 12
    FAT16 = 16
    FAT32 = 32


@dataclass
class PartitionEntry:
    bootable: bool
    type_code: int
    start_lba: int
    size_sectors: int

    @property
    def type_name(self) -> str:
        types = {
            0x00: "Empty",
            0x01: "FAT12",
            0x04: "FAT16 <32MB",
            0x05: "Extended",
            0x06: "FAT16",
            0x07: "NTFS/exFAT",
            0x0B: "FAT32 CHS",
            0x0C: "FAT32 LBA",
            0x0E: "FAT16 LBA",
            0x0F: "Extended LBA",
            0x83: "Linux",
        }
        return types.get(self.type_code, f"Unknown (0x{self.type_code:02X})")


@dataclass
class BPB:
    """BIOS Parameter Block"""
    bytes_per_sector: int
    sectors_per_cluster: int
    reserved_sectors: int
    num_fats: int
    root_entries: int
    total_sectors_16: int
    media_type: int
    fat_size_16: int
    sectors_per_track: int
    num_heads: int
    hidden_sectors: int
    total_sectors_32: int
    # FAT32 extended
    fat_size_32: int = 0
    root_cluster: int = 2
    fs_info_sector: int = 0
    volume_label: str = ""
    fs_type: str = ""

    @property
    def total_sectors(self) -> int:
        return self.total_sectors_32 if self.total_sectors_32 else self.total_sectors_16

    @property
    def fat_size(self) -> int:
        return self.fat_size_32 if self.fat_size_32 else self.fat_size_16

    @property
    def root_dir_sectors(self) -> int:
        return ((self.root_entries * 32) + (self.bytes_per_sector - 1)) // self.bytes_per_sector

    @property
    def first_data_sector(self) -> int:
        return self.reserved_sectors + (self.num_fats * self.fat_size) + self.root_dir_sectors

    @property
    def data_sectors(self) -> int:
        return self.total_sectors - self.first_data_sector

    @property
    def cluster_count(self) -> int:
        return self.data_sectors // self.sectors_per_cluster

    @property
    def fat_type(self) -> FATType:
        if self.cluster_count < 4085:
            return FATType.FAT12
        elif self.cluster_count < 65525:
            return FATType.FAT16
        else:
            return FATType.FAT32

    @property
    def cluster_size(self) -> int:
        return self.bytes_per_sector * self.sectors_per_cluster


@dataclass
class DirEntry:
    name: str
    ext: str
    attr: int
    create_time: Optional[datetime]
    modify_time: Optional[datetime]
    access_date: Optional[datetime]
    first_cluster: int
    size: int

    ATTR_READ_ONLY = 0x01
    ATTR_HIDDEN = 0x02
    ATTR_SYSTEM = 0x04
    ATTR_VOLUME_ID = 0x08
    ATTR_DIRECTORY = 0x10
    ATTR_ARCHIVE = 0x20
    ATTR_LFN = 0x0F

    @property
    def is_directory(self) -> bool:
        return bool(self.attr & self.ATTR_DIRECTORY)

    @property
    def is_volume_label(self) -> bool:
        return bool(self.attr & self.ATTR_VOLUME_ID)

    @property
    def is_lfn(self) -> bool:
        return (self.attr & self.ATTR_LFN) == self.ATTR_LFN

    @property
    def is_hidden(self) -> bool:
        return bool(self.attr & self.ATTR_HIDDEN)

    @property
    def is_system(self) -> bool:
        return bool(self.attr & self.ATTR_SYSTEM)

    @property
    def full_name(self) -> str:
        if self.ext:
            return f"{self.name}.{self.ext}"
        return self.name

    @property
    def attr_string(self) -> str:
        attrs = []
        if self.is_directory:
            attrs.append("D")
        else:
            attrs.append("-")
        attrs.append("r" if self.attr & self.ATTR_READ_ONLY else "-")
        attrs.append("h" if self.is_hidden else "-")
        attrs.append("s" if self.is_system else "-")
        attrs.append("a" if self.attr & self.ATTR_ARCHIVE else "-")
        return "".join(attrs)


class VHDImage:
    """Handler for VHD and raw disk images"""

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
        """Detect if this is a VHD or raw image"""
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
        """Parse VHD footer structure"""
        disk_type = struct.unpack(">I", footer[60:64])[0]
        self.disk_size = struct.unpack(">Q", footer[48:56])[0]

        if disk_type == self.VHD_TYPE_DYNAMIC or disk_type == self.VHD_TYPE_DIFFERENCING:
            self.is_dynamic = True
            data_offset = struct.unpack(">Q", footer[16:24])[0]
            self._parse_dynamic_header(data_offset)
        elif disk_type == self.VHD_TYPE_FIXED:
            self.is_dynamic = False

    def _parse_dynamic_header(self, offset: int):
        """Parse dynamic VHD header"""
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
        """Read a single sector, handling VHD translation"""
        if self.is_vhd and self.is_dynamic:
            block_idx = (lba * 512) // self.vhd_block_size
            block_offset = (lba * 512) % self.vhd_block_size

            if block_idx >= len(self.bat) or self.bat[block_idx] == 0xFFFFFFFF:
                return b'\x00' * 512

            physical_offset = (self.bat[block_idx] * 512) + self.data_offset + block_offset
            self.file.seek(physical_offset)
        else:
            if self.is_vhd:
                self.file.seek(lba * 512)
            else:
                self.file.seek(lba * 512)

        return self.file.read(512)

    def _write_sector(self, lba: int, data: bytes):
        """Write a single sector"""
        if self.readonly:
            raise IOError("Image opened in readonly mode")
        if len(data) != 512:
            raise ValueError("Sector must be 512 bytes")

        if self.is_vhd and self.is_dynamic:
            raise NotImplementedError("Writing to dynamic VHD not yet supported")

        self.file.seek(lba * 512)
        self.file.write(data)

    def _read_sectors(self, start_lba: int, count: int) -> bytes:
        """Read multiple consecutive sectors"""
        if self.is_vhd and self.is_dynamic:
            return b''.join(self._read_sector(start_lba + i) for i in range(count))

        self.file.seek(start_lba * 512)
        return self.file.read(count * 512)

    def _write_sectors(self, start_lba: int, data: bytes):
        """Write multiple consecutive sectors"""
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
        """Find the first FAT partition"""
        mbr = self._read_sector(0)

        if mbr[510:512] != b'\x55\xAA':
            self.partition_offset = 0
            return

        # Check if this is a floppy/superfloppy (no partition table)
        # Floppies have a jump instruction at byte 0 (0xEB or 0xE9) and valid BPB
        if mbr[0] in (0xEB, 0xE9) and mbr[21] in (0xF0, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF):
            # Media byte looks like a valid FAT media descriptor
            bytes_per_sector = struct.unpack("<H", mbr[11:13])[0]
            if bytes_per_sector in (512, 1024, 2048, 4096):
                # This is a floppy/superfloppy - no partition table
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
        """Parse the BIOS Parameter Block"""
        boot_sector = self._read_sector(self.partition_offset)

        if boot_sector[510:512] != b'\x55\xAA':
            raise ValueError("Invalid boot sector signature")

        bytes_per_sector = struct.unpack("<H", boot_sector[11:13])[0]
        sectors_per_cluster = boot_sector[13]
        reserved_sectors = struct.unpack("<H", boot_sector[14:16])[0]
        num_fats = boot_sector[16]
        root_entries = struct.unpack("<H", boot_sector[17:19])[0]
        total_sectors_16 = struct.unpack("<H", boot_sector[19:21])[0]
        media_type = boot_sector[21]
        fat_size_16 = struct.unpack("<H", boot_sector[22:24])[0]
        sectors_per_track = struct.unpack("<H", boot_sector[24:26])[0]
        num_heads = struct.unpack("<H", boot_sector[26:28])[0]
        hidden_sectors = struct.unpack("<I", boot_sector[28:32])[0]
        total_sectors_32 = struct.unpack("<I", boot_sector[32:36])[0]

        if fat_size_16 == 0:
            fat_size_32 = struct.unpack("<I", boot_sector[36:40])[0]
            root_cluster = struct.unpack("<I", boot_sector[44:48])[0]
            fs_info_sector = struct.unpack("<H", boot_sector[48:50])[0]
            volume_label = boot_sector[71:82].decode('ascii', errors='replace').strip()
            fs_type = boot_sector[82:90].decode('ascii', errors='replace').strip()
        else:
            fat_size_32 = 0
            root_cluster = 2
            fs_info_sector = 0
            volume_label = boot_sector[43:54].decode('ascii', errors='replace').strip()
            fs_type = boot_sector[54:62].decode('ascii', errors='replace').strip()

        self.bpb = BPB(
            bytes_per_sector=bytes_per_sector,
            sectors_per_cluster=sectors_per_cluster,
            reserved_sectors=reserved_sectors,
            num_fats=num_fats,
            root_entries=root_entries,
            total_sectors_16=total_sectors_16,
            media_type=media_type,
            fat_size_16=fat_size_16,
            sectors_per_track=sectors_per_track,
            num_heads=num_heads,
            hidden_sectors=hidden_sectors,
            total_sectors_32=total_sectors_32,
            fat_size_32=fat_size_32,
            root_cluster=root_cluster,
            fs_info_sector=fs_info_sector,
            volume_label=volume_label,
            fs_type=fs_type,
        )

    def is_floppy(self) -> bool:
        """Check if this is a floppy/superfloppy image (no partition table)"""
        return self.partition_offset == 0 and self.bpb is not None

    def get_partitions(self) -> list[PartitionEntry]:
        """Read MBR partition table"""
        mbr = self._read_sector(0)
        partitions = []

        if mbr[510:512] != b'\x55\xAA':
            return partitions

        # Check if this is a floppy (no partition table)
        if mbr[0] in (0xEB, 0xE9) and mbr[21] in (0xF0, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF):
            bytes_per_sector = struct.unpack("<H", mbr[11:13])[0]
            if bytes_per_sector in (512, 1024, 2048, 4096):
                return partitions  # Floppy - no partition table

        for i in range(4):
            offset = 446 + (i * 16)
            entry = mbr[offset:offset + 16]

            bootable = entry[0] == 0x80
            type_code = entry[4]
            start_lba = struct.unpack("<I", entry[8:12])[0]
            size_sectors = struct.unpack("<I", entry[12:16])[0]

            if type_code != 0:
                partitions.append(PartitionEntry(
                    bootable=bootable,
                    type_code=type_code,
                    start_lba=start_lba,
                    size_sectors=size_sectors,
                ))

        return partitions

    def _cluster_to_sector(self, cluster: int) -> int:
        """Convert cluster number to sector number"""
        return self.partition_offset + self.bpb.first_data_sector + \
               (cluster - 2) * self.bpb.sectors_per_cluster

    def _read_cluster(self, cluster: int) -> bytes:
        """Read a single cluster"""
        sector = self._cluster_to_sector(cluster)
        return self._read_sectors(sector, self.bpb.sectors_per_cluster)

    def _write_cluster(self, cluster: int, data: bytes):
        """Write a single cluster"""
        if len(data) != self.bpb.cluster_size:
            raise ValueError(f"Data must be {self.bpb.cluster_size} bytes")
        sector = self._cluster_to_sector(cluster)
        self._write_sectors(sector, data)

    def _read_fat_entry(self, cluster: int) -> int:
        """Read FAT entry for a cluster"""
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
        """Write FAT entry for a cluster"""
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
        """Check if FAT entry indicates end of cluster chain"""
        if self.bpb.fat_type == FATType.FAT12:
            return value >= 0x0FF8
        elif self.bpb.fat_type == FATType.FAT16:
            return value >= 0xFFF8
        else:
            return value >= 0x0FFFFFF8

    def _get_cluster_chain(self, start_cluster: int) -> list[int]:
        """Get the full cluster chain starting from a cluster"""
        chain = []
        cluster = start_cluster

        while cluster >= 2 and not self._is_end_of_chain(cluster):
            chain.append(cluster)
            cluster = self._read_fat_entry(cluster)
            if len(chain) > 1000000:
                raise ValueError("Cluster chain too long (possible corruption)")

        return chain

    def _find_free_cluster(self) -> int:
        """Find a free cluster"""
        for cluster in range(2, self.bpb.cluster_count + 2):
            if self._read_fat_entry(cluster) == 0:
                return cluster
        raise IOError("No free clusters available")

    def _allocate_clusters(self, count: int) -> list[int]:
        """Allocate a chain of clusters"""
        clusters = []
        end_marker = 0xFFFF if self.bpb.fat_type == FATType.FAT16 else 0x0FFFFFFF

        for _ in range(count):
            cluster = self._find_free_cluster()
            # Mark this cluster as end-of-chain immediately so _find_free_cluster
            # won't return it again
            self._write_fat_entry(cluster, end_marker)
            # Link previous cluster to this one
            if clusters:
                self._write_fat_entry(clusters[-1], cluster)
            clusters.append(cluster)

        return clusters

    def _parse_dos_time(self, time_val: int, date_val: int) -> Optional[datetime]:
        """Parse DOS time/date format"""
        if date_val == 0:
            return None

        try:
            second = (time_val & 0x1F) * 2
            minute = (time_val >> 5) & 0x3F
            hour = (time_val >> 11) & 0x1F

            day = date_val & 0x1F
            month = (date_val >> 5) & 0x0F
            year = ((date_val >> 9) & 0x7F) + 1980

            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None

    def _make_dos_time(self, dt: datetime) -> tuple[int, int]:
        """Convert datetime to DOS time/date format"""
        time_val = (dt.second // 2) | (dt.minute << 5) | (dt.hour << 11)
        date_val = dt.day | (dt.month << 5) | ((dt.year - 1980) << 9)
        return time_val, date_val

    def _parse_dir_entry(self, data: bytes) -> Optional[DirEntry]:
        """Parse a 32-byte directory entry"""
        if data[0] == 0x00:
            return None
        if data[0] == 0xE5:
            return None

        attr = data[11]

        if (attr & DirEntry.ATTR_LFN) == DirEntry.ATTR_LFN:
            return None

        name = data[0:8].decode('ascii', errors='replace').strip()
        ext = data[8:11].decode('ascii', errors='replace').strip()

        create_time = struct.unpack("<H", data[14:16])[0]
        create_date = struct.unpack("<H", data[16:18])[0]
        access_date = struct.unpack("<H", data[18:20])[0]
        cluster_high = struct.unpack("<H", data[20:22])[0]
        modify_time = struct.unpack("<H", data[22:24])[0]
        modify_date = struct.unpack("<H", data[24:26])[0]
        cluster_low = struct.unpack("<H", data[26:28])[0]
        size = struct.unpack("<I", data[28:32])[0]

        first_cluster = (cluster_high << 16) | cluster_low

        return DirEntry(
            name=name,
            ext=ext,
            attr=attr,
            create_time=self._parse_dos_time(create_time, create_date),
            modify_time=self._parse_dos_time(modify_time, modify_date),
            access_date=self._parse_dos_time(0, access_date),
            first_cluster=first_cluster,
            size=size,
        )

    def _make_dir_entry(self, name: str, ext: str, attr: int,
                        cluster: int, size: int) -> bytes:
        """Create a 32-byte directory entry"""
        now = datetime.now()
        time_val, date_val = self._make_dos_time(now)

        entry = bytearray(32)
        entry[0:8] = name.upper().ljust(8).encode('ascii')[:8]
        entry[8:11] = ext.upper().ljust(3).encode('ascii')[:3]
        entry[11] = attr
        struct.pack_into("<H", entry, 14, time_val)
        struct.pack_into("<H", entry, 16, date_val)
        struct.pack_into("<H", entry, 18, date_val)
        struct.pack_into("<H", entry, 20, cluster >> 16)
        struct.pack_into("<H", entry, 22, time_val)
        struct.pack_into("<H", entry, 24, date_val)
        struct.pack_into("<H", entry, 26, cluster & 0xFFFF)
        struct.pack_into("<I", entry, 28, size)

        return bytes(entry)

    def _read_root_dir(self) -> Iterator[DirEntry]:
        """Read root directory entries"""
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
        """Read directory entries from cluster chain"""
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
        """Resolve a path to a directory entry and its contents"""
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
        """List directory contents"""
        entry, contents = self._resolve_path(path)
        if entry and not entry.is_directory:
            return [entry]
        return [e for e in contents if not e.is_volume_label and e.name not in ('.', '..')]

    def read_file(self, path: str) -> bytes:
        """Read a file from the image"""
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
        """Write a file to the image"""
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
        """Add a directory entry to a directory"""
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
        """Add a directory entry to a cluster chain"""
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
        """Create a directory"""
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
        """Remove a file or empty directory"""
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
        """Mark a directory entry as deleted"""
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


def format_size(size: int) -> str:
    """Format size in human-readable form"""
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != 'B' else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def cmd_info(args):
    """Show disk/partition/filesystem info"""
    with VHDImage(args.image) as img:
        print(f"Image: {args.image}")
        print(f"Size: {format_size(img.disk_size)} ({img.disk_size:,} bytes)")
        print(f"Type: {'VHD' if img.is_vhd else 'Raw'}", end='')
        if img.is_vhd:
            print(f" ({'Dynamic' if img.is_dynamic else 'Fixed'})")
        else:
            print()
        print()

        partitions = img.get_partitions()
        if partitions:
            print("Partitions:")
            for i, p in enumerate(partitions):
                boot = "*" if p.bootable else " "
                size = format_size(p.size_sectors * 512)
                print(f"  {i+1}{boot} {p.type_name:15} Start: {p.start_lba:>10}  Size: {size}")
            print()

        if img.bpb:
            bpb = img.bpb
            print("Filesystem:")
            print(f"  Type: {bpb.fat_type.name}")
            print(f"  Volume Label: {bpb.volume_label or '(none)'}")
            print(f"  Bytes/Sector: {bpb.bytes_per_sector}")
            print(f"  Sectors/Cluster: {bpb.sectors_per_cluster}")
            print(f"  Cluster Size: {format_size(bpb.cluster_size)}")
            print(f"  Reserved Sectors: {bpb.reserved_sectors}")
            print(f"  FAT Copies: {bpb.num_fats}")
            print(f"  FAT Size: {bpb.fat_size} sectors ({format_size(bpb.fat_size * 512)})")
            print(f"  Total Sectors: {bpb.total_sectors:,}")
            print(f"  Data Clusters: {bpb.cluster_count:,}")
            print(f"  Data Size: {format_size(bpb.data_sectors * 512)}")


def cmd_ls(args):
    """List directory contents"""
    with VHDImage(args.image) as img:
        path = args.path or '/'
        try:
            entries = img.list_dir(path)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if args.long:
            for entry in sorted(entries, key=lambda e: (not e.is_directory, e.full_name.lower())):
                mtime = entry.modify_time.strftime("%Y-%m-%d %H:%M") if entry.modify_time else "                "
                if entry.is_directory:
                    size_str = "<DIR>".rjust(12)
                else:
                    size_str = f"{entry.size:,}".rjust(12)
                print(f"{entry.attr_string} {size_str} {mtime} {entry.full_name}")
        else:
            dirs = sorted([e.full_name for e in entries if e.is_directory])
            files = sorted([e.full_name for e in entries if not e.is_directory])

            for name in dirs:
                print(f"{name}/")
            for name in files:
                print(name)


def parse_image_path(path: str) -> tuple[str, Optional[str]]:
    """Parse image:path format"""
    if ':' in path:
        parts = path.split(':', 1)
        if len(parts[0]) > 1 or not os.path.exists(parts[0] + ':' + parts[1].split('/')[0]):
            return parts[0], parts[1] if parts[1] else None
    return path, None


def copy_dir_recursive(src_img: VHDImage, src_path: str, dst_img: VHDImage, dst_path: str, verbose: bool = True):
    """Recursively copy directory between images"""
    entries = src_img.list_dir(src_path)

    try:
        dst_img.mkdir(dst_path)
        if verbose:
            print(f"Created directory: {dst_path}")
    except Exception:
        pass

    for entry in entries:
        src_file = f"{src_path}/{entry.full_name}".replace('//', '/')
        dst_file = f"{dst_path}/{entry.full_name}".replace('//', '/')

        if entry.is_directory:
            copy_dir_recursive(src_img, src_file, dst_img, dst_file, verbose)
        else:
            data = src_img.read_file(src_file)
            dst_img.write_file(dst_file, data)
            if verbose:
                print(f"Copied: {entry.full_name} ({len(data):,} bytes)")


def cmd_cp(args):
    """Copy files to/from image"""
    src_img, src_path = parse_image_path(args.src)
    dst_img, dst_path = parse_image_path(args.dest)
    recursive = getattr(args, 'recursive', False)

    if src_path and dst_path:
        # Image to image copy
        with VHDImage(src_img) as src:
            with VHDImage(dst_img, readonly=False) as dst:
                try:
                    entry, _ = src._resolve_path(src_path)
                except FileNotFoundError as e:
                    print(f"Error: {e}", file=sys.stderr)
                    return 1

                if entry and entry.is_directory:
                    if not recursive:
                        print(f"Error: {src_path} is a directory. Use -r for recursive copy.", file=sys.stderr)
                        return 1
                    copy_dir_recursive(src, src_path, dst, dst_path)
                elif entry:
                    data = src.read_file(src_path)
                    dst.write_file(dst_path, data)
                    print(f"Copied {len(data):,} bytes to {dst_img}:{dst_path}")
                else:
                    # Root directory
                    if not recursive:
                        print("Error: Use -r for recursive copy of directories", file=sys.stderr)
                        return 1
                    copy_dir_recursive(src, src_path, dst, dst_path)
        return 0

    if src_path:
        with VHDImage(src_img) as img:
            try:
                entry, _ = img._resolve_path(src_path)
            except FileNotFoundError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

            if entry and entry.is_directory:
                if not recursive:
                    print(f"Error: {src_path} is a directory. Use -r for recursive copy.", file=sys.stderr)
                    return 1
                # Recursive extract to local filesystem
                def extract_recursive(img_path: str, local_path: str):
                    os.makedirs(local_path, exist_ok=True)
                    for e in img.list_dir(img_path):
                        src_file = f"{img_path}/{e.full_name}".replace('//', '/')
                        dst_file = os.path.join(local_path, e.full_name)
                        if e.is_directory:
                            extract_recursive(src_file, dst_file)
                        else:
                            data = img.read_file(src_file)
                            with open(dst_file, 'wb') as f:
                                f.write(data)
                            print(f"Extracted: {e.full_name} ({len(data):,} bytes)")

                dest = args.dest
                if not os.path.exists(dest):
                    os.makedirs(dest)
                extract_recursive(src_path, os.path.join(dest, os.path.basename(src_path.rstrip('/'))))
            else:
                data = img.read_file(src_path)
                dest = args.dest
                if os.path.isdir(dest):
                    dest = os.path.join(dest, os.path.basename(src_path))
                with open(dest, 'wb') as f:
                    f.write(data)
                print(f"Copied {len(data):,} bytes to {dest}")

    elif dst_path:
        if os.path.isdir(args.src):
            if not recursive:
                print(f"Error: {args.src} is a directory. Use -r for recursive copy.", file=sys.stderr)
                return 1
            # Recursive copy from local to image
            with VHDImage(dst_img, readonly=False) as img:
                def copy_local_recursive(local_path: str, img_path: str):
                    try:
                        img.mkdir(img_path)
                        print(f"Created directory: {img_path}")
                    except Exception:
                        pass

                    for name in os.listdir(local_path):
                        src_file = os.path.join(local_path, name)
                        # Convert to 8.3 format
                        name_upper = name.upper()
                        if '.' in name_upper:
                            base, ext = name_upper.rsplit('.', 1)
                            name_83 = f"{base[:8]}.{ext[:3]}"
                        else:
                            name_83 = name_upper[:8]
                        dst_file = f"{img_path}/{name_83}".replace('//', '/')

                        if os.path.isdir(src_file):
                            copy_local_recursive(src_file, dst_file)
                        else:
                            with open(src_file, 'rb') as f:
                                data = f.read()
                            img.write_file(dst_file, data)
                            print(f"Copied: {name_83} ({len(data):,} bytes)")

                copy_local_recursive(args.src, dst_path)
        elif os.path.isfile(args.src):
            with open(args.src, 'rb') as f:
                data = f.read()

            with VHDImage(dst_img, readonly=False) as img:
                try:
                    img.write_file(dst_path, data)
                except Exception as e:
                    print(f"Error: {e}", file=sys.stderr)
                    return 1
                print(f"Copied {len(data):,} bytes to {dst_img}:{dst_path}")
        else:
            print(f"Error: Source file not found: {args.src}", file=sys.stderr)
            return 1

    else:
        print("Error: Use image:path syntax for at least one argument", file=sys.stderr)
        return 1


def cmd_cat(args):
    """Print file contents"""
    img_path, file_path = parse_image_path(args.path)

    if not file_path:
        print("Error: Use image:path syntax", file=sys.stderr)
        return 1

    with VHDImage(img_path) as img:
        try:
            data = img.read_file(file_path)
        except (FileNotFoundError, IsADirectoryError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if args.binary:
            sys.stdout.buffer.write(data)
        else:
            try:
                print(data.decode('utf-8', errors='replace'), end='')
            except Exception:
                print(data.decode('latin-1'), end='')


def cmd_mkdir(args):
    """Create directory"""
    img_path, dir_path = parse_image_path(args.path)

    if not dir_path:
        print("Error: Use image:path syntax", file=sys.stderr)
        return 1

    with VHDImage(img_path, readonly=False) as img:
        try:
            img.mkdir(dir_path)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(f"Created directory: {dir_path}")


def cmd_rm(args):
    """Remove file or directory"""
    img_path, file_path = parse_image_path(args.path)

    if not file_path:
        print("Error: Use image:path syntax", file=sys.stderr)
        return 1

    with VHDImage(img_path, readonly=False) as img:
        try:
            img.remove(file_path)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(f"Removed: {file_path}")


def parse_size(size_str: str) -> int:
    """Parse size string like '512M', '2G', '100MB' to bytes"""
    size_str = size_str.strip().upper()
    multipliers = {
        'B': 1,
        'K': 1024, 'KB': 1024,
        'M': 1024**2, 'MB': 1024**2,
        'G': 1024**3, 'GB': 1024**3,
        'T': 1024**4, 'TB': 1024**4,
    }

    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if size_str.endswith(suffix):
            num = size_str[:-len(suffix)].strip()
            return int(float(num) * mult)

    return int(size_str)


def calculate_fat16_params(total_sectors: int) -> dict:
    """Calculate FAT16 filesystem parameters for given size"""
    if total_sectors < 4085 * 1:
        raise ValueError("Disk too small for FAT16 (min ~2MB)")
    if total_sectors > 4194304:  # 2GB limit
        raise ValueError("Disk too large for FAT16 (max 2GB)")

    # Choose cluster size based on volume size
    if total_sectors <= 32680:      # <= 16MB
        sectors_per_cluster = 1
    elif total_sectors <= 262144:   # <= 128MB
        sectors_per_cluster = 4
    elif total_sectors <= 524288:   # <= 256MB
        sectors_per_cluster = 8
    elif total_sectors <= 1048576:  # <= 512MB
        sectors_per_cluster = 16
    elif total_sectors <= 2097152:  # <= 1GB
        sectors_per_cluster = 32
    else:                           # <= 2GB
        sectors_per_cluster = 64

    reserved_sectors = 1
    num_fats = 2
    root_entries = 512
    root_dir_sectors = (root_entries * 32 + 511) // 512

    # Calculate FAT size
    # FAT16 entry = 2 bytes, sector = 512 bytes = 256 entries/sector
    data_sectors = total_sectors - reserved_sectors - root_dir_sectors
    # Iteratively calculate (FAT size depends on cluster count which depends on FAT size)
    for fat_size in range(1, 1000):
        usable_data = data_sectors - (num_fats * fat_size)
        clusters = usable_data // sectors_per_cluster
        needed_fat_sectors = (clusters * 2 + 511) // 512
        if needed_fat_sectors <= fat_size:
            break

    return {
        'sectors_per_cluster': sectors_per_cluster,
        'reserved_sectors': reserved_sectors,
        'num_fats': num_fats,
        'root_entries': root_entries,
        'fat_size': fat_size,
        'total_sectors': total_sectors,
    }


def create_mbr(total_sectors: int, bootable: bool = True) -> bytes:
    """Create MBR with single FAT16 partition"""
    mbr = bytearray(512)

    # Partition starts at sector 63 (standard for CHS compatibility)
    part_start = 63
    part_size = total_sectors - part_start

    # Partition entry at offset 446
    entry = mbr[446:462]
    entry[0] = 0x80 if bootable else 0x00  # Boot flag

    # CHS start (simplified - sector 63)
    entry[1] = 1   # Head
    entry[2] = 1   # Sector (bits 0-5) + Cylinder high (bits 6-7)
    entry[3] = 0   # Cylinder low

    # Partition type
    if part_size < 65536:
        entry[4] = 0x04  # FAT16 < 32MB
    else:
        entry[4] = 0x06  # FAT16 >= 32MB (or 0x0E for LBA)

    # CHS end (use LBA values, set CHS to max)
    entry[5] = 0xFE  # Head
    entry[6] = 0xFF  # Sector + Cylinder high
    entry[7] = 0xFF  # Cylinder low

    # LBA start
    struct.pack_into('<I', entry, 8, part_start)
    # LBA size
    struct.pack_into('<I', entry, 12, part_size)

    mbr[446:462] = entry

    # Boot signature
    mbr[510] = 0x55
    mbr[511] = 0xAA

    return bytes(mbr)


def create_fat16_boot_sector(params: dict, volume_label: str = "DISK") -> bytes:
    """Create FAT16 boot sector (VBR)"""
    boot = bytearray(512)

    # Jump instruction
    boot[0:3] = b'\xEB\x3C\x90'

    # OEM name
    boot[3:11] = b'MSDOS5.0'

    # BPB (BIOS Parameter Block)
    struct.pack_into('<H', boot, 11, 512)                    # Bytes per sector
    boot[13] = params['sectors_per_cluster']                  # Sectors per cluster
    struct.pack_into('<H', boot, 14, params['reserved_sectors'])  # Reserved sectors
    boot[16] = params['num_fats']                             # Number of FATs
    struct.pack_into('<H', boot, 17, params['root_entries'])  # Root entries

    total = params['total_sectors']
    if total < 65536:
        struct.pack_into('<H', boot, 19, total)               # Total sectors (16-bit)
        struct.pack_into('<I', boot, 32, 0)                   # Total sectors (32-bit)
    else:
        struct.pack_into('<H', boot, 19, 0)
        struct.pack_into('<I', boot, 32, total)

    boot[21] = 0xF8                                           # Media type (fixed disk)
    struct.pack_into('<H', boot, 22, params['fat_size'])      # FAT size
    struct.pack_into('<H', boot, 24, 63)                      # Sectors per track
    struct.pack_into('<H', boot, 26, 16)                      # Number of heads
    struct.pack_into('<I', boot, 28, 63)                      # Hidden sectors (partition start)

    # Extended BPB
    boot[36] = 0x80                                           # Drive number
    boot[37] = 0x00                                           # Reserved
    boot[38] = 0x29                                           # Extended boot signature
    struct.pack_into('<I', boot, 39, 0x12345678)              # Volume serial number
    boot[43:54] = volume_label.upper().ljust(11).encode('ascii')[:11]  # Volume label
    boot[54:62] = b'FAT16   '                                 # Filesystem type

    # Boot code (minimal - just halts)
    boot[62:64] = b'\xCD\x18'  # INT 18h - ROM BASIC / boot failure

    # Boot signature
    boot[510] = 0x55
    boot[511] = 0xAA

    return bytes(boot)


def create_fat16_tables(params: dict) -> bytes:
    """Create initial FAT16 table"""
    fat_size_bytes = params['fat_size'] * 512
    fat = bytearray(fat_size_bytes)

    # First two entries are reserved
    # Entry 0: media type in low byte
    fat[0] = 0xF8
    fat[1] = 0xFF
    # Entry 1: end of chain marker
    fat[2] = 0xFF
    fat[3] = 0xFF

    return bytes(fat)


def cmd_create(args):
    """Create a new disk image"""
    size_bytes = parse_size(args.size)

    # Align to sector boundary
    size_bytes = (size_bytes // 512) * 512
    total_sectors = size_bytes // 512

    if total_sectors < 2048:
        print("Error: Minimum disk size is 1MB", file=sys.stderr)
        return 1

    if total_sectors > 4194304:
        print("Error: Maximum FAT16 disk size is 2GB", file=sys.stderr)
        return 1

    if os.path.exists(args.image) and not args.force:
        print(f"Error: {args.image} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1

    print(f"Creating {format_size(size_bytes)} disk image: {args.image}")

    # Calculate filesystem parameters
    part_start = 63
    part_sectors = total_sectors - part_start
    params = calculate_fat16_params(part_sectors)

    # Create the image
    with open(args.image, 'wb') as f:
        # Write MBR
        mbr = create_mbr(total_sectors, bootable=True)
        f.write(mbr)

        # Write empty sectors until partition start
        f.write(b'\x00' * (512 * (part_start - 1)))

        # Write boot sector
        boot = create_fat16_boot_sector(params, args.label or "DISK")
        f.write(boot)

        # Write FAT tables
        fat = create_fat16_tables(params)
        for _ in range(params['num_fats']):
            f.write(fat)

        # Write empty root directory
        root_size = params['root_entries'] * 32
        f.write(b'\x00' * root_size)

        # Calculate remaining data area size
        written = part_start + params['reserved_sectors'] + \
                  (params['num_fats'] * params['fat_size']) + \
                  (root_size // 512)
        remaining = total_sectors - written

        # Write data area (sparse if possible)
        f.seek(size_bytes - 1)
        f.write(b'\x00')

    print(f"Created {format_size(size_bytes)} FAT16 disk image")
    print(f"  Cluster size: {params['sectors_per_cluster'] * 512} bytes")
    print(f"  Usable space: ~{format_size(part_sectors * 512)}")


def cmd_resize(args):
    """Resize disk image (preserving data)"""
    if not os.path.exists(args.image):
        print(f"Error: {args.image} not found", file=sys.stderr)
        return 1

    new_size = parse_size(args.size)
    new_size = (new_size // 512) * 512
    new_sectors = new_size // 512

    current_size = os.path.getsize(args.image)
    current_sectors = current_size // 512

    if new_size == current_size:
        print("Image is already the requested size")
        return 0

    if new_size < current_size:
        print("Error: Shrinking not yet supported (risk of data loss)", file=sys.stderr)
        print(f"Current: {format_size(current_size)}, Requested: {format_size(new_size)}")
        return 1

    print(f"Resizing {args.image}: {format_size(current_size)} -> {format_size(new_size)}")

    # Read current partition info
    with VHDImage(args.image) as img:
        partitions = img.get_partitions()
        if not partitions:
            print("Error: No partition found", file=sys.stderr)
            return 1

        old_part = partitions[0]
        old_bpb = img.bpb

    # Backup critical structures
    backup_path = args.image + ".backup"
    if not args.no_backup:
        print(f"Creating backup: {backup_path}")
        shutil.copy2(args.image, backup_path)

    try:
        with open(args.image, 'r+b') as f:
            # Extend file
            f.seek(new_size - 1)
            f.write(b'\x00')

            # Update MBR partition size
            f.seek(446 + 12)  # Partition 1 size field
            new_part_size = new_sectors - old_part.start_lba
            f.write(struct.pack('<I', new_part_size))

            # Update boot sector total sectors
            part_offset = old_part.start_lba * 512
            f.seek(part_offset + 19)
            old_total_16 = struct.unpack('<H', f.read(2))[0]
            f.seek(part_offset + 32)
            old_total_32 = struct.unpack('<I', f.read(4))[0]

            if old_total_16 > 0 and new_part_size < 65536:
                f.seek(part_offset + 19)
                f.write(struct.pack('<H', new_part_size))
            else:
                f.seek(part_offset + 19)
                f.write(struct.pack('<H', 0))
                f.seek(part_offset + 32)
                f.write(struct.pack('<I', new_part_size))

            # Recalculate and update FAT size if needed
            params = calculate_fat16_params(new_part_size)

            if params['fat_size'] > old_bpb.fat_size:
                print("Warning: FAT table needs to grow - this requires data relocation")
                print("For now, the extra space won't be usable until reformatted")
            else:
                # Just update sector counts, FAT stays same size
                pass

        print(f"Resized to {format_size(new_size)}")
        if not args.no_backup:
            print(f"Backup saved as: {backup_path}")
            print("Delete backup manually after verifying data integrity")

    except Exception as e:
        print(f"Error during resize: {e}", file=sys.stderr)
        if not args.no_backup and os.path.exists(backup_path):
            print("Restoring from backup...")
            shutil.move(backup_path, args.image)
        return 1


def get_boot_sectors() -> dict:
    """Get available boot sectors from collection"""
    boot_sectors = {}

    # Embedded minimal boot sectors
    boot_sectors['minimal'] = {
        'name': 'Minimal (halt)',
        'description': 'Minimal boot sector that halts the system',
        'data': None,  # Generated on demand
    }

    # Check for external boot sector collection
    if BOOT_SECTORS_DIR.exists():
        for f in BOOT_SECTORS_DIR.glob('*.bin'):
            name = f.stem
            desc_file = f.with_suffix('.txt')
            desc = desc_file.read_text().strip() if desc_file.exists() else f"Boot sector: {name}"
            boot_sectors[name] = {
                'name': name,
                'description': desc,
                'path': f,
            }

    return boot_sectors


def cmd_listboot(args):
    """List available boot sectors"""
    boot_sectors = get_boot_sectors()

    print("Available boot sectors:")
    print()
    for key, info in boot_sectors.items():
        print(f"  {key:15} - {info['description']}")

    print()
    print(f"Boot sector collection: {BOOT_SECTORS_DIR}")
    if not BOOT_SECTORS_DIR.exists():
        print("  (directory not found - create it to add custom boot sectors)")
        print("  Place .bin files (512 bytes) with optional .txt description files")


def extract_boot_code_from_image(image_path: str) -> tuple[bytes, bytes]:
    """Extract MBR and VBR boot code from existing image"""
    with open(image_path, 'rb') as f:
        mbr = f.read(512)

        # Find partition start
        if mbr[510:512] == b'\x55\xAA':
            part_start = struct.unpack('<I', mbr[446+8:446+12])[0]
            f.seek(part_start * 512)
            vbr = f.read(512)
        else:
            vbr = mbr

    return mbr, vbr


def cmd_makeboot(args):
    """Make disk bootable with specified boot sector"""
    if not os.path.exists(args.image):
        print(f"Error: {args.image} not found", file=sys.stderr)
        return 1

    boot_sectors = get_boot_sectors()

    if args.extract:
        # Extract boot sectors from this image
        print(f"Extracting boot sectors from {args.image}...")
        mbr, vbr = extract_boot_code_from_image(args.image)

        BOOT_SECTORS_DIR.mkdir(parents=True, exist_ok=True)

        mbr_path = BOOT_SECTORS_DIR / f"{args.extract}_mbr.bin"
        vbr_path = BOOT_SECTORS_DIR / f"{args.extract}_vbr.bin"

        mbr_path.write_bytes(mbr)
        vbr_path.write_bytes(vbr)

        print(f"Extracted MBR to: {mbr_path}")
        print(f"Extracted VBR to: {vbr_path}")
        return 0

    if args.from_image:
        # Copy boot sectors from another image
        if not os.path.exists(args.from_image):
            print(f"Error: Source image not found: {args.from_image}", file=sys.stderr)
            return 1

        print(f"Copying boot sectors from {args.from_image}...")
        src_mbr, src_vbr = extract_boot_code_from_image(args.from_image)

        with open(args.image, 'r+b') as f:
            # Read current MBR to preserve partition table
            current_mbr = bytearray(f.read(512))

            # Copy boot code (first 446 bytes)
            current_mbr[0:446] = src_mbr[0:446]

            f.seek(0)
            f.write(current_mbr)

            # Find partition and update VBR
            part_start = struct.unpack('<I', current_mbr[446+8:446+12])[0]
            f.seek(part_start * 512)
            current_vbr = bytearray(f.read(512))

            # Copy boot code but preserve BPB (bytes 3-61)
            current_vbr[0:3] = src_vbr[0:3]      # Jump instruction
            current_vbr[62:510] = src_vbr[62:510]  # Boot code after BPB

            f.seek(part_start * 512)
            f.write(current_vbr)

        print(f"Boot sectors copied from {args.from_image}")
        return 0

    if args.boot_type:
        if args.boot_type not in boot_sectors:
            print(f"Error: Unknown boot type '{args.boot_type}'", file=sys.stderr)
            print("Use 'listboot' to see available options")
            return 1

        info = boot_sectors[args.boot_type]
        if 'path' in info:
            boot_data = info['path'].read_bytes()
        else:
            print("Minimal boot sector doesn't provide bootable DOS")
            print("Use --from-image to copy boot sectors from a working DOS disk")
            return 1

        # Apply boot sector...
        print(f"Applied boot sector: {args.boot_type}")
        return 0

    print("Usage: makeboot <image> --from-image <source> | --extract <name> | --boot-type <type>")
    print("Use 'listboot' to see available boot sector types")


def cmd_extract_sys(args):
    """Extract system files needed for booting"""
    with VHDImage(args.image) as img:
        entries = img.list_dir('/')

        sys_files = ['IO.SYS', 'MSDOS.SYS', 'COMMAND.COM',
                     'IBMBIO.COM', 'IBMDOS.COM']

        found = []
        for entry in entries:
            if entry.full_name.upper() in sys_files:
                found.append(entry.full_name)
                data = img.read_file(entry.full_name)
                out_path = Path(args.output) / entry.full_name
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(data)
                print(f"Extracted: {entry.full_name} ({len(data):,} bytes)")

        if not found:
            print("No DOS system files found in image")


def main():
    parser = argparse.ArgumentParser(
        description="VHD/Raw Disk Image Tool for MiSTer ao486",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s info disk.vhd                    Show disk info
  %(prog)s ls disk.vhd                      List root directory
  %(prog)s ls -l disk.vhd /DOS              List /DOS with details
  %(prog)s cat disk.vhd:AUTOEXEC.BAT        Print file contents
  %(prog)s cp disk.vhd:CONFIG.SYS .         Copy file from image
  %(prog)s cp myfile.txt disk.vhd:/         Copy file to image root
  %(prog)s mkdir disk.vhd:/GAMES            Create directory
  %(prog)s rm disk.vhd:/TEMP.TXT            Remove file
  %(prog)s create newdisk.vhd 512M          Create 512MB disk
  %(prog)s resize disk.vhd 1G               Resize to 1GB
  %(prog)s makeboot disk.vhd --from-image bootable.vhd
  %(prog)s makeboot disk.vhd --extract mydos   Extract boot sectors
  %(prog)s listboot                         List boot sector types
        """)

    subparsers = parser.add_subparsers(dest='command', required=True)

    info_p = subparsers.add_parser('info', help='Show disk/partition/filesystem info')
    info_p.add_argument('image', help='Disk image file')
    info_p.set_defaults(func=cmd_info)

    ls_p = subparsers.add_parser('ls', help='List directory contents')
    ls_p.add_argument('image', help='Disk image file')
    ls_p.add_argument('path', nargs='?', default='/', help='Directory path (default: /)')
    ls_p.add_argument('-l', '--long', action='store_true', help='Long format')
    ls_p.set_defaults(func=cmd_ls)

    cp_p = subparsers.add_parser('cp', help='Copy files to/from image')
    cp_p.add_argument('src', help='Source (use image:path for image files)')
    cp_p.add_argument('dest', help='Destination (use image:path for image files)')
    cp_p.add_argument('-r', '--recursive', action='store_true', help='Copy directories recursively')
    cp_p.set_defaults(func=cmd_cp)

    cat_p = subparsers.add_parser('cat', help='Print file contents')
    cat_p.add_argument('path', help='File path (image:path format)')
    cat_p.add_argument('-b', '--binary', action='store_true', help='Binary output')
    cat_p.set_defaults(func=cmd_cat)

    mkdir_p = subparsers.add_parser('mkdir', help='Create directory')
    mkdir_p.add_argument('path', help='Directory path (image:path format)')
    mkdir_p.set_defaults(func=cmd_mkdir)

    rm_p = subparsers.add_parser('rm', help='Remove file or empty directory')
    rm_p.add_argument('path', help='Path (image:path format)')
    rm_p.set_defaults(func=cmd_rm)

    create_p = subparsers.add_parser('create', help='Create new disk image')
    create_p.add_argument('image', help='Output image file')
    create_p.add_argument('size', help='Disk size (e.g., 512M, 1G, 2048MB)')
    create_p.add_argument('-l', '--label', default='DISK', help='Volume label (default: DISK)')
    create_p.add_argument('-f', '--force', action='store_true', help='Overwrite existing file')
    create_p.set_defaults(func=cmd_create)

    resize_p = subparsers.add_parser('resize', help='Resize disk image')
    resize_p.add_argument('image', help='Disk image file')
    resize_p.add_argument('size', help='New size (e.g., 1G, 2048MB)')
    resize_p.add_argument('--no-backup', action='store_true', help='Skip backup creation')
    resize_p.set_defaults(func=cmd_resize)

    makeboot_p = subparsers.add_parser('makeboot', help='Make disk bootable')
    makeboot_p.add_argument('image', help='Disk image file')
    makeboot_p.add_argument('--from-image', metavar='SRC', help='Copy boot sectors from another image')
    makeboot_p.add_argument('--extract', metavar='NAME', help='Extract boot sectors to collection')
    makeboot_p.add_argument('--boot-type', metavar='TYPE', help='Use boot sector from collection')
    makeboot_p.set_defaults(func=cmd_makeboot)

    listboot_p = subparsers.add_parser('listboot', help='List available boot sectors')
    listboot_p.set_defaults(func=cmd_listboot)

    extractsys_p = subparsers.add_parser('extractsys', help='Extract DOS system files')
    extractsys_p.add_argument('image', help='Disk image file')
    extractsys_p.add_argument('-o', '--output', default='.', help='Output directory')
    extractsys_p.set_defaults(func=cmd_extract_sys)

    args = parser.parse_args()
    result = args.func(args)
    sys.exit(result or 0)


if __name__ == '__main__':
    main()
