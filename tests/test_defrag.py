"""Tests for disk defragmentation functionality."""

import os
import struct
import tempfile
import pytest

from vhdtool import VHDImage
from vhdtool.defrag import defragment_image, DefragmentedImage
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
        fat[0:4] = b'\xF8\xFF\xFF\xFF'

        for i in range(params['num_fats']):
            f.seek((fat_start + i * fat_size) * 512)
            f.write(fat)

        # Root directory
        root_start = fat_start + params['num_fats'] * fat_size
        root_sectors = (params['root_entries'] * 32 + 511) // 512
        f.seek(root_start * 512)
        f.write(b'\x00' * root_sectors * 512)

        f.seek(size_bytes - 1)
        f.write(b'\x00')


def write_test_file(path: str, filename: str, content: bytes) -> None:
    """Write a file to the test image."""
    with VHDImage(path, readonly=False) as img:
        img.write_file(f'/{filename}', content)


def create_fragmented_image(path: str, size_mb: int = 20) -> dict:
    """Create an image with fragmented files by interleaved writes."""
    create_test_image(path, size_mb)

    # Write files in interleaved fashion to create fragmentation
    files = {}
    chunk_size = 2048

    # Create file contents
    for i in range(5):
        files[f"FILE{i}.DAT"] = bytes([i] * (chunk_size * (i + 2)))

    # Write in small chunks interleaved
    for chunk_idx in range(10):
        for name, content in files.items():
            start = chunk_idx * chunk_size
            end = start + chunk_size
            if start < len(content):
                chunk = content[start:end]
                # This creates fragmentation by deleting and rewriting
                try:
                    with VHDImage(path, readonly=False) as img:
                        existing = img.read_file(f"/{name}")
                        img.remove(f"/{name}")
                        img.write_file(f"/{name}", existing + chunk)
                except:
                    write_test_file(path, name, chunk)

    return files


