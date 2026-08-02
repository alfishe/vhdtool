# VHDTool Technical Reference

## Disk Geometry

### MBR Structure (512 bytes)

| Offset | Size | Description |
|--------|------|-------------|
| 0x000 | 446 | Boot code |
| 0x1BE | 16 | Partition 1 entry |
| 0x1CE | 16 | Partition 2 entry |
| 0x1DE | 16 | Partition 3 entry |
| 0x1EE | 16 | Partition 4 entry |
| 0x1FE | 2 | Boot signature (55 AA) |

### Partition Entry (16 bytes)

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 1 | Boot flag (0x80 = bootable) |
| 0x01 | 3 | CHS start |
| 0x04 | 1 | Partition type |
| 0x05 | 3 | CHS end |
| 0x08 | 4 | LBA start |
| 0x0C | 4 | Sector count |

### Common Partition Types

| Code | Type |
|------|------|
| 0x01 | FAT12 |
| 0x04 | FAT16 <32MB |
| 0x06 | FAT16 |
| 0x0B | FAT32 CHS |
| 0x0C | FAT32 LBA |
| 0x0E | FAT16 LBA |

## FAT Boot Sector (VBR)

### BIOS Parameter Block (FAT12/16)

| Offset | Size | Field |
|--------|------|-------|
| 0x00 | 3 | Jump instruction |
| 0x03 | 8 | OEM name |
| 0x0B | 2 | Bytes per sector |
| 0x0D | 1 | Sectors per cluster |
| 0x0E | 2 | Reserved sectors |
| 0x10 | 1 | Number of FATs |
| 0x11 | 2 | Root directory entries |
| 0x13 | 2 | Total sectors (16-bit) |
| 0x15 | 1 | Media type |
| 0x16 | 2 | Sectors per FAT |
| 0x18 | 2 | Sectors per track |
| 0x1A | 2 | Number of heads |
| 0x1C | 4 | Hidden sectors |
| 0x20 | 4 | Total sectors (32-bit) |
| 0x24 | 1 | Drive number |
| 0x25 | 1 | Reserved |
| 0x26 | 1 | Extended boot signature (0x29) |
| 0x27 | 4 | Volume serial number |
| 0x2B | 11 | Volume label |
| 0x36 | 8 | Filesystem type |

### FAT32 Extended BPB

Additional fields at offset 0x24:

| Offset | Size | Field |
|--------|------|-------|
| 0x24 | 4 | Sectors per FAT (32-bit) |
| 0x28 | 2 | Flags |
| 0x2A | 2 | Version |
| 0x2C | 4 | Root cluster |
| 0x30 | 2 | FSInfo sector |
| 0x32 | 2 | Backup boot sector |

## FAT Type Determination

Per Microsoft FAT specification:

```python
if cluster_count < 4085:
    fat_type = FAT12
elif cluster_count < 65525:
    fat_type = FAT16
else:
    fat_type = FAT32
```

Where:
```
root_dir_sectors = (root_entries * 32 + 511) // 512
first_data_sector = reserved + (num_fats * fat_size) + root_dir_sectors
data_sectors = total_sectors - first_data_sector
cluster_count = data_sectors // sectors_per_cluster
```

## Directory Entry (32 bytes)

| Offset | Size | Field |
|--------|------|-------|
| 0x00 | 8 | Filename (8.3) |
| 0x08 | 3 | Extension |
| 0x0B | 1 | Attributes |
| 0x0C | 1 | Reserved |
| 0x0D | 1 | Create time (ms) |
| 0x0E | 2 | Create time |
| 0x10 | 2 | Create date |
| 0x12 | 2 | Access date |
| 0x14 | 2 | Cluster high (FAT32) |
| 0x16 | 2 | Modify time |
| 0x18 | 2 | Modify date |
| 0x1A | 2 | Cluster low |
| 0x1C | 4 | File size |

### Attribute Flags

| Bit | Flag |
|-----|------|
| 0x01 | Read-only |
| 0x02 | Hidden |
| 0x04 | System |
| 0x08 | Volume label |
| 0x10 | Directory |
| 0x20 | Archive |
| 0x0F | Long filename |

### DOS Date/Time Format

**Time (16-bit):**
- Bits 0-4: Seconds / 2 (0-29)
- Bits 5-10: Minutes (0-59)
- Bits 11-15: Hours (0-23)

