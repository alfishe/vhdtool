# Windows Boot Sectors

## Windows 3.1 - No Dedicated Bootloader

**Windows 3.1 does NOT have its own bootloader.** It runs entirely on top of MS-DOS.

The boot sector previously included as `win31_floppy_vbr.bin` was simply a standard MS-DOS 4.0 boot sector extracted from a Windows 3.1 setup disk. Analysis confirmed:

```
Comparison: msdos622_floppy_vbr.bin vs win31_floppy_vbr.bin

OEM String:     "MSDOS5.0"              "MSDOS4.0"
Boot Code:      Nearly identical        Minor version differences
Functionality:  Same                    Same
```

**Recommendation**: Use `dos622_fat16_vbr.bin` or `msdos622_floppy_vbr.bin` for Windows 3.1. They are newer and fully compatible.

### Windows 3.1 Boot Process

```
┌─────────────────────────────────────────────────────────────┐
│  1. BIOS → MBR → VBR (standard MS-DOS boot)                 │
│  2. VBR loads IO.SYS → MSDOS.SYS → COMMAND.COM              │
│  3. CONFIG.SYS and AUTOEXEC.BAT execute                     │
│  4. AUTOEXEC.BAT runs WIN.COM (or user types WIN)           │
│  5. WIN.COM loads WIN386.EXE or DOSX.EXE                    │
│  6. Windows kernel (KRNL386.EXE) loads                      │
│  7. Windows GUI starts                                      │
└─────────────────────────────────────────────────────────────┘
```

Windows 3.x is a graphical shell, not a standalone operating system. Any MS-DOS boot sector works.

---

## Windows 95 Boot Sectors

Windows 95 introduced its own boot code, distinct from MS-DOS.

### Files

| File | Type | Description |
|------|------|-------------|
| `win95_mbr.bin` | MBR | Windows 95 Master Boot Record |
| `win95_vbr.bin` | VBR | Windows 95 FAT16 Volume Boot Record |

### Key Differences from MS-DOS

| Feature | MS-DOS 6.22 | Windows 95 |
|---------|-------------|------------|
| MBR code | ~200 bytes | ~300 bytes |
| LBA support | Limited | Full INT 13h extensions |
| Error messages | Minimal | Descriptive |
| IO.SYS format | Separate kernel | Combined (IO.SYS + MSDOS.SYS merged) |
| Boot to GUI | No | Yes (BootGUI=1) |

### Windows 95 MBR Features

- Scans partition table for active partition
- Supports both CHS and LBA disk access
- Error messages: "Invalid partition table", "Error loading operating system", "Missing operating system"
- Relocates to 0x0600 before loading VBR

### Windows 95 Boot Process

```
┌─────────────────────────────────────────────────────────────┐
│                 WINDOWS 95 BOOT FLOW                         │
├─────────────────────────────────────────────────────────────┤
│  1. BIOS → MBR → VBR                                        │
│                  ↓                                           │
│  2. VBR loads IO.SYS (real mode stub)                       │
│                  ↓                                           │
│  3. IO.SYS processes MSDOS.SYS settings                     │
│                  ↓                                           │
│  4. CONFIG.SYS processed (DOS compatibility)                │
│                  ↓                                           │
│  5. COMMAND.COM loads, runs AUTOEXEC.BAT                    │
│                  ↓                                           │
│  6. WIN.COM starts (if BootGUI=1 in MSDOS.SYS)              │
│                  ↓                                           │
│  7. VMM32.VXD loads (Virtual Machine Manager)               │
│                  ↓                                           │
│  8. Protected mode, Windows GUI                             │
└─────────────────────────────────────────────────────────────┘
```

### MSDOS.SYS in Windows 95

In Windows 95, MSDOS.SYS is a **text configuration file** (not a binary kernel):

```ini
[Paths]
WinDir=C:\WINDOWS
WinBootDir=C:\WINDOWS
HostWinBootDrv=C

[Options]
BootGUI=1      ; 1=boot to Windows, 0=boot to DOS prompt
BootDelay=2    ; Seconds to wait before booting
Logo=1         ; Show Windows logo
BootMenu=0     ; 1=always show boot menu
```

---

## Usage with MiSTer ao486

### Compatibility

| Boot Sector | ao486 Compatibility | Notes |
|-------------|---------------------|-------|
| MS-DOS 6.22 | **Recommended** | Best tested, most compatible |
| Windows 95 | Limited | Protected mode may have issues |

### Recommended Setup

For Windows 3.1 on ao486:
1. Use MS-DOS 6.22 boot sectors
2. Install MS-DOS 6.22
3. Install Windows 3.11 for Workgroups
4. Add `WIN` to AUTOEXEC.BAT

Windows 95 has limited compatibility with ao486 due to protected mode requirements.

---

## License

- **Windows 95 boot sectors**: © Microsoft Corporation - provided for educational and interoperability purposes only (not open source)
- **Windows 3.1**: Uses MS-DOS boot sectors, which are MIT licensed (Microsoft open-sourced MS-DOS)

---

## Historical Context

| Version | Year | Boot Method |
|---------|------|-------------|
| Windows 1.0 | 1985 | Runs on DOS |
| Windows 2.0 | 1987 | Runs on DOS |
| Windows 3.0 | 1990 | Runs on DOS |
| Windows 3.1 | 1992 | Runs on DOS |
| Windows 95 | 1995 | Own bootloader (DOS underneath) |
| Windows 98 | 1998 | Own bootloader (DOS underneath) |
| Windows ME | 2000 | Own bootloader (last DOS-based) |
| Windows NT/2000/XP | 1993+ | NTLDR (completely different) |
