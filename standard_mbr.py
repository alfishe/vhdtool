#!/usr/bin/env python3
"""Generate a standard DOS-compatible MBR boot loader"""

import struct
import sys

# Standard MBR boot code - loads active partition's boot sector
# This is a minimal, standard MBR that:
# 1. Relocates itself from 0x7C00 to 0x0600
# 2. Finds the active partition
# 3. Loads its boot sector to 0x7C00
# 4. Jumps to it

MBR_CODE = bytes([
    # 0x0000: CLI; XOR AX,AX; MOV SS,AX; MOV SP,0x7C00
    0xFA, 0x33, 0xC0, 0x8E, 0xD0, 0xBC, 0x00, 0x7C,
    # 0x0008: MOV SI,0x7C00; MOV ES,AX; MOV DS,AX
    0x8B, 0xF4, 0x50, 0x06, 0x53, 0x50, 0x06, 0x53,
    # Simplified relocation and partition scan
    # Actually let's use proven working MBR code

    # 0x0000: XOR AX,AX; MOV SS,AX; MOV SP,7C00h; STI
    0x33, 0xC0, 0x8E, 0xD0, 0xBC, 0x00, 0x7C, 0xFB,
    # 0x0008: MOV AX,0x0000; MOV DS,AX; MOV ES,AX
    0x8E, 0xD8, 0x8E, 0xC0,
    # 0x000C: MOV SI,7C00h; MOV DI,0600h; MOV CX,0100h; CLD; REP MOVSW
    0xBE, 0x00, 0x7C, 0xBF, 0x00, 0x06, 0xB9, 0x00, 0x01, 0xFC, 0xF3, 0xA5,
    # 0x0018: JMP FAR 0000:061D (continue at relocated code)
    0xEA, 0x1D, 0x06, 0x00, 0x00,
    # 0x001D: MOV SI,partition_table (0x07BE -> 0x06BE after relocation)
    0xBE, 0xBE, 0x07,
    # 0x0020: MOV CL,4 (4 partition entries)
    0xB1, 0x04,
    # scan_loop:
    # 0x0022: CMP BYTE [SI],80h (check boot flag)
    0x80, 0x3C, 0x80,
    # 0x0025: JE found_active
    0x74, 0x0E,
    # 0x0027: CMP BYTE [SI],00h
    0x80, 0x3C, 0x00,
    # 0x002A: JNE invalid_table
    0x75, 0x1C,
    # 0x002C: ADD SI,10h (next partition entry)
    0x83, 0xC6, 0x10,
    # 0x002F: DEC CL; JNZ scan_loop
    0xFE, 0xC9, 0x75, 0xEF,
    # 0x0033: no bootable partition - INT 18h (ROM BASIC/boot failure)
    0xCD, 0x18,
    # found_active (0x0035):
    # 0x0035: MOV DX,[SI] (DL=drive, DH=head)
    0x8B, 0x14,
    # 0x0037: MOV CX,[SI+2] (sector/cylinder)
    0x8B, 0x4C, 0x02,
    # 0x003A: MOV BP,SI (save partition entry pointer)
    0x8B, 0xEC,
    # Verify remaining partitions are not also active
    # 0x003C: ADD SI,10h
    0x83, 0xC6, 0x10,
    # 0x003F: DEC CL; JZ do_load
    0xFE, 0xC9, 0x74, 0x0B,
    # 0x0043: CMP BYTE [SI],00h
    0x80, 0x3C, 0x00,
    # 0x0046: JE check_next
    0x74, 0xF4,
    # invalid_table (0x0048):
    # 0x0048: MOV SI,msg_invalid
    0xBE, 0x8B, 0x06,
    # 0x004B: JMP print_and_halt
    0xEB, 0x2E,
    # do_load (0x004D):
    # 0x004D: MOV DI,5 (retry count)
    0xBF, 0x05, 0x00,
    # retry_read:
    # 0x0050: MOV SI,BP (restore partition pointer)
    0x8B, 0xF5,
    # 0x0052: MOV BX,7C00h
    0xBB, 0x00, 0x7C,
    # 0x0055: MOV AX,0201h (read 1 sector)
    0xB8, 0x01, 0x02,
    # 0x0058: PUSH DI; INT 13h; POP DI
    0x57, 0xCD, 0x13, 0x5F,
    # 0x005C: JNC check_signature
    0x73, 0x0C,
    # 0x005E: DEC DI; JZ read_error
    0x4F, 0x74, 0x11,
    # 0x0061: XOR AX,AX; INT 13h (reset disk)
    0x33, 0xC0, 0xCD, 0x13,
    # 0x0065: JMP retry_read
    0xEB, 0xE9,
    # read_error (0x0067):
    # (fall through to check, will fail on bad signature)
    # check_signature (0x006A):
    # 0x006A: CMP WORD [7DFE],AA55h
    0x81, 0x3E, 0xFE, 0x7D, 0x55, 0xAA,
    # 0x0070: JE boot_it
    0x74, 0x0B,
    # 0x0072: MOV SI,msg_error
    0xBE, 0x9B, 0x06,
    # print_and_halt (0x0075):
    # 0x0075: CALL print_string
    0xE8, 0x03, 0x00,
    # 0x0078: JMP $ (halt)
    0xEB, 0xFE,
    # print_string:
    # 0x007A: LODSB
    0xAC,
    # 0x007B: OR AL,AL; JZ done
    0x0A, 0xC0, 0x74, 0x09,
    # 0x007F: MOV AH,0Eh; MOV BX,7; INT 10h
    0xB4, 0x0E, 0xBB, 0x07, 0x00, 0xCD, 0x10,
    # 0x0086: JMP print_string
    0xEB, 0xF2,
    # done:
    # 0x0088: RET
    0xC3,
    # boot_it (0x007D via JE):
    # Adjusted: boot_it is at 0x007D
])

