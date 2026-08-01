;===============================================================================
; STANDARD MBR (Master Boot Record)
;===============================================================================
;
; This is the first code that runs when a PC boots from a hard disk.
; The BIOS loads this 512-byte sector from LBA 0 to memory address 0x7C00
; and jumps to it.
;
; What this MBR does:
;   1. Sets up CPU segments and stack
;   2. Relocates itself to 0x0600 (so 0x7C00 is free for VBR)
;   3. Scans partition table for active (bootable) partition
;   4. Loads the VBR (first sector of active partition) to 0x7C00
;   5. Jumps to VBR to continue boot process
;
; Memory layout at boot:
;   0x0000:0x0000 - 0x0000:0x03FF  Interrupt Vector Table
;   0x0000:0x0500 - 0x0000:0x7BFF  Free (we use 0x0600 for relocated MBR)
;   0x0000:0x7C00 - 0x0000:0x7DFF  Boot sector loaded here by BIOS
;   0x0000:0x7E00+                  Free (stack grows down from 0x7C00)
;
; Build: nasm -f bin -o standard_mbr.bin standard_mbr.asm
;
; License: Public Domain
;===============================================================================

BITS 16                         ; x86 real mode is 16-bit
ORG 0x7C00                      ; BIOS loads us here

;-------------------------------------------------------------------------------
; Constants
;-------------------------------------------------------------------------------
RELOC_ADDR  equ 0x0600          ; Where we relocate ourselves
LOAD_ADDR   equ 0x7C00          ; Where we load the VBR
PART_TABLE  equ 0x1BE           ; Offset of partition table in MBR (446)
BOOT_SIG    equ 0xAA55          ; Required signature at end of boot sector

;===============================================================================
; Entry Point
;===============================================================================
; When BIOS jumps here:
;   DL = boot drive number (0x80 = first hard disk)
;   CS:IP = 0x0000:0x7C00 (usually, but not guaranteed)
;   Other registers are undefined
;===============================================================================

