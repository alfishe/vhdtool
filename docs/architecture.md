# VHDTool Architecture

## Overview

VHDTool is a Python library and CLI for manipulating VHD and raw disk images containing FAT filesystems. It was designed primarily for use with the MiSTer FPGA ao486 core but works with any FAT12/FAT16/FAT32 disk image.

## Module Structure

```
src/vhdtool/
├── __init__.py      # Package exports
├── cli.py           # Command-line interface
├── image.py         # VHDImage class - main disk image handler
├── fat.py           # FAT filesystem structures (BPB, DirEntry)
├── partition.py     # MBR partition table handling
├── boot.py          # Boot sector management
└── utils.py         # Utility functions
```

## Core Components

### VHDImage (image.py)

The central class that handles disk image I/O. Supports:

- **Fixed VHD** - Standard VHD format with "conectix" footer
- **Dynamic VHD** - Sparse VHD with block allocation table (BAT)
- **Raw images** - Direct sector-to-file mapping

Key responsibilities:
- VHD format detection and header parsing
- Sector read/write with VHD translation
- Partition table parsing
- FAT filesystem operations (read/write files, create directories)

### FAT Structures (fat.py)

- **BPB** - BIOS Parameter Block parsed from boot sector
- **DirEntry** - 32-byte directory entry representation
- **FATType** - Enum for FAT12/FAT16/FAT32

The BPB calculates derived values:
- `fat_type` - Determined by cluster count per FAT spec
- `cluster_size` - bytes_per_sector * sectors_per_cluster
- `first_data_sector` - Where file data begins

### Partition Handling (partition.py)

- **PartitionEntry** - Single MBR partition entry
- `parse_mbr_partitions()` - Extract entries from MBR
- `create_mbr()` - Build MBR with partition table

Handles floppy detection (no partition table) via media byte check.

### Boot Sector Management (boot.py)

- Maintains collection of boot sector templates in `bootsectors/`
- Extracts MBR/VBR from existing images
- Applies boot code while preserving BPB

## Data Flow

```
┌─────────────────┐
│   CLI Command   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    VHDImage     │
│  (context mgr)  │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌───────┐
│ VHD   │ │  Raw  │
│ Layer │ │ Layer │
└───┬───┘ └───┬───┘
    │         │
    └────┬────┘
         ▼
┌─────────────────┐
│   FAT Layer     │
│ (clusters,FAT)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  File/Dir Ops   │
└─────────────────┘
```

## VHD Format Details

### Fixed VHD
- File size = disk size + 512 byte footer
- Direct LBA to file offset mapping
- Footer at EOF contains "conectix" signature

### Dynamic VHD
- Sparse file with Block Allocation Table (BAT)
- Each block has bitmap + data sectors
- BAT entries: 0xFFFFFFFF = unallocated
- Header at offset from footer's data_offset field

## FAT Filesystem

### Cluster Allocation
1. Find free cluster via FAT scan
2. Write end-of-chain marker immediately (prevents reuse)
3. Link previous cluster to new one
4. Write data to cluster

### Directory Structure
- FAT12/16: Fixed root directory after FAT tables
- FAT32: Root is a cluster chain (root_cluster in BPB)
- 32 bytes per entry, 8.3 filename format

### FAT Entry Access
- FAT12: 12-bit entries, complex bit packing
- FAT16: 16-bit entries at cluster*2 offset
- FAT32: 28-bit entries at cluster*4 offset

## Thread Safety

VHDImage is NOT thread-safe. Each thread should use its own VHDImage instance with separate file handles.

## Error Handling

- Raises standard Python exceptions (FileNotFoundError, IsADirectoryError, etc.)
- IOError for disk full / read-only violations
- ValueError for format violations (bad boot sector, etc.)
