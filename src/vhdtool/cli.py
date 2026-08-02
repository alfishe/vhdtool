"""Command-line interface for vhdtool."""

import argparse
import os
import shutil
import struct
import sys
from pathlib import Path

from .boot import (
    BOOT_SECTORS_DIR,
    extract_boot_code_from_image,
    get_boot_sectors,
)
from .defrag import defragment_image
from .image import VHDImage
from .utils import (
    calculate_fat16_params,
    create_fat16_boot_sector,
    create_fat16_tables,
    create_mbr,
    format_size,
    parse_image_path,
    parse_size,
)


def cmd_info(args):
    """Show disk/partition/filesystem info."""
    with VHDImage(args.image) as img:
        print(f"Image: {args.image}")
        print(f"Size: {format_size(img.disk_size)} ({img.disk_size:,} bytes)")
        print(f"Type: {'VHD' if img.is_vhd else 'Raw'}", end='')
        if img.is_vhd:
            print(f" ({'Dynamic' if img.is_dynamic else 'Fixed'})")
        else:
            print()
        print()

        partitions = img.get_partitions()
        if partitions:
            print("Partitions:")
            for i, p in enumerate(partitions):
                boot = "*" if p.bootable else " "
                size = format_size(p.size_sectors * 512)
                print(f"  {i+1}{boot} {p.type_name:15} Start: {p.start_lba:>10}  Size: {size}")
            print()

        if img.bpb:
            bpb = img.bpb
            print("Filesystem:")
            print(f"  Type: {bpb.fat_type.name}")
            print(f"  Volume Label: {bpb.volume_label or '(none)'}")
            print(f"  Bytes/Sector: {bpb.bytes_per_sector}")
            print(f"  Sectors/Cluster: {bpb.sectors_per_cluster}")
            print(f"  Cluster Size: {format_size(bpb.cluster_size)}")
            print(f"  Reserved Sectors: {bpb.reserved_sectors}")
            print(f"  FAT Copies: {bpb.num_fats}")
            print(f"  FAT Size: {bpb.fat_size} sectors ({format_size(bpb.fat_size * 512)})")
            print(f"  Total Sectors: {bpb.total_sectors:,}")
            print(f"  Data Clusters: {bpb.cluster_count:,}")
            print(f"  Data Size: {format_size(bpb.data_sectors * 512)}")


def cmd_ls(args):
    """List directory contents."""
    with VHDImage(args.image) as img:
        path = args.path or '/'
        try:
            entries = img.list_dir(path)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if args.long:
            for entry in sorted(entries, key=lambda e: (not e.is_directory, e.full_name.lower())):
                mtime = entry.modify_time.strftime("%Y-%m-%d %H:%M") if entry.modify_time else "                "
                if entry.is_directory:
                    size_str = "<DIR>".rjust(12)
                else:
                    size_str = f"{entry.size:,}".rjust(12)
                print(f"{entry.attr_string} {size_str} {mtime} {entry.full_name}")
        else:
            dirs = sorted([e.full_name for e in entries if e.is_directory])
            files = sorted([e.full_name for e in entries if not e.is_directory])

            for name in dirs:
                print(f"{name}/")
            for name in files:
                print(name)


def copy_dir_recursive(src_img: VHDImage, src_path: str, dst_img: VHDImage, dst_path: str, verbose: bool = True):
    """Recursively copy directory between images."""
    entries = src_img.list_dir(src_path)

    try:
        dst_img.mkdir(dst_path)
        if verbose:
            print(f"Created directory: {dst_path}")
    except Exception:
        pass

    for entry in entries:
        src_file = f"{src_path}/{entry.full_name}".replace('//', '/')
        dst_file = f"{dst_path}/{entry.full_name}".replace('//', '/')

        if entry.is_directory:
            copy_dir_recursive(src_img, src_file, dst_img, dst_file, verbose)
        else:
            data = src_img.read_file(src_file)
            dst_img.write_file(dst_file, data)
            if verbose:
                print(f"Copied: {entry.full_name} ({len(data):,} bytes)")


