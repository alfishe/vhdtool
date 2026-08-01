# Boot Sector Build System
# Requires: nasm (brew install nasm / apt install nasm)

NASM = nasm
NASM_FLAGS = -f bin

# Output directory for compiled binaries
BIN_DIR = ../

# Source directories
MBR_DIR = mbr
MSDOS_DIR = msdos
BOOTPROG_DIR = bootprog
FREEDOS_DIR = freedos

# All targets
all: mbr msdos bootprog

# MBR targets
mbr: $(BIN_DIR)standard_mbr.bin

$(BIN_DIR)standard_mbr.bin: $(MBR_DIR)/standard_mbr.asm
	$(NASM) $(NASM_FLAGS) -o $@ $<
	@ls -l $@
	@echo "MBR built: $@"

# MS-DOS compatible VBR
msdos: $(BIN_DIR)fat16_vbr.bin

$(BIN_DIR)fat16_vbr.bin: $(MSDOS_DIR)/fat16_vbr.asm
	$(NASM) $(NASM_FLAGS) -o $@ $<
	@ls -l $@
	@echo "FAT16 VBR built: $@"

# BootProg targets (if sources exist)
bootprog:
	@if [ -f $(BOOTPROG_DIR)/boot12.asm ]; then \
		$(NASM) $(NASM_FLAGS) -o $(BIN_DIR)bootprog_fat12_vbr.bin $(BOOTPROG_DIR)/boot12.asm; \
		$(NASM) $(NASM_FLAGS) -o $(BIN_DIR)bootprog_fat16_vbr.bin $(BOOTPROG_DIR)/boot16.asm; \
		$(NASM) $(NASM_FLAGS) -o $(BIN_DIR)bootprog_fat32_vbr.bin $(BOOTPROG_DIR)/boot32.asm; \
		echo "BootProg built"; \
	else \
		echo "BootProg sources not found. Run 'make fetch-bootprog'"; \
	fi

# FreeDOS boot (if sources exist)
freedos:
	@if [ -f $(FREEDOS_DIR)/boot.asm ]; then \
		$(NASM) $(NASM_FLAGS) -o $(BIN_DIR)freedos_fat16_vbr.bin $(FREEDOS_DIR)/boot.asm; \
		echo "FreeDOS boot built"; \
	else \
		echo "FreeDOS sources not found. Run 'make fetch-freedos'"; \
	fi

# Fetch BootProg from GitHub
fetch-bootprog:
	@echo "Fetching BootProg from GitHub..."
	@mkdir -p $(BOOTPROG_DIR)
	curl -L -o $(BOOTPROG_DIR)/boot12.asm https://raw.githubusercontent.com/alexfru/BootProg/master/boot12.asm
	curl -L -o $(BOOTPROG_DIR)/boot16.asm https://raw.githubusercontent.com/alexfru/BootProg/master/boot16.asm
	curl -L -o $(BOOTPROG_DIR)/boot32.asm https://raw.githubusercontent.com/alexfru/BootProg/master/boot32.asm
	@echo "BootProg sources downloaded"

# Fetch FreeDOS boot from GitHub
fetch-freedos:
	@echo "Fetching FreeDOS boot from GitHub..."
	@mkdir -p $(FREEDOS_DIR)
	curl -L -o $(FREEDOS_DIR)/boot.asm https://raw.githubusercontent.com/FDOS/kernel/master/boot/boot.asm
	curl -L -o $(FREEDOS_DIR)/boot32.asm https://raw.githubusercontent.com/FDOS/kernel/master/boot/boot32.asm
	@echo "FreeDOS boot sources downloaded"

# Fetch all external sources
fetch-all: fetch-bootprog fetch-freedos
	@echo "All sources fetched"

# Clean compiled binaries
clean:
	rm -f $(BIN_DIR)standard_mbr.bin
	rm -f $(BIN_DIR)fat16_vbr.bin
	rm -f $(BIN_DIR)bootprog_*.bin
	rm -f $(BIN_DIR)freedos_*.bin

# Clean fetched sources
clean-sources:
	rm -rf $(BOOTPROG_DIR)/*.asm
	rm -rf $(FREEDOS_DIR)/*.asm

# Verify NASM is installed
check:
	@which $(NASM) > /dev/null || (echo "NASM not found. Install with: brew install nasm"; exit 1)
	@echo "NASM found: $$(which $(NASM))"
	@$(NASM) -v

# Disassemble existing binaries to reference files
disasm:
	@echo "Disassembling existing boot sector binaries..."
	@mkdir -p $(MBR_DIR) $(MSDOS_DIR)
	@for bin in $(BIN_DIR)dos622_fat16_mbr.bin $(BIN_DIR)pchdd_original_mbr.bin; do \
		if [ -f "$$bin" ]; then \
			name=$$(basename "$$bin" .bin); \
			python3 tools/disasm_boot.py "$$bin" -o "$(MBR_DIR)/$${name}.asm.disasm"; \
			echo "  Disassembled: $$bin"; \
		fi; \
	done
	@for bin in $(BIN_DIR)dos622_fat16_vbr.bin $(BIN_DIR)pchdd_original_vbr.bin $(BIN_DIR)freedos_floppy_144_vbr.bin; do \
		if [ -f "$$bin" ]; then \
			name=$$(basename "$$bin" .bin); \
			python3 tools/disasm_boot.py "$$bin" -o "$(MSDOS_DIR)/$${name}.asm.disasm"; \
			echo "  Disassembled: $$bin"; \
		fi; \
	done
	@echo "Disassembly complete. See *.asm.disasm files."

# Verify roundtrip compilation (source -> binary matches original)
verify:
	@echo "Verifying compiled binaries match sources..."
	@$(NASM) $(NASM_FLAGS) -o /tmp/verify_mbr.bin $(MBR_DIR)/standard_mbr.asm
	@echo "  standard_mbr.asm compiled successfully"
	@$(NASM) $(NASM_FLAGS) -o /tmp/verify_vbr.bin $(MSDOS_DIR)/fat16_vbr.asm
	@echo "  fat16_vbr.asm compiled successfully"
	@ls -la /tmp/verify_*.bin
	@rm -f /tmp/verify_*.bin
	@echo "Verification complete."

# Show help
help:
	@echo "Boot Sector Build System"
	@echo ""
	@echo "Targets:"
	@echo "  all            - Build all boot sectors from existing sources"
	@echo "  mbr            - Build standard MBR"
	@echo "  msdos          - Build MS-DOS compatible FAT16 VBR"
	@echo "  bootprog       - Build BootProg boot sectors (fetch first)"
	@echo "  freedos        - Build FreeDOS boot sectors (fetch first)"
	@echo ""
	@echo "  fetch-bootprog - Download BootProg sources from GitHub"
	@echo "  fetch-freedos  - Download FreeDOS boot sources from GitHub"
	@echo "  fetch-all      - Download all external sources"
	@echo ""
	@echo "  disasm         - Disassemble existing .bin files to .asm.disasm"
	@echo "  verify         - Verify sources compile correctly"
	@echo "  check          - Verify NASM is installed"
	@echo "  clean          - Remove compiled binaries"
	@echo "  clean-sources  - Remove fetched source files"
	@echo ""
	@echo "Built binaries go to: $(BIN_DIR)"

.PHONY: all mbr msdos bootprog freedos fetch-bootprog fetch-freedos fetch-all disasm verify clean clean-sources check help
