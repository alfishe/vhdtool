# Utility Boot Sectors and Boot Managers

## GMBLDR (Generic Master Bootstrap Loader)

GMBLDR is a generic MBR from BTTR Software (1997-2005).

### Features

- Standard MBR functionality (finds active partition, loads VBR)
- Supports both CHS and LBA (INT 13h extensions)
- Error messages: "No active partition!", "Bad partition table!", "OS load error!"
- Relocates to 0x0600 before loading partition VBR

### Code Analysis

```
Offset  Instruction       Description
------  ----------------  ------------------------------------
0600    xor cx,cx         Clear CX
0602    cli               Disable interrupts
0603    mov ss,cx         SS = 0
0605    mov sp,0x7c00     Stack below code
0608    sti               Enable interrupts
0609    mov es,cx         ES = 0
060B    mov ds,cx         DS = 0
060D    mov si,sp         SI = 0x7C00 (source)
060F    mov di,0x600      DI = 0x600 (destination)
0612    push si           Save original location
0613    mov ch,0x1        CX = 0x100 (256 words)
0615    cld               Clear direction
0616    rep movsw         Relocate 512 bytes to 0x0600
0618    mov al,[0x475]    Get hard disk count from BIOS
061B    or al,0x80        Convert to drive number
061D    cmp dl,al         Compare with boot drive
061F    jl 0x623          If boot drive < count, use it
0621    mov dl,0x80       Default to first hard disk
...
0632    mov cl,0x4        4 partition entries
0634    mov bx,0x7be      Start of partition table
0637    cmp [bx],ch       Check boot flag (0x80)
...
```

### Error Messages

| Offset | Message |
|--------|---------|
| 0x6D0 | "HD1:.Ok. Booting." |
| 0x6E3 | "No active partition!" |
| 0x6F9 | "Bad partition table!" |
| 0x70E | "OS load error!" |
| 0x71D | "Any key to reboot..." |

### Version String

```
GMBLDR Version 18-FEB-2005 - generic Master Bootstrap Loader
Copyright (c) 1997-2005 BTTR Software
```

---

## FreeDOS 4.1 VBR (METAKERN.SYS loader)

Some FreeDOS configurations use a kernel named `METAKERN.SYS` instead of `KERNEL.SYS`.

### Identification

- OEM String: "FRDOS4.1"
- Kernel file: METAKERN.SYS (11-character 8.3 format: "METAKERNSYS")

### Boot Process

```
┌─────────────────────────────────────────────────────────────┐
│  1. BIOS loads VBR at 0x7C00                                │
│  2. VBR relocates to 0x1FE0:7C00                            │
│  3. VBR searches root directory for "METAKERNSYS"           │
│  4. Loads METAKERN.SYS into memory                          │
│  5. Jumps to kernel entry point                             │
│  6. FreeDOS kernel initializes, runs CONFIG.SYS             │
│  7. COMMAND.COM runs AUTOEXEC.BAT                           │
└─────────────────────────────────────────────────────────────┘
```

---

## Utility Floppy Boot Process

Utility floppies (disk tools, installers) typically boot their own OS, then provide tools to modify the target hard disk.

### How It Works

```
Boot from utility floppy
    ↓
Floppy's VBR loads (e.g., FreeDOS)
    ↓
DOS runs from floppy
    ↓
User runs disk utilities (FDISK, FORMAT, SYS, etc.)
    ↓
Utilities modify hard disk (partitions, boot sectors)
    ↓
Reboot from HDD → HDD's MBR/VBR now active
```

### Common Misconception

A boot manager file stored **on** a floppy is not active during boot - it's a utility to be **installed** to a hard disk. The floppy boots using its own VBR, and the boot manager file is just data until written to sector 0 of the target disk.

### Typical Utility Floppy Contents

| File | Purpose |
|------|---------|
| KERNEL.SYS | DOS kernel (boots the floppy) |
| COMMAND.COM | Command interpreter |
| FDISK.EXE | Partition hard disks |
| FORMAT.COM | Format partitions |
| SYS.COM | Transfer system files to target |
| BOOTMGR.MBR | Boot manager to install (not active) |

---

## License

- **GMBLDR**: Copyright 1997-2005 BTTR Software (license unknown)
- **FreeDOS**: GPL v2+