**Date (16-bit):**
- Bits 0-4: Day (1-31)
- Bits 5-8: Month (1-12)
- Bits 9-15: Year - 1980 (0-127)

## VHD Format

### Footer (512 bytes at EOF)

| Offset | Size | Field |
|--------|------|-------|
| 0x00 | 8 | Cookie ("conectix") |
| 0x08 | 4 | Features |
| 0x0C | 4 | Format version |
| 0x10 | 8 | Data offset |
| 0x18 | 4 | Timestamp |
| 0x1C | 4 | Creator application |
| 0x20 | 4 | Creator version |
| 0x24 | 4 | Creator host OS |
| 0x28 | 8 | Original size |
| 0x30 | 8 | Current size |
| 0x38 | 4 | Disk geometry |
| 0x3C | 4 | Disk type |
| 0x40 | 4 | Checksum |
| 0x44 | 16 | Unique ID |
| 0x54 | 1 | Saved state |

### Disk Types

| Value | Type |
|-------|------|
| 2 | Fixed |
| 3 | Dynamic |
| 4 | Differencing |

### Dynamic VHD Header (1024 bytes)

| Offset | Size | Field |
|--------|------|-------|
| 0x00 | 8 | Cookie ("cxsparse") |
| 0x08 | 8 | Data offset |
| 0x10 | 8 | BAT offset |
| 0x18 | 4 | Header version |
| 0x1C | 4 | Max BAT entries |
| 0x20 | 4 | Block size |
| 0x24 | 4 | Checksum |

### Block Allocation

- BAT is array of 32-bit sector offsets
- 0xFFFFFFFF = block not allocated
- Each block has bitmap + data
- Bitmap size: ceil(block_size / 512 / 8)

## Cluster Chain

FAT entries form linked list:
```
cluster 2 -> FAT[2] -> FAT[FAT[2]] -> ... -> end marker
```

End markers:
- FAT12: >= 0x0FF8
- FAT16: >= 0xFFF8
- FAT32: >= 0x0FFFFFF8

Free cluster: FAT entry = 0

## Creating Bootable Disks

1. Install MBR boot code (preserving partition table)
2. Install VBR boot code (preserving BPB at bytes 3-61)
3. Copy system files (IO.SYS, MSDOS.SYS, COMMAND.COM)
4. IO.SYS must be first file in root directory
5. IO.SYS must occupy contiguous clusters (for some DOS versions)

## Disk Resizing

### Growing a Disk

1. Extend file to new size
2. Update partition table entry (sector count)
3. Update BPB total_sectors (16 or 32 bit field)
4. No FAT or data relocation needed if FAT size unchanged

### Shrinking a Disk

1. Check highest used cluster (data must fit in new size)
2. Verify FAT parameters won't change (cluster size, FAT size)
3. Update partition table and BPB
4. Truncate file

### Limitations

- FAT reorganization (changing cluster size or FAT table size) requires full filesystem rebuild
- Dynamic VHD resize not supported

## Defragmentation

The defrag operation creates a new image with files laid out sequentially:

1. Create new formatted image (same or different size)
2. Copy boot code from source (preserves bootability)
3. Copy files sequentially, allocating clusters in order
4. Result: all files occupy contiguous clusters (0% fragmentation)

### Benefits

- Faster file access (no seeking between fragments)
- Safe shrinking (files packed at start of data area)
- Boot sector preserved from source

### Process

```
Source Image                    Destination Image
┌─────────────────┐             ┌─────────────────┐
│ MBR/VBR (boot)  │ ────copy──→ │ MBR/VBR (boot)  │
├─────────────────┤             ├─────────────────┤
│ FAT (fragmented)│             │ FAT (linear)    │
├─────────────────┤             ├─────────────────┤
│ Root Dir        │ ────copy──→ │ Root Dir        │
├─────────────────┤             ├─────────────────┤
│ Data:           │             │ Data:           │
│  [File1 part 1] │             │  [File1 whole]  │
│  [File2 part 1] │ ────copy──→ │  [File2 whole]  │
│  [File1 part 2] │             │  [File3 whole]  │
│  [File3 part 1] │             │  ...            │
│  ...            │             │                 │
└─────────────────┘             └─────────────────┘
```
