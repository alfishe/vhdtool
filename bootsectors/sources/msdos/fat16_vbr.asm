;===============================================================================
; FAT16 VBR (Volume Boot Record)
;===============================================================================
;
; This boot sector loads IO.SYS from a FAT16 filesystem and starts MS-DOS.
; It's loaded by the MBR to address 0x7C00 and executed.
;
; What this VBR does:
;   1. Sets up CPU segments and stack
;   2. Parses the BPB (BIOS Parameter Block) to locate filesystem structures
;   3. Loads the root directory and searches for IO.SYS
;   4. Reads the FAT to follow IO.SYS's cluster chain
;   5. Loads IO.SYS to memory at 0x0070:0x0000
;   6. Jumps to IO.SYS to continue DOS boot
;
; FAT16 filesystem layout:
;   ┌─────────────────────────────────────────┐
;   │ VBR (this code) - 1 sector              │ ← We are here
;   ├─────────────────────────────────────────┤
;   │ FAT #1 (File Allocation Table)          │
;   ├─────────────────────────────────────────┤
;   │ FAT #2 (backup copy)                    │
;   ├─────────────────────────────────────────┤
;   │ Root Directory                          │ ← We search for IO.SYS here
;   ├─────────────────────────────────────────┤
;   │ Data Area (clusters 2, 3, 4, ...)       │ ← IO.SYS and other files here
;   └─────────────────────────────────────────┘
;
; Build: nasm -f bin -o fat16_vbr.bin fat16_vbr.asm
;
; License: Public Domain
;===============================================================================

BITS 16                         ; x86 real mode is 16-bit
ORG 0x7C00                      ; MBR loads us here

;-------------------------------------------------------------------------------
; Constants
;-------------------------------------------------------------------------------
LOAD_SEG    equ 0x0070          ; Segment where IO.SYS is loaded
                                ; Physical address = 0x0070 * 16 = 0x0700
BOOT_SIG    equ 0xAA55          ; Required signature at end of boot sector

;===============================================================================
; Entry Point and Jump Instruction
;===============================================================================
; The first 3 bytes MUST be a jump instruction to skip over the BPB.
; This is how FAT drivers identify the filesystem.

start:
    jmp short main              ; 2-byte short jump (0xEB xx)
    nop                         ; 1-byte NOP to pad to 3 bytes

;===============================================================================
; BIOS Parameter Block (BPB)
;===============================================================================
; The BPB describes the filesystem layout. This is the critical data structure
; that tells us where everything is located on the disk.
;
; These values are set by the formatting tool (FORMAT, vhdtool, etc.)
; We read these at runtime to locate the FAT and root directory.
;
; IMPORTANT: The BPB must start at offset 3 and be exactly 59 bytes.
; The boot code must NOT modify these values!
;===============================================================================

bpb:
; Standard BPB (DOS 2.0+)
.oem_name:          db "MSDOS5.0"   ; 8 bytes: OEM identifier
                                     ; Not actually used, just for show

.bytes_per_sector:  dw 512           ; Almost always 512
.sectors_per_clust: db 4             ; Cluster size = this × 512 bytes
                                     ; Common values: 1, 2, 4, 8, 16, 32, 64
.reserved_sectors:  dw 1             ; Sectors before first FAT (including VBR)
.num_fats:          db 2             ; Number of FAT copies (usually 2)
.root_entries:      dw 512           ; Max root directory entries
.total_sectors_16:  dw 0             ; Total sectors (16-bit) - 0 if > 65535
.media_type:        db 0xF8          ; Media descriptor:
                                     ;   0xF8 = hard disk
                                     ;   0xF0 = 1.44MB floppy
                                     ;   0xF9 = 720KB floppy