class TestDefragBasic:
    """Basic defragmentation tests."""

    def test_defrag_empty_image(self, tmp_path):
        """Test defragmenting an empty image."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)

        stats = defragment_image(src, dst)

        assert os.path.exists(dst)
        assert stats['files_copied'] == 0
        assert stats['fragmentation_after'] == 0.0

        with VHDImage(dst) as img:
            assert img.bpb is not None
            assert len(img.list_dir('/')) == 0

    def test_defrag_single_file(self, tmp_path):
        """Test defragmenting with a single file."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)

        content = b"Hello, World!" * 100
        write_test_file(src, "TEST.TXT", content)

        stats = defragment_image(src, dst)

        assert stats['files_copied'] == 1
        assert stats['bytes_copied'] == len(content)

        with VHDImage(dst) as img:
            recovered = img.read_file("/TEST.TXT")
            assert recovered == content

    def test_defrag_multiple_files(self, tmp_path):
        """Test defragmenting with multiple files."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)

        files = {
            "FILE1.TXT": b"First file content",
            "FILE2.TXT": b"Second file with more data" * 100,
            "FILE3.DAT": bytes(range(256)) * 10,
            "EMPTY.TXT": b"",
        }

        for name, content in files.items():
            if content:
                write_test_file(src, name, content)
            else:
                with VHDImage(src, readonly=False) as img:
                    img.write_file(f"/{name}", b"")

        stats = defragment_image(src, dst)

        assert stats['files_copied'] == 4  # Including empty file

        with VHDImage(dst) as img:
            for name, expected in files.items():
                actual = img.read_file(f"/{name}")
                assert actual == expected, f"File {name} content mismatch"


class TestDefragIntegrity:
    """Test data integrity during defragmentation."""

    def test_defrag_preserves_file_content(self, tmp_path):
        """Verify exact content preservation."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 20)

        # Various file types
        files = {
            "BINARY.BIN": bytes(range(256)) * 1000,
            "TEXT.TXT": b"Line 1\r\nLine 2\r\nLine 3\r\n" * 500,
            "ZEROS.DAT": b'\x00' * 10000,
            "ONES.DAT": b'\xFF' * 10000,
            "RANDOM.DAT": bytes([i % 251 for i in range(50000)]),
        }

        for name, content in files.items():
            write_test_file(src, name, content)

        defragment_image(src, dst)

        with VHDImage(dst) as img:
            for name, expected in files.items():
                actual = img.read_file(f"/{name}")
                assert actual == expected, f"Content mismatch in {name}"
                assert len(actual) == len(expected), f"Size mismatch in {name}"

    def test_defrag_preserves_file_attributes(self, tmp_path):
        """Verify file attributes are preserved."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)

        write_test_file(src, "TEST.TXT", b"content")

        with VHDImage(src) as img:
            entries = img.list_dir('/')
            src_entry = next(e for e in entries if e.name == "TEST")

        defragment_image(src, dst)

        with VHDImage(dst) as img:
            entries = img.list_dir('/')
            dst_entry = next(e for e in entries if e.name == "TEST")

        # Check attributes preserved
        assert src_entry.attr == dst_entry.attr
        assert src_entry.size == dst_entry.size

    def test_defrag_preserves_boot_sector(self, tmp_path):
        """Verify boot sector is preserved."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)

        # Read source boot code
        with VHDImage(src) as img:
            src_vbr = img._read_sector(img.partition_offset)

        defragment_image(src, dst)

        # Verify boot code preserved
        with VHDImage(dst) as img:
            dst_vbr = img._read_sector(img.partition_offset)

        # Jump instruction and boot code should match
        assert src_vbr[0:3] == dst_vbr[0:3], "Jump instruction changed"
        assert src_vbr[62:510] == dst_vbr[62:510], "Boot code changed"

    def test_defrag_files_are_sequential(self, tmp_path):
        """Verify files are stored in sequential clusters after defrag."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 20)

        # Create a file that spans multiple clusters
        cluster_size = 512 * 4  # Typical cluster size
        content = b"X" * (cluster_size * 5)  # 5 clusters
        write_test_file(src, "MULTI.DAT", content)

        defragment_image(src, dst)

        # Verify sequential allocation
        with VHDImage(dst) as img:
            entries = img.list_dir('/')
            entry = next(e for e in entries if e.name == "MULTI")
            chain = img._get_cluster_chain(entry.first_cluster)

            # Check clusters are sequential
            for i in range(len(chain) - 1):
                assert chain[i+1] == chain[i] + 1, f"Non-sequential: {chain[i]} -> {chain[i+1]}"


class TestDefragResize:
    """Test defragmentation with resizing."""

    def test_defrag_same_size(self, tmp_path):
        """Test defrag without size change."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)

        write_test_file(src, "TEST.TXT", b"content")

        src_size = os.path.getsize(src)
        defragment_image(src, dst)
        dst_size = os.path.getsize(dst)

        assert dst_size == src_size

    def test_defrag_grow(self, tmp_path):
        """Test defrag with size increase."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)

        content = b"Test content"
        write_test_file(src, "TEST.TXT", content)

        new_size = 20 * 1024 * 1024
        defragment_image(src, dst, new_size=new_size)

        assert os.path.getsize(dst) == new_size

        with VHDImage(dst) as img:
            assert img.read_file("/TEST.TXT") == content
            stats = img.get_filesystem_stats()
            # Should have more free space
            assert stats['free_bytes'] > 5 * 1024 * 1024

    def test_defrag_shrink(self, tmp_path):
        """Test defrag with size decrease."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 50)

        # Small file
        content = b"Small content"
        write_test_file(src, "SMALL.TXT", content)

        new_size = 10 * 1024 * 1024
        defragment_image(src, dst, new_size=new_size)

        assert os.path.getsize(dst) == new_size

        with VHDImage(dst) as img:
            assert img.read_file("/SMALL.TXT") == content

    def test_defrag_shrink_preserves_all_data(self, tmp_path):
        """Test that shrinking preserves all files."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 50)

        files = {
            "A.TXT": b"File A",
            "B.TXT": b"File B" * 100,
            "C.DAT": bytes(range(256)),
        }

        for name, content in files.items():
            write_test_file(src, name, content)

        # Shrink but keep enough space
        defragment_image(src, dst, new_size=10 * 1024 * 1024)

        with VHDImage(dst) as img:
            for name, expected in files.items():
                actual = img.read_file(f"/{name}")
                assert actual == expected


class TestDefragSubdirectories:
    """Test defragmentation with subdirectories."""

    def test_defrag_with_subdirectory(self, tmp_path):
        """Test defrag preserves subdirectory structure."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 20)

        with VHDImage(src, readonly=False) as img:
            img.mkdir("/SUBDIR")
            img.write_file("/SUBDIR/FILE.TXT", b"In subdirectory")
            img.write_file("/ROOT.TXT", b"In root")

        defragment_image(src, dst)

        with VHDImage(dst) as img:
            # Check root
            root_entries = img.list_dir('/')
            assert any(e.name == "ROOT" for e in root_entries)
            assert any(e.name == "SUBDIR" and e.is_directory for e in root_entries)

            # Check subdirectory
            assert img.read_file("/ROOT.TXT") == b"In root"
            assert img.read_file("/SUBDIR/FILE.TXT") == b"In subdirectory"

    def test_defrag_nested_directories(self, tmp_path):
        """Test defrag with nested directory structure."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 20)

        with VHDImage(src, readonly=False) as img:
            img.mkdir("/LEVEL1")
            img.mkdir("/LEVEL1/LEVEL2")
            img.write_file("/LEVEL1/LEVEL2/DEEP.TXT", b"Deep file")

        defragment_image(src, dst)

        with VHDImage(dst) as img:
            content = img.read_file("/LEVEL1/LEVEL2/DEEP.TXT")
            assert content == b"Deep file"


class TestDefragEdgeCases:
    """Test edge cases in defragmentation."""

    def test_defrag_dest_exists_error(self, tmp_path):
        """Test error when destination exists."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)
        create_test_image(dst, 10)  # Destination exists

        with pytest.raises(FileExistsError):
            defragment_image(src, dst)

    def test_defrag_large_file(self, tmp_path):
        """Test defrag with a file spanning many clusters."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 20)

        # ~5MB file
        content = bytes([i % 256 for i in range(5 * 1024 * 1024)])
        write_test_file(src, "LARGE.DAT", content)

        defragment_image(src, dst)

        with VHDImage(dst) as img:
            recovered = img.read_file("/LARGE.DAT")
            assert recovered == content

    def test_defrag_many_small_files(self, tmp_path):
        """Test defrag with many small files."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 20)

        files = {}
        for i in range(50):
            name = f"F{i:03d}.TXT"
            content = f"Content of file {i}".encode()
            files[name] = content
            write_test_file(src, name, content)

        stats = defragment_image(src, dst)

        assert stats['files_copied'] == 50

        with VHDImage(dst) as img:
            for name, expected in files.items():
                actual = img.read_file(f"/{name}")
                assert actual == expected

    def test_defrag_special_filenames(self, tmp_path):
        """Test defrag with various valid 8.3 filenames."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)

        files = {
            "ALLCAPS.TXT": b"uppercase",
            "NUM12345.DAT": b"numbers",
            "A.B": b"short",
            "LONGNAME.XYZ": b"long ext",
        }

        for name, content in files.items():
            write_test_file(src, name, content)

        defragment_image(src, dst)

        with VHDImage(dst) as img:
            for name, expected in files.items():
                actual = img.read_file(f"/{name}")
                assert actual == expected


class TestDefragProgress:
    """Test progress reporting."""

    def test_defrag_progress_callback(self, tmp_path):
        """Test that progress callback is called."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)

        for i in range(5):
            write_test_file(src, f"FILE{i}.TXT", f"Content {i}".encode())

        progress_calls = []

        def progress(phase, current, total):
            progress_calls.append((phase, current, total))

        defragment_image(src, dst, progress=progress)

        assert len(progress_calls) > 0
        assert any(p[0] == "copying" for p in progress_calls)