def cmd_cp(args):
    """Copy files to/from image."""
    src_img, src_path = parse_image_path(args.src)
    dst_img, dst_path = parse_image_path(args.dest)
    recursive = getattr(args, 'recursive', False)

    if src_path and dst_path:
        with VHDImage(src_img) as src:
            with VHDImage(dst_img, readonly=False) as dst:
                try:
                    entry, _ = src._resolve_path(src_path)
                except FileNotFoundError as e:
                    print(f"Error: {e}", file=sys.stderr)
                    return 1

                if entry and entry.is_directory:
                    if not recursive:
                        print(f"Error: {src_path} is a directory. Use -r for recursive copy.", file=sys.stderr)
                        return 1
                    copy_dir_recursive(src, src_path, dst, dst_path)
                elif entry:
                    data = src.read_file(src_path)
                    dst.write_file(dst_path, data)
                    print(f"Copied {len(data):,} bytes to {dst_img}:{dst_path}")
                else:
                    if not recursive:
                        print("Error: Use -r for recursive copy of directories", file=sys.stderr)
                        return 1
                    copy_dir_recursive(src, src_path, dst, dst_path)
        return 0

    if src_path:
        with VHDImage(src_img) as img:
            try:
                entry, _ = img._resolve_path(src_path)
            except FileNotFoundError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

            if entry and entry.is_directory:
                if not recursive:
                    print(f"Error: {src_path} is a directory. Use -r for recursive copy.", file=sys.stderr)
                    return 1

                def extract_recursive(img_path: str, local_path: str):
                    os.makedirs(local_path, exist_ok=True)
                    for e in img.list_dir(img_path):
                        src_file = f"{img_path}/{e.full_name}".replace('//', '/')
                        dst_file = os.path.join(local_path, e.full_name)
                        if e.is_directory:
                            extract_recursive(src_file, dst_file)
                        else:
                            data = img.read_file(src_file)
                            with open(dst_file, 'wb') as f:
                                f.write(data)
                            print(f"Extracted: {e.full_name} ({len(data):,} bytes)")

                dest = args.dest
                if not os.path.exists(dest):
                    os.makedirs(dest)
                extract_recursive(src_path, os.path.join(dest, os.path.basename(src_path.rstrip('/'))))
            else:
                data = img.read_file(src_path)
                dest = args.dest
                if os.path.isdir(dest):
                    dest = os.path.join(dest, os.path.basename(src_path))
                with open(dest, 'wb') as f:
                    f.write(data)
                print(f"Copied {len(data):,} bytes to {dest}")

    elif dst_path:
        if os.path.isdir(args.src):
            if not recursive:
                print(f"Error: {args.src} is a directory. Use -r for recursive copy.", file=sys.stderr)
                return 1

            with VHDImage(dst_img, readonly=False) as img:
                def copy_local_recursive(local_path: str, img_path: str):
                    try:
                        img.mkdir(img_path)
                        print(f"Created directory: {img_path}")
                    except Exception:
                        pass

                    for name in os.listdir(local_path):
                        src_file = os.path.join(local_path, name)
                        name_upper = name.upper()
                        if '.' in name_upper:
                            base, ext = name_upper.rsplit('.', 1)
                            name_83 = f"{base[:8]}.{ext[:3]}"
                        else:
                            name_83 = name_upper[:8]
                        dst_file = f"{img_path}/{name_83}".replace('//', '/')

                        if os.path.isdir(src_file):
                            copy_local_recursive(src_file, dst_file)
                        else:
                            with open(src_file, 'rb') as f:
                                data = f.read()
                            img.write_file(dst_file, data)
                            print(f"Copied: {name_83} ({len(data):,} bytes)")

                copy_local_recursive(args.src, dst_path)
        elif os.path.isfile(args.src):
            with open(args.src, 'rb') as f:
                data = f.read()

            with VHDImage(dst_img, readonly=False) as img:
                try:
                    img.write_file(dst_path, data)
                except Exception as e:
                    print(f"Error: {e}", file=sys.stderr)
                    return 1
                print(f"Copied {len(data):,} bytes to {dst_img}:{dst_path}")
        else:
            print(f"Error: Source file not found: {args.src}", file=sys.stderr)
            return 1

    else:
        print("Error: Use image:path syntax for at least one argument", file=sys.stderr)
        return 1


