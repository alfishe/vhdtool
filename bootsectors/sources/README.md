# Boot Sector Source Code Collection

This directory contains source code for building custom boot sectors. Understanding and modifying boot sectors allows you to create custom boot environments for MiSTer ao486.

## Quick Start

```bash
# Install NASM (see docs/building.md for other platforms)
# macOS:  brew install nasm
# Linux:  sudo apt install nasm
# Windows: choco install nasm

# Build all boot sectors
make all

# Test with QEMU
qemu-system-i386 -hda your_disk.img
```

For detailed installation instructions on **macOS**, **Linux**, and **Windows**, see **[docs/building.md](docs/building.md)**.

## Directory Structure

```
sources/
├── bootprog/       # BootProg - generic FAT boot loader (loads any .BIN file)
├── freedos/        # FreeDOS boot sectors
├── msdos/          # MS-DOS style boot sector templates
├── mbr/            # Master Boot Record implementations
├── tools/          # Assembly tools and utilities
└── docs/           # Technical documentation
```

## Quick Start

### Prerequisites

You need NASM (Netwide Assembler) to build boot sectors:

```bash
# macOS
brew install nasm

# Ubuntu/Debian
sudo apt install nasm

# Windows
# Download from https://www.nasm.us/
```

### Building a Boot Sector

```bash
# Assemble to raw binary
nasm -f bin -o bootsector.bin bootsector.asm

# Verify size (must be 512 bytes)
ls -l bootsector.bin

# View hex dump
xxd bootsector.bin | head -32
```

## Boot Sector Basics

### MBR (Master Boot Record)

Located at sector 0 of the disk. Structure:
- Bytes 0-445: Boot code
- Bytes 446-509: Partition table (4 entries × 16 bytes)
- Bytes 510-511: Signature (0x55, 0xAA)

The MBR's job:
1. Search partition table for active (bootable) partition
2. Load that partition's first sector (VBR)
3. Jump to VBR code

### VBR (Volume Boot Record)

Located at the first sector of each partition. Structure:
- Bytes 0-2: Jump instruction (to skip BPB)
- Bytes 3-61: BIOS Parameter Block (filesystem info)
- Bytes 62-509: Boot code
- Bytes 510-511: Signature (0x55, 0xAA)

The VBR's job:
1. Parse BPB to locate FAT and root directory
2. Find and load the boot file (IO.SYS, KERNEL.SYS, etc.)
3. Jump to the loaded code

## x86 Real Mode Programming

Boot sectors run in x86 real mode (16-bit):
- 1MB addressable memory
- Segment:offset addressing (CS:IP, DS:SI, etc.)
- BIOS interrupts for disk I/O (INT 13h)
- No protected mode, no paging

### Key BIOS Services

```asm
; Read disk sectors
mov ah, 02h         ; Function: read sectors
mov al, count       ; Number of sectors
mov ch, cylinder
mov cl, sector
mov dh, head
mov dl, drive       ; 0x80 = first hard disk
mov bx, buffer      ; ES:BX = destination
int 13h

; Print character
mov ah, 0Eh         ; Function: teletype output
mov al, char
int 10h
```

### Memory Map at Boot

```
0x0000:0x0000 - 0x0000:0x03FF  Interrupt Vector Table
0x0040:0x0000 - 0x0040:0x00FF  BIOS Data Area
0x0000:0x0500 - 0x0000:0x7BFF  Free (low memory)
0x0000:0x7C00 - 0x0000:0x7DFF  Boot sector loaded here
0x0000:0x7E00 - 0x9000:0xFFFF  Free (conventional memory)
0xA000:0x0000 - 0xF000:0xFFFF  Video memory, ROM
```

## Projects in This Collection

### BootProg

Minimal boot sector that loads and executes a file named `STARTUP.BIN`:
- FAT12, FAT16, FAT32 support
- Floppy and hard disk support
- Public domain license
- Perfect for custom bootloaders

### FreeDOS Boot

Open source boot sectors from the FreeDOS project:
- GPL license
- Well-documented code
- Compatible with MS-DOS

### MS-DOS Compatible Templates

Templates that replicate MS-DOS boot behavior:
- Load IO.SYS and MSDOS.SYS
- Compatible with original DOS system files
- Based on reverse-engineered specifications

## Building Your Own

### Minimal VBR Template

```asm
; minimal_vbr.asm - Minimal FAT16 VBR template
BITS 16
ORG 0x7C00

; Jump over BPB
jmp short start
nop

; BPB - filled in by vhdtool
times 59 db 0

start:
    ; Set up segments
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7C00
    
    ; Print message
    mov si, msg
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

msg: db "Boot sector loaded!", 13, 10, 0

; Pad to 510 bytes and add signature
times 510-($-$$) db 0
dw 0xAA55
```

Build: `nasm -f bin -o minimal_vbr.bin minimal_vbr.asm`

## Documentation

| Document | Description |
|----------|-------------|
| [docs/building.md](docs/building.md) | **Setup guide for macOS, Linux, Windows** |
| [docs/pc_boot_theory.md](docs/pc_boot_theory.md) | Complete boot process theory with diagrams |
| [docs/boot_process.md](docs/boot_process.md) | Technical boot sequence reference |
| [docs/x86_assembly.md](docs/x86_assembly.md) | x86 real-mode assembly quick reference |

## Resources

- [OSDev Wiki - Boot Sequence](https://wiki.osdev.org/Boot_Sequence)
- [OSDev Wiki - FAT](https://wiki.osdev.org/FAT)
- [Starman's Boot Records](https://thestarman.pcministry.com/asm/mbr/)
- [Microsoft FAT Specification](https://download.microsoft.com/download/1/6/1/161ba512-40e2-4cc9-843a-923143f3456c/fatgen103.doc)

## Contributing

To add a new boot sector:

1. Create a subdirectory with source files
2. Include a Makefile for building
3. Add documentation explaining what it does
4. Test with QEMU before deploying to MiSTer
5. Include license information
