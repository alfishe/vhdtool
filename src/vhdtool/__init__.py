"""
VHDTool - Disk Image Tool for MiSTer ao486

A Python tool for managing VHD and raw disk images with FAT12/FAT16/FAT32 filesystems.
"""

__version__ = "1.0.0"
__author__ = "VHDTool Contributors"

from .image import VHDImage
from .fat import FATType, BPB, DirEntry
from .partition import PartitionEntry
from .utils import format_size, parse_size

__all__ = [
    "VHDImage",
    "FATType",
    "BPB",
    "DirEntry",
    "PartitionEntry",
    "format_size",
    "parse_size",
]
