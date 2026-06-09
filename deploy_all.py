#!/usr/bin/env python3
"""
deploy_all.py — патч-скрипт для CentSDR (Eugene-HAM fork)

Изменения:
  1. ili9341.c  — поворот дисплея на 180°
  2. nanosdr.h  — убрать MOD_FM / MOD_FM_STEREO, добавить MOD_NFM
  3. dsp.c      — убрать fm_demod_stereo, добавить nfm_demod()
  4. main.c     — обновить mod_table[], cmd_mode(), каналы по умолчанию

Использование:
  python3 deploy_all.py          # применить все патчи
  python3 deploy_all.py --check  # только проверить, без изменений
"""

import os, sys, re

# ─────────────────────────────────────────────
# Вспомогательные функции
# ─────────────────────────────────────────────

def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"  ✓ записан: {path}")

def patch(path, old, , description=""):
    text = read(path)
    if old not in text:
        print(f"  ✗ [{path}] не найдено: {description or repr(old[:60])}")
        return False
    if  in text:
        print(f"  ~ [{path}] уже применено: {description or repr(old[:60])}")
        return True
    write(path, text.replace(old, , 1))
    print(f"  ✓ [{path}] применён патч: {description}")
    return True

CHECK_ONLY = "--check" in sys.argv

# ─────────────────────────────────────────────
# ПАТЧ 1: ili9341.c — поворот на 180°
# ─────────────────────────────────────────────
print("\n[1/4] ili9341.c — поворот дисплея на 180°")

# 1a. Байт инициализации MADCTL в init_seq
patch("ili9341.c",
    old="0x36, 1, 0x28, // landscape",
    new="0x36, 1, 0xE8, // landscape 180° (MY+MX+BGR)",
    description="MADCTL byte в init_seq"
)

# 1b. Функция ili9341_set_direction()
patch("ili9341.c",
    old="""void
ili9341_set_direction(int rot180)
{
\tchar value = 0x28; // landscape
\tif (rot180) {
\t\tvalue |= 0xc0; // reverse X and Y axis
\t}
\tsend_command(0x36, 1, &value);
}""",
    new="""void
ili9341_set_direction(int rot180)
{
\tchar value = 0xE8; // landscape 180° (default)
\tif (!rot180) {
\t\tvalue = 0x28; // landscape normal
\t}
\tsend_command(0x36, 1, &value);
}""",
    description="ili9341_set_direction()"
)

# ─────────────────────────────────────────────
# ПАТЧ 2: nanosdr.h — убрать FM, добавить NFM
# ─────────────────────────────────────────────
print("\n[2/4] nanosdr.h — MOD_FM/MOD_FM_STEREO → MOD_NFM")

patch("nanosdr.h",
    old="""typedef enum {
  MOD_CW,
  MOD_LSB,
  MOD_USB,
  MOD_AM,
  MOD_FM,
  MOD_FM_STEREO,
  MOD_MAX
} modulation_t;""",
    new="""typedef enum {
  MOD_CW,
  MOD_LSB,
  MOD_USB,
  MOD_AM,
  MOD_NFM,   // Narrow FM, полоса ±5 кГц (10 кГц)
  MOD_MAX
} modulation_t;""",
    description="enum modulation_t"
)

patch("nanosdr.h",
    old="void fm_demod(int16_t *src, int16_t *dst, size_t len);\nvoid fm_demod_stereo(int16_t *src, int16_t *dst, size_t len);",
    new="void nfm_demod(int16_t *src, int16_t *dst, size_t len);",
    description="объявления функций демодуляторов"
)

# ─────────────────────────────────────────────
# ПАТЧ 3: dsp.c — убрать FM stereo, добавить NFM
# ─────────────────────────────────────────────
print("\n[3/4] dsp.c — nfm_demod()")

# 3a. Добавить nfm_demod() и убрать stereo_separate_init()
patch("dsp.c",
    old="""void
dsp_init(void)
{
\tstereo_separate_init();
}""",
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
    description="добавить nfm_demod() + убрать stereo_separate_init()"
)

# ─────────────────────────────────────────────
# ПАТЧ 4: main.c — mod_table, каналы, команды
# ─────────────────────────────────────────────
print("\n[4/4] main.c — mod_table[], каналы, shell-команды")

# 4a. mod_table
patch("main.c",
    old="""} mod_table[] = {
\t{ cw_demod,        AM_FREQ_OFFSET, 48,  "cw"  },
\t{ lsb_demod,       0,              48,  "lsb" },
\t{ usb_demod,       0,              48,  "usb" },
\t{ am_demod,        AM_FREQ_OFFSET, 48,  "am"  },
\t{ fm_demod,        0,              192, "fm"  },
\t{ fm_demod_stereo, 0,              192, "fms" },
};""",
    new="""} mod_table[] = {
\t{ cw_demod,  AM_FREQ_OFFSET, 48, "cw"  },
\t{ lsb_demod, 0,              48, "lsb" },
\t{ usb_demod, 0,              48, "usb" },
\t{ am_demod,  AM_FREQ_OFFSET, 48, "am"  },
\t{ nfm_demod, 0,              48, "nfm" }, // Narrow FM ±5 kHz
};""",
    description="mod_table[]"
)

# 4b. Предустановленные каналы — убрать MOD_FM_STEREO
patch("main.c",
    old="""\t\t{ 26800200, MOD_FM_STEREO },
\t\t{ 27500200, MOD_FM_STEREO },
\t\t{ 28400200, MOD_FM_STEREO },""",
    new="""\t\t{ 145000000, MOD_NFM },  // 2m amateur band
\t\t{ 433500000, MOD_NFM },  // 70cm amateur band
\t\t{ 162550000, MOD_NFM },  // weather broadcast""",
    description="предустановленные каналы"
)

# 4c. cmd_mode() — shell команды
patch("main.c",
    old="""\t} else if (strncmp(cmd, "fms", 3) == 0) {
\t\tset_modulation(MOD_FM_STEREO);
\t} else if (strncmp(cmd, "fm", 1) == 0) {
\t\tset_modulation(MOD_FM);
\t}""",
    new="""\t} else if (strncmp(cmd, "nfm", 1) == 0) {
\t\tset_modulation(MOD_NFM);
\t}""",
    description="cmd_mode() shell handler"
)

# 4d. Обновить help-строку
patch("main.c",
    old='\tchprintf(chp, "usage: mode {lsb|usb|am|fm|fms}\\r\\n");',
    new='\tchprintf(chp, "usage: mode {cw|lsb|usb|am|nfm}\\r\\n");',
    description="help-строка cmd_mode()"
)

# 4e. Убрать строки stat про FM stereo
patch("main.c",
    old='\tchprintf(chp, "fm stereo: %d %d\\r\\n", stereo_separate_state.sdi, stereo_separate_state.sdq);\n'
        '\tchprintf(chp, " corr: %d %d %d\\r\\n", stereo_separate_state.corr, stereo_separate_state.corr_ave, stereo_separate_state.corr_std);\n'
        '\tchprintf(chp, " int: %d\\r\\n", stereo_separate_state.integrator);',
    new='\t/* FM stereo state removed */',
    description="убрать вывод fm stereo stat"
)

print("\n✅ Все патчи обработаны.")
print("Запусти 'make' для сборки прошивки.")