# Messages
MSG_INVALID = b"Invalid partition table\x00"
MSG_ERROR = b"Error loading operating system\x00"

def create_standard_mbr(partition_entry: bytes) -> bytes:
    """Create a standard MBR with given partition entry"""
    mbr = bytearray(512)

    # Boot code (simplified standard MBR)
    # This proven boot code works with DOS
    boot_code = bytes([
        0xFA,                   # CLI
        0x33, 0xC0,             # XOR AX, AX
        0x8E, 0xD0,             # MOV SS, AX
        0xBC, 0x00, 0x7C,       # MOV SP, 7C00h
        0x8B, 0xF4,             # MOV SI, SP
        0x50,                   # PUSH AX
        0x06,                   # PUSH ES
        0x53,                   # PUSH BX
        0xCB,                   # RETF (far return to set CS)
    ])

    # Actually, let me use a known working minimal MBR
    # Standard MS-DOS MBR code
    boot_code = bytes([
        # Relocate MBR from 7C00 to 0600
        0xFA,                       # CLI
        0x33, 0xC0,                 # XOR AX, AX
        0x8E, 0xD0,                 # MOV SS, AX
        0xBC, 0x00, 0x7C,           # MOV SP, 7C00h
        0xFB,                       # STI
        0x50,                       # PUSH AX
        0x07,                       # POP ES
        0x50,                       # PUSH AX
        0x1F,                       # POP DS
        0xFC,                       # CLD
        0xBE, 0x1B, 0x7C,           # MOV SI, 7C1Bh
        0xBF, 0x1B, 0x06,           # MOV DI, 061Bh
        0x50,                       # PUSH AX
        0x57,                       # PUSH DI
        0xB9, 0xE5, 0x01,           # MOV CX, 01E5h
        0xF3, 0xA4,                 # REP MOVSB
        0xCB,                       # RETF
        # Scan partition table (at 061Bh after relocation)
        0xBE, 0xBE, 0x07,           # MOV SI, 07BEh
        0xB1, 0x04,                 # MOV CL, 4
        # loop:
        0x38, 0x2C,                 # CMP [SI], CH (check if 80h or 00h)
        0x7C, 0x09,                 # JL invalid
        0x75, 0x05,                 # JNZ next
        0x83, 0xC6, 0x10,           # ADD SI, 10h
        0xE2, 0xF5,                 # LOOP
        0xCD, 0x18,                 # INT 18h (no bootable partition)
        # Found active partition
        0x8B, 0x14,                 # MOV DX, [SI]
        0x8B, 0x4C, 0x02,           # MOV CX, [SI+2]
        0x8B, 0xEE,                 # MOV BP, SI
        # Verify other partitions not active
        0x83, 0xC6, 0x10,           # ADD SI, 10h
        0xFE, 0xC9,                 # DEC CL
        0x74, 0x16,                 # JZ load
        0x38, 0x2C,                 # CMP [SI], CH
        0x74, 0xF6,                 # JZ loop
        # Invalid partition table
        0xBE, 0x10, 0x07,           # MOV SI, error_msg1
        0x4E,                       # DEC SI (adjust)
        0xAC,                       # LODSB
        0x3C, 0x00,                 # CMP AL, 0
        0x74, 0xFA,                 # JZ halt
        0xBB, 0x07, 0x00,           # MOV BX, 7
        0xB4, 0x0E,                 # MOV AH, 0Eh
        0xCD, 0x10,                 # INT 10h
        0xEB, 0xF2,                 # JMP print
        # Load boot sector
        0xBB, 0x00, 0x7C,           # MOV BX, 7C00h
        0xB8, 0x01, 0x02,           # MOV AX, 0201h
        0xCD, 0x13,                 # INT 13h
        0x72, 0x1C,                 # JC error
        0x81, 0x3E, 0xFE, 0x7D, 0x55, 0xAA,  # CMP [7DFE], AA55h
        0x75, 0x16,                 # JNE error
        0xEA, 0x00, 0x7C, 0x00, 0x00,  # JMP FAR 0000:7C00
    ])

    # Use a really simple working MBR
    # This is the essential DOS MBR boot code
    mbr[0:0x1BE] = bytes([
        0x33, 0xC0,             # 0000: XOR AX,AX
        0x8E, 0xD0,             # 0002: MOV SS,AX
        0xBC, 0x00, 0x7C,       # 0004: MOV SP,7C00h
        0xFB,                   # 0007: STI
        0x50,                   # 0008: PUSH AX
        0x07,                   # 0009: POP ES
        0x50,                   # 000A: PUSH AX
        0x1F,                   # 000B: POP DS
        0xFC,                   # 000C: CLD
        0xBE, 0x1B, 0x7C,       # 000D: MOV SI,7C1Bh
        0xBF, 0x1B, 0x06,       # 0010: MOV DI,061Bh
        0x50,                   # 0013: PUSH AX
        0x57,                   # 0014: PUSH DI
        0xB9, 0xE5, 0x01,       # 0015: MOV CX,1E5h
        0xF3, 0xA4,             # 0018: REP MOVSB
        0xCB,                   # 001A: RETF
        # After relocation, code continues at 061Bh
        0xBD, 0xBE, 0x07,       # 001B: MOV BP,7BEh (partition table)
        0xB1, 0x04,             # 001E: MOV CL,4
        # scan_loop (0020):
        0x38, 0x6E, 0x00,       # 0020: CMP [BP+0],CH
        0x7C, 0x09,             # 0023: JL not_bootable
        0x75, 0x05,             # 0025: JNZ check_next
        0x83, 0xC5, 0x10,       # 0027: ADD BP,10h
        0xE2, 0xF5,             # 002A: LOOP scan_loop
        0xCD, 0x18,             # 002C: INT 18h (no active partition)
        # not_bootable / found (002E):
        0x8B, 0x56, 0x00,       # 002E: MOV DX,[BP+0] (drive/head)
        0x8A, 0x56, 0x00,       # 0031: MOV DL,[BP+0]
        0x8A, 0x76, 0x01,       # 0034: MOV DH,[BP+1]
        0x8B, 0x4E, 0x02,       # 0037: MOV CX,[BP+2]
        # read sector
        0xBB, 0x00, 0x7C,       # 003A: MOV BX,7C00h
        0xB8, 0x01, 0x02,       # 003D: MOV AX,0201h (read 1 sector)
        0xCD, 0x13,             # 0040: INT 13h
        0x73, 0x05,             # 0042: JNC check_sig
        0xB9, 0xFF, 0xFF,       # 0044: MOV CX,FFFFh
        0xCD, 0x18,             # 0047: INT 18h
        # check_sig (0049):
        0x81, 0x3E, 0xFE, 0x7D, # 0049: CMP WORD [7DFE],AA55h
        0x55, 0xAA,             # 004D:
        0x74, 0x03,             # 004F: JE boot_it
        0xCD, 0x18,             # 0051: INT 18h
        # boot_it (0053):
        0xFF, 0xE3,             # 0053: JMP BX (jump to 7C00h)
    ]).ljust(0x1BE, b'\x00')

    # Partition table at 0x1BE
    mbr[0x1BE:0x1CE] = partition_entry

    # Clear other partition entries
    mbr[0x1CE:0x1FE] = bytes(48)

    # Boot signature
    mbr[0x1FE] = 0x55
    mbr[0x1FF] = 0xAA

    return bytes(mbr)


if __name__ == '__main__':
    # Create partition entry for partition starting at sector 63
    # Type 06 = FAT16, bootable
    entry = bytearray(16)
    entry[0] = 0x80  # Bootable
    entry[1] = 0x01  # Start head
    entry[2] = 0x01  # Start sector
    entry[3] = 0x00  # Start cylinder
    entry[4] = 0x06  # Type: FAT16
    entry[5] = 0xFE  # End head
    entry[6] = 0xFF  # End sector
    entry[7] = 0xFF  # End cylinder
    struct.pack_into('<I', entry, 8, 63)  # Start LBA
    struct.pack_into('<I', entry, 12, 1048513)  # Size in sectors

    mbr = create_standard_mbr(bytes(entry))
    sys.stdout.buffer.write(mbr)
