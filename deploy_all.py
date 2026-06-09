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

import os, sys

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

# ─────────────────────────────────────────────
# PATCH 1: ili9341.c - rotate 180 degrees
# ─────────────────────────────────────────────
print("\n[1/4] ili9341.c - rotate display 180 degrees")

patch("ili9341.c",
    old="0x36, 1, 0x28, // landscape",
    new="0x36, 1, 0xE8, // landscape 180 degrees (MY+MX+BGR)",
    description="MADCTL byte in init_seq"
)

patch("ili9341.c",
    old="void\nili9341_set_direction(int rot180)\n{\n\tchar value = 0x28; // landscape\n\tif (rot180) {\n\t\tvalue |= 0xc0; // reverse X and Y axis\n\t}\n\tsend_command(0x36, 1, &value);\n}",
    new="void\nili9341_set_direction(int rot180)\n{\n\tuint8_t value = 0xE8; // landscape 180 degrees (default)\n\tif (!rot180) {\n\t\tvalue = 0x28; // landscape normal\n\t}\n\tsend_command(0x36, 1, &value);\n}",
    description="ili9341_set_direction()"
)

# ─────────────────────────────────────────────
# PATCH 2: nanosdr.h - remove FM, add NFM
# ─────────────────────────────────────────────
print("\n[2/4] nanosdr.h - MOD_FM/MOD_FM_STEREO -> MOD_NFM")

patch("nanosdr.h",
    old="typedef enum {\n  MOD_CW,\n  MOD_LSB,\n  MOD_USB,\n  MOD_AM,\n  MOD_FM,\n  MOD_FM_STEREO,\n  MOD_MAX\n} modulation_t;",
    new="typedef enum {\n  MOD_CW,\n  MOD_LSB,\n  MOD_USB,\n  MOD_AM,\n  MOD_NFM,\n  MOD_MAX\n} modulation_t;",
    description="enum modulation_t"
)

patch("nanosdr.h",
    old="void fm_demod(int16_t *src, int16_t *dst, size_t len);\nvoid fm_demod_stereo(int16_t *src, int16_t *dst, size_t len);",
    new="void nfm_demod(int16_t *src, int16_t *dst, size_t len);",
    description="demodulator function declarations"
)

# ─────────────────────────────────────────────
# PATCH 3: dsp.c - add nfm_demod()
# ─────────────────────────────────────────────
print("\n[3/4] dsp.c - add nfm_demod()")

patch("dsp.c",
    old="void\ndsp_init(void)\n{\n\tstereo_separate_init();\n}",
    new="""// NFM filter state (zero-initialized by BSS)
static q15_t bq_nfm_state[4 * 3];

// Elliptic LPF 6th order, fc=5000 Hz @ fs=48000 Hz, stopband 60 dB
static q15_t bq_coeffs_nfm[] = {
    2271,  0, -3132,  2271, 25663, -11568,
    9849,  0, -16121, 9849, 26986, -13909,
   16384,  0, -26655,16384, 28887, -15349
};

static arm_biquad_casd_df1_inst_q15 bq_nfm = {
    3, bq_nfm_state, bq_coeffs_nfm, 1
};

void
nfm_demod(int16_t *src, int16_t *dst, size_t len)
{
    int32_t  *s   = __SIMD32(src);
    int32_t  *d32 = __SIMD32(dst);
    unsigned  i;
    uint32_t  x0  = fm_demod_state.last;
    q15_t     v;

    disp_fetch_samples(B_CAPTURE, BT_C_INTERLEAVE, src, NULL, len);

    for (i = 0; i < len; i += 2) {
        uint32_t x1 = *s++;
        v = atan_2iq(x0, x1);
        *d32++ = __PKHBT(v, v, 16);
        x0 = x1;
    }
    fm_demod_state.last = x0;

    disp_fetch_samples(B_IF1, BT_R_INTERLEAVE, dst, NULL, len);

    arm_biquad_cascade_df1_q15(&bq_nfm, dst, dst, len / 2);

    disp_fetch_samples(B_PLAYBACK, BT_R_INTERLEAVE, dst, NULL, len);
}

void
dsp_init(void)
{
}""",
    description="add nfm_demod() and remove stereo_separate_init()"
)

# ─────────────────────────────────────────────
# PATCH 4: main.c - mod_table, channels, commands
# ─────────────────────────────────────────────
print("\n[4/4] main.c - mod_table[], channels, shell commands")

# 4a. mod_table
patch("main.c",
    old="} mod_table[] = {\n\t{ cw_demod,        AM_FREQ_OFFSET, 48,  \"cw\"  },\n\t{ lsb_demod,       0,              48,  \"lsb\" },\n\t{ usb_demod,       0,              48,  \"usb\" },\n\t{ am_demod,        AM_FREQ_OFFSET, 48,  \"am\"  },\n\t{ fm_demod,        0,              192, \"fm\"  },\n\t{ fm_demod_stereo, 0,              192, \"fms\" },\n};",
    new="} mod_table[] = {\n\t{ cw_demod,  AM_FREQ_OFFSET, 48, \"cw\"  },\n\t{ lsb_demod, 0,              48, \"lsb\" },\n\t{ usb_demod, 0,              48, \"usb\" },\n\t{ am_demod,  AM_FREQ_OFFSET, 48, \"am\"  },\n\t{ nfm_demod, 0,              48, \"nfm\" },\n};",
    description="mod_table[]"
)

# 4b. Default channels - remove MOD_FM_STEREO
patch("main.c",
    old="\t\t{ 26800200, MOD_FM_STEREO },\n\t\t{ 27500200, MOD_FM_STEREO },\n\t\t{ 28400200, MOD_FM_STEREO },",
    new="\t\t{ 145000000, MOD_NFM },\n\t\t{ 433500000, MOD_NFM },\n\t\t{ 162550000, MOD_NFM },",
    description="default channels"
)

# 4c. cmd_mode() shell commands
patch("main.c",
    old="\t} else if (strncmp(cmd, \"fms\", 3) == 0) {\n\t\tset_modulation(MOD_FM_STEREO);\n\t} else if (strncmp(cmd, \"fm\", 1) == 0) {\n\t\tset_modulation(MOD_FM);\n\t}",
    new="\t} else if (strncmp(cmd, \"nfm\", 1) == 0) {\n\t\tset_modulation(MOD_NFM);\n\t}",
    description="cmd_mode() shell handler"
)

# 4d. Update help string
patch("main.c",
    old="\tchprintf(chp, \"usage: mode {lsb|usb|am|fm|fms}\\r\\n\");",
    new="\tchprintf(chp, \"usage: mode {cw|lsb|usb|am|nfm}\\r\\n\");",
    description="cmd_mode() help string"
)

# 4e. Remove FM stereo stat output
patch("main.c",
    old="\tchprintf(chp, \"fm stereo: %d %d\\r\\n\", stereo_separate_state.sdi, stereo_separate_state.sdq);\n\tchprintf(chp, \" corr: %d %d %d\\r\\n\", stereo_separate_state.corr, stereo_separate_state.corr_ave, stereo_separate_state.corr_std);\n\tchprintf(chp, \" int: %d\\r\\n\", stereo_separate_state.integrator);",
    new="\t/* FM stereo removed */",
    description="remove fm stereo stat output"
)

print("\nAll patches processed.")
print("Run 'make' to build firmware.")
