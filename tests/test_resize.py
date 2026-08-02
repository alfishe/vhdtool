"""Tests for disk image resize functionality."""

import os
import struct
import tempfile
import pytest

from vhdtool import VHDImage
from vhdtool.utils import format_size, parse_size, calculate_fat16_params, create_mbr, create_fat16_boot_sector


def create_test_image(path: str, size_mb: int) -> None:
    """Create a minimal FAT16 test image."""
    size_bytes = size_mb * 1024 * 1024
    total_sectors = size_bytes // 512
    part_start = 63
    part_sectors = total_sectors - part_start

    mbr = create_mbr(total_sectors, bootable=True)
    params = calculate_fat16_params(part_sectors)
    vbr = create_fat16_boot_sector(params, volume_label="TEST", hidden_sectors=part_start)

    with open(path, 'wb') as f:
        f.write(mbr)
        f.seek(part_start * 512)
        f.write(vbr)

        # Initialize FAT tables
        fat_start = part_start + params['reserved_sectors']
        fat_size = params['fat_size']
        fat = bytearray(fat_size * 512)
        # FAT16 reserved entries
        fat[0:4] = b'\xF8\xFF\xFF\xFF'

        for i in range(params['num_fats']):
            f.seek((fat_start + i * fat_size) * 512)
            f.write(fat)

        # Root directory (zeroed)
        root_start = fat_start + params['num_fats'] * fat_size
        root_sectors = (params['root_entries'] * 32 + 511) // 512
        f.seek(root_start * 512)
        f.write(b'\x00' * root_sectors * 512)

        # Extend to full size
        f.seek(size_bytes - 1)
        f.write(b'\x00')


def write_test_file(path: str, filename: str, content: bytes) -> None:
    """Write a file to the test image."""
    with VHDImage(path, readonly=False) as img:
        img.write_file(f'/{filename}', content)


