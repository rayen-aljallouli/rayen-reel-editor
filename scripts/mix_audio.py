"""Final audio: voice (audio.wav) + SFX cues + optional music bed (ducked under speech) -> mix.wav.

Loudness the way it worked on real reels: the voice is brought to the target with plain gain
(not loudnorm's dynamic mode, which audibly changed the voice once), SFX and music are added,
the sum is corrected to the target, then a limiter keeps peaks under the ceiling.
Targets: -16 LUFS integrated, about -1 dBTP.

Cues come from <edit>/cues.json and from "sfx" keys in <edit>/overlays.json:
    cues.json: [{"t": 3.20, "sfx": "whoosh", "gain": 1.0}, ...]
"t" is the output time where the sound's loudest moment should land (a riser peaks on t,
a whoosh is centred on t). Sounds are looked up in <edit>/sfx/<name>.wav (make_sfx.py, or
any wav you put there yourself).

Usage:
    python mix_audio.py <edit_dir>
    python mix_audio.py <edit_dir> --music music.mp3 --music-db -24 --duck 0.45
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import numpy as np

from common import SR, die, load_any_audio, load_json, measure_loudness, read_wav, write_wav


def lufs_of(pcm: np.ndarray, tmp: Path) -> float:
    write_wav(tmp, np.clip(pcm, -1, 1))
    return measure_loudness(tmp).get("lufs", -99.0)


def main() -> None:
    ap = argparse.ArgumentParser(description="voice + SFX + optional music -> mix.wav at -16 LUFS")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--music", type=Path, help="music file you are allowed to use (any format)")
    ap.add_argument("--music-db", type=float, default=-24.0, help="music peak level before ducking (dBFS)")
    ap.add_argument("--music-start", type=float, default=0.0, help="seconds to skip into the music file")
    ap.add_argument("--duck", type=float, default=0.45, help="how far music dips under speech (0 = no ducking)")
    ap.add_argument("--sfx-db", type=float, default=-13.0, help="SFX peak level at gain 1.0 (dBFS)")
    ap.add_argument("--target-lufs", type=float, default=-16.0)
    ap.add_argument("--ceiling-db", type=float, default=-1.5, help="limiter ceiling (sample peak, dBFS)")
    args = ap.parse_args()
    edit = args.edit_dir.expanduser().resolve()
    if not (edit / "audio.wav").exists():
        die("no audio.wav; run build_cut.py first")
    tmp = edit / "_mix_tmp.wav"

    voice = read_wav(edit / "audio.wav").astype(np.float64)
    n = len(voice)
    v_lufs = measure_loudness(edit / "audio.wav").get("lufs", -99.0)
    if v_lufs < -70:
        die("voice is silent")
    voice *= 10 ** ((args.target_lufs - v_lufs) / 20)
    print(f"voice {v_lufs:.1f} LUFS -> gain {args.target_lufs - v_lufs:+.1f} dB")
    mix = voice.copy()

    if args.music:
        m = load_any_audio(args.music.expanduser().resolve()).astype(np.float64)
        m = m[int(args.music_start * SR):]
        if len(m) < n:                       # loop a short bed
            m = np.vstack([m] * (n // max(1, len(m)) + 1))
        m = m[:n]
        m = m / (np.abs(m).max() or 1.0) * 10 ** (args.music_db / 20)
        fade = min(int(1.5 * SR), n // 4)
        m[-fade:] *= np.linspace(1, 0, fade)[:, None]
        # envelope follower on the voice -> smooth gain curve
        env = np.abs(voice).mean(axis=1)
        win = int(0.25 * SR)
        cs = np.concatenate([[0.0], np.cumsum(env)])
        idx = np.arange(n)
        lo, hi = np.clip(idx - win // 2, 0, n), np.clip(idx + win // 2, 0, n)
        env = (cs[hi] - cs[lo]) / np.maximum(1, hi - lo)
        duck = 1.0 - args.duck * np.clip(env / (env.max() + 1e-9) * 3, 0, 1)
        mix += m * duck[:, None]
        print(f"music {args.music.name}: peak {args.music_db} dBFS, ducked to {100 * (1 - args.duck):.0f} % under speech")

    cues = list(load_json(edit / "cues.json", []) or [])
    for ov in load_json(edit / "overlays.json", []) or []:
        if ov.get("sfx"):
            cues.append({"t": float(ov["start"]) + float(ov.get("sfx_offset", 0)), "sfx": ov["sfx"],
                         "gain": float(ov.get("sfx_gain", 1.0))})
    bank, missing = {}, set()
    for c in cues:
        name = c["sfx"]
        if name not in bank:
            p = edit / "sfx" / f"{name}.wav"
            if not p.exists():
                missing.add(name)
                continue
            s = load_any_audio(p).astype(np.float64)
            s = s / (np.abs(s).max() or 1.0) * 10 ** (args.sfx_db / 20)
            bank[name] = (s, int(np.abs(s).max(axis=1).argmax()))
        if name not in bank:
            continue
        s, peak = bank[name]
        s = s * float(c.get("gain", 1.0))
        a = int(round(float(c["t"]) * SR)) - peak
        sa = max(0, -a)
        a = max(0, a)
        L = min(len(s) - sa, n - a)
        if L > 0:
            mix[a:a + L] += s[sa:sa + L]
    if missing:
        print(f"warn: missing SFX (run make_sfx.py or add the wav): {', '.join(sorted(missing))}")

    # correct the sum to the target, then limit (float in, no clipping before the limiter)
    m_lufs = lufs_of(mix / max(1.0, np.abs(mix).max()), tmp) + 20 * np.log10(max(1.0, np.abs(mix).max()))
    mix *= 10 ** ((args.target_lufs - m_lufs) / 20)
    limit = 10 ** (args.ceiling_db / 20)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f64le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-af", f"alimiter=limit={limit:.4f}:attack=3:release=80:asc=1:level=false",
                    "-c:a", "pcm_s16le", str(edit / "mix.wav")], input=mix.astype(np.float64).tobytes(), check=True)
    tmp.unlink(missing_ok=True)
    final = measure_loudness(edit / "mix.wav")
    print(f"-> mix.wav {n / SR:.2f}s, {len(cues)} cue(s): {final.get('lufs', 0):.1f} LUFS, "
          f"{final.get('tp', 0):.1f} dBTP")


if __name__ == "__main__":
    main()
