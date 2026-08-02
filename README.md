# VHDTool

A Python tool for managing VHD and raw disk images with FAT12/FAT16/FAT32 filesystems. Designed for use with the MiSTer FPGA ao486 core.

## Features

- Read/write files to FAT12/FAT16/FAT32 filesystems
- Support for VHD (fixed and dynamic) and raw disk images
- Create new disk images with FAT16 formatting
- Resize existing images (grow and shrink with validation)
- Defragmentation via copy to new image (safe, preserves bootability)
- Boot sector management and extraction
- Cross-image file operations
- No external dependencies - pure Python 3.10+

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/vhdtool.git
cd vhdtool

# Install in development mode
pip install -e .

# Or install directly
pip install .
```

For standalone use without installing:
```bash
# Use the legacy single-file script
python vhdtool.py info disk.vhd
```

## Quick Start

```bash
# Show disk information
vhdtool info disk.vhd

# List directory contents
vhdtool ls disk.vhd
vhdtool ls -l disk.vhd /DOS

# Copy files from image
vhdtool cp disk.vhd:AUTOEXEC.BAT .
vhdtool cp -r disk.vhd:/GAMES ./games

# Copy files to image
vhdtool cp myfile.txt disk.vhd:/
vhdtool cp -r ./games disk.vhd:/GAMES

# View file contents
vhdtool cat disk.vhd:CONFIG.SYS

# Create directories
vhdtool mkdir disk.vhd:/APPS

# Remove files
vhdtool rm disk.vhd:/TEMP.TXT

# Create new disk image (512MB FAT16)
vhdtool create newdisk.vhd 512M --label MSDOS622

# Resize disk image
vhdtool resize disk.vhd 1G

# Create defragmented copy (files laid out sequentially)
vhdtool defrag disk.vhd

# Defragment and shrink to smaller size
vhdtool defrag disk.vhd -s 256M -o disk_small.vhd

# Make disk bootable from another image
vhdtool makeboot disk.vhd --from-image bootable.vhd

# List available boot sectors
vhdtool listboot
```

## Use as Library

```python
from vhdtool import VHDImage

# Read files
with VHDImage("disk.vhd") as img:
    entries = img.list_dir("/")
    for entry in entries:
        print(f"{entry.full_name} - {entry.size} bytes")
    
    data = img.read_file("/AUTOEXEC.BAT")
    print(data.decode('ascii'))

# Write files
with VHDImage("disk.vhd", readonly=False) as img:
    img.write_file("/TEST.TXT", b"Hello, DOS!\r\n")
    img.mkdir("/NEWDIR")
```

## Supported Formats

### Disk Images
- **VHD Fixed** - Microsoft VHD format with full allocation
- **VHD Dynamic** - Sparse VHD (read-only currently)
- **Raw** - Direct sector mapping (IMG, IMA, etc.)

### Filesystems
- **FAT12** - Floppy disks, small volumes (<16MB)
- **FAT16** - Hard disks up to 2GB
- **FAT32** - Large volumes (read support)

## Project Structure

```
vhdtool/
├── src/vhdtool/        # Main package
│   ├── __init__.py     # Package exports
│   ├── cli.py          # Command-line interface
│   ├── image.py        # VHDImage class
│   ├── fat.py          # FAT structures (BPB, DirEntry)
│   ├── partition.py    # MBR handling
│   ├── boot.py         # Boot sector management
│   ├── defrag.py       # Disk defragmentation
│   └── utils.py        # Utilities
├── tests/              # Unit tests
├── docs/               # Documentation
│   ├── architecture.md # Module architecture
│   └── technical.md    # Technical reference
├── bootsectors/        # Boot sector collection
├── vhdtool.py          # Legacy single-file script
├── pyproject.toml      # Package configuration
└── README.md
```

## Boot Sector Collection

The `bootsectors/` directory contains MBR and VBR templates for:
- MS-DOS 6.22
- FreeDOS
- BootProg (generic boot sectors)
- Windows 3.1/95

See `bootsectors/README.md` for details.

## MiSTer ao486 Usage

### Creating a Bootable DOS Disk

```bash
# 1. Create new disk
vhdtool create dos622.vhd 512M --label DOS622

# 2. Copy boot sectors from a working DOS disk
vhdtool makeboot dos622.vhd --from-image working_dos.vhd

# 3. Copy DOS system files (must be first entries in root)
vhdtool cp /path/to/IO.SYS dos622.vhd:/IO.SYS
vhdtool cp /path/to/MSDOS.SYS dos622.vhd:/MSDOS.SYS
vhdtool cp /path/to/COMMAND.COM dos622.vhd:/COMMAND.COM

# 4. Create startup files
printf '@ECHO OFF\r\nPATH=C:\\DOS\r\n' > /tmp/AUTOEXEC.BAT
vhdtool cp /tmp/AUTOEXEC.BAT dos622.vhd:/AUTOEXEC.BAT
```

### Deploying to MiSTer

1. Copy the `.vhd` file to your MiSTer SD card:
   ```
   /media/fat/games/ao486/
   ```

2. In ao486 OSD menu, select the VHD as IDE Primary Master

3. Boot and enjoy DOS!

## Development

```bash
# Install in development mode
pip install -e .

# Run tests
pytest

# Run specific test
pytest tests/test_fat.py -v
```

## Limitations

- FAT12 write support not implemented
- VHD dynamic write not supported
- Long filenames (LFN) not supported - 8.3 only
- Shrinking disk images not supported
- Single partition only

## Documentation

- [Architecture Overview](docs/architecture.md) - Module structure and design
- [Technical Reference](docs/technical.md) - Disk format specifications

## License

MIT License - see LICENSE file.

## References

- [Microsoft FAT Specification](https://download.microsoft.com/download/1/6/1/161ba512-40e2-4cc9-843a-923143f3456c/fatgen103.doc)
- [VHD Specification](https://www.microsoft.com/en-us/download/details.aspx?id=23850)
- [MiSTer FPGA ao486 Core](https://github.com/MiSTer-devel/ao486_MiSTer)