start:
    ;---------------------------------------------------------------------------
    ; Step 1: Set up segments and stack
    ;---------------------------------------------------------------------------
    ; In real mode, memory addresses are segment:offset
    ; Physical address = segment * 16 + offset
    ; We set all segments to 0 for simplicity (linear addressing up to 64KB)

    cli                         ; Disable interrupts during setup
                                ; (prevents interrupt handlers from corrupting
                                ; our stack before it's properly set up)

    xor ax, ax                  ; AX = 0 (faster than mov ax, 0)
    mov ds, ax                  ; Data segment = 0
    mov es, ax                  ; Extra segment = 0
    mov ss, ax                  ; Stack segment = 0
    mov sp, LOAD_ADDR           ; Stack pointer just below boot sector
                                ; Stack grows downward, so this gives us
                                ; about 30KB of stack space (0x0500 to 0x7BFF)

    sti                         ; Re-enable interrupts

    ;---------------------------------------------------------------------------
    ; Step 2: Save boot drive number
    ;---------------------------------------------------------------------------
    ; BIOS passes drive number in DL:
    ;   0x00 = first floppy (A:)
    ;   0x80 = first hard disk (C:)
    ;   0x81 = second hard disk
    ; We save it because we'll need it for disk reads

    mov [drive_num], dl         ; Save for later use

    ;---------------------------------------------------------------------------
    ; Step 3: Relocate MBR to 0x0600
    ;---------------------------------------------------------------------------
    ; We need to move ourselves out of 0x7C00 because that's where we'll
    ; load the VBR. The standard relocation address is 0x0600.

    mov si, LOAD_ADDR           ; Source: where BIOS loaded us
    mov di, RELOC_ADDR          ; Destination: where we're moving to
    mov cx, 256                 ; Count: 512 bytes / 2 = 256 words
    cld                         ; Clear direction flag (increment SI/DI)
    rep movsw                   ; Copy CX words from DS:SI to ES:DI

    ;---------------------------------------------------------------------------
    ; Step 4: Jump to relocated code
    ;---------------------------------------------------------------------------
    ; We use a far jump to update CS (code segment) and IP (instruction pointer)
    ; The "0:" means segment 0, and "relocated" is the offset

    jmp 0:relocated             ; Jump to our new location

;===============================================================================
; Relocated Code (now running from 0x0600)
;===============================================================================

relocated:
    ; Update DS to point to our new location
    ; (CS was updated by the far jump above)
    push cs
    pop ds                      ; DS = CS = 0

    ;---------------------------------------------------------------------------
    ; Step 5: Scan partition table for active partition
    ;---------------------------------------------------------------------------
    ; The partition table is at offset 446 (0x1BE) in the MBR
    ; Each entry is 16 bytes, and there are 4 entries
    ; The first byte of each entry is the boot flag:
    ;   0x80 = active (bootable)
    ;   0x00 = inactive

    mov si, RELOC_ADDR + PART_TABLE  ; Point to partition table
    mov cx, 4                        ; 4 partition entries

.scan_partitions:
    cmp byte [si], 0x80         ; Is this partition active?
    je .found_active            ; Yes! Go load it
    add si, 16                  ; No, move to next entry (16 bytes each)
    loop .scan_partitions       ; Decrement CX and loop if not zero

    ; If we get here, no active partition was found
    mov si, msg_no_active
    jmp error

;-------------------------------------------------------------------------------
; Found active partition - load its boot sector
;-------------------------------------------------------------------------------

.found_active:
    ; SI now points to the active partition entry
    ; Partition entry format (16 bytes):
    ;   Offset 0:  Boot flag (0x80 = active)
    ;   Offset 1:  Starting head (CHS)
    ;   Offset 2:  Starting sector (bits 0-5) + cylinder high (bits 6-7)
    ;   Offset 3:  Starting cylinder (low 8 bits)
    ;   Offset 4:  Partition type code
    ;   Offset 5:  Ending head
    ;   Offset 6:  Ending sector + cylinder high
    ;   Offset 7:  Ending cylinder low
    ;   Offset 8:  Starting LBA (32-bit little endian)
    ;   Offset 12: Partition size in sectors (32-bit)

    ;---------------------------------------------------------------------------
    ; Try LBA (Logical Block Addressing) first
    ;---------------------------------------------------------------------------
    ; Modern BIOSes support LBA, which is simpler than CHS
    ; We check if LBA extensions are available using INT 13h AH=41h

    mov ah, 41h                 ; Check LBA extensions present
    mov bx, 0x55AA              ; Required signature
    mov dl, [drive_num]         ; Drive number
    int 13h                     ; Call BIOS disk service
    jc .try_chs                 ; Carry flag set = LBA not supported
    cmp bx, 0xAA55              ; Check for signature swap (confirms LBA)
    jne .try_chs                ; Not swapped = LBA not supported

    ;---------------------------------------------------------------------------
    ; Use LBA to read sector
    ;---------------------------------------------------------------------------
    ; LBA uses a Disk Address Packet (DAP) structure

    mov di, lba_packet          ; Point to our DAP
    mov word [di], 0x10         ; Packet size (16 bytes)
    mov word [di+2], 1          ; Number of sectors to read
    mov word [di+4], LOAD_ADDR  ; Buffer offset (where to load)
    mov word [di+6], 0          ; Buffer segment

    ; Copy LBA from partition entry (offset 8, 4 bytes)
    mov eax, [si+8]             ; Get 32-bit LBA
    mov [di+8], eax             ; Store in DAP
    xor eax, eax
    mov [di+12], eax            ; High 32 bits = 0 (we don't use 48-bit LBA)

    mov ah, 42h                 ; Extended read sectors
    mov dl, [drive_num]         ; Drive number
    int 13h                     ; Call BIOS
    jc .try_chs                 ; If LBA read failed, fall back to CHS
    jmp .check_vbr              ; Success! Check the loaded sector

    ;---------------------------------------------------------------------------
    ; Use CHS (Cylinder-Head-Sector) addressing
    ;---------------------------------------------------------------------------
    ; Fallback for old BIOSes that don't support LBA
    ; CHS values are already in the partition entry

.try_chs:
    mov dh, [si+1]              ; Head number
    mov cx, [si+2]              ; Sector (bits 0-5) + Cylinder (bits 6-15)
    mov bx, LOAD_ADDR           ; Buffer address (ES:BX)
    mov ax, 0x0201              ; AH=02 (read), AL=01 (1 sector)
    mov dl, [drive_num]         ; Drive number
    int 13h                     ; Call BIOS disk service
    jc .disk_error              ; Carry flag set = error

.check_vbr:
    ;---------------------------------------------------------------------------
    ; Verify VBR signature
    ;---------------------------------------------------------------------------
    ; Every valid boot sector ends with 0x55, 0xAA

    cmp word [LOAD_ADDR + 510], BOOT_SIG
    jne .invalid_vbr

    ;---------------------------------------------------------------------------
    ; Jump to VBR
    ;---------------------------------------------------------------------------
    ; Pass drive number in DL (some VBRs expect this)
    ; Jump to 0x7C00 where we loaded the VBR

    mov dl, [drive_num]         ; Drive number for VBR
    jmp 0:LOAD_ADDR             ; Far jump to VBR

;-------------------------------------------------------------------------------
; Error handlers
;-------------------------------------------------------------------------------

.disk_error:
    mov si, msg_disk_error
    jmp error

.invalid_vbr:
    mov si, msg_invalid
    jmp error

;===============================================================================
; Print error message and halt
;===============================================================================
; Input: SI = pointer to null-terminated string
; This routine never returns - it halts the CPU
;===============================================================================

error:
.print_loop:
    lodsb                       ; AL = [DS:SI], SI++
    or al, al                   ; Test if AL is zero (null terminator)
    jz .halt                    ; If zero, we're done
    mov ah, 0x0E                ; BIOS teletype function
    mov bx, 0x0007              ; Page 0, white on black
    int 10h                     ; Print character
    jmp .print_loop

.halt:
    hlt                         ; Halt CPU (waits for interrupt)
    jmp .halt                   ; In case of NMI, halt again

;===============================================================================
; Data Section
;===============================================================================

drive_num:      db 0            ; Storage for boot drive number

; Error messages (null-terminated strings)
msg_no_active:  db "No active partition", 13, 10, 0
msg_disk_error: db "Disk error", 13, 10, 0
msg_invalid:    db "Invalid VBR", 13, 10, 0

;-------------------------------------------------------------------------------
; LBA Disk Address Packet
;-------------------------------------------------------------------------------
; Structure used by INT 13h AH=42h (extended read)
; Must be aligned to word boundary for some BIOSes

align 4                         ; Align to 4-byte boundary
lba_packet:
    dw 0x10                     ; Packet size (16 bytes)
    dw 1                        ; Number of sectors to read
    dw LOAD_ADDR                ; Buffer offset
    dw 0                        ; Buffer segment
    dd 0                        ; LBA low 32 bits (filled in at runtime)
    dd 0                        ; LBA high 32 bits (not used)

;===============================================================================
; Partition Table
;===============================================================================
; The partition table is at offset 446 (0x1BE) in the MBR
; We pad to that offset, leaving space for the partition table
; (which will be filled in by partitioning tools)

times PART_TABLE-($-$$) db 0    ; Pad with zeros to offset 446

; Partition table placeholder (4 entries × 16 bytes = 64 bytes)
; In a real MBR, this would be populated by fdisk or similar tool
partition_table:
    times 64 db 0               ; 4 partition entries

;===============================================================================
; Boot Signature
;===============================================================================
; Every boot sector MUST end with 0x55, 0xAA at offsets 510-511
; The BIOS checks for this signature before executing the boot sector

dw BOOT_SIG                     ; 0xAA55 (little-endian: 0x55, 0xAA in memory)

;===============================================================================
; End of MBR
; Total size: exactly 512 bytes
;===============================================================================
