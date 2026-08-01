# Building Boot Sectors - Platform Guide

Complete instructions for setting up the build environment on macOS, Linux, and Windows.

## Table of Contents

- [Prerequisites](#prerequisites)
- [macOS Setup](#macos-setup)
- [Linux Setup](#linux-setup)
- [Windows Setup](#windows-setup)
- [Building](#building)
- [Testing with Emulators](#testing-with-emulators)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

To build boot sectors, you need:

| Tool | Purpose | Required |
|------|---------|----------|
| **NASM** | Netwide Assembler - compiles .asm to .bin | Yes |
| **Make** | Build automation | Recommended |
| **Python 3.10+** | For vhdtool and disassembler | For tools |
| **QEMU** | Testing boot sectors | Recommended |
| **xxd/hexdump** | Viewing binary files | Optional |

---

## macOS Setup

### Using Homebrew (Recommended)

```bash
# Install Homebrew if not present
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install NASM
brew install nasm

# Install QEMU for testing
brew install qemu

# Verify installations
nasm --version
qemu-system-i386 --version
```

### Using MacPorts

```bash
sudo port install nasm
sudo port install qemu
```

### Manual Installation

1. Download NASM from https://www.nasm.us/pub/nasm/releasebuilds/
2. Extract and add to PATH:
   ```bash
   tar xzf nasm-2.16.01-macosx.tar.gz
   sudo mv nasm-2.16.01 /usr/local/nasm
   echo 'export PATH="/usr/local/nasm:$PATH"' >> ~/.zshrc
   source ~/.zshrc
   ```

### Python Setup (for vhdtool)

```bash
# macOS includes Python 3, but you may want pyenv for version management
brew install pyenv
pyenv install 3.12
pyenv global 3.12

# Install vhdtool
cd /path/to/vhdtool
pip install -e .
```

---

## Linux Setup

### Ubuntu / Debian

```bash
# Update package list
sudo apt update

# Install NASM and build tools
sudo apt install nasm make

# Install QEMU for testing
sudo apt install qemu-system-x86

# Install Python and pip
sudo apt install python3 python3-pip python3-venv

# Verify
nasm --version
qemu-system-i386 --version
python3 --version
```

### Fedora / RHEL / CentOS

```bash
# Install NASM
sudo dnf install nasm make

# Install QEMU
sudo dnf install qemu-system-x86

# Install Python
sudo dnf install python3 python3-pip
```

### Arch Linux

```bash
sudo pacman -S nasm make qemu-system-x86 python python-pip
```

### openSUSE

```bash
sudo zypper install nasm make qemu-x86 python3 python3-pip
```

### From Source (Any Linux)

```bash
# Download NASM source
wget https://www.nasm.us/pub/nasm/releasebuilds/2.16.01/nasm-2.16.01.tar.gz
tar xzf nasm-2.16.01.tar.gz
cd nasm-2.16.01

# Build and install
./configure
make
sudo make install

# Verify
nasm --version
```

### Python Setup

```bash
# Create virtual environment (recommended)
python3 -m venv ~/.venvs/vhdtool
source ~/.venvs/vhdtool/bin/activate

# Install vhdtool
cd /path/to/vhdtool
pip install -e .
```

---

## Windows Setup

### Option 1: Using Chocolatey (Recommended)

```powershell
# Install Chocolatey (run as Administrator)
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))

# Install NASM
choco install nasm

# Install Make (via GnuWin32 or use nmake)
choco install make

# Install QEMU
choco install qemu

# Install Python
choco install python

# Restart terminal, then verify
nasm --version
make --version
qemu-system-i386 --version
python --version
```

### Option 2: Using winget (Windows 11)

```powershell
winget install NASM.NASM
winget install Python.Python.3.12
winget install SoftwareFreedomConservancy.QEMU
```

### Option 3: Manual Installation

#### NASM

1. Download from https://www.nasm.us/pub/nasm/releasebuilds/
2. Choose `nasm-X.XX-installer-x64.exe`
3. Run installer, note installation path (e.g., `C:\Program Files\NASM`)
4. Add to PATH:
   - Open System Properties → Advanced → Environment Variables
   - Edit `Path` → Add `C:\Program Files\NASM`

#### Make (GnuWin32)

1. Download from http://gnuwin32.sourceforge.net/packages/make.htm
2. Install to default location
3. Add `C:\Program Files (x86)\GnuWin32\bin` to PATH

#### Alternative: Use WSL2

Windows Subsystem for Linux provides a full Linux environment:

```powershell
# Enable WSL (run as Administrator)
wsl --install

# Restart computer, then install Ubuntu
wsl --install -d Ubuntu

# Now use Linux instructions inside WSL
```

### Python Setup (Windows)

```powershell
# Using pip (after Python is installed)
cd C:\path\to\vhdtool
pip install -e .

# Or use virtual environment
python -m venv venv
.\venv\Scripts\activate
pip install -e .
```

### Windows-Specific Notes

1. **Line Endings**: Git may convert line endings. Configure:
   ```bash
   git config --global core.autocrlf false
   ```

2. **Path Separators**: Use forward slashes in Makefiles, or use WSL

3. **Command Prompt vs PowerShell**: Some commands differ:
   ```powershell
   # PowerShell
   nasm -f bin -o boot.bin boot.asm
   
   # Or use cmd.exe for more Unix-like behavior
   ```

---

## Building

### Quick Start

```bash
# Navigate to sources directory
cd bootsectors/sources

# Check prerequisites
make check

# Fetch external sources (BootProg, FreeDOS)
make fetch-all

# Build all boot sectors
make all

# List all targets
make help
```

### Build Individual Components

```bash
# Build just the MBR
make mbr

# Build MS-DOS compatible VBR
make msdos

# Build BootProg boot sectors
make bootprog
```

### Manual Build (Without Make)

```bash
# Assemble MBR
nasm -f bin -o ../standard_mbr.bin mbr/standard_mbr.asm

# Assemble VBR
nasm -f bin -o ../fat16_vbr.bin msdos/fat16_vbr.asm

# Verify size (must be exactly 512 bytes)
ls -l ../standard_mbr.bin ../fat16_vbr.bin
```

### Windows (Without Make)

```batch
REM Build MBR
nasm -f bin -o ..\standard_mbr.bin mbr\standard_mbr.asm

REM Build VBR  
nasm -f bin -o ..\fat16_vbr.bin msdos\fat16_vbr.asm
```

---

## Testing with Emulators

### QEMU

```bash
# Test MBR + VBR with disk image
qemu-system-i386 -hda disk.img

# Test floppy boot sector
qemu-system-i386 -fda floppy.img

# With debugging (pause at start)
qemu-system-i386 -hda disk.img -S -s

# Monitor boot process
qemu-system-i386 -hda disk.img -d int -no-reboot 2>&1 | head -100
```

### Bochs

```bash
# Create bochsrc configuration
cat > bochsrc << 'EOF'
megs: 32
romimage: file=$BXSHARE/BIOS-bochs-latest
vgaromimage: file=$BXSHARE/VGABIOS-lgpl-latest
boot: disk
ata0-master: type=disk, path="disk.img", mode=flat
log: bochs.log
EOF

# Run
bochs -f bochsrc
```

### VirtualBox

```bash
# Convert raw image to VDI
VBoxManage convertfromraw disk.img disk.vdi --format VDI

# Create and configure VM via GUI or:
VBoxManage createvm --name "BootTest" --ostype DOS --register
VBoxManage storagectl "BootTest" --name "IDE" --add ide
VBoxManage storageattach "BootTest" --storagectl "IDE" --port 0 --device 0 --type hdd --medium disk.vdi
VBoxManage startvm "BootTest"
```

### 86Box (for ao486 accuracy)

86Box emulates vintage hardware more accurately than QEMU:

1. Download from https://86box.net/
2. Configure machine type similar to ao486 (486DX, ~40MHz)
3. Attach disk image
4. Boot and test

---

## Troubleshooting

### "nasm: command not found"

**macOS:**
```bash
brew install nasm
# Or check if installed elsewhere
which nasm
```

**Linux:**
```bash
sudo apt install nasm  # Debian/Ubuntu
sudo dnf install nasm  # Fedora
```

**Windows:**
- Check PATH includes NASM directory
- Try running from NASM installation folder

### "make: command not found"

**macOS:**
```bash
xcode-select --install  # Includes make
# Or
brew install make
```

**Linux:**
```bash
sudo apt install build-essential  # Includes make, gcc, etc.
```

**Windows:**
```powershell
choco install make
# Or use nmake (comes with Visual Studio)
# Or use WSL
```

### Binary size is not 512 bytes

Check your assembly for:
- Missing `times 510-($-$$) db 0` padding
- Missing `dw 0xAA55` signature
- Code overflow (too much code)

```bash
# Check assembled size
nasm -f bin -o test.bin boot.asm
ls -l test.bin  # Should be exactly 512

# If larger, find where overflow occurs
nasm -f bin -l test.lst boot.asm
cat test.lst  # Check line numbers at end
```

### Boot sector doesn't boot

1. **Check signature**: Last 2 bytes must be `0x55 0xAA`
   ```bash
   xxd -s 510 -l 2 boot.bin
   # Should show: 000001fe: 55aa
   ```

2. **Check BPB**: For VBR, BPB values must match actual disk
   ```bash
   # View BPB
   xxd -s 11 -l 51 boot.bin
   ```

3. **Test in QEMU with debug**:
   ```bash
   qemu-system-i386 -hda disk.img -d int -no-reboot 2>&1 | less
   ```

### QEMU shows "No bootable device"

- Image file must exist and have valid boot signature
- For HDD: MBR at sector 0 with valid partition table
- For floppy: VBR at sector 0

```bash
# Quick check
xxd -l 512 disk.img | tail -1
# Last line should end with "55aa"
```

### Python/vhdtool issues

```bash
# Check Python version (need 3.10+)
python3 --version

# Reinstall in development mode
pip uninstall vhdtool
pip install -e .

# If import errors, check PYTHONPATH
python3 -c "import vhdtool; print(vhdtool.__file__)"
```

---

## Quick Reference

### Build Commands

| Command | Description |
|---------|-------------|
| `make all` | Build all boot sectors |
| `make mbr` | Build standard MBR only |
| `make msdos` | Build FAT16 VBR only |
| `make bootprog` | Build BootProg sectors |
| `make fetch-all` | Download external sources |
| `make disasm` | Disassemble existing .bin files |
| `make verify` | Verify compilation |
| `make clean` | Remove built binaries |
| `make check` | Verify NASM installed |

### NASM Commands

| Command | Description |
|---------|-------------|
| `nasm -f bin -o out.bin in.asm` | Assemble to raw binary |
| `nasm -f bin -l out.lst in.asm` | Generate listing file |
| `ndisasm -b 16 file.bin` | Disassemble 16-bit binary |
| `ndisasm -b 16 -o 0x7c00 file.bin` | Disassemble with origin |

### File Locations

| Path | Content |
|------|---------|
| `bootsectors/*.bin` | Compiled boot sector binaries |
| `bootsectors/sources/mbr/` | MBR source code |
| `bootsectors/sources/msdos/` | VBR source code |
| `bootsectors/sources/bootprog/` | BootProg sources |
| `bootsectors/sources/docs/` | Documentation |
| `bootsectors/sources/tools/` | Python utilities |