class TestDefragStress:
    """Stress tests for defragmentation with hash verification."""

    def test_many_small_files_hash_consistency(self, tmp_path):
        """Test defrag with 100+ small files (>1 sector each), verify by hash."""
        import hashlib

        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 50)  # 50MB to fit many files

        # Create 100 small files, each 1-4KB (2-8 sectors)
        files = {}
        for i in range(100):
            # Varying sizes: 600-2000 bytes (all > 512 bytes = 1 sector)
            size = 600 + (i * 17) % 1400
            # Unique content for each file
            content = bytes([(i + j) % 256 for j in range(size)])
            name = f"F{i:03d}.DAT"
            files[name] = {
                'content': content,
                'hash': hashlib.sha256(content).hexdigest()
            }
            write_test_file(src, name, content)

        # Verify source files before defrag
        with VHDImage(src) as img:
            for name, info in files.items():
                data = img.read_file(f"/{name}")
                assert hashlib.sha256(data).hexdigest() == info['hash'], \
                    f"Source file {name} corrupted before defrag"

        # Defragment
        stats = defragment_image(src, dst)

        assert stats['files_copied'] == 100
        assert stats['fragmentation_after'] == 0.0

        # Verify all files after defrag by hash
        with VHDImage(dst) as img:
            for name, info in files.items():
                data = img.read_file(f"/{name}")
                actual_hash = hashlib.sha256(data).hexdigest()
                assert actual_hash == info['hash'], \
                    f"File {name} hash mismatch after defrag: expected {info['hash'][:16]}..., got {actual_hash[:16]}..."

    def test_large_files_hash_consistency(self, tmp_path):
        """Test defrag with large files, verify by hash."""
        import hashlib

        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 50)  # 50MB for large files

        # Create 5 large files (100KB - 500KB each)
        file_specs = []
        for i in range(5):
            size = 100 * 1024 + i * 100 * 1024  # 100KB to 500KB
            content = bytes([(i * 37 + j) % 256 for j in range(size)])
            name = f"LARGE{i:02d}.DAT"
            file_specs.append({
                'name': name,
                'content': content,
                'hash': hashlib.sha256(content).hexdigest(),
            })
            write_test_file(src, name, content)

        # Verify source
        with VHDImage(src) as img:
            for spec in file_specs:
                data = img.read_file(f"/{spec['name']}")
                assert hashlib.sha256(data).hexdigest() == spec['hash']

        # Defragment
        stats = defragment_image(src, dst)
        assert stats['files_copied'] == 5

        # Verify all files after defrag
        with VHDImage(dst) as img:
            for spec in file_specs:
                data = img.read_file(f"/{spec['name']}")
                actual_hash = hashlib.sha256(data).hexdigest()
                assert actual_hash == spec['hash'], \
                    f"File {spec['name']} hash mismatch"

                # Verify contiguous
                entries = img.list_dir('/')
                entry = next(e for e in entries if e.full_name == spec['name'])
                if entry.first_cluster > 0:
                    chain = img._get_cluster_chain(entry.first_cluster)
                    for j in range(len(chain) - 1):
                        assert chain[j + 1] == chain[j] + 1

    def test_mixed_files_with_subdirs_hash_consistency(self, tmp_path):
        """Test defrag with mix of files in root and subdirectories, verify by hash."""
        import hashlib

        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 50)

        all_files = {}

        # Create subdirectories and files
        with VHDImage(src, readonly=False) as img:
            # Root files
            for i in range(20):
                size = 1024 + i * 100
                content = bytes([(i * 13 + j) % 256 for j in range(size)])
                name = f"ROOT{i:02d}.DAT"
                img.write_file(f"/{name}", content)
                all_files[f"/{name}"] = hashlib.sha256(content).hexdigest()

            # Create subdirectory with files
            img.mkdir("/SUBDIR1")
            for i in range(15):
                size = 2048 + i * 200
                content = bytes([(i * 17 + j) % 256 for j in range(size)])
                name = f"SUB1F{i:02d}.DAT"
                img.write_file(f"/SUBDIR1/{name}", content)
                all_files[f"/SUBDIR1/{name}"] = hashlib.sha256(content).hexdigest()

            # Nested subdirectory
            img.mkdir("/SUBDIR1/NESTED")
            for i in range(10):
                size = 3072 + i * 300
                content = bytes([(i * 19 + j) % 256 for j in range(size)])
                name = f"NEST{i:02d}.DAT"
                img.write_file(f"/SUBDIR1/NESTED/{name}", content)
                all_files[f"/SUBDIR1/NESTED/{name}"] = hashlib.sha256(content).hexdigest()

        # Verify source
        with VHDImage(src) as img:
            for path, expected_hash in all_files.items():
                data = img.read_file(path)
                assert hashlib.sha256(data).hexdigest() == expected_hash

        # Defragment
        stats = defragment_image(src, dst)

        assert stats['files_copied'] == 45  # 20 + 15 + 10

        # Verify all files after defrag
        with VHDImage(dst) as img:
            for path, expected_hash in all_files.items():
                data = img.read_file(path)
                actual_hash = hashlib.sha256(data).hexdigest()
                assert actual_hash == expected_hash, \
                    f"File {path} hash mismatch after defrag"

    def test_defrag_with_shrink_hash_consistency(self, tmp_path):
        """Test defrag with size reduction, verify file integrity by hash."""
        import hashlib

        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 100)  # Start with 100MB

        # Write ~10MB of files
        files = {}
        total_size = 0
        for i in range(20):
            size = 400 * 1024 + i * 50 * 1024  # 400KB to ~1.3MB each
            content = bytes([(i * 41 + j) % 256 for j in range(size)])
            name = f"FILE{i:02d}.DAT"
            files[name] = hashlib.sha256(content).hexdigest()
            write_test_file(src, name, content)
            total_size += size

        print(f"Total data size: {total_size / (1024*1024):.1f}MB")

        # Verify source
        with VHDImage(src) as img:
            for name, expected_hash in files.items():
                data = img.read_file(f"/{name}")
                assert hashlib.sha256(data).hexdigest() == expected_hash

        # Defrag and shrink to 30MB (should fit ~17MB of data easily)
        new_size = 30 * 1024 * 1024
        stats = defragment_image(src, dst, new_size=new_size)

        assert os.path.getsize(dst) == new_size
        assert stats['files_copied'] == 20

        # Verify all files preserved after shrink
        with VHDImage(dst) as img:
            for name, expected_hash in files.items():
                data = img.read_file(f"/{name}")
                actual_hash = hashlib.sha256(data).hexdigest()
                assert actual_hash == expected_hash, \
                    f"File {name} corrupted after defrag+shrink"


