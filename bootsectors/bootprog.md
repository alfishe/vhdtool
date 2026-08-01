# BootProg Boot Sectors

Generic boot sectors that load and execute `STARTUP.BIN` from FAT filesystems.

## Overview

BootProg is a collection of minimalist boot sectors by Alexei Frounze. Unlike DOS boot sectors that load IO.SYS, BootProg loads a file named `STARTUP.BIN` - making it perfect for custom bootloaders, bare-metal programs, or alternative operating systems.

**Repository**: https://github.com/alexfru/BootProg  
**License**: Public Domain  
**Author**: Alexei Frounze

## Files

| File | Type | FAT | Description |
|------|------|-----|-------------|
| `bootprog_fat12_vbr.bin` | VBR | FAT12 | For floppies and small volumes |
| `bootprog_fat16_vbr.bin` | VBR | FAT16 | For hard disks up to 2GB |
| `bootprog_fat32_vbr.bin` | VBR | FAT32 | For large volumes |
| `bootprog_floppy_144_vbr.bin` | VBR | FAT12 | Pre-configured for 1.44MB floppy |

## How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                    BOOTPROG BOOT FLOW                        │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. BIOS loads VBR to 0x7C00                                │
│                        ↓                                     │
│  2. VBR parses BPB, locates root directory                  │
│                        ↓                                     │
│  3. Searches for "STARTUP BIN" (8.3 format)                 │
│                        ↓                                     │
│  4. Reads FAT to follow cluster chain                       │
│                        ↓                                     │
│  5. Loads STARTUP.BIN to 0x0000:0x7E00                      │
│                        ↓                                     │
│  6. Jumps to 0x0000:0x7E00                                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## STARTUP.BIN Requirements

Your `STARTUP.BIN` must:

1. **Be a flat binary** - No headers (not EXE or COM with relocation)
2. **Start with executable code** - First byte is executed
3. **Expect to run at 0x7E00** - ORG 0x7E00 in assembly
4. **Fit in memory** - Loaded contiguously from 0x7E00

### Minimal STARTUP.BIN Example

```asm
; startup.asm - Minimal BootProg payload
BITS 16
ORG 0x7E00

start:
    ; Set up segments
    xor ax, ax
    mov ds, ax
    mov es, ax
    
    ; Print message
    mov si, message
.print:
    lodsb
    or al, al
    jz .halt
    mov ah, 0x0E
    int 0x10
    jmp .print

.halt:
    hlt
    jmp .halt

message: db "Hello from STARTUP.BIN!", 13, 10, 0
```

Build and deploy:
```bash
nasm -f bin -o STARTUP.BIN startup.asm
mcopy -i floppy.img STARTUP.BIN ::
```

## Register State at Entry

When STARTUP.BIN receives control:

| Register | Value |
|----------|-------|
| CS | 0x0000 |
| IP | 0x7E00 |
| DL | Boot drive (0x00=floppy, 0x80=HDD) |
| DS, ES | Undefined (set them yourself) |
| SS:SP | Valid stack below 0x7C00 |

## Usage Examples

### Create Bootable Floppy

```bash
# Create 1.44MB floppy image
dd if=/dev/zero of=floppy.img bs=512 count=2880

# Write BootProg VBR
dd if=bootprog_floppy_144_vbr.bin of=floppy.img conv=notrunc

# Format with FAT12 (Linux)
mkfs.fat -F 12 floppy.img

# Re-apply boot sector (mkfs overwrites it)
dd if=bootprog_floppy_144_vbr.bin of=floppy.img bs=1 count=3 conv=notrunc
dd if=bootprog_floppy_144_vbr.bin of=floppy.img bs=1 skip=62 seek=62 count=448 conv=notrunc

# Copy your program
mcopy -i floppy.img STARTUP.BIN ::

# Test
qemu-system-i386 -fda floppy.img
```

### Create Bootable Hard Disk Partition

```bash
# Assuming partition starts at sector 63
# 1. Format partition with FAT16
# 2. Apply BootProg VBR (preserving BPB)

python3 << 'EOF'
with open('disk.img', 'r+b') as f:
    f.seek(63 * 512)  # Partition start
    vbr = bytearray(f.read(512))
    
    with open('bootprog_fat16_vbr.bin', 'rb') as bp:
        template = bp.read(512)
    
    # Copy boot code, keep BPB
    vbr[0:3] = template[0:3]
    vbr[62:510] = template[62:510]
    
    f.seek(63 * 512)
    f.write(vbr)
EOF

# Copy STARTUP.BIN using vhdtool
vhdtool cp STARTUP.BIN disk.img:/STARTUP.BIN
```

## Use Cases

| Use Case | Description |
|----------|-------------|
| **Custom OS** | Boot your own kernel without DOS |
| **Bootloader** | Chain-load other operating systems |
| **Diagnostics** | Hardware testing without OS |
| **Demos** | Bare-metal demos/intros |
| **Education** | Learn OS development basics |

## Comparison with DOS Boot Sectors

| Feature | BootProg | DOS VBR |
|---------|----------|---------|
| Target file | STARTUP.BIN | IO.SYS |
| Load address | 0x7E00 | 0x0070:0x0000 |
| File format | Flat binary | DOS executable |
| FAT support | 12/16/32 | Version dependent |
| License | Public Domain | Proprietary |
| Source available | Yes | No (reverse-engineered) |

## Building from Source

```bash
cd bootsectors/sources

# Fetch BootProg sources
make fetch-bootprog

# Build all BootProg variants
make bootprog

# Sources are in bootprog/*.asm
```

## Technical Details

### Memory Map After Load

```
0x0000:0x0000 - 0x0000:0x04FF   Reserved (IVT, BDA)
0x0000:0x0500 - 0x0000:0x7BFF   Free
0x0000:0x7C00 - 0x0000:0x7DFF   Boot sector (BootProg VBR)
0x0000:0x7E00 - 0x0000:0x????   STARTUP.BIN loaded here
              - 0x0000:0x7BFF   Stack (grows down from 0x7C00)
```

### Supported File Sizes

| FAT Type | Max STARTUP.BIN Size |
|----------|---------------------|
| FAT12 | ~500 KB (limited by conventional memory) |
| FAT16 | ~500 KB |
| FAT32 | ~500 KB |

Practical limit is available conventional memory (~600 KB minus system areas).

## Troubleshooting

### "STARTUP.BIN not found"
- File must be named exactly `STARTUP.BIN` (uppercase)
- Must be in root directory
- Check with: `mdir -i floppy.img`

### System hangs after loading
- Verify STARTUP.BIN is valid x86 code
- Check ORG directive matches load address (0x7E00)
- Ensure segments are set correctly

### Works in QEMU, fails on real hardware
- Some BIOSes are pickier about BPB values
- Try different disk geometry settings
- Ensure boot signature (0x55AA) is present

## Related Files

- [sources/bootprog/boot12.asm](sources/bootprog/boot12.asm) - FAT12 source
- [sources/bootprog/boot16.asm](sources/bootprog/boot16.asm) - FAT16 source
- [sources/bootprog/boot32.asm](sources/bootprog/boot32.asm) - FAT32 source

## References

- [BootProg GitHub](https://github.com/alexfru/BootProg)
- [OSDev Wiki - Rolling Your Own Bootloader](https://wiki.osdev.org/Rolling_Your_Own_Bootloader)
