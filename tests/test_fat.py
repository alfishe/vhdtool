"""Tests for FAT filesystem structures."""

import pytest
from vhdtool.fat import BPB, DirEntry, FATType


class TestBPB:
    def test_fat16_detection(self):
        bpb = BPB(
            bytes_per_sector=512,
            sectors_per_cluster=4,
            reserved_sectors=1,
            num_fats=2,
            root_entries=512,
            total_sectors_16=0,
            media_type=0xF8,
            fat_size_16=128,
            sectors_per_track=63,
            num_heads=16,
            hidden_sectors=63,
            total_sectors_32=200000,
        )
        assert bpb.fat_type == FATType.FAT16

    def test_fat12_detection(self):
        bpb = BPB(
            bytes_per_sector=512,
            sectors_per_cluster=1,
            reserved_sectors=1,
            num_fats=2,
            root_entries=224,
            total_sectors_16=2880,
            media_type=0xF0,
            fat_size_16=9,
            sectors_per_track=18,
            num_heads=2,
            hidden_sectors=0,
            total_sectors_32=0,
        )
        assert bpb.fat_type == FATType.FAT12

    def test_cluster_size(self):
        bpb = BPB(
            bytes_per_sector=512,
            sectors_per_cluster=8,
            reserved_sectors=1,
            num_fats=2,
            root_entries=512,
            total_sectors_16=0,
            media_type=0xF8,
            fat_size_16=128,
            sectors_per_track=63,
            num_heads=16,
            hidden_sectors=63,
            total_sectors_32=200000,
        )
        assert bpb.cluster_size == 4096

    def test_total_sectors_prefers_32bit(self):
        bpb = BPB(
            bytes_per_sector=512,
            sectors_per_cluster=4,
            reserved_sectors=1,
            num_fats=2,
            root_entries=512,
            total_sectors_16=1000,
            media_type=0xF8,
            fat_size_16=128,
            sectors_per_track=63,
            num_heads=16,
            hidden_sectors=63,
            total_sectors_32=200000,
        )
        assert bpb.total_sectors == 200000


class TestDirEntry:
    def test_directory_detection(self):
        entry = DirEntry(
            name="DOS",
            ext="",
            attr=DirEntry.ATTR_DIRECTORY,
            create_time=None,
            modify_time=None,
            access_date=None,
            first_cluster=100,
            size=0,
        )
        assert entry.is_directory
        assert not entry.is_volume_label

    def test_full_name_with_ext(self):
        entry = DirEntry(
            name="CONFIG",
            ext="SYS",
            attr=DirEntry.ATTR_ARCHIVE,
            create_time=None,
            modify_time=None,
            access_date=None,
            first_cluster=50,
            size=1024,
        )
        assert entry.full_name == "CONFIG.SYS"

    def test_full_name_without_ext(self):
        entry = DirEntry(
            name="README",
            ext="",
            attr=DirEntry.ATTR_ARCHIVE,
            create_time=None,
            modify_time=None,
            access_date=None,
            first_cluster=50,
            size=1024,
        )
        assert entry.full_name == "README"

    def test_attr_string(self):
        entry = DirEntry(
            name="IO",
            ext="SYS",
            attr=DirEntry.ATTR_HIDDEN | DirEntry.ATTR_SYSTEM | DirEntry.ATTR_READ_ONLY,
            create_time=None,
            modify_time=None,
            access_date=None,
            first_cluster=2,
            size=40000,
        )
        assert entry.attr_string == "-rhs-"

    def test_roundtrip_serialization(self):
        entry = DirEntry(
            name="TEST",
            ext="TXT",
            attr=DirEntry.ATTR_ARCHIVE,
            create_time=None,
            modify_time=None,
            access_date=None,
            first_cluster=100,
            size=5000,
        )
        data = entry.to_bytes()
        assert len(data) == 32

        parsed = DirEntry.from_bytes(data)
        assert parsed.name == "TEST"
        assert parsed.ext == "TXT"
        assert parsed.first_cluster == 100
        assert parsed.size == 5000