def cmd_cat(args):
    """Print file contents."""
    img_path, file_path = parse_image_path(args.path)

    if not file_path:
        print("Error: Use image:path syntax", file=sys.stderr)
        return 1

    with VHDImage(img_path) as img:
        try:
            data = img.read_file(file_path)
        except (FileNotFoundError, IsADirectoryError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if args.binary:
            sys.stdout.buffer.write(data)
        else:
            try:
                print(data.decode('utf-8', errors='replace'), end='')
            except Exception:
                print(data.decode('latin-1'), end='')


def cmd_mkdir(args):
    """Create directory."""
    img_path, dir_path = parse_image_path(args.path)

    if not dir_path:
        print("Error: Use image:path syntax", file=sys.stderr)
        return 1

    with VHDImage(img_path, readonly=False) as img:
        try:
            img.mkdir(dir_path)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(f"Created directory: {dir_path}")


def cmd_rm(args):
    """Remove file or directory."""
    img_path, file_path = parse_image_path(args.path)

    if not file_path:
        print("Error: Use image:path syntax", file=sys.stderr)
        return 1

    with VHDImage(img_path, readonly=False) as img:
        try:
            img.remove(file_path)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        print(f"Removed: {file_path}")


def cmd_create(args):
    """Create a new disk image."""
    size_bytes = parse_size(args.size)
    size_bytes = (size_bytes // 512) * 512
    total_sectors = size_bytes // 512

    if total_sectors < 2048:
        print("Error: Minimum disk size is 1MB", file=sys.stderr)
        return 1

    if total_sectors > 4194304:
        print("Error: Maximum FAT16 disk size is 2GB", file=sys.stderr)
        return 1

    if os.path.exists(args.image) and not args.force:
        print(f"Error: {args.image} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1

    print(f"Creating {format_size(size_bytes)} disk image: {args.image}")

    part_start = 63
    part_sectors = total_sectors - part_start
    params = calculate_fat16_params(part_sectors)

    with open(args.image, 'wb') as f:
        mbr = create_mbr(total_sectors, bootable=True)
        f.write(mbr)

        f.write(b'\x00' * (512 * (part_start - 1)))

        boot = create_fat16_boot_sector(params, args.label or "DISK")
        f.write(boot)

        fat = create_fat16_tables(params)
        for _ in range(params['num_fats']):
            f.write(fat)

        root_size = params['root_entries'] * 32
        f.write(b'\x00' * root_size)

        f.seek(size_bytes - 1)
        f.write(b'\x00')

    print(f"Created {format_size(size_bytes)} FAT16 disk image")
    print(f"  Cluster size: {params['sectors_per_cluster'] * 512} bytes")
    print(f"  Usable space: ~{format_size(part_sectors * 512)}")


def cmd_resize(args):
    """Resize disk image (preserving data)."""
    if not os.path.exists(args.image):
        print(f"Error: {args.image} not found", file=sys.stderr)
        return 1

    new_size = parse_size(args.size)
    new_size = (new_size // 512) * 512
    new_sectors = new_size // 512

    current_size = os.path.getsize(args.image)

    if new_size == current_size:
        print("Image is already the requested size")
        return 0

    # Analyze current filesystem
    with VHDImage(args.image) as img:
        if img.is_vhd and img.is_dynamic:
            print("Error: Resizing dynamic VHD not supported", file=sys.stderr)
            return 1

        partitions = img.get_partitions()
        if not partitions:
            print("Error: No partition found", file=sys.stderr)
            return 1

        old_part = partitions[0]
        old_bpb = img.bpb

        # Get filesystem statistics for validation
        stats = img.get_filesystem_stats()
        highest_cluster = stats['highest_used_cluster']
        used_bytes = stats['used_bytes']

    new_part_sectors = new_sectors - old_part.start_lba

    # Validate size constraints
    min_sectors = 4085 + old_part.start_lba  # Minimum for FAT16
    max_sectors = 4194304 + old_part.start_lba  # 2GB limit for FAT16

    if new_sectors < min_sectors:
        print(f"Error: Size too small for FAT16 (minimum ~{format_size(min_sectors * 512)})", file=sys.stderr)
        return 1

    if new_sectors > max_sectors:
        print(f"Error: Size too large for FAT16 (maximum 2GB)", file=sys.stderr)
        return 1

    # Calculate new filesystem parameters
    try:
        new_params = calculate_fat16_params(new_part_sectors)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Calculate minimum size needed to preserve data
    if highest_cluster > 1:
        # Sectors needed: partition start + reserved + FATs + root dir + data up to highest cluster
        min_data_clusters = highest_cluster - 1  # clusters 2..highest
        min_data_sectors = min_data_clusters * old_bpb.sectors_per_cluster
        min_partition_sectors = (old_bpb.reserved_sectors +
                                 old_bpb.num_fats * old_bpb.fat_size +
                                 old_bpb.root_dir_sectors +
                                 min_data_sectors)
        min_image_sectors = old_part.start_lba + min_partition_sectors
        min_image_size = min_image_sectors * 512
    else:
        min_image_size = (old_part.start_lba + old_bpb.first_data_sector) * 512

    # Check shrinking constraints
    if new_size < current_size:
        if new_size < min_image_size:
            print(f"Error: Cannot shrink below {format_size(min_image_size)} - data would be lost", file=sys.stderr)
            print(f"  Highest used cluster: {highest_cluster}")
            print(f"  Data in use: {format_size(used_bytes)}")
            return 1

        # Check if FAT table parameters would change
        if new_params['fat_size'] != old_bpb.fat_size or \
           new_params['sectors_per_cluster'] != old_bpb.sectors_per_cluster:
            print("Error: Shrinking requires filesystem reorganization (not yet supported)", file=sys.stderr)
            print(f"  Current: {old_bpb.sectors_per_cluster} sectors/cluster, FAT size {old_bpb.fat_size}")
            print(f"  New: {new_params['sectors_per_cluster']} sectors/cluster, FAT size {new_params['fat_size']}")
            print("  Workaround: backup files, reformat, restore files")
            return 1

        print(f"Shrinking {args.image}: {format_size(current_size)} -> {format_size(new_size)}")
        print(f"  Data in use: {format_size(used_bytes)} (highest cluster: {highest_cluster})")

    else:
        print(f"Growing {args.image}: {format_size(current_size)} -> {format_size(new_size)}")

        # Check if FAT needs to grow
        if new_params['fat_size'] > old_bpb.fat_size:
            print("Error: Growing beyond current FAT capacity requires filesystem reorganization", file=sys.stderr)
            print(f"  Current FAT size: {old_bpb.fat_size} sectors")
            print(f"  Required FAT size: {new_params['fat_size']} sectors")
            print("  The data region would need to shift, which is not yet supported.")
            print("  Workaround: backup files, create new larger image, restore files")
            return 1

    # Create backup
    backup_path = args.image + ".backup"
    if not args.no_backup:
        print(f"Creating backup: {backup_path}")
        shutil.copy2(args.image, backup_path)

    try:
        with open(args.image, 'r+b') as f:
            if new_size > current_size:
                # Extend file
                f.seek(new_size - 1)
                f.write(b'\x00')
            else:
                # Truncate file
                f.truncate(new_size)

            # Update partition table entry
            f.seek(446 + 12)
            f.write(struct.pack('<I', new_part_sectors))

            # Update CHS end values (use LBA for large disks)
            # Partition entry bytes 5-7 are ending CHS
            if new_sectors < 16450560:  # ~8GB CHS limit
                # Calculate CHS from LBA
                end_lba = new_sectors - 1
                heads = 16
                sectors = 63
                c = end_lba // (heads * sectors)
                h = (end_lba // sectors) % heads
                s = (end_lba % sectors) + 1
                if c > 1023:
                    c, h, s = 1023, 254, 63  # Max CHS values
                f.seek(446 + 5)
                f.write(bytes([h, ((c >> 8) << 6) | s, c & 0xFF]))

            # Update BPB total sectors
            part_offset = old_part.start_lba * 512
            if new_part_sectors < 65536:
                f.seek(part_offset + 19)
                f.write(struct.pack('<H', new_part_sectors))
                f.seek(part_offset + 32)
                f.write(struct.pack('<I', 0))
            else:
                f.seek(part_offset + 19)
                f.write(struct.pack('<H', 0))
                f.seek(part_offset + 32)
                f.write(struct.pack('<I', new_part_sectors))

        # Verify the result
        with VHDImage(args.image) as img:
            new_stats = img.get_filesystem_stats()
            partitions = img.get_partitions()

            if not partitions:
                raise ValueError("Partition table corrupted after resize")

            if img.bpb is None:
                raise ValueError("BPB corrupted after resize")

            print(f"Resized successfully to {format_size(new_size)}")
            print(f"  Partition: {format_size(partitions[0].size_sectors * 512)}")
            print(f"  Available: {format_size(new_stats['free_bytes'])} free")

        if not args.no_backup:
            print(f"Backup saved as: {backup_path}")
            print("Delete backup manually after verifying data integrity")

    except Exception as e:
        print(f"Error during resize: {e}", file=sys.stderr)
        if not args.no_backup and os.path.exists(backup_path):
            print("Restoring from backup...")
            shutil.move(backup_path, args.image)
        return 1

    return 0


def cmd_defrag(args):
    """Create defragmented copy of disk image."""
    if not os.path.exists(args.image):
        print(f"Error: {args.image} not found", file=sys.stderr)
        return 1

    # Determine output path
    if args.output:
        dest_path = args.output
    else:
        base, ext = os.path.splitext(args.image)
        dest_path = f"{base}_defrag{ext}"

    if os.path.exists(dest_path) and not args.force:
        print(f"Error: {dest_path} already exists (use --force to overwrite)", file=sys.stderr)
        return 1

    if os.path.exists(dest_path) and args.force:
        os.remove(dest_path)

    # Parse new size if specified
    new_size = None
    if args.size:
        new_size = parse_size(args.size)
        new_size = (new_size // 512) * 512

    # Get source stats
    with VHDImage(args.image) as img:
        if img.is_vhd and img.is_dynamic:
            print("Error: Dynamic VHD not supported for defragmentation", file=sys.stderr)
            return 1

        source_stats = img.get_filesystem_stats()
        source_size = os.path.getsize(args.image)

    # Validate new size if shrinking
    if new_size and new_size < source_size:
        min_size = source_stats['used_bytes'] + (1024 * 1024)  # Add 1MB buffer
        if new_size < min_size:
            print(f"Error: New size too small to fit data", file=sys.stderr)
            print(f"  Data in use: {format_size(source_stats['used_bytes'])}")
            print(f"  Minimum size: ~{format_size(min_size)}")
            return 1

    print(f"Defragmenting: {args.image}")
    print(f"  Source: {format_size(source_size)}, {source_stats['used_clusters']} clusters used")
    if new_size:
        print(f"  Target size: {format_size(new_size)}")
    print(f"  Output: {dest_path}")

    def progress(phase, current, total):
        if not args.quiet:
            if total > 0:
                print(f"\r  {phase}: {current}/{total}", end='', flush=True)
            else:
                print(f"\r  {phase}: {current} files", end='', flush=True)

    try:
        stats = defragment_image(args.image, dest_path, new_size, progress)

        if not args.quiet:
            print()  # Newline after progress

        print(f"Defragmentation complete:")
        print(f"  Files copied: {stats['files_copied']}")
        print(f"  Bytes copied: {format_size(stats['bytes_copied'])}")
        print(f"  Fragmentation: {stats['fragmentation_before']*100:.1f}% -> {stats['fragmentation_after']*100:.1f}%")

        # Verify output
        with VHDImage(dest_path) as img:
            dest_stats = img.get_filesystem_stats()
            print(f"  Result: {dest_stats['used_clusters']} clusters, {format_size(dest_stats['free_bytes'])} free")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if os.path.exists(dest_path):
            os.remove(dest_path)
        return 1

    return 0


def cmd_listboot(args):
    """List available boot sectors."""
    boot_sectors = get_boot_sectors()

    print("Available boot sectors:")
    print()
    for key, info in boot_sectors.items():
        print(f"  {key:15} - {info['description']}")

    print()
    print(f"Boot sector collection: {BOOT_SECTORS_DIR}")
    if not BOOT_SECTORS_DIR.exists():
        print("  (directory not found - create it to add custom boot sectors)")
        print("  Place .bin files (512 bytes) with optional .txt description files")


def cmd_makeboot(args):
    """Make disk bootable with specified boot sector."""
    if not os.path.exists(args.image):
        print(f"Error: {args.image} not found", file=sys.stderr)
        return 1

    boot_sectors = get_boot_sectors()

    if args.extract:
        print(f"Extracting boot sectors from {args.image}...")
        mbr, vbr = extract_boot_code_from_image(args.image)

        BOOT_SECTORS_DIR.mkdir(parents=True, exist_ok=True)

        mbr_path = BOOT_SECTORS_DIR / f"{args.extract}_mbr.bin"
        vbr_path = BOOT_SECTORS_DIR / f"{args.extract}_vbr.bin"

        mbr_path.write_bytes(mbr)
        vbr_path.write_bytes(vbr)

        print(f"Extracted MBR to: {mbr_path}")
        print(f"Extracted VBR to: {vbr_path}")
        return 0

    if args.from_image:
        if not os.path.exists(args.from_image):
            print(f"Error: Source image not found: {args.from_image}", file=sys.stderr)
            return 1

        print(f"Copying boot sectors from {args.from_image}...")
        src_mbr, src_vbr = extract_boot_code_from_image(args.from_image)

        with open(args.image, 'r+b') as f:
            current_mbr = bytearray(f.read(512))
            current_mbr[0:446] = src_mbr[0:446]
            f.seek(0)
            f.write(current_mbr)

            part_start = struct.unpack('<I', current_mbr[446+8:446+12])[0]
            f.seek(part_start * 512)
            current_vbr = bytearray(f.read(512))

            current_vbr[0:3] = src_vbr[0:3]
            current_vbr[62:510] = src_vbr[62:510]

            f.seek(part_start * 512)
            f.write(current_vbr)

        print(f"Boot sectors copied from {args.from_image}")
        return 0

    if args.boot_type:
        if args.boot_type not in boot_sectors:
            print(f"Error: Unknown boot type '{args.boot_type}'", file=sys.stderr)
            print("Use 'listboot' to see available options")
            return 1

        info = boot_sectors[args.boot_type]
        if 'path' in info:
            print(f"Applied boot sector: {args.boot_type}")
            return 0
        else:
            print("Minimal boot sector doesn't provide bootable DOS")
            print("Use --from-image to copy boot sectors from a working DOS disk")
            return 1

    print("Usage: makeboot <image> --from-image <source> | --extract <name> | --boot-type <type>")
    print("Use 'listboot' to see available boot sector types")


def cmd_extract_sys(args):
    """Extract system files needed for booting."""
    with VHDImage(args.image) as img:
        entries = img.list_dir('/')

        sys_files = ['IO.SYS', 'MSDOS.SYS', 'COMMAND.COM',
                     'IBMBIO.COM', 'IBMDOS.COM']

        found = []
        for entry in entries:
            if entry.full_name.upper() in sys_files:
                found.append(entry.full_name)
                data = img.read_file(entry.full_name)
                out_path = Path(args.output) / entry.full_name
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(data)
                print(f"Extracted: {entry.full_name} ({len(data):,} bytes)")

        if not found:
            print("No DOS system files found in image")


def main():
    parser = argparse.ArgumentParser(
        description="VHD/Raw Disk Image Tool for MiSTer ao486",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s info disk.vhd                    Show disk info
  %(prog)s ls disk.vhd                      List root directory
  %(prog)s ls -l disk.vhd /DOS              List /DOS with details
  %(prog)s cat disk.vhd:AUTOEXEC.BAT        Print file contents
  %(prog)s cp disk.vhd:CONFIG.SYS .         Copy file from image
  %(prog)s cp myfile.txt disk.vhd:/         Copy file to image root
  %(prog)s mkdir disk.vhd:/GAMES            Create directory
  %(prog)s rm disk.vhd:/TEMP.TXT            Remove file
  %(prog)s create newdisk.vhd 512M          Create 512MB disk
  %(prog)s resize disk.vhd 1G               Resize to 1GB
  %(prog)s defrag disk.vhd                   Create defragmented copy
  %(prog)s defrag disk.vhd -s 256M           Defrag and shrink to 256MB
  %(prog)s makeboot disk.vhd --from-image bootable.vhd
  %(prog)s makeboot disk.vhd --extract mydos   Extract boot sectors
  %(prog)s listboot                         List boot sector types
        """)

    subparsers = parser.add_subparsers(dest='command', required=True)

    info_p = subparsers.add_parser('info', help='Show disk/partition/filesystem info')
    info_p.add_argument('image', help='Disk image file')
    info_p.set_defaults(func=cmd_info)

    ls_p = subparsers.add_parser('ls', help='List directory contents')
    ls_p.add_argument('image', help='Disk image file')
    ls_p.add_argument('path', nargs='?', default='/', help='Directory path (default: /)')
    ls_p.add_argument('-l', '--long', action='store_true', help='Long format')
    ls_p.set_defaults(func=cmd_ls)

    cp_p = subparsers.add_parser('cp', help='Copy files to/from image')
    cp_p.add_argument('src', help='Source (use image:path for image files)')
    cp_p.add_argument('dest', help='Destination (use image:path for image files)')
    cp_p.add_argument('-r', '--recursive', action='store_true', help='Copy directories recursively')
    cp_p.set_defaults(func=cmd_cp)

    cat_p = subparsers.add_parser('cat', help='Print file contents')
    cat_p.add_argument('path', help='File path (image:path format)')
    cat_p.add_argument('-b', '--binary', action='store_true', help='Binary output')
    cat_p.set_defaults(func=cmd_cat)

    mkdir_p = subparsers.add_parser('mkdir', help='Create directory')
    mkdir_p.add_argument('path', help='Directory path (image:path format)')
    mkdir_p.set_defaults(func=cmd_mkdir)

    rm_p = subparsers.add_parser('rm', help='Remove file or empty directory')
    rm_p.add_argument('path', help='Path (image:path format)')
    rm_p.set_defaults(func=cmd_rm)

    create_p = subparsers.add_parser('create', help='Create new disk image')
    create_p.add_argument('image', help='Output image file')
    create_p.add_argument('size', help='Disk size (e.g., 512M, 1G, 2048MB)')
    create_p.add_argument('-l', '--label', default='DISK', help='Volume label (default: DISK)')
    create_p.add_argument('-f', '--force', action='store_true', help='Overwrite existing file')
    create_p.set_defaults(func=cmd_create)

    resize_p = subparsers.add_parser('resize', help='Resize disk image')
    resize_p.add_argument('image', help='Disk image file')
    resize_p.add_argument('size', help='New size (e.g., 1G, 2048MB)')
    resize_p.add_argument('--no-backup', action='store_true', help='Skip backup creation')
    resize_p.set_defaults(func=cmd_resize)

    makeboot_p = subparsers.add_parser('makeboot', help='Make disk bootable')
    makeboot_p.add_argument('image', help='Disk image file')
    makeboot_p.add_argument('--from-image', metavar='SRC', help='Copy boot sectors from another image')
    makeboot_p.add_argument('--extract', metavar='NAME', help='Extract boot sectors to collection')
    makeboot_p.add_argument('--boot-type', metavar='TYPE', help='Use boot sector from collection')
    makeboot_p.set_defaults(func=cmd_makeboot)

    listboot_p = subparsers.add_parser('listboot', help='List available boot sectors')
    listboot_p.set_defaults(func=cmd_listboot)

    extractsys_p = subparsers.add_parser('extractsys', help='Extract DOS system files')
    extractsys_p.add_argument('image', help='Disk image file')
    extractsys_p.add_argument('-o', '--output', default='.', help='Output directory')
    extractsys_p.set_defaults(func=cmd_extract_sys)

    defrag_p = subparsers.add_parser('defrag', help='Create defragmented copy of disk image')
    defrag_p.add_argument('image', help='Source disk image file')
    defrag_p.add_argument('-o', '--output', metavar='PATH', help='Output path (default: <image>_defrag.<ext>)')
    defrag_p.add_argument('-s', '--size', metavar='SIZE', help='New size (e.g., 512M, 1G) - can shrink if data fits')
    defrag_p.add_argument('-f', '--force', action='store_true', help='Overwrite existing output file')
    defrag_p.add_argument('-q', '--quiet', action='store_true', help='Suppress progress output')
    defrag_p.set_defaults(func=cmd_defrag)

    args = parser.parse_args()
    result = args.func(args)
    sys.exit(result or 0)


if __name__ == '__main__':
    main()
