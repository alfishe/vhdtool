"""Boot sector management."""

import struct
from pathlib import Path


BOOT_SECTORS_DIR = Path(__file__).parent.parent.parent / "bootsectors"


def get_boot_sectors() -> dict:
    """Get available boot sectors from collection."""
    boot_sectors = {}

    boot_sectors['minimal'] = {
        'name': 'Minimal (halt)',
        'description': 'Minimal boot sector that halts the system',
        'data': None,
    }

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


def extract_boot_code_from_image(image_path: str) -> tuple[bytes, bytes]:
    """Extract MBR and VBR boot code from existing image."""
    with open(image_path, 'rb') as f:
        mbr = f.read(512)

        if mbr[510:512] == b'\x55\xAA':
            part_start = struct.unpack('<I', mbr[446+8:446+12])[0]
            f.seek(part_start * 512)
            vbr = f.read(512)
        else:
            vbr = mbr

    return mbr, vbr


def apply_boot_sectors(image_path: str, src_mbr: bytes, src_vbr: bytes):
    """Apply MBR and VBR boot sectors to an image (preserving BPB)."""
    with open(image_path, 'r+b') as f:
        current_mbr = bytearray(f.read(512))
        current_mbr[0:446] = src_mbr[0:446]
        f.seek(0)
        f.write(current_mbr)

        part_start = struct.unpack('<I', current_mbr[446+8:446+12])[0]
        f.seek(part_start * 512)
        current_vbr = bytearray(f.read(512))

        current_vbr[0:3] = src_vbr[0:3]
        current_vbr[62:510] = src_vbr[62:510]

        f.seek(part_start * 512)
        f.write(current_vbr)
