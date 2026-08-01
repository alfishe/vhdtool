"""FAT filesystem structures and parsing."""

import struct
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Optional


class FATType(IntEnum):
    """FAT filesystem types."""
    FAT12 = 12
    FAT16 = 16
    FAT32 = 32


@dataclass
class BPB:
    """BIOS Parameter Block - FAT filesystem metadata."""
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
    # FAT32 extended fields
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

    @classmethod
    def from_bytes(cls, data: bytes) -> "BPB":
        """Parse BPB from boot sector."""
        if len(data) < 512:
            raise ValueError("Boot sector must be at least 512 bytes")

        bytes_per_sector = struct.unpack("<H", data[11:13])[0]
        sectors_per_cluster = data[13]
        reserved_sectors = struct.unpack("<H", data[14:16])[0]
        num_fats = data[16]
        root_entries = struct.unpack("<H", data[17:19])[0]
        total_sectors_16 = struct.unpack("<H", data[19:21])[0]
        media_type = data[21]
        fat_size_16 = struct.unpack("<H", data[22:24])[0]
        sectors_per_track = struct.unpack("<H", data[24:26])[0]
        num_heads = struct.unpack("<H", data[26:28])[0]
        hidden_sectors = struct.unpack("<I", data[28:32])[0]
        total_sectors_32 = struct.unpack("<I", data[32:36])[0]

        # FAT32 extended fields
        if fat_size_16 == 0:
            fat_size_32 = struct.unpack("<I", data[36:40])[0]
            root_cluster = struct.unpack("<I", data[44:48])[0]
            fs_info_sector = struct.unpack("<H", data[48:50])[0]
            volume_label = data[71:82].decode('ascii', errors='replace').strip()
            fs_type = data[82:90].decode('ascii', errors='replace').strip()
        else:
            fat_size_32 = 0
            root_cluster = 2
            fs_info_sector = 0
            volume_label = data[43:54].decode('ascii', errors='replace').strip()
            fs_type = data[54:62].decode('ascii', errors='replace').strip()

        return cls(
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


@dataclass
class DirEntry:
    """FAT directory entry."""
    name: str
    ext: str
    attr: int
    create_time: Optional[datetime]
    modify_time: Optional[datetime]
    access_date: Optional[datetime]
    first_cluster: int
    size: int

    # Attribute flags
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
        """Human-readable attribute string like 'Drhs-'."""
        attrs = []
        attrs.append("D" if self.is_directory else "-")
        attrs.append("r" if self.attr & self.ATTR_READ_ONLY else "-")
        attrs.append("h" if self.is_hidden else "-")
        attrs.append("s" if self.is_system else "-")
        attrs.append("a" if self.attr & self.ATTR_ARCHIVE else "-")
        return "".join(attrs)

    @classmethod
    def from_bytes(cls, data: bytes) -> Optional["DirEntry"]:
        """Parse a 32-byte directory entry."""
        if len(data) != 32:
            raise ValueError("Directory entry must be 32 bytes")

        # Check for empty or deleted entry
        if data[0] == 0x00 or data[0] == 0xE5:
            return None

        attr = data[11]

        # Skip long filename entries
        if (attr & cls.ATTR_LFN) == cls.ATTR_LFN:
            return None

        name = data[0:8].decode('ascii', errors='replace').strip()
        ext = data[8:11].decode('ascii', errors='replace').strip()

        create_time_raw = struct.unpack("<H", data[14:16])[0]
        create_date_raw = struct.unpack("<H", data[16:18])[0]
        access_date_raw = struct.unpack("<H", data[18:20])[0]
        cluster_high = struct.unpack("<H", data[20:22])[0]
        modify_time_raw = struct.unpack("<H", data[22:24])[0]
        modify_date_raw = struct.unpack("<H", data[24:26])[0]
        cluster_low = struct.unpack("<H", data[26:28])[0]
        size = struct.unpack("<I", data[28:32])[0]

        first_cluster = (cluster_high << 16) | cluster_low

        return cls(
            name=name,
            ext=ext,
            attr=attr,
            create_time=_parse_dos_datetime(create_time_raw, create_date_raw),
            modify_time=_parse_dos_datetime(modify_time_raw, modify_date_raw),
            access_date=_parse_dos_datetime(0, access_date_raw),
            first_cluster=first_cluster,
            size=size,
        )

    def to_bytes(self) -> bytes:
        """Serialize to 32-byte directory entry."""
        entry = bytearray(32)

        # Name and extension (8.3 format)
        entry[0:8] = self.name.upper().ljust(8).encode('ascii')[:8]
        entry[8:11] = self.ext.upper().ljust(3).encode('ascii')[:3]

        # Attributes
        entry[11] = self.attr

        # Timestamps
        now = datetime.now()
        time_val, date_val = _make_dos_datetime(now)
        struct.pack_into("<H", entry, 14, time_val)  # Create time
        struct.pack_into("<H", entry, 16, date_val)  # Create date
        struct.pack_into("<H", entry, 18, date_val)  # Access date
        struct.pack_into("<H", entry, 20, self.first_cluster >> 16)  # Cluster high
        struct.pack_into("<H", entry, 22, time_val)  # Modify time
        struct.pack_into("<H", entry, 24, date_val)  # Modify date
        struct.pack_into("<H", entry, 26, self.first_cluster & 0xFFFF)  # Cluster low
        struct.pack_into("<I", entry, 28, self.size)

        return bytes(entry)


def _parse_dos_datetime(time_val: int, date_val: int) -> Optional[datetime]:
    """Parse DOS time/date format to datetime."""
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


def _make_dos_datetime(dt: datetime) -> tuple[int, int]:
    """Convert datetime to DOS time/date format."""
    time_val = (dt.second // 2) | (dt.minute << 5) | (dt.hour << 11)
    date_val = dt.day | (dt.month << 5) | ((dt.year - 1980) << 9)
    return time_val, date_val
