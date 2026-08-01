# Boot Sector Collection

A collection of MBR (Master Boot Record) and VBR (Volume Boot Record) boot sectors for various DOS and Windows versions. Designed for MiSTer FPGA ao486 core.

## Quick Start

```bash
# Apply boot sectors from a working DOS image
vhdtool makeboot newdisk.vhd --from-image bootable_dos.vhd

# Or use command line
dd if=bootsectors/dos622_fat16_mbr.bin of=disk.img bs=1 count=446 conv=notrunc
```

## Documentation by Category

Each boot sector family has detailed documentation:

| Document | Description |
|----------|-------------|
| [dos622_fat16.md](dos622_fat16.md) | **MS-DOS 6.22** - Recommended for ao486 |
| [bootprog.md](bootprog.md) | **BootProg** - Custom bootloaders, loads STARTUP.BIN |
| [freedos.md](freedos.md) | **FreeDOS** - Open-source DOS alternative |
| [windows.md](windows.md) | **Windows 3.1/95** - Historical reference |
| [utilities.md](utilities.md) | **Utilities** - GMBLDR, FreeDOS 4.1, utility floppy boot process |

## Available Boot Sectors

### MS-DOS 6.22 (Recommended for ao486)

| File | Type | Description |
|------|------|-------------|
| `dos622_fat16_mbr.bin` | MBR | Standard DOS MBR for FAT16 hard disks |
| `dos622_fat16_vbr.bin` | VBR | FAT16 boot sector, loads IO.SYS |
| `dos622_template_mbr.bin` | MBR | MiSTer ao486 template MBR |
| `dos622_template_vbr.bin` | VBR | FAT12 boot sector from 10MB template |
| `msdos622_floppy_vbr.bin` | VBR | Original MS-DOS 6.22 floppy boot sector |

**Details**: [dos622_fat16.md](dos622_fat16.md)

### BootProg (Generic Boot Sectors)

| File | Type | Description |
|------|------|-------------|
| `bootprog_fat12_vbr.bin` | VBR | Loads STARTUP.BIN from FAT12 |
| `bootprog_fat16_vbr.bin` | VBR | Loads STARTUP.BIN from FAT16 |
| `bootprog_fat32_vbr.bin` | VBR | Loads STARTUP.BIN from FAT32 |
| `bootprog_floppy_144_vbr.bin` | VBR | 1.44MB floppy, loads STARTUP.BIN |

**Details**: [bootprog.md](bootprog.md) | **License**: Public Domain

### FreeDOS

| File | Type | Description |
|------|------|-------------|
| `freedos_floppy_144_vbr.bin` | VBR | 1.44MB floppy boot sector (FAT12) |
| `freedos_floppy_720_vbr.bin` | VBR | 720K floppy boot sector (FAT12) |
| `freedos_floppy_360_vbr.bin` | VBR | 360K floppy boot sector (FAT12) |
| `freedos41_floppy_vbr.bin` | VBR | FreeDOS 4.1 boot sector |

**Details**: [freedos.md](freedos.md) | **License**: GPL v2+

### Windows 95

| File | Type | Description |
|------|------|-------------|
| `win95_mbr.bin` | MBR | Windows 95 MBR |
| `win95_vbr.bin` | VBR | Windows 95 FAT16 boot sector |

**Details**: [windows.md](windows.md)

> **Note**: Windows 3.1 has no dedicated bootloader - it uses standard MS-DOS boot sectors.
> Use `dos622_fat16_vbr.bin` for Windows 3.1.

### Other

| File | Type | Description |
|------|------|-------------|
| `pchdd_original_mbr.bin` | MBR | Smart Boot Manager V2.0 |
| `pchdd_original_vbr.bin` | VBR | MS-DOS 8.0 style boot sector |
| `standard_mbr.bin` | MBR | Built from sources/mbr/standard_mbr.asm |
| `fat16_vbr.bin` | VBR | Built from sources/msdos/fat16_vbr.asm |

## File Naming Convention

| Pattern | Meaning |
|---------|---------|
| `*_mbr.bin` | Master Boot Record (sector 0 of disk) |
| `*_vbr.bin` | Volume Boot Record (first sector of partition) |
| `*.img` | Complete disk/floppy image |
| `*.md` | Documentation (detailed info about each type) |

## Usage

### With vhdtool

```bash
# Copy boot sectors from a working image
vhdtool makeboot newdisk.vhd --from-image dos622.vhd

# Extract boot sectors for safekeeping
vhdtool makeboot myimage.vhd --extract mydos
```

