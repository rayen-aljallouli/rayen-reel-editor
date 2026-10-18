"""Compose the reel: base.mp4 -> image/video overlays -> text overlays -> captions LAST -> + mix.wav.

One encode for the whole composite. Order matters: anything drawn after the captions would
hide them, so captions.ass is always the last filter.

Overlays live in <edit>/overlays.json (all times on the OUTPUT timeline, seconds):
  {"type": "text",  "text": "...", "start": 0.0, "end": 2.5, "style": "hook|title|pill|label",
   "x": 540, "y": 420, "accent_words": ["..."], "anim": "pop|fade|slide|none", "sfx": "whoosh"}
  {"type": "image", "file": "logo.png", "start": 3.0, "end": 6.0, "x": 540, "y": 500, "width": 360,
   "anim": "pop|fade|none", "sfx": "pop"}
  {"type": "video", "file": "animations/slot_1/render.webm", "start": 8.0, "end": 12.0,
   "x": 540, "y": 960, "width": 1080}      # alpha WebM (VP9) or ProRes 4444 MOV, e.g. a HyperFrames render
Paths are relative to the edit folder. x/y are the centre of the element in 1080x1920 pixels.

Usage:
    python render.py <edit_dir> --preview          # fast encode -> preview_vN.mp4
    python render.py <edit_dir> --final            # high quality -> final_vN.mp4
    python render.py <edit_dir> --preview --no-captions
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from asslib import FONT_FILES, RLM, Measure, clean, color, event, header, install_fonts, is_rtl, style
from common import BT709_TAGS, FPS, SAFE_BOTTOM, SAFE_RIGHT, SAFE_TOP, W, die, load_json

TEXT_STYLES = {
    #        size  font                 text       box/outline  border  outline  shadow
    "hook":  (92, "Tajawal ExtraBold", "#FFFFFF", "#000000", 1, 5, 4),
    "title": (64, "Tajawal ExtraBold", "#FFFFFF", "#0B1430", 3, 18, 0),
    "pill":  (54, "Tajawal ExtraBold", "#0B1020", None, 3, 16, 0),   # box = accent colour
    "label": (44, "Tajawal Bold", "#FFFFFF", "#0B1430", 3, 12, 0),
}


def next_version(edit: Path, stem: str) -> Path:
    nums = [int(m.group(1)) for p in edit.glob(f"{stem}_v*.mp4") if (m := re.search(r"_v(\d+)\.mp4$", p.name))]
    return edit / f"{stem}_v{max(nums, default=0) + 1}.mp4"


def wrap(words: list[str], widths: list[float], space: float, maxw: float) -> list[list[int]]:
    lines, cur, w = [], [], 0.0
    for i, ww in enumerate(widths):
        add = ww if not cur else w + space + ww
        if cur and add > maxw:
            lines.append(cur)
            cur, w = [i], ww
        else:
            cur.append(i)
            w = add
    if cur:
        lines.append(cur)
    return lines


def text_overlays_ass(items: list[dict], accent: str, edit: Path) -> str | None:
    texts = [o for o in items if o.get("type") == "text"]
    if not texts:
        return None
    styles, events = [], []
    meas = {}
    for name, (size, font, fg, box, border, outl, shad) in TEXT_STYLES.items():
        m = meas.setdefault(font, Measure(FONT_FILES[font]))
        box_col = color(accent) if name == "pill" else color(box, 0x20 if border == 3 else 0x40)
        styles.append(style(name, font, round(size / m.em_ratio, 1), color(fg), box_col, color("#000000", 0x80),
                            outl, shad, 5, 0, 0, 0, border_style=border))
    for o in texts:
        st = o.get("style", "title")
        if st not in TEXT_STYLES:
            die(f"unknown text style {st}; use one of {', '.join(TEXT_STYLES)}")
        size, font = TEXT_STYLES[st][0], TEXT_STYLES[st][1]
        m = meas[font]
        ass_size = size / m.em_ratio
        x, y = int(o.get("x", 540)), int(o.get("y", 420))
        maxw = float(o.get("max_width", 2 * min(x - 60, SAFE_RIGHT - x) * 0.94))
        words = []
        for wd in clean(o["text"]).split():          # keep "الـ" with the word after it
            if words and words[-1].endswith("ـ"):
                words[-1] += " " + wd
            else:
                words.append(wd)
        widths = [m.width(wd, ass_size) for wd in words]
        lines = wrap(words, widths, m.width(" ", ass_size), maxw)
        acc = set(o.get("accent_words", []))
        out_lines = []
        for ln in lines:
            parts = [f"{{\\c{color(accent)}}}{words[i]}{{\\c{color(TEXT_STYLES[st][2])}}}" if words[i] in acc else words[i]
                     for i in ln]
            line = " ".join(parts)
            out_lines.append((RLM if is_rtl(line) else "") + line)
        s, e = float(o["start"]), float(o["end"])
        anim = o.get("anim", "pop" if st in ("pill", "title") else "fade")
        tag = f"\\an5\\pos({x},{y})"
        if anim == "pop":
            tag += "\\fad(60,120)\\fscx60\\fscy60\\t(0,140,\\fscx108\\fscy108)\\t(140,240,\\fscx100\\fscy100)"
        elif anim == "slide":
            tag = f"\\an5\\move({x},{y + 60},{x},{y},0,220)\\fad(120,120)"
        elif anim == "fade":
            tag += "\\fad(150,150)"
        events.append(event(s, e, st, f"{{{tag}}}" + "\\N".join(out_lines), layer=int(o.get("layer", 1))))
        top = y - len(lines) * size * 0.65
        bottom = y + len(lines) * size * 0.65
        if top < SAFE_TOP or bottom > SAFE_BOTTOM:
            print(f"warn: text '{o['text'][:24]}' reaches outside the safe zone (y {top:.0f}-{bottom:.0f})")
    return header(styles) + "\n".join(events) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="base + overlays + captions (last) + mix -> preview/final mp4")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", action="store_true")
    mode.add_argument("--final", action="store_true")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--accent", default="#E9C46A", help="accent colour for text overlays")
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()
    edit = args.edit_dir.expanduser().resolve()
    base = edit / "base.mp4"
    tl = load_json(edit / "timeline.json")
    if not base.exists() or not tl:
        die("base.mp4 / timeline.json missing; run build_cut.py first")
    total = float(tl["total"])

    audio = edit / "mix.wav"
    if not audio.exists():
        audio = edit / "audio.wav"
        print("warn: no mix.wav, using the raw voice (run mix_audio.py for loudness + SFX)")
    stale = []
    caps = edit / "captions.ass"
    if caps.exists() and caps.stat().st_mtime < (edit / "timeline.json").stat().st_mtime:
        stale.append("captions.ass is older than timeline.json (re-run captions.py)")
    if audio.name == "mix.wav":
        newest = max(p.stat().st_mtime for p in [edit / "audio.wav", edit / "cues.json", edit / "overlays.json"] if p.exists())
        if audio.stat().st_mtime < newest:
            stale.append("mix.wav is older than audio.wav / cues.json / overlays.json (re-run mix_audio.py)")
    for s in stale:
        print(f"warn: {s}")

    items = load_json(edit / "overlays.json", []) or []
    fonts = install_fonts(edit)
    inputs = ["-i", str(base)]
    chains, last, idx = [], "[0:v]", 1
    for o in items:
        if o.get("type") not in ("image", "video"):
            continue
        f = (edit / o["file"]).resolve()
        if not f.exists():
            die(f"overlay file not found: {f}")
        s = float(o["start"])
        e = float(o.get("end", total))
        d = max(0.05, e - s)
        if o["type"] == "image":
            inputs += ["-loop", "1", "-framerate", str(FPS), "-t", f"{d:.3f}", "-i", str(f)]
        else:
            inputs += (["-c:v", "libvpx-vp9"] if f.suffix.lower() == ".webm" else []) + ["-i", str(f)]
        wdt = int(o.get("width", 400 if o["type"] == "image" else W))
        anim = o.get("anim", "pop" if o["type"] == "image" else "none")
        if anim == "pop":
            p = "min(1,t/0.25)-1"
            sc = (f"scale=w='max(2,trunc({wdt}*(1+2.70158*pow({p},3)+1.70158*pow({p},2))/2)*2)':h=-1:eval=frame")
        else:
            sc = f"scale={wdt}:-1"
        fades = ""
        if anim in ("pop", "fade"):
            fades = f",fade=t=in:st=0:d=0.12:alpha=1,fade=t=out:st={max(0, d - 0.15):.3f}:d=0.15:alpha=1"
        chains.append(f"[{idx}:v]format=rgba,{sc}{fades},setpts=PTS-STARTPTS+{s:.3f}/TB[ov{idx}]")
        x, y = int(o.get("x", 540)), int(o.get("y", 960))
        chains.append(f"{last}[ov{idx}]overlay=x='{x}-w/2':y='{y}-h/2':enable='between(t,{s:.3f},{e:.3f})'"
                      f":eof_action=pass[v{idx}]")
        last = f"[v{idx}]"
        idx += 1

    ass_files = []
    txt = text_overlays_ass(items, args.accent, edit)
    if txt:
        (edit / "overlays.ass").write_text(txt, encoding="utf-8")
        ass_files.append("overlays.ass")
    if not args.no_captions:
        if caps.exists():
            ass_files.append("captions.ass")          # LAST: nothing may cover the captions
        else:
            print("note: no captions.ass (run captions.py), rendering without captions")
    for k, a in enumerate(ass_files):
        out = f"[t{k}]"
        chains.append(f"{last}ass={a}:fontsdir={fonts.name}{out}")
        last = out
    chains.append(f"{last}format=yuv420p[vout]")

    out = args.output or next_version(edit, "final" if args.final else "preview")
    venc = (["-preset", "slow", "-crf", "18", "-profile:v", "high"] if args.final else ["-preset", "veryfast", "-crf", "23"])
    cmd = ["ffmpeg", "-y", "-v", "error", "-stats", *inputs, "-i", str(audio), "-filter_complex", ";".join(chains),
           "-map", "[vout]", "-map", f"{idx}:a", "-t", f"{total:.3f}", "-c:v", "libx264", *venc, "-r", str(FPS),
           "-pix_fmt", "yuv420p", *BT709_TAGS, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out)]
    print(f"rendering {'final' if args.final else 'preview'}: {len(ass_files)} text layer(s), "
          f"{idx - 1} image/video overlay(s) -> {out.name}")
    p = subprocess.run(cmd, cwd=edit, capture_output=True, text=True)
    if p.returncode != 0:
        die("ffmpeg failed:\n" + "\n".join(p.stderr.strip().splitlines()[-20:]))
    print(f"-> {out}  ({out.stat().st_size / 1e6:.1f} MB). Next: qc.py {out.name}")


if __name__ == "__main__":
    main()
