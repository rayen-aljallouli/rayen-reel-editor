"""Self-check a render before anyone else sees it.

Checks
  * duration of picture and sound vs timeline.json (within one frame), 1080x1920, 30 fps
  * loudness: -16 LUFS +-1, true peak <= -1 dBTP
  * every cut: the frame before / after and the waveform around it, with a click score
    (a sharp sample jump right at the cut = audible pop)
  * safe zone: sample frames with the zone drawn on top (nothing important outside it)
Writes <edit>/verify/qc_cuts_<name>.jpg, qc_safe_<name>.jpg and qc_<name>.json.
LOOK at both images (Read them) before showing the render. The script cannot judge looks.

Usage:
    python qc.py <edit_dir>/preview_v1.mp4 [--edit-dir DIR] [--samples 8]
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from common import FPS, H, SAFE_BOTTOM, SAFE_RIGHT, SAFE_TOP, SR, W, ffprobe_json, load_any_audio, load_json, measure_loudness, save_json

TW, TH = 216, 384           # thumbnail size (1/5)


def frame(video: Path, t: float, w: int = TW, h: int = TH) -> Image.Image:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", str(video), "-frames:v", "1",
                          "-vf", f"scale={w}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    if len(raw) < w * h * 3:
        return Image.new("RGB", (w, h), (40, 0, 0))
    return Image.frombytes("RGB", (w, h), raw[: w * h * 3])


def click_score(audio: np.ndarray, t: float) -> float:
    """Max sample jump within +-4 ms of t, relative to the 99th percentile jump in the 300 ms around it."""
    mono = audio.mean(axis=1)
    c = int(t * SR)
    d = np.abs(np.diff(mono[max(0, c - int(0.15 * SR)): c + int(0.15 * SR)]))
    if len(d) < 100:
        return 0.0
    mid = len(d) // 2
    w = int(0.004 * SR)
    core = d[max(0, mid - w): mid + w].max()
    ref = np.percentile(np.concatenate([d[: mid - w], d[mid + w:]]), 99) + 1e-6
    return float(core / ref)


def wave_strip(audio: np.ndarray, t: float, w: int, h: int = 70) -> Image.Image:
    img = Image.new("RGB", (w, h), (18, 18, 24))
    dr = ImageDraw.Draw(img)
    mono = audio.mean(axis=1)
    a, b = int((t - 0.25) * SR), int((t + 0.25) * SR)
    seg = mono[max(0, a): max(0, b)]
    if len(seg):
        cols = np.array_split(seg, w)
        for x, col in enumerate(cols):
            v = float(np.abs(col).max()) if len(col) else 0.0
            dr.line([(x, h / 2 - v * h / 2), (x, h / 2 + v * h / 2)], fill=(120, 170, 255))
    dr.line([(w // 2, 0), (w // 2, h)], fill=(255, 70, 70), width=1)
    return img


def safe_overlay(img: Image.Image) -> Image.Image:
    sx, sy = img.width / W, img.height / H
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    red = (255, 40, 40, 70)
    d.rectangle([0, 0, img.width, SAFE_TOP * sy], fill=red)
    d.rectangle([0, SAFE_BOTTOM * sy, img.width, img.height], fill=red)
    d.rectangle([SAFE_RIGHT * sx, SAFE_TOP * sy, img.width, SAFE_BOTTOM * sy], fill=red)
    out = Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")
    ImageDraw.Draw(out).rectangle([0, SAFE_TOP * sy, SAFE_RIGHT * sx, SAFE_BOTTOM * sy], outline=(255, 60, 60), width=1)
    return out


def label(img: Image.Image, text: str, bad: bool = False) -> None:
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, img.width, 16], fill=(150, 0, 0) if bad else (0, 0, 0))
    d.text((4, 2), text, fill=(255, 255, 255))


def grid(tiles: list[Image.Image], cols: int) -> Image.Image:
    if not tiles:
        return Image.new("RGB", (TW, TH), (0, 0, 0))
    tw, th = tiles[0].size
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + 6), rows * (th + 6)), (10, 10, 10))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * (tw + 6), (i // cols) * (th + 6)))
    return sheet


def main() -> None:
    ap = argparse.ArgumentParser(description="Self-check a rendered reel")
    ap.add_argument("video", type=Path)
    ap.add_argument("--edit-dir", type=Path, default=None)
    ap.add_argument("--samples", type=int, default=8, help="frames on the safe-zone sheet")
    ap.add_argument("--target-lufs", type=float, default=-16.0)
    args = ap.parse_args()
    video = args.video.expanduser().resolve()
    edit = (args.edit_dir or video.parent).resolve()
    verify = edit / "verify"
    verify.mkdir(exist_ok=True)
    tl = load_json(edit / "timeline.json", {}) or {}
    issues, report = [], {"file": video.name}

    meta = ffprobe_json(video)
    v = next((s for s in meta["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in meta["streams"] if s["codec_type"] == "audio"), None)
    dur = float(meta["format"].get("duration", 0))
    report.update(width=v.get("width"), height=v.get("height"), fps=v.get("r_frame_rate"), duration=round(dur, 3))
    if (v.get("width"), v.get("height")) != (W, H):
        issues.append(f"size {v.get('width')}x{v.get('height')}, expected {W}x{H}")
    tags = {k: v.get(k) for k in ("color_transfer", "color_primaries", "color_space")}
    report["color"] = tags
    if any(x in ("arib-std-b67", "smpte2084", "bt2020", "bt2020nc", "bt2020ncl") for x in tags.values() if x):
        issues.append(f"HDR/BT.2020 colour tags on the output {tags}: players treat it as HDR; "
                      "rebuild with build_cut.py (it converts and tags BT.709)")
    if v.get("r_frame_rate") != f"{FPS}/1":
        issues.append(f"frame rate {v.get('r_frame_rate')}, expected {FPS}/1")
    if a is None:
        issues.append("no audio stream")
    elif abs(float(a.get("duration", dur)) - float(v.get("duration", dur))) > 1.5 / FPS:
        issues.append(f"audio {float(a['duration']):.3f}s vs video {float(v['duration']):.3f}s")
    if tl and abs(dur - float(tl["total"])) > 1.5 / FPS:
        issues.append(f"duration {dur:.3f}s, timeline says {tl['total']:.3f}s")

    loud = measure_loudness(video)
    report["loudness"] = loud
    if loud:
        if abs(loud["lufs"] - args.target_lufs) > 1.0:
            issues.append(f"loudness {loud['lufs']:.1f} LUFS (target {args.target_lufs:.0f}); run mix_audio.py")
        if loud["tp"] > -1.0:
            issues.append(f"true peak {loud['tp']:.1f} dBTP (want <= -1.0); lower --ceiling-db in mix_audio.py")

    audio = load_any_audio(video)
    cut_tiles, cuts_rep = [], []
    for c in (tl.get("cuts") or [])[1:]:
        b = float(c["out_start"])
        score = click_score(audio, b)
        bad = score > 2.5
        before, after = frame(video, b - 2 / FPS, 160, 284), frame(video, b + 1 / FPS, 160, 284)
        tile = Image.new("RGB", (326, 284 + 70), (0, 0, 0))
        tile.paste(before, (0, 0))
        tile.paste(after, (166, 0))
        tile.paste(wave_strip(audio, b, 326), (0, 284))
        label(tile, f"cut {c['i']} @{b:.2f}s {c['beat'][:10]} click {score:.1f}", bad)
        cut_tiles.append(tile)
        cuts_rep.append({"i": c["i"], "t": b, "click": round(score, 2)})
        if bad:
            issues.append(f"possible pop at cut {c['i']} ({b:.2f}s, click score {score:.1f}): listen / check the fade")
    report["cuts"] = cuts_rep
    if cut_tiles:
        grid(cut_tiles, 4).save(verify / f"qc_cuts_{video.stem}.jpg", quality=85)

    n = max(2, args.samples)
    times = [0.05] + [dur * (k + 0.5) / (n - 1) for k in range(n - 2)] + [max(0, dur - 0.1)]
    for ov in load_json(edit / "overlays.json", []) or []:
        times.append((float(ov["start"]) + float(ov.get("end", ov["start"] + 1))) / 2)
    tiles = []
    for t in sorted(set(round(x, 2) for x in times))[:16]:
        img = safe_overlay(frame(video, t, 270, 480))
        label(img, f"{t:.2f}s")
        tiles.append(img)
    grid(tiles, 4).save(verify / f"qc_safe_{video.stem}.jpg", quality=85)

    report["issues"] = issues
    save_json(verify / f"qc_{video.stem}.json", report)
    print(f"{video.name}: {dur:.2f}s, {report['width']}x{report['height']}, "
          f"{loud.get('lufs', 0):.1f} LUFS, {loud.get('tp', 0):.1f} dBTP, {len(cuts_rep)} cuts checked")
    for i in issues:
        print(f"  ISSUE: {i}")
    if not issues:
        print("  numbers OK")
    print(f"  now look at: verify/qc_cuts_{video.stem}.jpg and verify/qc_safe_{video.stem}.jpg")


if __name__ == "__main__":
    main()
