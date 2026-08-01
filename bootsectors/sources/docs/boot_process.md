# DOS Boot Process

This document explains how a PC boots from a FAT disk, from BIOS to DOS prompt.

## Boot Sequence Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         POWER ON                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ BIOS POST (Power-On Self Test)                                   │
│ - Initialize hardware                                            │
│ - Detect drives                                                  │
│ - Check boot order                                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ BIOS loads MBR (sector 0) to 0x7C00                              │
│ - Reads first sector of boot device                              │
│ - Verifies 0x55AA signature                                      │
│ - Jumps to 0x7C00                                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ MBR executes                                                     │
│ - Relocates self to 0x0600                                       │
│ - Scans partition table for active partition                     │
│ - Loads VBR of active partition to 0x7C00                        │
│ - Jumps to 0x7C00                                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ VBR (Volume Boot Record) executes                                │
│ - Parses BPB (BIOS Parameter Block)                              │
│ - Locates FAT and root directory                                 │
│ - Finds IO.SYS (or KERNEL.SYS for FreeDOS)                       │
│ - Loads IO.SYS to memory (typically 0x0070:0000)                 │
│ - Jumps to IO.SYS                                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ IO.SYS executes                                                  │
│ - Initializes DOS kernel                                         │
│ - Loads MSDOS.SYS                                                │
│ - Processes CONFIG.SYS                                           │
│ - Loads device drivers                                           │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ COMMAND.COM loaded                                               │
│ - Processes AUTOEXEC.BAT                                         │
│ - Displays DOS prompt                                            │
│ - Waits for user commands                                        │
└─────────────────────────────────────────────────────────────────┘
```

## Memory Map at Boot

```
0x00000 - 0x003FF   Interrupt Vector Table (1 KB)
0x00400 - 0x004FF   BIOS Data Area (256 bytes)
0x00500 - 0x07BFF   Free (conventional memory - 30 KB)
0x07C00 - 0x07DFF   Boot sector loaded here (512 bytes)
0x07E00 - 0x9FFFF   Free (conventional memory - ~600 KB)
0xA0000 - 0xBFFFF   Video memory (128 KB)
0xC0000 - 0xC7FFF   Video BIOS ROM (32 KB)
0xC8000 - 0xEFFFF   Adapter ROMs
0xF0000 - 0xFFFFF   System BIOS ROM (64 KB)
```

## BIOS Services Used by Boot Sectors

### INT 13h - Disk Services

```asm
; Reset disk system
mov ah, 00h
mov dl, drive       ; 0x00=A:, 0x80=C:
int 13h

; Read sectors (CHS)
mov ah, 02h
mov al, count       ; Number of sectors
mov ch, cylinder    ; Cylinder (0-1023)
mov cl, sector      ; Sector (1-63) + high 2 bits of cylinder
mov dh, head        ; Head (0-255)
mov dl, drive       ; Drive number
les bx, buffer      ; ES:BX = destination
int 13h
; CF=1 on error, AH=error code

; Check LBA extensions present
mov ah, 41h
mov bx, 0x55AA
mov dl, drive
int 13h
; CF=0 if extensions supported, BX=0xAA55

; Extended read (LBA)
mov ah, 42h
mov dl, drive
mov si, dap         ; DS:SI = Disk Address Packet
int 13h

; Disk Address Packet structure:
;   db 10h          ; Size of packet (16 bytes)
;   db 0            ; Reserved
;   dw count        ; Number of sectors
;   dw offset       ; Buffer offset
;   dw segment      ; Buffer segment
;   dq lba          ; Starting LBA (64-bit)
```

### INT 10h - Video Services

```asm
; Teletype output (print character)
mov ah, 0Eh
mov al, char
mov bx, 0007h       ; Page 0, attribute (white on black)
int 10h

; Set cursor position
mov ah, 02h
mov bh, page
mov dh, row
mov dl, column
int 10h
```

## FAT Filesystem Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ VBR (Volume Boot Record) - 1 sector                              │
│ Contains: Jump, BPB, Boot code                                   │
├─────────────────────────────────────────────────────────────────┤
│ Reserved sectors (optional, FAT32 has more)                      │
├─────────────────────────────────────────────────────────────────┤
│ FAT #1 (File Allocation Table)                                   │
├─────────────────────────────────────────────────────────────────┤
│ FAT #2 (backup copy)                                             │
├─────────────────────────────────────────────────────────────────┤
│ Root Directory (FAT12/16 only - fixed size)                      │
├─────────────────────────────────────────────────────────────────┤
│ Data Area (clusters 2, 3, 4, ...)                                │
│ - Files and subdirectories                                       │
│ - FAT32: Root directory is here too                              │
└─────────────────────────────────────────────────────────────────┘
```

## Calculating Filesystem Locations

```
; From BPB values:
reserved_sectors    = BPB[0x0E]     ; 2 bytes
num_fats            = BPB[0x10]     ; 1 byte
root_entries        = BPB[0x11]     ; 2 bytes
fat_size            = BPB[0x16]     ; 2 bytes (FAT12/16) or BPB[0x24] (FAT32)
sectors_per_cluster = BPB[0x0D]     ; 1 byte

; Calculate locations:
fat_start    = reserved_sectors
root_start   = fat_start + (num_fats * fat_size)
root_sectors = (root_entries * 32 + 511) / 512
data_start   = root_start + root_sectors

; Convert cluster to sector:
sector = data_start + (cluster - 2) * sectors_per_cluster
```

## MS-DOS System Files

| File | Purpose |
|------|---------|
| IO.SYS | DOS kernel initialization, device drivers |
| MSDOS.SYS | DOS kernel, system calls (INT 21h) |
| COMMAND.COM | Command interpreter |
| CONFIG.SYS | System configuration (drivers, memory) |
| AUTOEXEC.BAT | Startup commands |

### Boot Requirements

1. **IO.SYS must be first file in root directory**
   - Some DOS versions require contiguous clusters
   - VBR searches for exactly "IO      SYS" (8.3 format)

2. **MSDOS.SYS must be second file**
   - Loaded by IO.SYS
   - Contains DOS kernel

3. **Both must have System and Hidden attributes**
   - Attribute byte = 0x07 (Hidden + System + Read-only)

## Common Boot Errors

| Message | Cause |
|---------|-------|
| "Invalid system disk" | IO.SYS not found or corrupted |
| "Non-system disk or disk error" | VBR can't load system files |
| "Error loading operating system" | MBR can't load VBR |
| "Missing operating system" | No active partition |
| "Invalid partition table" | Corrupted MBR partition entries |

## Testing Boot Sectors

### Using QEMU

```bash
# Test MBR with disk image
qemu-system-i386 -hda disk.img

# Test VBR (floppy)
qemu-system-i386 -fda floppy.img

# With debugging
qemu-system-i386 -hda disk.img -d int -no-reboot
```

### Using Bochs

```bash
# Create bochsrc
echo "boot: disk" > bochsrc
echo "ata0-master: type=disk, path=disk.img" >> bochsrc
bochs -f bochsrc
```

## References

- [OSDev Wiki - Boot Sequence](https://wiki.osdev.org/Boot_Sequence)
- [OSDev Wiki - MBR](https://wiki.osdev.org/MBR_(x86))
- [Ralph Brown's Interrupt List](http://www.ctyme.com/rbrown.htm)
- [The Starman's Realm](https://thestarman.pcministry.com/asm/mbr/)
