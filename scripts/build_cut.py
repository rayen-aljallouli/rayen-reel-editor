"""Build the cut from edl.json -> base.mp4 (picture), audio.wav (voice), cut.mp4 (rough cut), timeline.json.

Per-segment extract -> lossless concat, the order the video-use pipeline (Browser Use, MIT) uses,
plus fixes from real reels:
 1. Every range edge snaps to a word boundary from the transcript, with padding (default 60 ms
    before the first word, 80 ms after the last). Never inside a word, never into a neighbour.
 2. Optional pause tightening: a range splits at inner silences longer than `max_gap`.
 3. Every range is snapped to whole output frames, so picture and sound keep the same length.
 4. Picture: cut from the camera file at transcript time + A/V start offset (lip sync), cropped
    to 9:16 with an optional punch-in, 1080x1920, HDR turned into SDR Rec.709 and tagged BT.709
    (an HLG/BT.2020-tagged base makes HyperFrames render overlays UNDER the video), constant
    30 fps, then concatenated with -c copy (no second encode).
 5. Sound: from a wav of the source's audio track (the transcript's clock), 30 ms fades at every
    edge, optional speed-up (atempo keeps the pitch), sample-exact PCM concat (no AAC drift).
 6. timeline.json: cuts + every word on the output timeline. Captions and overlays use it.

Usage:
    python build_cut.py <edit>/edl.json --dry-run   # snapped ranges + runtime, no video work
    python build_cut.py <edit>/edl.json             # build (segments are cached)
    python build_cut.py <edit>/edl.json --draft     # fast low-quality segments, same geometry
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from common import BT709_TAGS, FPS, H, SR, W, die, hdr_chain, load_json, resolve, run, save_json, video_info, write_wav

GRADES = {
    "none": "",
    "lift": "eq=contrast=1.03:gamma=1.09:saturation=1.04",      # brighter midtones, used on indoor phone footage
    "punch": "eq=contrast=1.06:saturation=1.06",
    "warm": "eq=contrast=1.03:saturation=1.03,colorbalance=rs=.03:bs=-.03",
    "cool": "eq=contrast=1.03,colorbalance=rs=-.02:bs=.03",
}
FADE = 0.03


# ----------------------------------------------------------------------------- planning
def load_words(path: Path) -> list[dict]:
    data = load_json(path, {}) or {}
    return [w for w in data.get("words", []) if w.get("type") == "word" and w.get("start") is not None
            and w.get("end") is not None]


def plan(edl: dict, edit: Path) -> tuple[list[dict], list[str], dict]:
    """EDL ranges -> final segments (snapped, split, frame-exact). Returns (segments, warnings, infos)."""
    speed = float(edl.get("speed", 1.0))
    pad_b, pad_a = edl.get("pad", [0.06, 0.08])
    max_gap = edl.get("max_gap")
    zcfg = {"center_x": 0.5, "center_y": 0.4, **(edl.get("zoom") or {})}
    sources = {k: resolve(v, edit) for k, v in edl["sources"].items()}
    for k, p in sources.items():
        if not p.exists():
            die(f"source {k} not found: {p}")
    tpaths = {k: resolve(edl.get("transcripts", {}).get(k, f"transcripts/{p.stem}.json"), edit)
              for k, p in sources.items()}
    words = {k: load_words(tp) for k, tp in tpaths.items()}
    infos = {k: video_info(p) for k, p in sources.items()}
    warns: list[str] = []
    segs: list[dict] = []

    for ri, r in enumerate(edl["ranges"]):
        k = r["source"]
        if k not in sources:
            die(f"range {ri}: unknown source {k}")
        ws = words[k]
        start, end = float(r["start"]), float(r["end"])
        if end <= start:
            die(f"range {ri} ({r.get('beat')}): end <= start")
        base = {"source": k, "beat": r.get("beat", f"R{ri}"), "zoom": float(r.get("zoom", 1.0)),
                "center_x": float(r.get("center_x", zcfg["center_x"])),
                "center_y": float(r.get("center_y", zcfg["center_y"])),
                "freeze_tail": float(r.get("freeze_tail", 0)), "mute": bool(r.get("mute", False)),
                "range": ri}
        snap = r.get("snap", True) and bool(ws)
        if r.get("snap", True) and not ws:
            warns.append(f"range {ri} ({base['beat']}): no transcript for {k}, cut taken as written")
        if not snap:
            segs.append({**base, "start": start, "end": end, "limit": None, "first": "", "last": ""})
            continue
        inside = [i for i, w in enumerate(ws) if start <= (w["start"] + w["end"]) / 2 <= end]
        if not inside:
            warns.append(f"range {ri} ({base['beat']}): no words inside {start:.2f}-{end:.2f}, taken as written")
            segs.append({**base, "start": start, "end": end, "limit": None, "first": "", "last": ""})
            continue
        runs = [[inside[0]]]
        if max_gap and not r.get("keep_pauses"):
            for a, b in zip(inside, inside[1:]):
                if ws[b]["start"] - ws[a]["end"] > float(max_gap):
                    runs.append([b])
                else:
                    runs[-1].append(b)
        else:
            runs[0] = inside
        hold = float(r.get("hold", 0))
        for n, run_ in enumerate(runs):
            fi, li = run_[0], run_[-1]
            prev_end = ws[fi - 1]["end"] if fi > 0 else 0.0
            next_start = ws[li + 1]["start"] if li + 1 < len(ws) else None
            s = max(prev_end, ws[fi]["start"] - pad_b, 0.0)
            s = min(s, ws[fi]["start"])
            tail = max(pad_a, hold) if n == len(runs) - 1 else pad_a
            e = ws[li]["end"] + tail
            if next_start is not None:
                e = min(e, next_start)
            e = max(e, ws[li]["end"])
            if fi > 0 and ws[fi]["start"] - prev_end < FADE:
                warns.append(f"{base['beat']}: connected speech before \"{ws[fi]['text'].strip()}\" "
                             f"({ws[fi]['start'] - prev_end:.3f}s gap), check the cut at {s:.2f}")
            if next_start is not None and next_start - ws[li]["end"] < FADE:
                warns.append(f"{base['beat']}: connected speech after \"{ws[li]['text'].strip()}\", check the cut at {e:.2f}")
            beat = base["beat"] if len(runs) == 1 else f"{base['beat']}_{n + 1}"
            segs.append({**base, "beat": beat, "start": round(s, 3), "end": round(e, 3), "limit": next_start,
                         "first": ws[fi]["text"].strip(), "last": ws[li]["text"].strip()})

    # whole output frames: picture and sound get the same length, and the cumulative timeline is exact
    for sg in segs:
        frames = max(1, round((sg["end"] - sg["start"]) / speed * FPS))
        e = sg["start"] + frames * speed / FPS
        if sg["limit"] is not None and e > sg["limit"] and frames > 1:
            frames -= 1
            e = sg["start"] + frames * speed / FPS
        sg["frames"] = frames
        sg["freeze_frames"] = round(sg["freeze_tail"] * FPS)
        sg["end"] = round(e, 4)
    return segs, warns, {"speed": speed, "sources": sources, "infos": infos, "tpaths": tpaths, "words": words}


# ----------------------------------------------------------------------------- picture
def grade_filter(g: str | None) -> str:
    if not g:
        return ""
    return GRADES.get(g, g)   # preset name or a raw ffmpeg filter string


def extract_video(i: int, sg: dict, src: Path, info: dict, grade: str, speed: float, out_dir: Path, draft: bool,
                  hdr_mode: str = "auto") -> Path:
    out = out_dir / f"seg_{i:02d}.mp4"
    stamp = out.with_suffix(".json")
    total_frames = sg["frames"] + sg["freeze_frames"]
    params = {"src": str(src), "mtime": os.path.getmtime(src), "start": sg["start"], "frames": total_frames,
              "zoom": sg["zoom"], "cx": sg["center_x"], "cy": sg["center_y"], "grade": grade, "speed": speed,
              "av": info["av_offset"], "draft": draft, "hdr": hdr_mode, "v": 3}
    key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()
    if out.exists() and stamp.exists() and load_json(stamp, {}).get("key") == key:
        return out
    z, cx, cy = sg["zoom"], sg["center_x"], sg["center_y"]
    cw = f"min(iw,ih*9/16)/{z}"
    vf = [f"crop=w='trunc({cw}/2)*2':h='trunc({cw}*16/9/2)*2':x='(iw-ow)*{cx}':y='(ih-oh)*{cy}'",
          f"scale={W}:{H}:flags=lanczos,setsar=1"]
    if info.get("hdr"):
        vf.append(hdr_chain(info, hdr_mode))    # after the downscale: 4x fewer pixels to convert
    if grade:
        vf.append(grade)
    if speed != 1.0:
        vf.append(f"setpts=(PTS-STARTPTS)/{speed}")
    vf.append(f"fps={FPS}")
    # clone the last frame: covers a freeze tail and guarantees the frame count at the end of a file
    vf.append(f"tpad=stop_mode=clone:stop_duration={sg['freeze_tail'] + 0.3:.3f}")
    preset, crf = ("ultrafast", "26") if draft else ("medium", "17")
    seek = sg["start"] + info["av_offset"]          # transcript clock -> file clock (lip sync)
    # -t before -i limits what is read; the frame count is fixed by -frames:v, tpad fills the tail
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{seek:.4f}", "-t", f"{(sg['end'] - sg['start']) + 0.3:.4f}",
         "-i", src, "-map", "0:v:0", "-vf", ",".join(vf), "-an",
         "-frames:v", str(total_frames), "-c:v", "libx264", "-preset", preset, "-crf", crf,
         "-pix_fmt", "yuv420p", *BT709_TAGS, "-r", str(FPS), "-movflags", "+faststart", out])
    stamp.write_text(json.dumps({"key": key}))
    return out


def count_frames(path: Path) -> int:
    out = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
               "stream=nb_read_packets", "-of", "csv=p=0", path])
    return int(out.stdout.strip().strip(","))


# ----------------------------------------------------------------------------- sound
def source_wav(src: Path, edit: Path, track: int, denoise: bool) -> Path:
    """The source's audio track as 48 kHz stereo PCM, starting at the first audio sample
    (the same clock as the transcript)."""
    d = edit / "audio_src"
    d.mkdir(exist_ok=True)
    out = d / f"{src.stem}{'' if track == 0 else f'.track{track}'}{'.dn' if denoise else ''}.wav"
    stamp = out.with_suffix(".json")
    key = {"mtime": os.path.getmtime(src), "size": src.stat().st_size, "track": track, "dn": denoise}
    if out.exists() and load_json(stamp, {}) == key:
        return out
    af = ["-af", "highpass=f=80,afftdn=nr=12:nf=-40:tn=1"] if denoise else []
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-map", f"0:a:{track}", "-vn", *af, "-ac", "2",
         "-ar", str(SR), "-c:a", "pcm_s16le", out])
    save_json(stamp, key)
    return out


def read_span(wav_path: Path, start: float, dur: float) -> np.ndarray:
    with wave.open(str(wav_path)) as w:
        n_total = w.getnframes()
        a = max(0, min(n_total, int(round(start * SR))))
        w.setpos(a)
        raw = w.readframes(max(0, int(round(dur * SR))))
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32).reshape(-1, 2) / 32768
    return pcm


def tempo(pcm: np.ndarray, speed: float) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                        "-af", f"atempo={speed}", "-f", "f32le", "-"], input=pcm.astype(np.float32).tobytes(),
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, dtype=np.float32).reshape(-1, 2).copy()


def segment_audio(sg: dict, wav_path: Path, n_samples: int, speed: float) -> np.ndarray:
    voiced = n_samples - int(round(sg["freeze_frames"] / FPS * SR))
    if sg["mute"]:
        return np.zeros((n_samples, 2), dtype=np.float32)
    pcm = read_span(wav_path, sg["start"], sg["end"] - sg["start"] + 0.05)
    if speed != 1.0 and len(pcm):
        pcm = tempo(pcm, speed)
    pcm = pcm[:voiced]
    if len(pcm) < voiced:
        pcm = np.vstack([pcm, np.zeros((voiced - len(pcm), 2), dtype=np.float32)])
    nf = min(int(FADE * SR), len(pcm) // 2)
    if nf > 0:
        ramp = np.linspace(0.0, 1.0, nf, dtype=np.float32)[:, None]
        pcm[:nf] *= ramp
        pcm[-nf:] *= ramp[::-1]
    if n_samples > voiced:
        pcm = np.vstack([pcm, np.zeros((n_samples - voiced, 2), dtype=np.float32)])
    return pcm


# ----------------------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description="EDL -> base.mp4 + audio.wav + cut.mp4 + timeline.json")
    ap.add_argument("edl", type=Path)
    ap.add_argument("--dry-run", action="store_true", help="print the snapped plan only")
    ap.add_argument("--draft", action="store_true", help="fast, low-quality segments (cut check)")
    ap.add_argument("--workers", type=int, default=max(1, min(3, (os.cpu_count() or 2) // 2)))
    args = ap.parse_args()
    edl_path = args.edl.expanduser().resolve()
    edit = edl_path.parent
    edl = load_json(edl_path)
    if not edl:
        die(f"cannot read {edl_path}")
    segs, warns, ctx = plan(edl, edit)
    speed = ctx["speed"]

    cum, offsets = 0, []
    for sg in segs:
        offsets.append(cum)
        cum += sg["frames"] + sg["freeze_frames"]
    total = cum / FPS
    print(f"{len(segs)} segments, {total:.2f}s at speed {speed}")
    for i, (sg, off) in enumerate(zip(segs, offsets)):
        print(f"  {i:02d} {sg['beat']:<12} src {sg['start']:8.2f}-{sg['end']:8.2f}  out {off / FPS:6.2f}  "
              f"z{sg['zoom']:.2f}  {sg['first'][:18]} ... {sg['last'][:18]}")
    for w in warns:
        print(f"  warn: {w}")
    for k, inf in ctx["infos"].items():
        if inf.get("av_offset", 0) > 0.005:
            print(f"  note: source {k} audio starts {inf['av_offset'] * 1000:.0f} ms late, picture shifted to match")
    save_json(edit / "edl.snapped.json", {"total": round(total, 3), "segments": segs, "warnings": warns})
    if args.dry_run:
        return

    clips = edit / ("clips_draft" if args.draft else "clips")
    clips.mkdir(exist_ok=True)
    grade = grade_filter(edl.get("grade"))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(extract_video, i, sg, ctx["sources"][sg["source"]], ctx["infos"][sg["source"]],
                            grade, speed, clips, args.draft, str(edl.get("hdr", "auto"))) for i, sg in enumerate(segs)]
        paths = [f.result() for f in futs]
    for i, (p, sg) in enumerate(zip(paths, segs)):
        n = count_frames(p)
        want = sg["frames"] + sg["freeze_frames"]
        if n != want:
            die(f"segment {i} has {n} frames, expected {want} ({p.name}); delete it and rebuild")

    lst = edit / "_concat.txt"
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in paths))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-map", "0:v", "-c", "copy",
         "-movflags", "+faststart", edit / "base.mp4"])
    lst.unlink(missing_ok=True)

    track = int(edl.get("audio_track", 0))
    wavs = {k: source_wav(p, edit, track, bool(edl.get("denoise"))) for k, p in ctx["sources"].items()}
    parts = []
    for sg, off in zip(segs, offsets):
        a = int(round(off / FPS * SR))
        b = int(round((off + sg["frames"] + sg["freeze_frames"]) / FPS * SR))
        parts.append(segment_audio(sg, wavs[sg["source"]], b - a, speed))
    write_wav(edit / "audio.wav", np.vstack(parts))

    run(["ffmpeg", "-y", "-v", "error", "-i", edit / "base.mp4", "-i", edit / "audio.wav", "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", edit / "cut.mp4"])

    cuts, words = [], []
    for i, (sg, off) in enumerate(zip(segs, offsets)):
        o0 = off / FPS
        o1 = (off + sg["frames"] + sg["freeze_frames"]) / FPS
        cuts.append({"i": i, "beat": sg["beat"], "source": sg["source"], "src_start": sg["start"], "src_end": sg["end"],
                     "out_start": round(o0, 4), "out_end": round(o1, 4), "zoom": sg["zoom"]})
        for w in ctx["words"].get(sg["source"], []):
            mid = (w["start"] + w["end"]) / 2
            if not (sg["start"] <= mid <= sg["end"]):
                continue
            words.append({"text": w["text"].strip(), "cut": i, "beat": sg["beat"], "src": round(w["start"], 3),
                          "start": round(o0 + (max(w["start"], sg["start"]) - sg["start"]) / speed, 3),
                          "end": round(o0 + (min(w["end"], sg["end"]) - sg["start"]) / speed, 3)})
    save_json(edit / "timeline.json", {"total": round(total, 4), "fps": FPS, "speed": speed,
                                       "width": W, "height": H, "cuts": cuts, "words": words})
    print(f"-> base.mp4 + audio.wav + cut.mp4 ({total:.2f}s, {len(cuts)} segments, {len(words)} words), timeline.json")


if __name__ == "__main__":
    main()