.fat_size_16:       dw 128           ; Sectors per FAT
.sectors_per_track: dw 63            ; For CHS translation
.num_heads:         dw 16            ; For CHS translation
.hidden_sectors:    dd 63            ; Sectors before this partition
                                     ; (partition's starting LBA)
.total_sectors_32:  dd 200000        ; Total sectors (32-bit)

; Extended BPB (DOS 3.31+)
.drive_number:      db 0x80          ; BIOS drive number (0x80 = first HDD)
.reserved:          db 0             ; Reserved
.boot_signature:    db 0x29          ; Extended boot signature (indicates
                                     ; following 3 fields are present)
.volume_serial:     dd 0x12345678    ; Volume serial number (random)
.volume_label:      db "NO NAME    " ; 11 bytes: Volume label
.fs_type:           db "FAT16   "    ; 8 bytes: Filesystem type string

;===============================================================================
; Boot Code Starts Here (offset 62 = 0x3E)
;===============================================================================
; We have only 448 bytes for code (offset 62 to 510)!
; Every byte counts. This is why boot code is compact and tricky.
;===============================================================================

main:
    ;---------------------------------------------------------------------------
    ; Step 1: Set up segments and stack
    ;---------------------------------------------------------------------------
    cli                         ; Disable interrupts during setup
    xor ax, ax                  ; AX = 0
    mov ds, ax                  ; Data segment = 0 (for accessing BPB)
    mov es, ax                  ; Extra segment = 0
    mov ss, ax                  ; Stack segment = 0
    mov sp, 0x7C00              ; Stack below boot sector
    sti                         ; Re-enable interrupts

    ; Save drive number (passed by MBR in DL)
    mov [bpb.drive_number], dl

    ;---------------------------------------------------------------------------
    ; Step 2: Calculate filesystem locations
    ;---------------------------------------------------------------------------
    ; We need to find:
    ;   1. Where the root directory starts
    ;   2. How many sectors the root directory occupies
    ;   3. Where the data area starts (cluster 2)

    ; root_start = reserved_sectors + (num_fats × fat_size)
    ; This is the sector number relative to the partition start

    xor ax, ax
    mov al, [bpb.num_fats]      ; AL = number of FATs (usually 2)
    mul word [bpb.fat_size_16]  ; AX = num_fats × fat_size
    add ax, [bpb.reserved_sectors]  ; AX = root directory start sector
    mov [root_start], ax

    ; root_sectors = (root_entries × 32 + 511) / 512
    ; Each directory entry is 32 bytes

    mov ax, [bpb.root_entries]  ; AX = number of root entries (e.g., 512)
    shl ax, 5                   ; AX = root_entries × 32 (shift left 5 = ×32)
    add ax, 511                 ; Round up
    shr ax, 9                   ; AX = (root_entries × 32 + 511) / 512
    mov [root_sectors], ax

    ; data_start = root_start + root_sectors
    ; This is where cluster 2 begins

    add ax, [root_start]
    mov [data_start], ax

    ;---------------------------------------------------------------------------
    ; Step 3: Load root directory into memory
    ;---------------------------------------------------------------------------
    ; We load the entire root directory to 0x8000 and search it for IO.SYS

    mov ax, [root_start]        ; Relative sector number
    add ax, [bpb.hidden_sectors]      ; Add partition offset
    adc dx, [bpb.hidden_sectors + 2]  ; Handle 32-bit addition
    mov cx, [root_sectors]      ; Number of sectors to read
    mov bx, 0x8000              ; Load root directory here
    call read_sectors

    ;---------------------------------------------------------------------------
    ; Step 4: Search root directory for IO.SYS
    ;---------------------------------------------------------------------------
    ; Directory entries are 32 bytes each:
    ;   Offset 0-7:   Filename (8 chars, space padded)
    ;   Offset 8-10:  Extension (3 chars, space padded)
    ;   Offset 11:    Attributes
    ;   Offset 26-27: First cluster (low word)
    ;   Offset 28-31: File size

    mov si, 0x8000              ; Point to first entry
    mov cx, [bpb.root_entries]  ; Number of entries to check

.search:
    cmp byte [si], 0            ; First byte = 0 means end of directory
    je .not_found

    cmp byte [si], 0xE5         ; 0xE5 means deleted entry
    je .next_entry

    ; Compare filename (11 bytes: 8 name + 3 extension)
    push cx
    push si
    mov di, filename_io_sys     ; "IO      SYS" (note the spaces!)
    mov cx, 11                  ; Compare 11 characters
    repe cmpsb                  ; Compare strings
    pop si
    pop cx
    je .found                   ; Match found!

.next_entry:
    add si, 32                  ; Move to next entry (32 bytes each)
    loop .search                ; Decrement CX and repeat

.not_found:
    mov si, msg_no_system
    jmp error

    ;---------------------------------------------------------------------------
    ; Step 5: Found IO.SYS - load it
    ;---------------------------------------------------------------------------

.found:
    ; Get the starting cluster number from directory entry
    ; The cluster number is at offset 26 in the entry
    mov ax, [si + 26]           ; First cluster (16-bit)
    mov [start_cluster], ax

    ; Set up segment for loading IO.SYS
    push es
    mov ax, LOAD_SEG            ; Segment 0x0070
    mov es, ax
    xor bx, bx                  ; Offset 0 (ES:BX = 0x0070:0x0000 = 0x700)

    ; Start loading clusters
    mov ax, [start_cluster]

.load_cluster:
    ;-----------------------------------------------------------------------
    ; Convert cluster number to sector number
    ;-----------------------------------------------------------------------
    ; sector = data_start + (cluster - 2) × sectors_per_cluster
    ; Clusters are numbered starting from 2 (0 and 1 are reserved)

    push ax                     ; Save cluster number
    sub ax, 2                   ; Cluster 2 is the first data cluster
    xor dx, dx
    mov cl, [bpb.sectors_per_clust]
    xor ch, ch
    mul cx                      ; AX = (cluster - 2) × sectors_per_cluster
    add ax, [data_start]        ; Add data area start
    add ax, [bpb.hidden_sectors]      ; Add partition offset
    adc dx, [bpb.hidden_sectors + 2]

    ; Read the cluster
    mov cl, [bpb.sectors_per_clust]
    call read_sectors

    ; Advance buffer pointer
    mov cl, [bpb.sectors_per_clust]
    xor ch, ch
    shl cx, 9                   ; CX = sectors × 512 = bytes read
    add bx, cx                  ; Advance buffer

    ;-----------------------------------------------------------------------
    ; Get next cluster from FAT
    ;-----------------------------------------------------------------------
    pop ax                      ; Restore current cluster number
    call get_fat_entry          ; Get next cluster in chain
    cmp ax, 0xFFF8              ; End of chain marker (0xFFF8-0xFFFF)
    jb .load_cluster            ; If not end, continue loading

    pop es

    ;---------------------------------------------------------------------------
    ; Step 6: Jump to IO.SYS
    ;---------------------------------------------------------------------------
    ; Set up registers as expected by IO.SYS:
    ;   DL = boot drive number
    ;   DS:SI = pointer to this boot sector (optional)
    ;   ES:BX = undefined

    mov dl, [bpb.drive_number]
    mov ax, LOAD_SEG
    mov ds, ax
    mov es, ax
    jmp LOAD_SEG:0              ; Far jump to IO.SYS

;===============================================================================
; Subroutine: Read Sectors
;===============================================================================
; Input:
;   DX:AX = Starting LBA (32-bit)
;   CX = Number of sectors to read
;   ES:BX = Buffer address
;
; Uses INT 13h AH=02h (CHS read) for compatibility with ao486
;===============================================================================

read_sectors:
    push ax
    push bx
    push cx
    push dx

.read_loop:
    push cx                     ; Save remaining count
    push ax
    push dx

    ;---------------------------------------------------------------------------
    ; Convert LBA to CHS (Cylinder-Head-Sector)
    ;---------------------------------------------------------------------------
    ; This is required for older BIOSes and the ao486 core
    ;
    ; LBA = (Cylinder × Heads + Head) × Sectors + Sector - 1
    ;
    ; To convert LBA to CHS:
    ;   Sector = (LBA mod SectorsPerTrack) + 1
    ;   temp = LBA / SectorsPerTrack
    ;   Head = temp mod Heads
    ;   Cylinder = temp / Heads

    div word [bpb.sectors_per_track]  ; AX = LBA / SPT, DX = LBA mod SPT
    inc dl                            ; Sector = (LBA mod SPT) + 1
    mov cl, dl                        ; CL = sector number

    xor dx, dx
    div word [bpb.num_heads]          ; AX = cylinder, DX = head
    mov dh, dl                        ; DH = head
    mov ch, al                        ; CH = cylinder (low 8 bits)
    shl ah, 6                         ; Move high 2 bits of cylinder
    or cl, ah                         ; CL bits 6-7 = cylinder high bits

    ; Set up for INT 13h
    mov dl, [bpb.drive_number]  ; Drive number
    mov ax, 0x0201              ; AH=02 (read), AL=01 (1 sector)
    int 13h                     ; Call BIOS disk service
    jc .disk_error              ; Jump if error (carry flag set)

    pop dx
    pop ax
    pop cx

    ; Move to next sector
    add ax, 1                   ; Next LBA
    adc dx, 0                   ; Handle 32-bit increment
    add bx, 512                 ; Advance buffer by 512 bytes
    loop .read_loop             ; Decrement CX, repeat if not zero

    pop dx
    pop cx
    pop bx
    pop ax
    ret

.disk_error:
    mov si, msg_disk_error
    jmp error

;===============================================================================
; Subroutine: Get FAT Entry
;===============================================================================
; Input:
;   AX = Cluster number
;
; Output:
;   AX = Next cluster in chain (or 0xFFF8+ if end)
;
; FAT16 format:
;   Each FAT entry is 2 bytes (16 bits)
;   Entry offset = cluster × 2
;   We need to load the FAT sector containing this entry
;===============================================================================

get_fat_entry:
    push bx
    push dx

    ; Calculate FAT entry offset
    ; offset = cluster × 2 (each FAT16 entry is 2 bytes)
    shl ax, 1                   ; AX = cluster × 2
    xor dx, dx

    ; Calculate which sector of the FAT contains this entry
    ; sector = offset / bytes_per_sector
    ; position = offset mod bytes_per_sector
    div word [bpb.bytes_per_sector]  ; AX = sector, DX = position within sector
    push dx                          ; Save position

    ; Load that FAT sector
    ; FAT starts at: reserved_sectors + hidden_sectors
    add ax, [bpb.reserved_sectors]
    add ax, [bpb.hidden_sectors]
    adc dx, [bpb.hidden_sectors + 2]

    push es
    push bx
    xor bx, bx
    mov cx, 0x8000 >> 4         ; Use 0x8000 as temporary buffer
    mov es, cx
    mov cx, 1                   ; Read 1 sector
    call read_sectors
    pop bx
    pop es

    ; Read the FAT entry
    pop si                      ; Restore position within sector
    add si, 0x8000              ; Add buffer base address
    mov ax, [si]                ; Read 16-bit FAT entry

    pop dx
    pop bx
    ret

;===============================================================================
; Error Handler
;===============================================================================
; Print error message and halt
; Input: SI = pointer to null-terminated string
;===============================================================================

error:
.print:
    lodsb                       ; AL = [DS:SI], SI++
    or al, al                   ; Test for null terminator
    jz .halt
    mov ah, 0x0E                ; BIOS teletype output
    mov bx, 7                   ; White on black
    int 10h
    jmp .print

.halt:
    hlt                         ; Stop CPU
    jmp .halt                   ; Loop in case of interrupt

;===============================================================================
; Data Section
;===============================================================================

; Filename to search for (8.3 format, space-padded)
filename_io_sys:    db "IO      SYS"    ; "IO.SYS" in 8.3 format

; Error messages
msg_no_system:      db "No system", 13, 10, 0
msg_disk_error:     db "Disk error", 13, 10, 0

; Variables (filled in at runtime)
root_start:         dw 0        ; Sector number of root directory
root_sectors:       dw 0        ; Number of sectors in root directory
data_start:         dw 0        ; Sector number of first data cluster
start_cluster:      dw 0        ; Starting cluster of IO.SYS

;===============================================================================
; Pad and Boot Signature
;===============================================================================

times 510-($-$$) db 0           ; Pad to 510 bytes with zeros
dw BOOT_SIG                     ; Boot signature (0x55, 0xAA)

;===============================================================================
; End of FAT16 VBR
; Total size: exactly 512 bytes
;===============================================================================
