#!/usr/bin/env python3
"""
Boot Sector Disassembler and Source Generator

Disassembles boot sector binaries into compilable NASM source code.
Preserves data structures (BPB, partition table) and generates
working assembly that compiles back to the original binary.

Usage:
    ./disasm_boot.py <boot.bin> [--type mbr|vbr] [--output boot.asm]
    ./disasm_boot.py --verify <boot.bin> <boot.asm>
"""

import argparse
import subprocess
import struct
import sys
from pathlib import Path


def detect_boot_type(data: bytes) -> str:
    """Detect if binary is MBR or VBR."""
    if len(data) != 512:
        raise ValueError(f"Boot sector must be 512 bytes, got {len(data)}")

    if data[510:512] != b'\x55\xAA':
        raise ValueError("Missing boot signature (0x55AA)")

    # Check for BPB (VBR indicator)
    if data[0] in (0xEB, 0xE9):  # Jump instruction
        bytes_per_sector = struct.unpack("<H", data[11:13])[0]
        if bytes_per_sector in (512, 1024, 2048, 4096):
            return "vbr"

    # Check partition table area
    has_partition = False
    for i in range(4):
        offset = 446 + i * 16
        type_byte = data[offset + 4]
        if type_byte != 0:
            has_partition = True
            break

    if has_partition:
        return "mbr"

    # Default to VBR if jump instruction present
    if data[0] in (0xEB, 0xE9):
        return "vbr"

    return "mbr"


def get_fat_type(data: bytes) -> str:
    """Detect FAT type from VBR."""
    fat_size_16 = struct.unpack("<H", data[22:24])[0]
    if fat_size_16 == 0:
        return "fat32"

    fs_type = data[54:62].decode('ascii', errors='replace').strip()
    if "FAT12" in fs_type:
        return "fat12"
    elif "FAT16" in fs_type:
        return "fat16"
    elif "FAT32" in fs_type:
        return "fat32"

    # Calculate from cluster count
    bytes_per_sector = struct.unpack("<H", data[11:13])[0]
    sectors_per_cluster = data[13]
    reserved = struct.unpack("<H", data[14:16])[0]
    num_fats = data[16]
    root_entries = struct.unpack("<H", data[17:19])[0]
    total_16 = struct.unpack("<H", data[19:21])[0]
    total_32 = struct.unpack("<I", data[32:36])[0]

    total = total_32 if total_32 else total_16
    root_sectors = (root_entries * 32 + bytes_per_sector - 1) // bytes_per_sector
    data_sectors = total - reserved - (num_fats * fat_size_16) - root_sectors
    clusters = data_sectors // sectors_per_cluster

    if clusters < 4085:
        return "fat12"
    elif clusters < 65525:
        return "fat16"
    return "fat32"


def disasm_mbr(data: bytes) -> str:
    """Generate NASM source for MBR."""
    lines = []
    lines.append("; MBR - Master Boot Record")
    lines.append("; Auto-generated from binary - DO NOT EDIT directly")
    lines.append("; Reassemble with: nasm -f bin -o mbr.bin mbr.asm")
    lines.append("")
    lines.append("BITS 16")
    lines.append("ORG 0x7C00")
    lines.append("")

    # Disassemble code section (0-445)
    lines.append("; Boot code")
    result = subprocess.run(
        ["ndisasm", "-b", "16", "-o", "0x7C00", "-"],
        input=data[:446],
        capture_output=True
    )

    for line in result.stdout.decode().split('\n'):
        if line.strip():
            # Parse ndisasm output: "00007C00  EB3C              jmp short 0x7c3e"
            parts = line.split(None, 2)
            if len(parts) >= 3:
                addr = parts[0]
                inst = parts[2] if len(parts) > 2 else ""
                lines.append(f"    {inst:40} ; {addr}")

    # Partition table
    lines.append("")
    lines.append("; Partition table at offset 446 (0x1BE)")
    lines.append("times 446-($-$$) db 0")
    lines.append("")

    for i in range(4):
        offset = 446 + i * 16
        entry = data[offset:offset + 16]
        bootable = entry[0]
        type_code = entry[4]
        start_lba = struct.unpack("<I", entry[8:12])[0]
        size = struct.unpack("<I", entry[12:16])[0]

        lines.append(f"; Partition {i+1}")
        if type_code == 0:
            lines.append(f"times 16 db 0")
        else:
            lines.append(f"db 0x{bootable:02X}                    ; Boot flag")
            lines.append(f"db 0x{entry[1]:02X}, 0x{entry[2]:02X}, 0x{entry[3]:02X}       ; CHS start")
            lines.append(f"db 0x{type_code:02X}                    ; Type")
            lines.append(f"db 0x{entry[5]:02X}, 0x{entry[6]:02X}, 0x{entry[7]:02X}       ; CHS end")
            lines.append(f"dd {start_lba}                ; LBA start")
            lines.append(f"dd {size}                ; Sectors")
        lines.append("")

    lines.append("; Boot signature")
    lines.append("dw 0xAA55")

    return '\n'.join(lines)


