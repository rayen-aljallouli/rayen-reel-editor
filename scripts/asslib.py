"""ASS subtitle helpers shared by captions.py and render.py.

All on-screen text goes through libass (ffmpeg's `ass` filter): HarfBuzz shapes Arabic
correctly (joined letters) and FriBidi orders mixed Arabic/English lines. Two settings make
right-to-left lines come out in the right order:
  * Encoding -1 in the style  -> libass detects the base direction instead of forcing LTR
  * an RLM (U+200F) at the start of every RTL line -> a line that starts with an English
    word ("Claude Code ...") still reads right-to-left
"""
from __future__ import annotations

import re
import shutil
import struct
from pathlib import Path

from common import FONTS_DIR, H, W

RTL_CHARS = re.compile(r"[֐-ࣿיִ-﷿ﹰ-﻿]")
LATIN_CHARS = re.compile(r"[A-Za-z0-9À-ɏ]")
RLM = "‏"

FONT_FILES = {
    "Tajawal ExtraBold": FONTS_DIR / "Tajawal-ExtraBold.ttf",
    "Tajawal Bold": FONTS_DIR / "Tajawal-Bold.ttf",
}


def is_rtl(text: str) -> bool:
    return bool(RTL_CHARS.search(text))


def is_latin_only(text: str) -> bool:
    return bool(LATIN_CHARS.search(text)) and not RTL_CHARS.search(text)


def color(hex_rgb: str, alpha: int = 0) -> str:
    """'#E9C46A' -> '&H006AC4E9' (ASS is AABBGGRR, alpha 0 = opaque)."""
    h = hex_rgb.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ts(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def clean(text: str) -> str:
    """Make arbitrary text safe inside an ASS event."""
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ")


def header(styles: list[str]) -> str:
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        *styles, "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]) + "\n"


def style(name: str, font: str, size: float, primary: str, outline: str, back: str, outline_w: float, shadow: float,
          align: int, ml: int, mr: int, mv: int, border_style: int = 1) -> str:
    # Encoding -1: automatic base direction in libass (needed for RTL lines)
    return (f"Style: {name},{font},{size:g},{primary},{primary},{outline},{back},0,0,0,0,100,100,0,0,"
            f"{border_style},{outline_w:g},{shadow:g},{align},{ml},{mr},{mv},-1")


def event(start: float, end: float, style_name: str, text: str, layer: int = 0) -> str:
    return f"Dialogue: {layer},{ts(start)},{ts(end)},{style_name},,0,0,0,,{text}"


# ----------------------------------------------------------------------------- measuring
def _font_metrics(path: Path) -> tuple[int, int, int]:
    """(unitsPerEm, winAscent, winDescent): libass sizes a font so that winAscent+winDescent = Fontsize."""
    d = path.read_bytes()
    n = struct.unpack(">H", d[4:6])[0]
    tables = {}
    for i in range(n):
        tag, _, off, ln = struct.unpack(">4sIII", d[12 + 16 * i: 28 + 16 * i])
        tables[tag] = off
    upem = struct.unpack(">H", d[tables[b"head"] + 18: tables[b"head"] + 20])[0]
    o = tables.get(b"OS/2")
    if o is not None:
        wa, wd = struct.unpack(">HH", d[o + 74: o + 78])
    else:
        hh = tables[b"hhea"]
        wa, wd = struct.unpack(">hh", d[hh + 4: hh + 8])
        wd = -wd
    return upem, wa, wd


class Measure:
    """Approximate rendered width of a string in ASS pixels (PlayRes 1080x1920)."""

    def __init__(self, font_file: Path):
        from PIL import ImageFont
        self.ImageFont = ImageFont
        self.path = font_file
        upem, wa, wd = _font_metrics(font_file)
        self.em_ratio = upem / float(wa + wd)
        try:
            from PIL import features
            self.engine = ImageFont.Layout.RAQM if features.check("raqm") else ImageFont.Layout.BASIC
        except Exception:  # noqa: BLE001
            self.engine = ImageFont.Layout.BASIC
        self.cache = {}

    def font(self, size: float):
        px = max(4, int(round(size * self.em_ratio)))
        if px not in self.cache:
            self.cache[px] = self.ImageFont.truetype(str(self.path), px, layout_engine=self.engine)
        return self.cache[px]

    def width(self, text: str, size: float) -> float:
        return float(self.font(size).getlength(text))


def install_fonts(edit: Path, extra: list[Path] | None = None) -> Path:
    """Copy the bundled fonts (and any user font files) to <edit>/.fonts for the ass filter's fontsdir."""
    d = edit / ".fonts"
    d.mkdir(exist_ok=True)
    for f in list(FONTS_DIR.glob("*.ttf")) + list(FONTS_DIR.glob("*.otf")) + list(extra or []):
        dst = d / f.name
        if not dst.exists() or dst.stat().st_size != f.stat().st_size:
            shutil.copy2(f, dst)
    return d
