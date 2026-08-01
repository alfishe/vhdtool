"""Partition table handling for MBR disks."""

import struct
from dataclasses import dataclass

PARTITION_TYPES = {
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


@dataclass
class PartitionEntry:
    """MBR partition table entry."""
    bootable: bool
    type_code: int
    start_lba: int
    size_sectors: int

    @property
    def type_name(self) -> str:
        return PARTITION_TYPES.get(self.type_code, f"Unknown (0x{self.type_code:02X})")

    @property
    def size_bytes(self) -> int:
        return self.size_sectors * 512

    @classmethod
    def from_bytes(cls, data: bytes) -> "PartitionEntry":
        """Parse a 16-byte partition entry."""
        if len(data) != 16:
            raise ValueError("Partition entry must be 16 bytes")

        bootable = data[0] == 0x80
        type_code = data[4]
        start_lba = struct.unpack("<I", data[8:12])[0]
        size_sectors = struct.unpack("<I", data[12:16])[0]

        return cls(bootable, type_code, start_lba, size_sectors)

    def to_bytes(self) -> bytes:
        """Serialize to 16-byte partition entry."""
        entry = bytearray(16)
        entry[0] = 0x80 if self.bootable else 0x00
        # CHS values (simplified)
        entry[1] = 0x01  # Start head
        entry[2] = 0x01  # Start sector
        entry[3] = 0x00  # Start cylinder
        entry[4] = self.type_code
        entry[5] = 0xFE  # End head
        entry[6] = 0xFF  # End sector/cylinder
        entry[7] = 0xFF  # End cylinder
        struct.pack_into("<I", entry, 8, self.start_lba)
        struct.pack_into("<I", entry, 12, self.size_sectors)
        return bytes(entry)


def parse_mbr_partitions(mbr: bytes) -> list[PartitionEntry]:
    """Parse partition table from MBR."""
    if len(mbr) != 512:
        raise ValueError("MBR must be 512 bytes")

    if mbr[510:512] != b'\x55\xAA':
        return []

    # Check if this is a floppy (no partition table)
    if mbr[0] in (0xEB, 0xE9) and mbr[21] in (0xF0, 0xF8, 0xF9, 0xFA, 0xFB, 0xFC, 0xFD, 0xFE, 0xFF):
        bytes_per_sector = struct.unpack("<H", mbr[11:13])[0]
        if bytes_per_sector in (512, 1024, 2048, 4096):
            return []

    partitions = []
    for i in range(4):
        offset = 446 + (i * 16)
        entry_data = mbr[offset:offset + 16]
        if entry_data[4] != 0:  # Non-empty partition
            partitions.append(PartitionEntry.from_bytes(entry_data))

    return partitions


def create_mbr(partitions: list[PartitionEntry], boot_code: bytes = None) -> bytes:
    """Create an MBR with the given partitions and optional boot code."""
    mbr = bytearray(512)

    # Boot code (first 446 bytes)
    if boot_code:
        mbr[0:min(len(boot_code), 446)] = boot_code[:446]

    # Partition table
    for i, part in enumerate(partitions[:4]):
        offset = 446 + (i * 16)
        mbr[offset:offset + 16] = part.to_bytes()

    # Boot signature
    mbr[510] = 0x55
    mbr[511] = 0xAA

    return bytes(mbr)