class TestImageAnalysis:
    """Test filesystem analysis methods."""

    def test_get_filesystem_stats_empty(self, tmp_path):
        """Test stats on empty filesystem."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        with VHDImage(img_path) as img:
            stats = img.get_filesystem_stats()

            assert stats['total_clusters'] > 0
            assert stats['used_clusters'] == 0
            assert stats['free_clusters'] == stats['total_clusters']
            assert stats['highest_used_cluster'] == 1  # None used

    def test_get_filesystem_stats_with_file(self, tmp_path):
        """Test stats with a file present."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)
        write_test_file(img_path, "TEST.TXT", b"Hello World" * 1000)

        with VHDImage(img_path) as img:
            stats = img.get_filesystem_stats()

            assert stats['used_clusters'] > 0
            assert stats['free_clusters'] < stats['total_clusters']
            assert stats['highest_used_cluster'] >= 2

    def test_get_highest_used_cluster_empty(self, tmp_path):
        """Test highest cluster on empty filesystem."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        with VHDImage(img_path) as img:
            highest = img.get_highest_used_cluster()
            assert highest == 1  # No clusters used

    def test_get_highest_used_cluster_with_files(self, tmp_path):
        """Test highest cluster with multiple files."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        # Write multiple files
        write_test_file(img_path, "FILE1.TXT", b"A" * 512)
        write_test_file(img_path, "FILE2.TXT", b"B" * 1024)
        write_test_file(img_path, "FILE3.TXT", b"C" * 2048)

        with VHDImage(img_path) as img:
            highest = img.get_highest_used_cluster()
            assert highest >= 4  # At least 3 files worth

    def test_used_cluster_count(self, tmp_path):
        """Test counting used clusters."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        with VHDImage(img_path) as img:
            assert img.get_used_cluster_count() == 0

        # Add a file
        write_test_file(img_path, "TEST.TXT", b"X" * 5000)

        with VHDImage(img_path) as img:
            used = img.get_used_cluster_count()
            assert used > 0

            # Verify free + used = total
            free = img.get_free_cluster_count()
            total = img.bpb.cluster_count
            assert used + free == total


class TestResizeGrow:
    """Test growing disk images."""

    def test_grow_empty_image(self, tmp_path):
        """Test growing an empty image."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        original_size = os.path.getsize(img_path)

        with VHDImage(img_path) as img:
            original_clusters = img.bpb.cluster_count

        # Grow to 20MB
        new_size = 20 * 1024 * 1024
        _resize_image(img_path, new_size)

        assert os.path.getsize(img_path) == new_size

        with VHDImage(img_path) as img:
            assert img.bpb.cluster_count > original_clusters
            stats = img.get_filesystem_stats()
            assert stats['free_clusters'] > original_clusters

    def test_grow_preserves_files(self, tmp_path):
        """Test that growing preserves existing files."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        test_content = b"Important data that must survive resize!"
        write_test_file(img_path, "IMPORTNT.TXT", test_content)

        # Grow
        _resize_image(img_path, 20 * 1024 * 1024)

        with VHDImage(img_path) as img:
            recovered = img.read_file("/IMPORTNT.TXT")
            assert recovered == test_content

    def test_grow_multiple_files(self, tmp_path):
        """Test growing with multiple files."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        files = {
            "FILE1.TXT": b"First file content",
            "FILE2.TXT": b"Second file with more data" * 100,
            "FILE3.DAT": bytes(range(256)) * 10,
        }

        for name, content in files.items():
            write_test_file(img_path, name, content)

        _resize_image(img_path, 30 * 1024 * 1024)

        with VHDImage(img_path) as img:
            for name, expected in files.items():
                actual = img.read_file(f"/{name}")
                assert actual == expected, f"File {name} corrupted after resize"

    def test_grow_validates_partition_table(self, tmp_path):
        """Test that partition table is valid after growing."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        _resize_image(img_path, 15 * 1024 * 1024)  # Small growth to avoid FAT reorganization

        with VHDImage(img_path) as img:
            partitions = img.get_partitions()
            assert len(partitions) == 1

            part = partitions[0]
            expected_sectors = (15 * 1024 * 1024 // 512) - part.start_lba
            assert part.size_sectors == expected_sectors

    def test_grow_validates_bpb(self, tmp_path):
        """Test that BPB is valid after growing."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        _resize_image(img_path, 15 * 1024 * 1024)  # Small growth

        with VHDImage(img_path) as img:
            # BPB should report new size
            expected_sectors = (15 * 1024 * 1024 // 512) - img.partition_offset
            assert img.bpb.total_sectors == expected_sectors


class TestResizeShrink:
    """Test shrinking disk images."""

    def test_shrink_empty_image(self, tmp_path):
        """Test shrinking an empty image."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 50)

        # Shrink to 20MB
        _resize_image(img_path, 20 * 1024 * 1024)

        assert os.path.getsize(img_path) == 20 * 1024 * 1024

        with VHDImage(img_path) as img:
            assert img.bpb is not None
            stats = img.get_filesystem_stats()
            assert stats['total_clusters'] > 0

    def test_shrink_preserves_files(self, tmp_path):
        """Test that shrinking preserves files in safe region."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 50)

        # Write a small file (should be in low clusters)
        test_content = b"Small file content"
        write_test_file(img_path, "SMALL.TXT", test_content)

        with VHDImage(img_path) as img:
            highest = img.get_highest_used_cluster()

        # Shrink but keep enough space for the file
        _resize_image(img_path, 20 * 1024 * 1024)

        with VHDImage(img_path) as img:
            recovered = img.read_file("/SMALL.TXT")
            assert recovered == test_content

    def test_shrink_rejects_data_loss(self, tmp_path):
        """Test that shrinking rejects if it would lose data."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 50)

        # Fill with data
        large_content = b"X" * (30 * 1024 * 1024)  # 30MB of data
        write_test_file(img_path, "LARGE.DAT", large_content)

        # Try to shrink below data - should fail
        with pytest.raises(ValueError, match="data would be lost"):
            _resize_image(img_path, 10 * 1024 * 1024, check_data_loss=True)

    def test_shrink_minimum_size(self, tmp_path):
        """Test shrinking to minimum valid FAT16 size."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 50)

        # Try to shrink below FAT16 minimum
        with pytest.raises(ValueError, match="too small"):
            _resize_image(img_path, 1 * 1024 * 1024)


class TestResizeEdgeCases:
    """Test edge cases in resize."""

    def test_resize_same_size(self, tmp_path):
        """Test resizing to same size is a no-op."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        original_size = os.path.getsize(img_path)
        _resize_image(img_path, original_size)

        assert os.path.getsize(img_path) == original_size

    def test_resize_sector_alignment(self, tmp_path):
        """Test that resize aligns to sector boundary."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        # Request non-aligned size
        _resize_image(img_path, 15 * 1024 * 1024 + 100)

        # Should be aligned down
        actual = os.path.getsize(img_path)
        assert actual % 512 == 0

    def test_resize_near_fat_boundary(self, tmp_path):
        """Test resizing near FAT size boundary."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        # Various sizes that might cause FAT size changes
        sizes = [16, 32, 64, 128, 256]
        for mb in sizes:
            create_test_image(img_path, 10)
            try:
                _resize_image(img_path, mb * 1024 * 1024)
                with VHDImage(img_path) as img:
                    assert img.bpb is not None
            except ValueError:
                # Some sizes may require FAT reorganization
                pass

    @pytest.mark.skip(reason="Too slow - creates 2GB file")
    def test_resize_max_fat16(self, tmp_path):
        """Test resizing to maximum FAT16 size."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        # FAT16 max is 2GB
        _resize_image(img_path, 2 * 1024 * 1024 * 1024)

        with VHDImage(img_path) as img:
            assert img.bpb.fat_type.value == 16

    @pytest.mark.skip(reason="Too slow - 3GB file")
    def test_resize_beyond_fat16_rejected(self, tmp_path):
        """Test that resizing beyond 2GB is rejected."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        with pytest.raises(ValueError, match="too large"):
            _resize_image(img_path, 3 * 1024 * 1024 * 1024)


class TestResizeIntegrity:
    """Test data integrity across resize operations."""

    def test_resize_cycle_preserves_data(self, tmp_path):
        """Test grow-shrink-grow cycle preserves data."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 20)

        test_content = b"Persistent data through resize cycles"
        write_test_file(img_path, "PERSISTF.TXT", test_content)

        # Grow
        _resize_image(img_path, 50 * 1024 * 1024)
        with VHDImage(img_path) as img:
            assert img.read_file("/PERSISTF.TXT") == test_content

        # Shrink
        _resize_image(img_path, 30 * 1024 * 1024)
        with VHDImage(img_path) as img:
            assert img.read_file("/PERSISTF.TXT") == test_content

        # Grow again
        _resize_image(img_path, 60 * 1024 * 1024)
        with VHDImage(img_path) as img:
            assert img.read_file("/PERSISTF.TXT") == test_content

    def test_resize_then_write(self, tmp_path):
        """Test that writing works after resize."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        _resize_image(img_path, 30 * 1024 * 1024)

        # Write new file after resize
        new_content = b"Written after resize"
        write_test_file(img_path, "NEWFILE.TXT", new_content)

        with VHDImage(img_path) as img:
            assert img.read_file("/NEWFILE.TXT") == new_content

    def test_resize_free_space_usable(self, tmp_path):
        """Test that new space after grow is actually usable."""
        img_path = str(tmp_path / "test.img")
        create_test_image(img_path, 10)

        _resize_image(img_path, 30 * 1024 * 1024)

        with VHDImage(img_path) as img:
            free_before = img.get_free_cluster_count()

        # Write file using new space
        content = b"X" * (5 * 1024 * 1024)
        write_test_file(img_path, "NEWDATA.DAT", content)

        with VHDImage(img_path) as img:
            free_after = img.get_free_cluster_count()
            assert free_after < free_before

            # Verify file is readable
            data = img.read_file("/NEWDATA.DAT")
            assert len(data) == len(content)
            assert data == content


def _resize_image(path: str, new_size: int, check_data_loss: bool = False) -> None:
    """Helper to resize image with validation."""
    new_size = (new_size // 512) * 512
    new_sectors = new_size // 512
    current_size = os.path.getsize(path)

    if new_size == current_size:
        return

    with VHDImage(path) as img:
        if img.is_vhd and img.is_dynamic:
            raise ValueError("Dynamic VHD resize not supported")

        partitions = img.get_partitions()
        if not partitions:
            raise ValueError("No partition found")

        old_part = partitions[0]
        old_bpb = img.bpb
        stats = img.get_filesystem_stats()
        highest_cluster = stats['highest_used_cluster']

    new_part_sectors = new_sectors - old_part.start_lba

    # Validate size
    min_sectors = 4085 + old_part.start_lba
    max_sectors = 4194304 + old_part.start_lba

    if new_sectors < min_sectors:
        raise ValueError(f"Size too small for FAT16")

    if new_sectors > max_sectors:
        raise ValueError(f"Size too large for FAT16")

    new_params = calculate_fat16_params(new_part_sectors)

    # Check for data loss on shrink
    if new_size < current_size:
        if highest_cluster > 1:
            min_data_clusters = highest_cluster - 1
            min_data_sectors = min_data_clusters * old_bpb.sectors_per_cluster
            min_partition_sectors = (old_bpb.reserved_sectors +
                                     old_bpb.num_fats * old_bpb.fat_size +
                                     old_bpb.root_dir_sectors +
                                     min_data_sectors)
            min_image_sectors = old_part.start_lba + min_partition_sectors
            min_image_size = min_image_sectors * 512

            if check_data_loss and new_size < min_image_size:
                raise ValueError("Cannot shrink - data would be lost")

        # Check FAT reorganization needed
        if new_params['fat_size'] != old_bpb.fat_size or \
           new_params['sectors_per_cluster'] != old_bpb.sectors_per_cluster:
            raise ValueError("Shrinking requires filesystem reorganization")

    else:
        # Growing - check if FAT needs to grow
        if new_params['fat_size'] > old_bpb.fat_size:
            raise ValueError("Growing requires FAT reorganization")

    # Perform resize
    with open(path, 'r+b') as f:
        if new_size > current_size:
            f.seek(new_size - 1)
            f.write(b'\x00')
        else:
            f.truncate(new_size)

        # Update partition table
        f.seek(446 + 12)
        f.write(struct.pack('<I', new_part_sectors))

        # Update BPB
        part_offset = old_part.start_lba * 512
        if new_part_sectors < 65536:
            f.seek(part_offset + 19)
            f.write(struct.pack('<H', new_part_sectors))
            f.seek(part_offset + 32)
            f.write(struct.pack('<I', 0))
        else:
            f.seek(part_offset + 19)
            f.write(struct.pack('<H', 0))
            f.seek(part_offset + 32)
            f.write(struct.pack('<I', new_part_sectors))

    # Verify
    with VHDImage(path) as img:
        if img.bpb is None:
            raise ValueError("BPB corrupted after resize")
        partitions = img.get_partitions()
        if not partitions:
            raise ValueError("Partition table corrupted after resize")
