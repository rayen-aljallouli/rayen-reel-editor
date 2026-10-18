"""Shared helpers for the skill's scripts: paths, ffprobe, the edit folder, wav I/O.

Every script resolves paths relative to the skill folder (the parent of scripts/),
so the skill works wherever it is copied.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
FONTS_DIR = SKILL_DIR / "assets" / "fonts"

# Output format: vertical 9:16 reel.
W, H, FPS = 1080, 1920, 30
SR = 48000

# Instagram / TikTok interface covers everything outside this box on a 1080x1920 frame.
SAFE_TOP, SAFE_BOTTOM, SAFE_RIGHT = 230, 1440, 850

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}
HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}  # PQ (HDR10) and HLG (iPhone default)



# Colour tags written on every encode: SDR Rec.709. A file that still says BT.2020 / HLG makes
# players (and HyperFrames) treat it as HDR.
BT709_TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]


def hdr_chain(info: dict, mode: str = "auto") -> str:
    """Filter chain that turns an HDR source into SDR Rec.709. Run it after the downscale.

    HLG (iPhone default, arib-std-b67): HLG is SDR-compatible, so keep the transfer curve and only
    convert matrix + primaries BT.2020 -> BT.709. This looked natural on a real iPhone reel, where
    zscale tone-mapping (hable / mobius) looked too orange and dark.
    PQ (HDR10, smpte2084) is not SDR-compatible: it needs real tone-mapping (zscale).
    mode: auto | convert | tonemap
    """
    trc = info.get("color_transfer") or ""
    if mode == "convert" or (mode == "auto" and trc == "arib-std-b67"):
        return ("format=yuv420p10le,colorspace=ispace=bt2020ncl:iprimaries=bt2020:itrc=bt709:irange=tv"
                ":space=bt709:primaries=bt709:trc=bt709:range=tv:format=yuv420p")
    tin = trc or "smpte2084"
    pin = info.get("color_primaries") or "bt2020"
    mat = info.get("color_space") or "bt2020nc"
    return (f"zscale=tin={tin}:pin={pin}:min={mat}:t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
            "tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def die(msg: str, code: int = 1) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd: list, quiet: bool = True, **kw) -> subprocess.CompletedProcess:
    """Run a command, raise with stderr on failure."""
    p = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"command failed ({p.returncode}): {' '.join(str(c) for c in cmd[:8])} ...\n{tail}")
    if not quiet and p.stdout:
        print(p.stdout, end="")
    return p


def ffprobe_json(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    return json.loads(out.stdout)


def _f(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def video_info(path: Path) -> dict:
    """Facts about one source that change how it must be cut."""
    data = ffprobe_json(path)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    fmt = data.get("format", {})
    info = {"path": str(path), "name": path.stem, "duration": round(_f(fmt.get("duration")), 3),
            "size_mb": round(_f(fmt.get("size")) / 1e6, 1), "audio_tracks": len(audios)}
    if v is None:
        info["error"] = "no video stream"
        return info
    w, h = int(v.get("width", 0)), int(v.get("height", 0))
    rot = 0
    for sd in v.get("side_data_list") or []:
        if sd.get("rotation") is not None:
            rot = int(round(_f(sd["rotation"])))
    if rot % 180 != 0:
        w, h = h, w
    def rate(s):
        try:
            a, b = s.split("/")
            return float(a) / float(b) if float(b) else 0.0
        except Exception:
            return 0.0
    avg, r = rate(v.get("avg_frame_rate", "0/0")), rate(v.get("r_frame_rate", "0/0"))
    fmt_start = _f(fmt.get("start_time"))
    v_start = _f(v.get("start_time"))
    a_start = _f(audios[0].get("start_time")) if audios else v_start
    info.update({
        "width": w, "height": h, "rotation": rot, "codec": v.get("codec_name"),
        "pix_fmt": v.get("pix_fmt"), "fps_avg": round(avg, 3), "fps_r": round(r, 3),
        "vfr": bool(avg and r and abs(avg - r) > 0.05),
        "hdr": v.get("color_transfer") in HDR_TRANSFERS, "color_transfer": v.get("color_transfer"),
        "color_primaries": v.get("color_primaries"), "color_space": v.get("color_space"),
        "portrait": h > w,
        # Seconds the first audio sample sits after the file start. The transcript and every
        # extracted wav start at that first sample, so a transcript time t is file time t + av_offset.
        # Phones write this as an edit list (one real case: 0.317 s -> lips visibly late).
        "av_offset": round(max(0.0, a_start - min(fmt_start, a_start, v_start)), 4),
    })
    return info


def find_videos(target: Path) -> list[Path]:
    if target.is_file():
        return [target]
    return sorted(p for p in target.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS)


def edit_dir_for(target: Path, explicit: Path | None = None) -> Path:
    """<footage folder>/edit, created on demand. All session outputs live there."""
    if explicit:
        d = explicit
    else:
        d = (target if target.is_dir() else target.parent) / "edit"
    d = d.resolve()
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve(p: str | Path, base: Path) -> Path:
    p = Path(p).expanduser()
    return p if p.is_absolute() else (base / p).resolve()


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def read_wav(path: Path):
    """16-bit PCM wav -> float32 array (n, 2) in [-1, 1]."""
    import numpy as np
    with wave.open(str(path)) as w:
        ch, sr = w.getnchannels(), w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    pcm = pcm.reshape(-1, ch)
    if ch == 1:
        pcm = np.repeat(pcm, 2, axis=1)
    if sr != SR:
        raise RuntimeError(f"{path.name}: expected {SR} Hz, got {sr}")
    return pcm[:, :2]


def write_wav(path: Path, pcm) -> None:
    import numpy as np
    data = (np.clip(pcm, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(data.shape[1] if data.ndim == 2 else 1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def load_any_audio(path: Path):
    """Any audio/video file -> float32 (n, 2) at 48 kHz via ffmpeg."""
    import numpy as np
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-f", "f32le", "-ac", "2",
                          "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32).reshape(-1, 2).copy()


def measure_loudness(path: Path) -> dict:
    """Integrated loudness (LUFS), true peak (dBTP) and LRA of a file's audio."""
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn",
                        "-af", "loudnorm=print_format=json", "-f", "null", "-"], capture_output=True, text=True)
    err = p.stderr
    a, b = err.rfind("{"), err.rfind("}")
    if a < 0 or b < a:
        return {}
    d = json.loads(err[a:b + 1])
    return {"lufs": _f(d.get("input_i"), -99), "tp": _f(d.get("input_tp"), -99), "lra": _f(d.get("input_lra"))}


def python_cmd() -> str:
    """The interpreter to recommend in messages: the skill's .venv if present."""
    venv = SKILL_DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(venv) if venv.exists() else "python3"
