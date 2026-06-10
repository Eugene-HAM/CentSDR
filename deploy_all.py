#!/usr/bin/env python3
"""
deploy_all.py - patch script for CentSDR (Eugene-HAM fork)

Changes:
  1. ili9341.c  - rotate display 180 degrees
  2. nanosdr.h  - remove MOD_FM / MOD_FM_STEREO, add MOD_NFM
  3. dsp.c      - add nfm_demod(), remove stereo_separate_init()
  4. main.c     - update mod_table[], cmd_mode(), default channels

Usage:
  python3 deploy_all.py
"""

import sys
import re

def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print("  OK written: " + path)

def patch(path, old, new, description=""):
    text = read(path)
    if old not in text:
        print("  SKIP [" + path + "] not found: " + (description or old[:60]))
        return False
    if new in text:
        print("  ALREADY [" + path + "] already applied: " + (description or old[:60]))
        return True
    write(path, text.replace(old, new, 1))
    print("  PATCHED [" + path + "]: " + description)
    return True

def patch_re(path, pattern, new, description="", already_marker=None):
    """Patch using regex. already_marker is a string to detect if already applied."""
    text = read(path)
    if already_marker and already_marker in text:
        print("  ALREADY [" + path + "] already applied: " + description)
        return True
    result, count = re.subn(pattern, new, text, count=1, flags=re.DOTALL)
    if count == 0:
        print("  SKIP [" + path + "] regex not found: " + description)
        return False
    write(path, result)
    print("  PATCHED [" + path + "]: " + description)
    return True

# ─────────────────────────────────────────────
# PATCH 1: ili9341.c - rotate 180 degrees
# ─────────────────────────────────────────────
print("\n[1/4] ili9341.c - rotate display 180 degrees")

patch("ili9341.c",
    old="0x36, 1, 0x28, // landscape",
    new="0x36, 1, 0xE8, // landscape 180 degrees (MY+MX+BGR)",
    description="MADCTL byte in init_seq"
)

# Use regex to handle any whitespace variation in ili9341_set_direction
patch_re("ili9341.c",
    pattern=r"void\s*\nili9341_set_direction\(int rot180\)\s*\{[^}]*\}",
    new=(
        "void\n"
        "ili9341_set_direction(int rot180)\n"
        "{\n"
        "\tuint8_t value = 0xE8; // landscape 180 degrees (default)\n"
        "\tif (!rot180) {\n"
        "\t\tvalue = 0x28; // landscape normal\n"
        "\t}\n"
        "\tsend_command(0x36, 1, &value);\n"
        "}"
    ),
    description="ili9341_set_direction()",
    already_marker="landscape 180 degrees (default)"
)

# ─────────────────────────────────────────────
# PATCH 2: nanosdr.h - remove FM, add NFM
# ─────────────────────────────────────────────
print("\n[2/4] nanosdr.h - MOD_FM/MOD_FM_STEREO -> MOD_NFM")

patch_re("nanosdr.h",
    pattern=r"typedef enum \{[^}]*MOD_FM_STEREO,[^}]*\} modulation_t;",
    new=(
        "typedef enum {\n"
        "  MOD_CW,\n"
        "  MOD_LSB,\n"
        "  MOD_USB,\n"
        "  MOD_AM,\n"
        "  MOD_NFM,\n"
        "  MOD_MAX\n"
        "} modulation_t;"
    ),
    description="enum modulation_t",
    already_marker="MOD_NFM"
)

patch_re("nanosdr.h",
    pattern=r"void fm_demod\(int16_t \*src, int16_t \*dst, size_t len\);\s*\nvoid fm_demod_stereo\(int16_t \*src, int16_t \*dst, size_t len\);",
    new="void nfm_demod(int16_t *src, int16_t *dst, size_t len);",
    description="demodulator function declarations",
    already_marker="nfm_demod"
)

# ─────────────────────────────────────────────
# PATCH 3: dsp.c - add nfm_demod()
# ─────────────────────────────────────────────
print("\n[3/4] dsp.c - add nfm_demod()")

patch_re("dsp.c",
    pattern=r"void\s*\ndsp_init\(void\)\s*\{\s*\nstereo_separate_init\(\);\s*\n\}",
    new=(
        "// NFM filter state (zero-initialized by BSS)\n"
        "static q15_t bq_nfm_state[4 * 3];\n"
        "\n"
        "// Elliptic LPF 6th order, fc=5000 Hz @ fs=48000 Hz, stopband 60 dB\n"
        "static q15_t bq_coeffs_nfm[] = {\n"
        "    2271,  0, -3132,  2271, 25663, -11568,\n"
        "    9849,  0, -16121, 9849, 26986, -13909,\n"
        "   16384,  0, -26655,16384, 28887, -15349\n"
        "};\n"
        "\n"
        "static arm_biquad_casd_df1_inst_q15 bq_nfm = {\n"
        "    3, bq_nfm_state, bq_coeffs_nfm, 1\n"
        "};\n"
        "\n"
        "void\n"
        "nfm_demod(int16_t *src, int16_t *dst, size_t len)\n"
        "{\n"
        "    int32_t  *s   = __SIMD32(src);\n"
        "    int32_t  *d32 = __SIMD32(dst);\n"
        "    unsigned  i;\n"
        "    uint32_t  x0  = fm_demod_state.last;\n"
        "    q15_t     v;\n"
        "\n"
        "    disp_fetch_samples(B_CAPTURE, BT_C_INTERLEAVE, src, NULL, len);\n"
        "\n"
        "    for (i = 0; i < len; i += 2) {\n"
        "        uint32_t x1 = *s++;\n"
        "        v = atan_2iq(x0, x1);\n"
        "        *d32++ = __PKHBT(v, v, 16);\n"
        "        x0 = x1;\n"
        "    }\n"
        "    fm_demod_state.last = x0;\n"
        "\n"
        "    disp_fetch_samples(B_IF1, BT_R_INTERLEAVE, dst, NULL, len);\n"
        "\n"
        "    arm_biquad_cascade_df1_q15(&bq_nfm, dst, dst, len / 2);\n"
        "\n"
        "    disp_fetch_samples(B_PLAYBACK, BT_R_INTERLEAVE, dst, NULL, len);\n"
        "}\n"
        "\n"
        "void\n"
        "dsp_init(void)\n"
        "{\n"
        "}"
    ),
    description="add nfm_demod() and remove stereo_separate_init()",
    already_marker="nfm_demod"
)

