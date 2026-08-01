"""Tests for utility functions."""

import pytest
from vhdtool.utils import format_size, parse_size, parse_image_path


class TestFormatSize:
    def test_bytes(self):
        assert format_size(100) == "100 B"

    def test_kilobytes(self):
        assert format_size(2048) == "2.0 KB"

    def test_megabytes(self):
        assert format_size(10 * 1024 * 1024) == "10.0 MB"

    def test_gigabytes(self):
        assert format_size(2 * 1024 * 1024 * 1024) == "2.0 GB"


class TestParseSize:
    def test_bytes(self):
        assert parse_size("1024B") == 1024

    def test_kilobytes(self):
        assert parse_size("64K") == 64 * 1024
        assert parse_size("64KB") == 64 * 1024

    def test_megabytes(self):
        assert parse_size("512M") == 512 * 1024 * 1024
        assert parse_size("512MB") == 512 * 1024 * 1024

    def test_gigabytes(self):
        assert parse_size("2G") == 2 * 1024 * 1024 * 1024
        assert parse_size("2GB") == 2 * 1024 * 1024 * 1024

    def test_raw_number(self):
        assert parse_size("1048576") == 1048576

    def test_case_insensitive(self):
        assert parse_size("100m") == parse_size("100M")
        assert parse_size("1gb") == parse_size("1GB")


class TestParseImagePath:
    def test_image_with_path(self):
        img, path = parse_image_path("disk.vhd:/DOS/GAMES")
        assert img == "disk.vhd"
        assert path == "/DOS/GAMES"

    def test_image_only(self):
        img, path = parse_image_path("disk.vhd")
        assert img == "disk.vhd"
        assert path is None

    def test_root_path(self):
        img, path = parse_image_path("disk.vhd:/")
        assert img == "disk.vhd"
        assert path == "/"
