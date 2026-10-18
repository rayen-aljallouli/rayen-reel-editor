"""Inventory of the footage: everything about a source that changes how it must be cut.

For each video: duration, displayed size, fps (and whether it is variable), HDR, audio tracks
and the A/V start offset (phones write the audio a few hundred ms after the video as an
edit list; ignore it and the lips run late after every cut). Writes <edit>/inventory.json.

Usage:
    python probe.py <footage_folder_or_video> [--edit-dir DIR]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from common import edit_dir_for, find_videos, save_json, video_info


def main() -> None:
    ap = argparse.ArgumentParser(description="Probe source videos (A/V offset, HDR, fps, size)")
    ap.add_argument("target", type=Path, help="footage folder or one video")
    ap.add_argument("--edit-dir", type=Path, default=None)
    args = ap.parse_args()
    target = args.target.expanduser().resolve()
    videos = find_videos(target)
    if not videos:
        raise SystemExit(f"no videos in {target}")
    edit = edit_dir_for(target, args.edit_dir)

    rows, notes = [], []
    for v in videos:
        i = video_info(v)
        rows.append(i)
        if "error" in i:
            notes.append(f"{v.name}: {i['error']}")
            continue
        if i["av_offset"] > 0.005:
            notes.append(f"{v.name}: audio starts {i['av_offset'] * 1000:.0f} ms after the video. "
                         "build_cut.py shifts the picture by this amount (lip sync). Keep it that way.")
        if i["hdr"]:
            kind = "HLG" if i["color_transfer"] == "arib-std-b67" else "PQ/HDR10"
            how = ("converted BT.2020 -> BT.709 (HLG curve kept, looks natural)" if kind == "HLG"
                   else "tone-mapped with zscale")
            notes.append(f"{v.name}: HDR {kind} ({i['color_transfer']}, {i.get('color_primaries')}): {how} and "
                         "tagged BT.709 on extract. Never put the raw file into HyperFrames: an HDR-tagged "
                         "video makes it render overlays under the video.")
        if i["vfr"]:
            notes.append(f"{v.name}: variable frame rate (avg {i['fps_avg']}), output is constant 30 fps.")
        if not i["portrait"]:
            notes.append(f"{v.name}: landscape, it will be cropped to 9:16 (set center_x in the EDL).")
        if i["height"] < 1920 and i["portrait"]:
            notes.append(f"{v.name}: {i['width']}x{i['height']} is below 1080x1920, it will be upscaled.")
        if i["audio_tracks"] == 0:
            notes.append(f"{v.name}: no audio track, cannot be transcribed.")
        elif i["audio_tracks"] > 1:
            notes.append(f"{v.name}: {i['audio_tracks']} audio tracks, check which one has the voice (--audio-track).")

    print(f"{'file':<28} {'dur':>7} {'size':>11} {'fps':>6} {'HDR':>4} {'A/V ms':>7} {'MB':>7}")
    for i in rows:
        if "error" in i:
            print(f"{i['name']:<28} ERROR {i['error']}")
            continue
        print(f"{i['name'][:28]:<28} {i['duration']:7.1f} {i['width']:>5}x{i['height']:<5} {i['fps_avg']:6.2f} "
              f"{'yes' if i['hdr'] else 'no':>4} {i['av_offset'] * 1000:7.0f} {i['size_mb']:7.0f}")
    total = sum(i.get("duration", 0) for i in rows)
    free_gb = shutil.disk_usage(edit).free / 1e9
    print(f"\n{len(rows)} file(s), {total / 60:.1f} min of footage. Free disk at {edit}: {free_gb:.0f} GB")
    if free_gb < 10:
        notes.append(f"only {free_gb:.0f} GB free; 4K footage plus renders can need 10+ GB")
    for n in notes:
        print(f"  note: {n}")
    save_json(edit / "inventory.json", {"sources": rows, "notes": notes})
    print(f"-> {edit / 'inventory.json'}")


if __name__ == "__main__":
    main()