def disasm_vbr(data: bytes) -> str:
    """Generate NASM source for VBR."""
    fat_type = get_fat_type(data)

    lines = []
    lines.append(f"; VBR - Volume Boot Record ({fat_type.upper()})")
    lines.append("; Auto-generated from binary - DO NOT EDIT directly")
    lines.append("; Reassemble with: nasm -f bin -o vbr.bin vbr.asm")
    lines.append("")
    lines.append("BITS 16")
    lines.append("ORG 0x7C00")
    lines.append("")

    # Jump instruction
    if data[0] == 0xEB:
        jump_target = 0x7C00 + 2 + struct.unpack("b", data[1:2])[0]
        lines.append(f"jmp short 0x{jump_target:04X}")
        lines.append("nop")
    elif data[0] == 0xE9:
        jump_target = 0x7C00 + 3 + struct.unpack("<h", data[1:3])[0]
        lines.append(f"jmp 0x{jump_target:04X}")

    lines.append("")
    lines.append("; BIOS Parameter Block (BPB)")

    # OEM name
    oem = data[3:11].decode('ascii', errors='replace')
    lines.append(f"bpb_oem:            db \"{oem}\"")

    # BPB fields
    bps = struct.unpack("<H", data[11:13])[0]
    spc = data[13]
    res = struct.unpack("<H", data[14:16])[0]
    nfat = data[16]
    root = struct.unpack("<H", data[17:19])[0]
    tot16 = struct.unpack("<H", data[19:21])[0]
    media = data[21]
    fat16 = struct.unpack("<H", data[22:24])[0]
    spt = struct.unpack("<H", data[24:26])[0]
    heads = struct.unpack("<H", data[26:28])[0]
    hidden = struct.unpack("<I", data[28:32])[0]
    tot32 = struct.unpack("<I", data[32:36])[0]

    lines.append(f"bpb_bytes_per_sec:  dw {bps}")
    lines.append(f"bpb_sec_per_clust:  db {spc}")
    lines.append(f"bpb_reserved:       dw {res}")
    lines.append(f"bpb_num_fats:       db {nfat}")
    lines.append(f"bpb_root_entries:   dw {root}")
    lines.append(f"bpb_total_sec_16:   dw {tot16}")
    lines.append(f"bpb_media:          db 0x{media:02X}")
    lines.append(f"bpb_fat_size_16:    dw {fat16}")
    lines.append(f"bpb_sec_per_track:  dw {spt}")
    lines.append(f"bpb_heads:          dw {heads}")
    lines.append(f"bpb_hidden:         dd {hidden}")
    lines.append(f"bpb_total_sec_32:   dd {tot32}")

    # Extended BPB
    if fat_type == "fat32":
        fat32 = struct.unpack("<I", data[36:40])[0]
        flags = struct.unpack("<H", data[40:42])[0]
        ver = struct.unpack("<H", data[42:44])[0]
        root_clust = struct.unpack("<I", data[44:48])[0]
        fsinfo = struct.unpack("<H", data[48:50])[0]
        backup = struct.unpack("<H", data[50:52])[0]

        lines.append("")
        lines.append("; FAT32 Extended BPB")
        lines.append(f"bpb_fat_size_32:    dd {fat32}")
        lines.append(f"bpb_ext_flags:      dw {flags}")
        lines.append(f"bpb_fs_version:     dw {ver}")
        lines.append(f"bpb_root_cluster:   dd {root_clust}")
        lines.append(f"bpb_fsinfo:         dw {fsinfo}")
        lines.append(f"bpb_backup_boot:    dw {backup}")
        lines.append(f"                    times 12 db 0  ; Reserved")
        ext_offset = 64
    else:
        ext_offset = 36

    # Extended boot record
    lines.append("")
    lines.append("; Extended Boot Record")
    drive = data[ext_offset]
    res1 = data[ext_offset + 1]
    sig = data[ext_offset + 2]
    serial = struct.unpack("<I", data[ext_offset + 3:ext_offset + 7])[0]
    label = data[ext_offset + 7:ext_offset + 18].decode('ascii', errors='replace')
    fstype = data[ext_offset + 18:ext_offset + 26].decode('ascii', errors='replace')

    lines.append(f"ebr_drive:          db 0x{drive:02X}")
    lines.append(f"ebr_reserved:       db 0x{res1:02X}")
    lines.append(f"ebr_signature:      db 0x{sig:02X}")
    lines.append(f"ebr_serial:         dd 0x{serial:08X}")
    lines.append(f"ebr_label:          db \"{label}\"")
    lines.append(f"ebr_fs_type:        db \"{fstype}\"")

    # Boot code
    code_start = ext_offset + 26
    lines.append("")
    lines.append("; Boot code")
    lines.append(f"; Code starts at offset {code_start} (0x{code_start:02X})")

    # Find where actual code starts (after any padding)
    code_data = data[code_start:510]

    result = subprocess.run(
        ["ndisasm", "-b", "16", "-o", f"0x{0x7C00 + code_start:04X}", "-"],
        input=code_data,
        capture_output=True
    )

    for line in result.stdout.decode().split('\n'):
        if line.strip():
            parts = line.split(None, 2)
            if len(parts) >= 3:
                addr = parts[0]
                inst = parts[2] if len(parts) > 2 else ""
                lines.append(f"    {inst:40} ; {addr}")

    lines.append("")
    lines.append("; Boot signature")
    lines.append("times 510-($-$$) db 0")
    lines.append("dw 0xAA55")

    return '\n'.join(lines)