# ─────────────────────────────────────────────
# PATCH 4: main.c - mod_table, channels, commands
# ─────────────────────────────────────────────
print("\n[4/4] main.c - mod_table[], channels, shell commands")

# 4a. mod_table - regex handles any whitespace/alignment between fields
patch_re("main.c",
    pattern=(
        r"\} mod_table\[\] = \{\s*\n"
        r"\s*\{ cw_demod,\s+AM_FREQ_OFFSET,\s+48,\s+\"cw\"\s*\},\s*\n"
        r"\s*\{ lsb_demod,\s+0,\s+48,\s+\"lsb\"\s*\},\s*\n"
        r"\s*\{ usb_demod,\s+0,\s+48,\s+\"usb\"\s*\},\s*\n"
        r"\s*\{ am_demod,\s+AM_FREQ_OFFSET,\s+48,\s+\"am\"\s*\},\s*\n"
        r"\s*\{ fm_demod,\s+0,\s+192,\s+\"fm\"\s*\},\s*\n"
        r"\s*\{ fm_demod_stereo,\s+0,\s+192,\s+\"fms\"\s*\},\s*\n"
        r"\};"
    ),
    new=(
        '} mod_table[] = {\n'
        '  { cw_demod,  AM_FREQ_OFFSET, 48, "cw"  },\n'
        '  { lsb_demod, 0,              48, "lsb" },\n'
        '  { usb_demod, 0,              48, "usb" },\n'
        '  { am_demod,  AM_FREQ_OFFSET, 48, "am"  },\n'
        '  { nfm_demod, 0,              48, "nfm" },\n'
        '};'
    ),
    description="mod_table[]",
    already_marker='nfm_demod, 0,              48, "nfm"'
)

# 4b. Default channels - regex handles any whitespace
patch_re("main.c",
    pattern=(
        r"\{ 26800200,\s+MOD_FM_STEREO \},\s*\n"
        r"\s*\{ 27500200,\s+MOD_FM_STEREO \},\s*\n"
        r"\s*\{ 28400200,\s+MOD_FM_STEREO \},"
    ),
    new=(
        "{ 145000000, MOD_NFM },\n"
        "\t\t{ 433500000, MOD_NFM },\n"
        "\t\t{ 162550000, MOD_NFM },"
    ),
    description="default channels",
    already_marker="145000000, MOD_NFM"
)

# 4c. cmd_mode() shell commands
patch_re("main.c",
    pattern=(
        r'\} else if \(strncmp\(cmd, "fms", 3\) == 0\) \{\s*\n'
        r'\s*set_modulation\(MOD_FM_STEREO\);\s*\n'
        r'\s*\} else if \(strncmp\(cmd, "fm", 1\) == 0\) \{\s*\n'
        r'\s*set_modulation\(MOD_FM\);\s*\n'
        r'\s*\}'
    ),
    new=(
        '} else if (strncmp(cmd, "nfm", 1) == 0) {\n'
        '\t\tset_modulation(MOD_NFM);\n'
        '\t}'
    ),
    description="cmd_mode() shell handler",
    already_marker='strncmp(cmd, "nfm"'
)

# 4d. Update help string
patch("main.c",
    old='\tchprintf(chp, "usage: mode {lsb|usb|am|fm|fms}\\r\\n");',
    new='\tchprintf(chp, "usage: mode {cw|lsb|usb|am|nfm}\\r\\n");',
    description="cmd_mode() help string"
)

# 4e. Remove FM stereo stat output
patch_re("main.c",
    pattern=(
        r'\tchprintf\(chp, "fm stereo: %d %d\\r\\n",\s*stereo_separate_state\.sdi,\s*stereo_separate_state\.sdq\);\s*\n'
        r'\s*chprintf\(chp, " corr: %d %d %d\\r\\n",\s*stereo_separate_state\.corr,\s*stereo_separate_state\.corr_ave,\s*stereo_separate_state\.corr_std\);\s*\n'
        r'\s*chprintf\(chp, " int: %d\\r\\n",\s*stereo_separate_state\.integrator\);'
    ),
    new='\t/* FM stereo removed */',
    description="remove fm stereo stat output",
    already_marker="FM stereo removed"
)

print("\nAll patches processed.")
print("Run 'make' to build firmware.")
