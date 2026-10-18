"""Burned-in captions from timeline.json -> captions.ass (rendered LAST by render.py).

Styles
  karaoke  (default) the block shows dimmed, each word lights up when it is spoken,
           one keyword per block in the accent colour and a bit bigger
  plain    the whole block at once, keyword highlighted
  word     one word at a time, big

Chunking rules from real reels: at most 4 units / ~22 characters per block, break on
punctuation, on every cut and on pauses, never leave a function word ("في", "the") alone at
the end of a block, keep "الـ" glued to the Arabic word after it, keep consecutive English words
together ("Claude Code"). At most two lines, measured with the real font, inside the safe zone
(bottom edge y=1440, x between 230 and 850 by default).

Config: <edit>/captions.json (optional, every key also has a flag):
  {"style": "karaoke", "keywords": ["Claude Code", "مجاني"], "auto_keyword": true,
   "replace": {"wrong": "right"}, "at": {"12.34": "fixed word or empty to drop"},
   "hide": [[0.0, 2.5]], "size": 66, "key_size": 74, "accent": "#E9C46A", "color": "#FFFFFF",
   "bottom": 1440, "left": 230, "right": 850, "max_units": 4, "max_chars": 22, "upper": false}
  "at" keys are SOURCE times of the word (timeline.json "src"), so they survive re-cuts.
  Sizes are like CSS font sizes (em px at 1080x1920).

Usage:
    python captions.py <edit_dir> [--style karaoke|plain|word] [--keywords "a,b"] [--accent "#E9C46A"]
    python captions.py <edit_dir> --find "word"      # output times of a word, to time overlays/SFX
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from asslib import FONT_FILES, RLM, Measure, clean, color, event, header, is_latin_only, is_rtl, style
from common import SAFE_BOTTOM, SAFE_RIGHT, die, load_json

BREAK = (".", ",", "،", "؟", "?", "!", ":", "؛", ";", "…")
PUNCT = ".,،؛;:!؟?…\"'«»“”()[]"
FUNC = {
    # Tunisian Derja / Arabic
    "في", "على", "ما", "متاع", "متع", "باش", "ولا", "وإلا", "اللي", "إلي", "إذا", "شنو", "له", "لك", "لي", "من", "الـ",
    "حتى", "كان", "مع", "عن", "يا", "هو", "هي", "أنا", "إنت", "بش", "فال", "بال", "لل",
    # English / French / German
    "the", "a", "an", "to", "of", "and", "in", "on", "for", "is", "at", "or", "my", "your", "it",
    "le", "la", "les", "de", "des", "un", "une", "et", "à", "en", "der", "die", "das", "und", "ein", "zu",
}
DEFAULTS = {"style": "karaoke", "keywords": [], "auto_keyword": True, "replace": {}, "at": {}, "hide": [],
            "size": 66, "key_size": 74, "accent": "#E9C46A", "color": "#FFFFFF", "bottom": SAFE_BOTTOM,
            "left": 230, "right": SAFE_RIGHT, "max_units": 4, "max_chars": 22, "upper": False,
            "font": "Tajawal ExtraBold", "font_file": None}
DIM = r"\1a&H9E&\3a&HD0&\4a&HE6&"      # unlit word: ~38 % opacity
LIT = r"\1a&H00&\3a&H50&\4a&H90&"


def units_from_words(words: list[dict], cfg: dict) -> list[dict]:
    rep, at = cfg["replace"], {f"{float(k):.2f}": v for k, v in cfg["at"].items()}
    hide = cfg["hide"]
    out, prefix = [], None
    for w in words:
        if any(a <= w["start"] < b for a, b in hide):
            continue
        raw = w["text"].strip()
        brk = raw.endswith(BREAK)
        text = raw.strip(PUNCT).strip()
        key = f"{float(w.get('src', -1)):.2f}"
        if key in at:
            text = at[key]
        text = rep.get(text, text)
        if not text:
            if brk and out:
                out[-1]["brk"] = True
            continue
        start = w["start"]
        if text.endswith("ـ") and not brk:          # "الـ" waits for the next word
            prefix = {"text": text, "start": start, "end": w["end"], "cut": w["cut"]}
            continue
        if prefix:
            if is_latin_only(text) or prefix["cut"] != w["cut"]:   # Latin after الـ: own unit (bidi)
                out.append({**prefix, "brk": False})
            else:
                text, start = f"{prefix['text']} {text}", prefix["start"]
            prefix = None
        u = {"text": text, "start": start, "end": w["end"], "brk": brk, "cut": w["cut"]}
        prev = out[-1] if out else None
        if (prev and is_latin_only(text) and is_latin_only(prev["text"]) and not prev["brk"]
                and prev["cut"] == u["cut"] and len(prev["text"]) + len(text) < 24):
            prev.update(text=f"{prev['text']} {text}", end=u["end"], brk=brk)
            continue
        out.append(u)
    if prefix:
        out.append({**prefix, "brk": True})
    return out


def blocks_from_units(units: list[dict], cfg: dict) -> list[list[dict]]:
    blocks, cur = [], []
    mu, mc = int(cfg["max_units"]), int(cfg["max_chars"])
    for k, u in enumerate(units):
        cur.append(u)
        n = sum(len(x["text"]) for x in cur)
        nxt = units[k + 1] if k + 1 < len(units) else None
        edge = nxt is None or nxt["cut"] != u["cut"] or nxt["start"] - u["end"] > 0.6
        full = len(cur) >= mu or (nxt is not None and n + len(nxt["text"]) > mc)
        if u["brk"] or edge or full:
            carry = []
            if full and not u["brk"] and not edge:
                while len(cur) > 1 and cur[-1]["text"] in FUNC:
                    carry.insert(0, cur.pop())
            blocks.append(cur)
            cur = carry
    if cur:
        blocks.append(cur)
    return blocks


def pick_keyword(b: list[dict], cfg: dict) -> dict | None:
    for kw in cfg["keywords"]:
        for u in b:
            if kw.lower() in u["text"].lower():
                return u
    if not cfg["auto_keyword"]:
        return None
    cands = [u for u in b if u["text"] not in FUNC and len(u["text"]) > 2]
    return max(cands, key=lambda u: len(u["text"])) if cands else None


def layout(b: list[dict], key: dict | None, cfg: dict, meas: Measure, ass_size, ass_key) -> tuple[list[list[int]], float]:
    """Split a block into 1-2 lines that fit the box. Returns (lines as unit indexes, scale %)."""
    maxw = (cfg["right"] - cfg["left"]) * 0.96
    space = meas.width(" ", ass_size)
    widths = [meas.width(u["text"], ass_key if u is key else ass_size) for u in b]
    def line_w(ix):
        return sum(widths[i] for i in ix) + space * max(0, len(ix) - 1)
    idx = list(range(len(b)))
    if line_w(idx) <= maxw or len(b) == 1:
        lines = [idx]
    else:
        best = min(range(1, len(b)), key=lambda s: max(line_w(idx[:s]), line_w(idx[s:])))
        lines = [idx[:best], idx[best:]]
    widest = max(line_w(ln) for ln in lines)
    scale = 100.0 if widest <= maxw else max(60.0, 100.0 * maxw / widest)
    return lines, scale


def unit_text(u: dict, cfg: dict) -> str:
    t = clean(u["text"])
    return t.upper() if cfg["upper"] and is_latin_only(t) else t


def render_text(b, lines, key, lit_upto, cfg, ass_size, ass_key, scale, intro) -> str:
    acc, col = color(cfg["accent"]), color(cfg["color"])
    head = ""
    if scale < 99.9:
        head += f"\\fscx{scale:.0f}\\fscy{scale:.0f}"
    if intro:
        s0 = scale * 0.92
        head += f"\\fad(70,0)\\fscx{s0:.0f}\\fscy{s0:.0f}\\t(0,110,\\fscx{scale:.0f}\\fscy{scale:.0f})"
    rtl = any(is_rtl(u["text"]) for u in b)
    out = []
    for ln in lines:
        parts = []
        for i in ln:
            u = b[i]
            c = acc if u is key else col
            size = ass_key if u is key else ass_size
            a = LIT if i <= lit_upto else DIM
            parts.append(f"{{\\c{c}\\fs{size:.1f}{a}}}{unit_text(u, cfg)}")
        out.append((RLM if rtl else "") + " ".join(parts))
    return (f"{{{head}}}" if head else "") + "\\N".join(out)


def build(timeline: dict, cfg: dict) -> tuple[str, int]:
    font_file = Path(cfg["font_file"]) if cfg.get("font_file") else FONT_FILES.get(cfg["font"])
    if not font_file or not font_file.exists():
        die(f"font file for '{cfg['font']}' not found; pass font_file in captions.json")
    meas = Measure(font_file)
    ass_size = cfg["size"] / meas.em_ratio          # CSS-like size -> ASS Fontsize
    ass_key = cfg["key_size"] / meas.em_ratio
    st = style("Cap", cfg["font"], round(ass_size, 1), color(cfg["color"]), color("#000000", 0x50),
               color("#000000", 0x90), outline_w=4, shadow=3, align=2, ml=int(cfg["left"]),
               mr=int(1080 - cfg["right"]), mv=int(1920 - cfg["bottom"]))
    total = float(timeline["total"])
    units = units_from_words(timeline["words"], cfg)
    blocks = blocks_from_units(units, cfg)
    lines_out = []
    for bi, b in enumerate(blocks):
        start = max(0.0, b[0]["start"] - 0.05)
        nxt = blocks[bi + 1][0]["start"] - 0.05 if bi + 1 < len(blocks) else total
        end = nxt if nxt - b[-1]["end"] <= 0.9 else b[-1]["end"] + 0.5
        end = min(end, total)
        if end - start < 0.12:
            end = min(total, start + 0.12)
        key = pick_keyword(b, cfg)
        if cfg["style"] == "word":
            for k, u in enumerate(b):
                s = start if k == 0 else max(start, u["start"] - 0.03)
                e = end if k == len(b) - 1 else max(s + 0.05, b[k + 1]["start"] - 0.03)
                big = 1.35
                txt = render_text([u], [[0]], key if u is key else None, 0, cfg, ass_size * big, ass_key * big, 100, True)
                lines_out.append(event(s, e, "Cap", txt))
            continue
        lines, scale = layout(b, key, cfg, meas, ass_size, ass_key)
        if cfg["style"] == "plain":
            lines_out.append(event(start, end, "Cap", render_text(b, lines, key, len(b), cfg, ass_size, ass_key, scale, True)))
            continue
        # karaoke: one event per state, word k lit from its start
        times = [start] + [max(start, u["start"] - 0.03) for u in b[1:]] + [end]
        for k in range(len(b)):
            s, e = times[k], times[k + 1]
            if e - s < 0.01:
                continue
            lines_out.append(event(s, e, "Cap", render_text(b, lines, key, k, cfg, ass_size, ass_key, scale, k == 0)))
    return header([st]) + "\n".join(lines_out) + "\n", len(blocks)


def main() -> None:
    ap = argparse.ArgumentParser(description="timeline.json -> captions.ass (karaoke / plain / word)")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--style", choices=["karaoke", "plain", "word"])
    ap.add_argument("--keywords", help="comma-separated keywords to highlight (checked in order)")
    ap.add_argument("--accent")
    ap.add_argument("--size", type=float)
    ap.add_argument("--bottom", type=int, help="bottom edge of the caption block in px (default 1440)")
    ap.add_argument("--no-auto-keyword", action="store_true", help="only highlight listed keywords")
    ap.add_argument("--find", help="print output times of a word (to time overlays/SFX), then exit")
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()
    edit = args.edit_dir.expanduser().resolve()
    timeline = load_json(edit / "timeline.json")
    if not timeline:
        die(f"no timeline.json in {edit}; run build_cut.py first")
    if args.find:
        hits = [w for w in timeline["words"] if args.find.lower() in w["text"].lower()]
        for w in hits:
            print(f"{w['start']:7.2f}-{w['end']:6.2f}  cut {w['cut']:2d} {w['beat']:<10} src {w['src']:7.2f}  {w['text']}")
        print(f"{len(hits)} match(es) for '{args.find}' (output seconds)")
        return
    cfg = {**DEFAULTS, **(load_json(edit / "captions.json", {}) or {})}
    if args.style:
        cfg["style"] = args.style
    if args.keywords:
        cfg["keywords"] = [k.strip() for k in re.split(r"[,،]", args.keywords) if k.strip()]
    if args.accent:
        cfg["accent"] = args.accent
    if args.size:
        cfg["size"], cfg["key_size"] = args.size, args.size * 1.12
    if args.bottom:
        cfg["bottom"] = args.bottom
    if args.no_auto_keyword:
        cfg["auto_keyword"] = False
    if cfg["bottom"] > SAFE_BOTTOM or cfg["right"] > SAFE_RIGHT:
        print(f"warn: captions reach outside the safe zone (bottom {cfg['bottom']} > {SAFE_BOTTOM} "
              f"or right {cfg['right']} > {SAFE_RIGHT}); the app UI will cover them")
    ass, n = build(timeline, cfg)
    out = args.output or edit / "captions.ass"
    out.write_text(ass, encoding="utf-8")
    print(f"-> {out} ({n} blocks, style {cfg['style']})")


if __name__ == "__main__":
    main()
