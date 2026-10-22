#!/usr/bin/env python3
"""
tools/app2elf.py - Reconstruct loadable RISC-V 32-bit ELF from ESP32-C3 firmware image.
"""
import sys, struct, os

def convert_esp_to_elf(bin_path, elf_path):
    with open(bin_path, 'rb') as f:
        data = f.read()

    magic = data[0]
    if magic != 0xE9:
        raise ValueError(f"Invalid image magic: 0x{magic:02X} (expected 0xE9)")

    seg_count = data[1]
    entry = struct.unpack('<I', data[4:8])[0]
    
    segments = []
    off = 24
    for s in range(seg_count):
        load_addr, seg_len = struct.unpack('<II', data[off:off+8])
        off += 8
        seg_data = data[off:off+seg_len]
        segments.append((load_addr, seg_len, seg_data))
        off += seg_len

    # Name segments based on ESP32-C3 memory map
    # 0x3C000000 - 0x3C800000: DROM (.flash.rodata)
    # 0x3FC80000 - 0x3FCE0000: DRAM (.dram0.data)
    # 0x4037C000 - 0x40390000: IRAM (.iram0.text)
    # 0x42000000 - 0x42800000: IROM (.flash.text)
    # 0x50000000 - 0x50002000: RTC (.rtc.text)
    
    sec_names = []
    sec_flags = []
    ph_flags = []
    for load_addr, seg_len, _ in segments:
        if 0x3C000000 <= load_addr < 0x3D000000:
            sec_names.append(".flash.rodata")
            sec_flags.append(0x02) # SHF_ALLOC
            ph_flags.append(0x04)  # PF_R
        elif 0x3FC00000 <= load_addr < 0x3FD00000:
            sec_names.append(".dram0.data")
            sec_flags.append(0x03) # SHF_WRITE | SHF_ALLOC
            ph_flags.append(0x06)  # PF_R | PF_W
        elif 0x42000000 <= load_addr < 0x43000000:
            sec_names.append(".flash.text")
            sec_flags.append(0x06) # SHF_ALLOC | SHF_EXECINSTR
            ph_flags.append(0x05)  # PF_R | PF_X
        elif 0x40370000 <= load_addr < 0x403A0000:
            sec_names.append(f".iram.text.{load_addr:08x}")
            sec_flags.append(0x06) # SHF_ALLOC | SHF_EXECINSTR
            ph_flags.append(0x07)  # PF_R | PF_W | PF_X
        elif 0x50000000 <= load_addr < 0x50010000:
            sec_names.append(".rtc.data")
            sec_flags.append(0x03)
            ph_flags.append(0x06)
        else:
            sec_names.append(f".seg_{load_addr:08x}")
            sec_flags.append(0x07)
            ph_flags.append(0x07)

    # Build section name string table (.shstrtab)
    shstrtab = b"\x00"
    sec_name_offsets = []
    for name in sec_names:
        sec_name_offsets.append(len(shstrtab))
        shstrtab += name.encode('ascii') + b"\x00"
    shstrtab_offset_in_shstrtab = len(shstrtab)
    shstrtab += b".shstrtab\x00"

    # Layout:
    # 0x00: ELF Header (52 bytes)
    # 0x34: Program Headers (seg_count * 32 bytes)
    # 0x34 + seg_count * 32: padded to align
    ehdr_size = 52
    phdr_size = 32
    shdr_size = 40
    
    phoff = ehdr_size
    first_seg_offset = (phoff + seg_count * phdr_size + 15) & ~15
    
    seg_offsets = []
    current_off = first_seg_offset
    for _, seg_len, _ in segments:
        current_off = (current_off + 15) & ~15
        seg_offsets.append(current_off)
        current_off += seg_len
        
    shstrtab_file_offset = (current_off + 15) & ~15
    current_off = shstrtab_file_offset + len(shstrtab)
    
    shoff = (current_off + 15) & ~15
    total_sections = 1 + seg_count + 1 # null + segments + shstrtab
    
    # ELF Header
    # e_ident: 16 bytes
    e_ident = b'\x7FELF\x01\x01\x01\x00' + b'\x00' * 8
    e_type = 2      # ET_EXEC
    e_machine = 243 # EM_RISCV
    e_version = 1
    e_entry = entry
    e_phoff = phoff
    e_shoff = shoff
    e_flags = 0x00000005 # EF_RISCV_RVC | EF_RISCV_FLOAT_ABI_SOFT
    e_ehsize = ehdr_size
    e_phentsize = phdr_size
    e_phnum = seg_count
    e_shentsize = shdr_size
    e_shnum = total_sections
    e_shstrndx = total_sections - 1

    ehdr = struct.pack('<16sHHIIIIIHHHHHH',
        e_ident, e_type, e_machine, e_version,
        e_entry, e_phoff, e_shoff, e_flags,
        e_ehsize, e_phentsize, e_phnum,
        e_shentsize, e_shnum, e_shstrndx)

    # Program Headers
    phdrs = b""
    for i, (load_addr, seg_len, _) in enumerate(segments):
        p_type = 1 # PT_LOAD
        p_offset = seg_offsets[i]
        p_vaddr = load_addr
        p_paddr = load_addr
        p_filesz = seg_len
        p_memsz = seg_len
        p_flags = ph_flags[i]
        p_align = 0x1000
        phdrs += struct.pack('<IIIIIIII',
            p_type, p_offset, p_vaddr, p_paddr,
            p_filesz, p_memsz, p_flags, p_align)

    # Section Headers
    # 0: NULL section
    shdrs = b"\x00" * shdr_size
    for i, (load_addr, seg_len, _) in enumerate(segments):
        sh_name = sec_name_offsets[i]
        sh_type = 1 # SHT_PROGBITS
        sh_flags = sec_flags[i]
        sh_addr = load_addr
        sh_offset = seg_offsets[i]
        sh_size = seg_len
        sh_link = 0
        sh_info = 0
        sh_addralign = 4
        sh_entsize = 0
        shdrs += struct.pack('<IIIIIIIIII',
            sh_name, sh_type, sh_flags, sh_addr,
            sh_offset, sh_size, sh_link, sh_info,
            sh_addralign, sh_entsize)

    # Section header for .shstrtab
    shdrs += struct.pack('<IIIIIIIIII',
        shstrtab_offset_in_shstrtab, 3, 0, 0, # SHT_STRTAB
        shstrtab_file_offset, len(shstrtab), 0, 0,
        1, 0)

    # Assemble ELF file
    elf = bytearray(shoff + total_sections * shdr_size)
    elf[0:ehdr_size] = ehdr
    elf[phoff:phoff + len(phdrs)] = phdrs
    for i, (_, _, seg_data) in enumerate(segments):
        off = seg_offsets[i]
        elf[off:off + len(seg_data)] = seg_data
    elf[shstrtab_file_offset:shstrtab_file_offset + len(shstrtab)] = shstrtab
    elf[shoff:shoff + len(shdrs)] = shdrs

    with open(elf_path, 'wb') as f:
        f.write(elf)

    print(f"Reconstructed valid RISC-V ELF at {elf_path} ({len(elf)} bytes)")
    print(f"Entry point: 0x{entry:08X}, Sections: {total_sections}, Segments: {seg_count}")

if __name__ == '__main__':
    src = sys.argv[1] if len(sys.argv) > 1 else 'work/parts/ota_1.bin'
    dst = sys.argv[2] if len(sys.argv) > 2 else 'work/elf/app_active.elf'
    convert_esp_to_elf(src, dst)
