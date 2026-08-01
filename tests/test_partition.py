"""Tests for partition handling."""

import pytest
from vhdtool.partition import PartitionEntry, parse_mbr_partitions, create_mbr


class TestPartitionEntry:
    def test_type_name_fat16(self):
        entry = PartitionEntry(bootable=True, type_code=0x06, start_lba=63, size_sectors=100000)
        assert entry.type_name == "FAT16"

    def test_type_name_unknown(self):
        entry = PartitionEntry(bootable=False, type_code=0x99, start_lba=63, size_sectors=1000)
        assert "Unknown" in entry.type_name

    def test_size_bytes(self):
        entry = PartitionEntry(bootable=True, type_code=0x06, start_lba=63, size_sectors=2048)
        assert entry.size_bytes == 2048 * 512

    def test_roundtrip_serialization(self):
        entry = PartitionEntry(bootable=True, type_code=0x0B, start_lba=2048, size_sectors=500000)
        data = entry.to_bytes()
        assert len(data) == 16

        parsed = PartitionEntry.from_bytes(data)
        assert parsed.bootable == True
        assert parsed.type_code == 0x0B
        assert parsed.start_lba == 2048
        assert parsed.size_sectors == 500000


class TestMBRParsing:
    def test_empty_mbr(self):
        mbr = bytes(512)
        partitions = parse_mbr_partitions(mbr)
        assert partitions == []

    def test_valid_mbr_with_signature(self):
        mbr = bytearray(512)
        mbr[510] = 0x55
        mbr[511] = 0xAA
        partitions = parse_mbr_partitions(mbr)
        assert partitions == []

    def test_floppy_detection(self):
        mbr = bytearray(512)
        mbr[0] = 0xEB  # Jump instruction
        mbr[11] = 0x00  # Bytes per sector (512)
        mbr[12] = 0x02
        mbr[21] = 0xF0  # Media byte (floppy)
        mbr[510] = 0x55
        mbr[511] = 0xAA
        partitions = parse_mbr_partitions(bytes(mbr))
        assert partitions == []


class TestMBRCreation:
    def test_create_mbr_signature(self):
        mbr = create_mbr([])
        assert mbr[510:512] == b'\x55\xAA'

    def test_create_mbr_with_partition(self):
        part = PartitionEntry(bootable=True, type_code=0x06, start_lba=63, size_sectors=100000)
        mbr = create_mbr([part])

        parsed = parse_mbr_partitions(mbr)
        assert len(parsed) == 1
        assert parsed[0].bootable == True
        assert parsed[0].type_code == 0x06
        assert parsed[0].start_lba == 63
        assert parsed[0].size_sectors == 100000
