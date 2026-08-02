"""Utility functions for vhdtool."""

import os
import struct
from pathlib import Path


def format_size(size: int) -> str:
    """Format size in human-readable form."""
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size < 1024:
            return f"{size:.1f} {unit}" if unit != 'B' else f"{size} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def parse_size(size_str: str) -> int:
    """Parse size string like '512M', '2G', '100MB' to bytes."""
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


def parse_image_path(path: str) -> tuple[str, str | None]:
    """Parse image:path format."""
    if ':' in path:
        parts = path.split(':', 1)
        if len(parts[0]) > 1 or not os.path.exists(parts[0] + ':' + parts[1].split('/')[0]):
            return parts[0], parts[1] if parts[1] else None
    return path, None


def calculate_fat16_params(total_sectors: int) -> dict:
    """Calculate FAT16 filesystem parameters for given size."""
    if total_sectors < 4085 * 1:
        raise ValueError("Disk too small for FAT16 (min ~2MB)")
    if total_sectors > 4194304:  # 2GB limit
        raise ValueError("Disk too large for FAT16 (max 2GB)")

    if total_sectors <= 32680:
        sectors_per_cluster = 1
    elif total_sectors <= 262144:
        sectors_per_cluster = 4
    elif total_sectors <= 524288:
        sectors_per_cluster = 8
    elif total_sectors <= 1048576:
        sectors_per_cluster = 16
    elif total_sectors <= 2097152:
        sectors_per_cluster = 32
    else:
        sectors_per_cluster = 64

    reserved_sectors = 1
    num_fats = 2
    root_entries = 512
    root_dir_sectors = (root_entries * 32 + 511) // 512

    data_sectors = total_sectors - reserved_sectors - root_dir_sectors
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
    """Create MBR with single FAT16 partition."""
    mbr = bytearray(512)

    part_start = 63
    part_size = total_sectors - part_start

    entry = mbr[446:462]
    entry[0] = 0x80 if bootable else 0x00

    entry[1] = 1
    entry[2] = 1
    entry[3] = 0

    if part_size < 65536:
        entry[4] = 0x04
    else:
        entry[4] = 0x06

    entry[5] = 0xFE
    entry[6] = 0xFF
    entry[7] = 0xFF

    struct.pack_into('<I', entry, 8, part_start)
    struct.pack_into('<I', entry, 12, part_size)

    mbr[446:462] = entry
    mbr[510] = 0x55
    mbr[511] = 0xAA

    return bytes(mbr)


def create_fat16_boot_sector(params: dict, volume_label: str = "DISK", hidden_sectors: int = 63) -> bytes:
    """Create FAT16 boot sector (VBR)."""
    boot = bytearray(512)

    boot[0:3] = b'\xEB\x3C\x90'
    boot[3:11] = b'MSDOS5.0'

    struct.pack_into('<H', boot, 11, 512)
    boot[13] = params['sectors_per_cluster']
    struct.pack_into('<H', boot, 14, params['reserved_sectors'])
    boot[16] = params['num_fats']
    struct.pack_into('<H', boot, 17, params['root_entries'])

    total = params['total_sectors']
    if total < 65536:
        struct.pack_into('<H', boot, 19, total)
        struct.pack_into('<I', boot, 32, 0)
    else:
        struct.pack_into('<H', boot, 19, 0)
        struct.pack_into('<I', boot, 32, total)

    boot[21] = 0xF8
    struct.pack_into('<H', boot, 22, params['fat_size'])
    struct.pack_into('<H', boot, 24, 63)  # sectors per track
    struct.pack_into('<H', boot, 26, 16)  # heads
    struct.pack_into('<I', boot, 28, hidden_sectors)

    boot[36] = 0x80
    boot[37] = 0x00
    boot[38] = 0x29
    struct.pack_into('<I', boot, 39, 0x12345678)
    boot[43:54] = volume_label.upper().ljust(11).encode('ascii')[:11]
    boot[54:62] = b'FAT16   '

    boot[62:64] = b'\xCD\x18'
    boot[510] = 0x55
    boot[511] = 0xAA

    return bytes(boot)


def create_fat16_tables(params: dict) -> bytes:
    """Create initial FAT16 table."""
    fat_size_bytes = params['fat_size'] * 512
    fat = bytearray(fat_size_bytes)

    fat[0] = 0xF8
    fat[1] = 0xFF
    fat[2] = 0xFF
    fat[3] = 0xFF

    return bytes(fat)