def verify_roundtrip(bin_path: Path, asm_path: Path) -> bool:
    """Verify that assembly compiles to identical binary."""
    original = bin_path.read_bytes()

    # Compile assembly
    result = subprocess.run(
        ["nasm", "-f", "bin", "-o", "/dev/stdout", str(asm_path)],
        capture_output=True
    )

    if result.returncode != 0:
        print(f"Assembly failed: {result.stderr.decode()}")
        return False

    compiled = result.stdout

    if original == compiled:
        print(f"MATCH: {asm_path.name} compiles to identical binary")
        return True

    # Find differences
    print(f"MISMATCH: Binaries differ")
    for i, (a, b) in enumerate(zip(original, compiled)):
        if a != b:
            print(f"  Offset 0x{i:03X}: original=0x{a:02X}, compiled=0x{b:02X}")
            if i > 10:
                print("  ...")
                break

    return False


def main():
    parser = argparse.ArgumentParser(description="Boot sector disassembler")
    parser.add_argument("binary", nargs="?", help="Boot sector binary file")
    parser.add_argument("--type", choices=["mbr", "vbr"], help="Force boot sector type")
    parser.add_argument("--output", "-o", help="Output assembly file")
    parser.add_argument("--verify", nargs=2, metavar=("BIN", "ASM"),
                       help="Verify assembly compiles to binary")

    args = parser.parse_args()

    if args.verify:
        bin_path = Path(args.verify[0])
        asm_path = Path(args.verify[1])
        success = verify_roundtrip(bin_path, asm_path)
        sys.exit(0 if success else 1)

    if not args.binary:
        parser.print_help()
        sys.exit(1)

    bin_path = Path(args.binary)
    data = bin_path.read_bytes()

    boot_type = args.type or detect_boot_type(data)
    print(f"Detected type: {boot_type.upper()}", file=sys.stderr)

    if boot_type == "mbr":
        asm = disasm_mbr(data)
    else:
        asm = disasm_vbr(data)

    if args.output:
        Path(args.output).write_text(asm)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(asm)


if __name__ == "__main__":
    main()
