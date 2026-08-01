# x86 Real Mode Assembly for Boot Sectors

Quick reference for writing boot sector code in x86 assembly.

## NASM Basics

### File Structure

```asm
; boot.asm - Example boot sector
BITS 16                 ; 16-bit real mode
ORG 0x7C00              ; Boot sector loads here

start:
    ; Code here

; Pad to 510 bytes
times 510-($-$$) db 0

; Boot signature
dw 0xAA55
```

### Build Command

```bash
nasm -f bin -o boot.bin boot.asm
```

## Registers

### General Purpose (16-bit)

| Register | Purpose | 8-bit parts |
|----------|---------|-------------|
| AX | Accumulator | AH, AL |
| BX | Base | BH, BL |
| CX | Counter | CH, CL |
| DX | Data | DH, DL |

### Index and Pointer

| Register | Purpose |
|----------|---------|
| SI | Source index |
| DI | Destination index |
| BP | Base pointer |
| SP | Stack pointer |
| IP | Instruction pointer |

### Segment

| Register | Default use |
|----------|-------------|
| CS | Code segment |
| DS | Data segment |
| ES | Extra segment |
| SS | Stack segment |

### Flags

| Flag | Name | Set when |
|------|------|----------|
| CF | Carry | Unsigned overflow |
| ZF | Zero | Result is zero |
| SF | Sign | Result is negative |
| OF | Overflow | Signed overflow |

## Addressing Modes

```asm
; Immediate
mov ax, 1234h           ; AX = 0x1234

; Register
mov ax, bx              ; AX = BX

; Direct
mov ax, [0x1000]        ; AX = word at address 0x1000

; Register indirect
mov ax, [bx]            ; AX = word at DS:BX
mov ax, [si]            ; AX = word at DS:SI

; Base + displacement
mov ax, [bx+10]         ; AX = word at DS:BX+10

; Segment override
mov ax, [es:bx]         ; AX = word at ES:BX
```

## Common Instructions

### Data Movement

```asm
mov dest, src           ; Copy src to dest
xchg ax, bx             ; Swap AX and BX
push ax                 ; Push AX onto stack
pop ax                  ; Pop stack into AX
lea bx, [si+10]         ; Load effective address
```

### Arithmetic

```asm
add ax, bx              ; AX = AX + BX
sub ax, bx              ; AX = AX - BX
inc ax                  ; AX++
dec ax                  ; AX--
mul bx                  ; DX:AX = AX * BX (unsigned)
div bx                  ; AX = DX:AX / BX, DX = remainder
neg ax                  ; AX = -AX
```

### Logic

```asm
and ax, bx              ; AX = AX & BX
or ax, bx               ; AX = AX | BX
xor ax, bx              ; AX = AX ^ BX
not ax                  ; AX = ~AX
shl ax, 1               ; AX <<= 1
shr ax, 1               ; AX >>= 1 (unsigned)
sar ax, 1               ; AX >>= 1 (signed)
rol ax, 1               ; Rotate left
ror ax, 1               ; Rotate right
```

### Comparison and Jumps

```asm
cmp ax, bx              ; Compare AX with BX (sets flags)
test ax, bx             ; AND without storing result

; Unconditional
jmp label               ; Jump to label

; Conditional (after cmp)
je label                ; Jump if equal (ZF=1)
jne label               ; Jump if not equal (ZF=0)
jl label                ; Jump if less (signed)
jg label                ; Jump if greater (signed)
jb label                ; Jump if below (unsigned)
ja label                ; Jump if above (unsigned)
jc label                ; Jump if carry (CF=1)
jnc label               ; Jump if no carry (CF=0)
jz label                ; Jump if zero (ZF=1)
jnz label               ; Jump if not zero (ZF=0)

; Loop
loop label              ; Dec CX, jump if CX != 0
```

### String Operations

```asm
cld                     ; Clear direction (forward)
std                     ; Set direction (backward)

lodsb                   ; AL = [DS:SI], SI++
lodsw                   ; AX = [DS:SI], SI += 2
stosb                   ; [ES:DI] = AL, DI++
stosw                   ; [ES:DI] = AX, DI += 2
movsb                   ; [ES:DI] = [DS:SI], both++
movsw                   ; Same, word
cmpsb                   ; Compare [DS:SI] with [ES:DI]
scasb                   ; Compare AL with [ES:DI]

; With repeat prefix
rep movsb               ; Copy CX bytes
rep stosb               ; Fill CX bytes with AL
repe cmpsb              ; Compare until mismatch or CX=0
repne scasb             ; Scan until match or CX=0
```

