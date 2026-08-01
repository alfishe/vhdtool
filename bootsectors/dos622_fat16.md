# MS-DOS 6.22 FAT16 Boot Sectors

Boot sectors extracted from a working MS-DOS 6.22 MiSTer ao486 disk image.

## Files

| File | Type | Size | Description |
|------|------|------|-------------|
| `dos622_fat16_mbr.bin` | MBR | 512 bytes | Master Boot Record |
| `dos622_fat16_vbr.bin` | VBR | 512 bytes | Volume Boot Record (FAT16) |

## MBR Details

**Purpose**: Loads VBR from the active partition.

```
Offset  Content
------  -------
0x000   Boot code (446 bytes)
0x1BE   Partition table (64 bytes)
0x1FE   Boot signature (0x55, 0xAA)
```

### Key Features
- Scans partition table for active partition (boot flag 0x80)
- Loads VBR from partition's first sector to 0x7C00
- Passes drive number in DL register
- Compatible with CHS and LBA addressing

### Hex Dump (First 64 bytes)
```
00000000: 33c0 8ed0 bc00 7c8e c08e d8be 007c bf00  3.....|......|..
00000010: 06b9 0002 fcf3 a450 6819 06cb be07 7cbf  .......Ph.....|.
00000020: 0506 b901 028b f2f3 a4ea 0506 0000 bebe  ................
00000030: 07b1 0438 2c74 0983 c610 fecb 75f2 cd18  ...8,t......u...
```

## VBR Details

**Purpose**: Loads IO.SYS from FAT16 filesystem.

### BIOS Parameter Block (BPB)
```
Offset  Size  Field                Value (typical)
------  ----  -----                -----
0x00    3     Jump instruction     EB 3C 90
0x03    8     OEM Name             "MSDOS5.0"
0x0B    2     Bytes per sector     512
0x0D    1     Sectors per cluster  4-64 (size dependent)
0x0E    2     Reserved sectors     1
0x10    1     Number of FATs       2
0x11    2     Root entries         512
0x13    2     Total sectors (16)   0 (use 32-bit)
0x15    1     Media descriptor     0xF8 (hard disk)
0x16    2     Sectors per FAT      varies
0x18    2     Sectors per track    63
0x1A    2     Number of heads      16-255
0x1C    4     Hidden sectors       63 (partition start)
0x20    4     Total sectors (32)   partition size
```

### Boot Process
1. Sets up stack at 0x7C00
2. Calculates root directory location: `reserved + (FATs × FAT_size)`
3. Loads root directory to memory
4. Searches for "IO      SYS" (8.3 format)
5. Reads FAT to follow cluster chain
6. Loads IO.SYS to 0x0070:0x0000
7. Jumps to IO.SYS entry point

### System File Requirements
- **IO.SYS** - Must be first file in root directory
- **MSDOS.SYS** - Must be second file
- Both should have Hidden + System attributes (0x06)

## Usage

### Apply to New Disk Image
```bash
# Copy MBR boot code (preserve partition table)
vhdtool makeboot newdisk.vhd --from-image dos622_source.vhd

# Or manually:
dd if=dos622_fat16_mbr.bin of=newdisk.img bs=1 count=446 conv=notrunc
```

### Apply VBR (preserve BPB)
```python
# The BPB (bytes 3-61) must match the actual filesystem!
with open('disk.img', 'r+b') as f:
    f.seek(63 * 512)  # Partition start
    vbr = bytearray(f.read(512))
    
    with open('dos622_fat16_vbr.bin', 'rb') as src:
        template = src.read(512)
    
    # Copy jump and boot code, preserve BPB
    vbr[0:3] = template[0:3]      # Jump instruction
    vbr[62:510] = template[62:510]  # Boot code
    
    f.seek(63 * 512)
    f.write(vbr)
```

## Compatibility

| System | Compatible |
|--------|------------|
| MS-DOS 3.x | Yes |
| MS-DOS 4.x | Yes |
| MS-DOS 5.x | Yes |
| MS-DOS 6.x | Yes |
| Windows 3.x | Yes |
| Windows 95/98 | Partial (prefers own VBR) |
| FreeDOS | Yes |
| MiSTer ao486 | **Yes** (tested) |

## Source

Extracted from MiSTer ao486 200MB FAT16 template image using:
```bash
vhdtool makeboot template.vhd --extract dos622_fat16
```

## Related Files
- [sources/msdos/fat16_vbr.asm](sources/msdos/fat16_vbr.asm) - Commented source code
- [sources/mbr/standard_mbr.asm](sources/mbr/standard_mbr.asm) - MBR source code

## License

These boot sectors are functional equivalents based on public specifications.
Original MS-DOS code is © Microsoft Corporation.