class TestDefragShrinkValidation:
    """Test shrink validation with clear error messages."""

    def test_shrink_too_small_shows_error(self, tmp_path):
        """Test that shrinking too small shows clear error with sizes."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 50)

        # Write ~15MB of data
        for i in range(15):
            content = bytes([i] * (1024 * 1024))  # 1MB each
            write_test_file(src, f"BIG{i:02d}.DAT", content)

        # Try to shrink to 5MB - should fail with clear message
        with pytest.raises(ValueError) as exc_info:
            defragment_image(src, dst, new_size=5 * 1024 * 1024)

        error_msg = str(exc_info.value)
        assert "Cannot shrink" in error_msg
        assert "data would not fit" in error_msg or "minimum FAT16 size" in error_msg

    def test_shrink_just_right_succeeds(self, tmp_path):
        """Test shrinking to a size that just fits the data."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 50)

        # Write ~5MB of data
        for i in range(5):
            content = bytes([i] * (1024 * 1024))
            write_test_file(src, f"FILE{i:02d}.DAT", content)

        # Shrink to 15MB - should succeed with 5MB data
        defragment_image(src, dst, new_size=15 * 1024 * 1024)

        assert os.path.getsize(dst) == 15 * 1024 * 1024

        # Verify files
        with VHDImage(dst) as img:
            for i in range(5):
                data = img.read_file(f"/FILE{i:02d}.DAT")
                assert len(data) == 1024 * 1024