### Subroutines

```asm
call subroutine         ; Push IP, jump to subroutine
ret                     ; Pop IP, return

; With arguments on stack
push arg1
push arg2
call func
add sp, 4               ; Clean up stack
```

## Boot Sector Patterns

### Setup Segments

```asm
start:
    cli                     ; Disable interrupts
    xor ax, ax
    mov ds, ax
    mov es, ax
    mov ss, ax
    mov sp, 0x7C00          ; Stack below boot sector
    sti                     ; Enable interrupts
```

### Print String

```asm
print:
    mov si, message
.loop:
    lodsb                   ; AL = [DS:SI++]
    or al, al               ; Check for null
    jz .done
    mov ah, 0x0E            ; BIOS teletype
    mov bx, 0x0007          ; Page 0, white
    int 0x10
    jmp .loop
.done:
    ret

message: db "Hello, World!", 13, 10, 0
```

### Read Sector (CHS)

```asm
read_sector:
    ; Input: AX = LBA, ES:BX = buffer
    push ax

    ; Convert LBA to CHS
    ; Sector = (LBA % sectors_per_track) + 1
    ; Head = (LBA / sectors_per_track) % heads
    ; Cylinder = LBA / (sectors_per_track * heads)

    xor dx, dx
    div word [sectors_per_track]
    inc dl
    mov cl, dl              ; Sector

    xor dx, dx
    div word [heads]
    mov dh, dl              ; Head
    mov ch, al              ; Cylinder

    mov dl, [drive]
    mov ax, 0x0201          ; Read 1 sector
    int 0x13
    jc .error

    pop ax
    ret

.error:
    ; Handle error
    pop ax
    ret
```

### Read Sector (LBA)

```asm
read_sector_lba:
    ; Input: EAX = LBA, ES:BX = buffer
    mov [dap.lba], eax
    mov [dap.buffer], bx
    mov word [dap.segment], es

    mov ah, 0x42
    mov dl, [drive]
    mov si, dap
    int 0x13
    ret

dap:
    .size:    db 0x10       ; Packet size
    .zero:    db 0
    .count:   dw 1          ; Sectors to read
    .buffer:  dw 0          ; Buffer offset
    .segment: dw 0          ; Buffer segment
    .lba:     dq 0          ; LBA address
```

### Halt

```asm
halt:
    hlt
    jmp halt
```

## Data Definitions

```asm
; Bytes
db 0x55                 ; Define byte
db "Hello", 0           ; String with null
db 10 dup(0)            ; 10 zeros

; Words (16-bit)
dw 0x1234               ; Define word
dw label                ; Address of label

; Doublewords (32-bit)
dd 0x12345678

; Quadwords (64-bit)
dq 0x123456789ABCDEF0

; Reserve space
resb 512                ; Reserve 512 bytes
resw 256                ; Reserve 256 words
```

## Macros

```asm
; Simple macro
%macro print_char 1
    mov al, %1
    mov ah, 0x0E
    int 0x10
%endmacro

; Usage
print_char 'A'

; Conditional assembly
%ifdef DEBUG
    call debug_print
%endif
```

## Debugging Tips

1. **Print markers**: Insert teletype prints to trace execution
2. **Infinite loops**: Use `jmp $` to halt at specific points
3. **Check registers**: Print register values as hex
4. **Use emulator**: QEMU/Bochs with `-d int` shows interrupts

### Hex Print Routine

```asm
print_hex:
    ; Print AX as 4 hex digits
    push ax
    mov cx, 4
.loop:
    rol ax, 4
    push ax
    and al, 0x0F
    add al, '0'
    cmp al, '9'
    jbe .print
    add al, 7           ; 'A' - '9' - 1
.print:
    mov ah, 0x0E
    int 0x10
    pop ax
    loop .loop
    pop ax
    ret
```

## Resources

- [NASM Manual](https://www.nasm.us/doc/)
- [Intel x86 Manual](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
- [OSDev Wiki](https://wiki.osdev.org/)
- [x86 Instruction Reference](https://www.felixcloutier.com/x86/)