### Manual Application

```python
# Apply MBR (preserving partition table)
with open('dos622_fat16_mbr.bin', 'rb') as f:
    mbr_code = f.read(446)  # Only boot code

with open('mydisk.img', 'r+b') as f:
    disk_mbr = bytearray(f.read(512))
    disk_mbr[0:446] = mbr_code
    f.seek(0)
    f.write(bytes(disk_mbr))

# Apply VBR (preserving BPB at bytes 3-61)
with open('dos622_fat16_vbr.bin', 'rb') as f:
    template = f.read(512)

with open('mydisk.img', 'r+b') as f:
    f.seek(63 * 512)  # Partition start
    vbr = bytearray(f.read(512))
    vbr[0:3] = template[0:3]        # Jump instruction
    vbr[62:510] = template[62:510]  # Boot code
    f.seek(63 * 512)
    f.write(bytes(vbr))
```

## Building from Source

The `sources/` directory contains assembly source code:

```bash
cd sources

# Install NASM (see sources/docs/building.md for all platforms)
# macOS:  brew install nasm
# Linux:  sudo apt install nasm

# Build all boot sectors
make all

# List all targets
make help
```

### Documentation

| Document | Description |
|----------|-------------|
| [sources/docs/building.md](sources/docs/building.md) | **Setup guide for macOS, Linux, Windows** |
| [sources/docs/pc_boot_theory.md](sources/docs/pc_boot_theory.md) | Complete boot process with diagrams |
| [sources/docs/boot_process.md](sources/docs/boot_process.md) | Technical reference |
| [sources/docs/x86_assembly.md](sources/docs/x86_assembly.md) | x86 assembly quick reference |

### Source Code

| File | Description |
|------|-------------|
| `sources/mbr/standard_mbr.asm` | Fully commented MBR (educational) |
| `sources/msdos/fat16_vbr.asm` | Fully commented FAT16 VBR |
| `sources/bootprog/*.asm` | BootProg sources (Public Domain) |

## Boot Sector Structure

### MBR (512 bytes)

```
┌──────────────────────────────────────┐
│ Boot code (446 bytes)                │ 0x000-0x1BD
├──────────────────────────────────────┤
│ Partition 1 (16 bytes)               │ 0x1BE
├──────────────────────────────────────┤
│ Partition 2 (16 bytes)               │ 0x1CE
├──────────────────────────────────────┤
│ Partition 3 (16 bytes)               │ 0x1DE
├──────────────────────────────────────┤
│ Partition 4 (16 bytes)               │ 0x1EE
├──────────────────────────────────────┤
│ Signature (0x55, 0xAA)               │ 0x1FE
└──────────────────────────────────────┘
```

### VBR (512 bytes)

```
┌──────────────────────────────────────┐
│ Jump instruction (3 bytes)           │ 0x00
├──────────────────────────────────────┤
│ OEM Name (8 bytes)                   │ 0x03
├──────────────────────────────────────┤
│ BIOS Parameter Block (51 bytes)      │ 0x0B  ← Filesystem info
├──────────────────────────────────────┤
│ Boot code (448 bytes)                │ 0x3E
├──────────────────────────────────────┤
│ Signature (0x55, 0xAA)               │ 0x1FE
└──────────────────────────────────────┘
```

## Compatibility Matrix

| Boot Sector | ao486 | DOS 6.22 | FreeDOS | Win 3.x | Win 95 |
|-------------|-------|----------|---------|---------|--------|
| dos622_fat16 | ✅ | ✅ | ✅ | ✅ | ⚠️ |
| bootprog | ✅ | N/A | N/A | N/A | N/A |
| freedos | ✅ | ⚠️ | ✅ | ✅ | ⚠️ |
| win95 | ⚠️ | ✅ | ✅ | ✅ | ✅ |

✅ = Fully compatible | ⚠️ = May work | N/A = Not applicable

## References

- [Boot Records Revealed](https://thestarman.pcministry.com/asm/mbr/) - Detailed boot sector documentation
- [OSDev Wiki - Boot Sequence](https://wiki.osdev.org/Boot_Sequence)
- [Microsoft FAT Specification](https://download.microsoft.com/download/1/6/1/161ba512-40e2-4cc9-843a-923143f3456c/fatgen103.doc)
- [BootProg](https://github.com/alexfru/BootProg) - Public domain boot sectors
- [FreeDOS](https://www.freedos.org/) - Open source DOS