class TestDefragValidation:
    """Test filesystem validation after defrag."""

    def test_defrag_valid_partition_table(self, tmp_path):
        """Test partition table is valid after defrag."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)

        write_test_file(src, "TEST.TXT", b"content")

        defragment_image(src, dst)

        with VHDImage(dst) as img:
            partitions = img.get_partitions()
            assert len(partitions) == 1
            assert partitions[0].type_code in (0x04, 0x06, 0x0E)  # FAT16 types

    def test_defrag_valid_bpb(self, tmp_path):
        """Test BPB is valid after defrag."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)

        defragment_image(src, dst)

        with VHDImage(dst) as img:
            assert img.bpb is not None
            assert img.bpb.bytes_per_sector == 512
            assert img.bpb.sectors_per_cluster in (1, 2, 4, 8, 16, 32, 64)
            assert img.bpb.num_fats == 2

    def test_defrag_can_write_after(self, tmp_path):
        """Test that we can write new files after defrag."""
        src = str(tmp_path / "source.img")
        dst = str(tmp_path / "dest.img")
        create_test_image(src, 10)

        write_test_file(src, "BEFORE.TXT", b"before defrag")

        defragment_image(src, dst)

        # Write new file to defragmented image
        new_content = b"written after defrag"
        write_test_file(dst, "AFTER.TXT", new_content)

        with VHDImage(dst) as img:
            assert img.read_file("/BEFORE.TXT") == b"before defrag"
            assert img.read_file("/AFTER.TXT") == new_content
