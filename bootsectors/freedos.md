# FreeDOS Boot Sectors

Open-source boot sectors from the FreeDOS project.

## Overview

FreeDOS is a free, open-source DOS-compatible operating system. These boot sectors load the FreeDOS kernel (`KERNEL.SYS`) or can be configured to load MS-DOS system files.

**Project**: https://www.freedos.org/  
**Kernel Source**: https://github.com/FDOS/kernel  
**License**: GPL v2+

## Files

| File | Type | Description |
|------|------|-------------|
| `freedos_floppy_144_vbr.bin` | VBR | 1.44MB floppy boot sector |
| `freedos_floppy_720_vbr.bin` | VBR | 720KB floppy boot sector |
| `freedos_floppy_360_vbr.bin` | VBR | 360KB floppy boot sector |
| `freedos41_floppy_vbr.bin` | VBR | FreeDOS 4.1 boot sector |
| `freedos_floppy_144.img` | Image | Complete 1.44MB bootable floppy |
| `freedos_floppy_720.img` | Image | Complete 720KB bootable floppy |

## Boot Process

FreeDOS boot sectors are similar to MS-DOS but with some differences:

```
┌─────────────────────────────────────────────────────────────┐
│                   FREEDOS BOOT FLOW                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. BIOS loads VBR to 0x7C00                                │
│                        ↓                                     │
│  2. VBR searches for KERNEL.SYS (or IO.SYS)                 │
│                        ↓                                     │
│  3. Loads kernel to memory                                  │
│                        ↓                                     │
│  4. Kernel initializes, loads COMMAND.COM                   │
│                        ↓                                     │
│  5. Processes FDCONFIG.SYS (or CONFIG.SYS)                  │
│                        ↓                                     │
│  6. Runs FDAUTOEM.BAT (or AUTOEXEC.BAT)                     │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## FreeDOS vs MS-DOS File Names

| Purpose | FreeDOS | MS-DOS |
|---------|---------|--------|
| Kernel (BIOS) | KERNEL.SYS | IO.SYS |
| Kernel (DOS) | (in KERNEL.SYS) | MSDOS.SYS |
| Command interpreter | COMMAND.COM | COMMAND.COM |
| Config file | FDCONFIG.SYS | CONFIG.SYS |
| Startup batch | FDAUTOEM.BAT | AUTOEXEC.BAT |

Note: FreeDOS also supports MS-DOS file names for compatibility.

## Floppy Formats

### 1.44MB (3.5" HD)
```
Sectors per track:  18
Heads:              2
Cylinders:          80
Total sectors:      2880
Bytes per sector:   512
Total size:         1,474,560 bytes
FAT type:           FAT12
```

### 720KB (3.5" DD)
```
Sectors per track:  9
Heads:              2
Cylinders:          80
Total sectors:      1440
Bytes per sector:   512
Total size:         737,280 bytes
FAT type:           FAT12
```

### 360KB (5.25" DD)
```
Sectors per track:  9
Heads:              2
Cylinders:          40
Total sectors:      720
Bytes per sector:   512
Total size:         368,640 bytes
FAT type:           FAT12
```

## Usage

### Extract Files from FreeDOS Floppy
```bash
# List contents
mdir -i freedos_floppy_144.img

# Extract file
mcopy -i freedos_floppy_144.img ::KERNEL.SYS .

# Extract all
mcopy -i freedos_floppy_144.img ::* ./freedos_files/
```

### Create FreeDOS Boot Floppy
```bash
# Create blank floppy
dd if=/dev/zero of=floppy.img bs=512 count=2880

# Format as FAT12
mkfs.fat -F 12 -n FREEDOS floppy.img

# Apply FreeDOS boot sector
dd if=freedos_floppy_144_vbr.bin of=floppy.img bs=1 count=3 conv=notrunc
dd if=freedos_floppy_144_vbr.bin of=floppy.img bs=1 skip=62 seek=62 count=448 conv=notrunc

# Copy system files
mcopy -i floppy.img KERNEL.SYS ::
mcopy -i floppy.img COMMAND.COM ::

# Test
qemu-system-i386 -fda floppy.img
```

### Use FreeDOS Kernel with MS-DOS Boot Sector
FreeDOS kernel can work with MS-DOS boot sectors if you rename:
```bash
# Rename for MS-DOS compatibility
mv KERNEL.SYS IO.SYS
# Create empty MSDOS.SYS (FreeDOS doesn't need it but boot sector looks for it)
touch MSDOS.SYS
```

## Compatibility

| System | Compatible | Notes |
|--------|------------|-------|
| FreeDOS | **Yes** | Native |
| MS-DOS 6.x | Yes | Loads MS-DOS if files present |
| Windows 3.x | Yes | Run Windows from FreeDOS |
| MiSTer ao486 | **Yes** | Tested |
| Real 486 hardware | Yes | Well tested |

## Building from Source

```bash
cd bootsectors/sources

# Fetch FreeDOS boot sources
make fetch-freedos

# Build (requires adjustments for standalone use)
# FreeDOS boot.asm has dependencies on kernel build system
```

### FreeDOS Kernel Build (Full)
```bash
git clone https://github.com/FDOS/kernel.git
cd kernel
make
# Boot sectors will be in boot/
```

## Technical Details

### VBR Structure
```
Offset  Size  Description
------  ----  -----------
0x00    3     Jump instruction (EB xx 90)
0x03    8     OEM name ("FRDOS5.1" or similar)
0x0B    25    BIOS Parameter Block (BPB)
0x24    26    Extended BPB
0x3E    448   Boot code
0x1FE   2     Signature (55 AA)
```

### Kernel Loading
FreeDOS boot sector loads KERNEL.SYS to 0x0060:0x0000 (physical 0x600).

The kernel then:
1. Relocates itself higher in memory
2. Initializes device drivers
3. Sets up DOS interrupt handlers (INT 21h)
4. Loads COMMAND.COM

## Advantages Over MS-DOS

| Feature | FreeDOS | MS-DOS 6.22 |
|---------|---------|-------------|
| Source available | Yes (GPL) | No |
| FAT32 support | Yes | No |
| Long filename support | Yes (via DOSLFN) | No |
| Active development | Yes | Discontinued |
| Cost | Free | License required |

## Troubleshooting

### "No system disk" or "Invalid system disk"
- KERNEL.SYS must be in root directory
- Try renaming to IO.SYS for MS-DOS compatible boot sector
- Check file isn't fragmented (some boot sectors require contiguous)

### Boots but no prompt
- Check COMMAND.COM is present
- Verify CONFIG.SYS/FDCONFIG.SYS doesn't have errors
- Try booting with minimal config: `SHELL=COMMAND.COM /P`

### Works on QEMU, fails on MiSTer
- MiSTer ao486 is more sensitive to timing
- Try simpler CONFIG.SYS
- Ensure disk image geometry matches BPB

## Related Resources

- [FreeDOS Wiki](http://wiki.freedos.org/)
- [FreeDOS Kernel Source](https://github.com/FDOS/kernel)
- [FreeDOS Boot Disks Collection](https://github.com/codercowboy/freedosbootdisks)
