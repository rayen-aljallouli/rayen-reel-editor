"""Generate a small sound-effect bank offline with numpy (no samples, no copyright).

Sounds: whoosh, swoosh_up, pop, tick, click, ping, thud, riser, hit, typing.
Writes 48 kHz stereo wavs to <edit>/sfx/ and a sampler (all sounds in a row) to listen to.
Deterministic (fixed seeds): the same command always gives the same files.

Usage:
    python make_sfx.py <edit_dir>                 # all sounds + sfx/sampler.wav
    python make_sfx.py <edit_dir> --only pop tick
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from common import SR, write_wav


def t_axis(dur: float) -> np.ndarray:
    return np.arange(int(SR * dur)) / SR


def onepole_lp(x: np.ndarray, cutoff: np.ndarray | float) -> np.ndarray:
    """One-pole low-pass with a (possibly time-varying) cutoff in Hz."""
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=np.float64), x.shape)
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):
        acc = (1 - a[i]) * x[i] + a[i] * acc
        y[i] = acc
    return y


def env_ad(t: np.ndarray, attack: float, decay: float) -> np.ndarray:
    return np.minimum(t / max(attack, 1e-4), 1.0) * np.exp(-np.maximum(t - attack, 0) / max(decay, 1e-4))


def stereo(mono: np.ndarray, width: float = 0.0, seed: int = 0) -> np.ndarray:
    if width <= 0:
        return np.stack([mono, mono], axis=1)
    d = int(0.0007 * SR * width)
    r = np.concatenate([np.zeros(d), mono[:-d]]) if d else mono
    return np.stack([mono, r], axis=1)


def norm(x: np.ndarray, peak_db: float = -1.0) -> np.ndarray:
    m = np.abs(x).max() or 1.0
    return x / m * 10 ** (peak_db / 20)


def whoosh(seed=1, dur=0.6, up=False):
    rng = np.random.default_rng(seed)
    t = t_axis(dur)
    n = rng.standard_normal(len(t))
    pos = t / dur
    sweep = (300 + 5000 * pos ** 1.5) if up else (300 + 5000 * np.sin(np.pi * pos) ** 2)
    hp = n - onepole_lp(n, 200)
    band = onepole_lp(hp, sweep)
    env = np.sin(np.pi * np.clip(pos, 0, 1)) ** (1.2 if not up else 0.6)
    if up:
        env *= np.clip(pos * 1.2, 0, 1)
    return stereo(norm(band * env, -3), width=1.0)


def pop(seed=2):
    t = t_axis(0.14)
    f = 900 * np.exp(-t * 28) + 260
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_ad(t, 0.002, 0.035)
    return stereo(norm(s, -2))


def tick(seed=3):
    rng = np.random.default_rng(seed)
    t = t_axis(0.04)
    s = rng.standard_normal(len(t)) * env_ad(t, 0.0003, 0.004) + 0.6 * np.sin(2 * np.pi * 3200 * t) * env_ad(t, 0.0003, 0.006)
    return stereo(norm(s - onepole_lp(s, 1500), -4))


def click(seed=4):
    rng = np.random.default_rng(seed)
    t = t_axis(0.14)
    def one(t0, f):
        tt = np.clip(t - t0, 0, None)
        on = (t >= t0).astype(float)
        return on * (rng.standard_normal(len(t)) * env_ad(tt, 0.0002, 0.003) + 0.5 * np.sin(2 * np.pi * f * tt) * env_ad(tt, 0.0002, 0.008))
    s = one(0.0, 2400) + 0.6 * one(0.085, 3000)      # press + release
    return stereo(norm(s - onepole_lp(s, 800), -5))


def ping(seed=5):
    t = t_axis(0.9)
    s = sum(a * np.sin(2 * np.pi * f * t) * np.exp(-t * d) for f, a, d in
            ((1318.5, 1.0, 5.0), (2637.0, 0.35, 8.0), (3955.5, 0.15, 12.0), (1975.5, 0.2, 7.0)))
    s *= np.minimum(t / 0.002, 1)
    return stereo(norm(s, -3), width=0.6)


def thud(seed=6):
    rng = np.random.default_rng(seed)
    t = t_axis(0.45)
    body = np.sin(2 * np.pi * (60 + 90 * np.exp(-t * 30)) * t) * env_ad(t, 0.002, 0.12)
    noise = onepole_lp(rng.standard_normal(len(t)), 900) * env_ad(t, 0.001, 0.02) * 2
    return stereo(norm(body + noise, -2))


def riser(seed=7, dur=1.6):
    rng = np.random.default_rng(seed)
    t = t_axis(dur)
    pos = t / dur
    n = rng.standard_normal(len(t))
    band = onepole_lp(n - onepole_lp(n, 300), 400 + 9000 * pos ** 2)
    tone = np.sin(2 * np.pi * np.cumsum(180 + 700 * pos ** 2) / SR) * 0.3
    env = pos ** 2.2
    env[-int(0.01 * SR):] *= np.linspace(1, 0, int(0.01 * SR))   # peak at the very end
    return stereo(norm((band + tone) * env, -3), width=1.0)


def hit(seed=8):
    """Short cinematic hit: sub drop + noise transient + bright stab, for a hook's first frame."""
    rng = np.random.default_rng(seed)
    t = t_axis(1.2)
    sub = np.sin(2 * np.pi * np.cumsum(32 + 55 * np.exp(-t * 2.2)) / SR) * np.exp(-t * 4.5) * np.minimum(t / 0.003, 1)
    noise = rng.standard_normal(len(t)) * np.exp(-t * 45) * 0.5
    stab = sum(np.sign(np.sin(2 * np.pi * f * t)) for f in (174.6, 207.7, 261.6)) * 0.15
    stab = onepole_lp(stab, 9000 * np.exp(-t * 7) + 500) * env_ad(t, 0.004, 0.3)
    s = sub * 1.6 + noise + stab
    st = stereo(s, width=1.0)
    for d, g in ((0.031, .3), (0.047, .25), (0.071, .2), (0.113, .12)):     # tiny room
        k = int(d * SR)
        st[k:, 0] += st[:-k, 1] * g
        st[k:, 1] += st[:-k, 0] * g * .9
    return norm(st, -1)


def typing(seed=9, dur=1.0, rate=11.0):
    rng = np.random.default_rng(seed)
    t = t_axis(dur)
    s = np.zeros(len(t))
    k = 0.0
    while k < dur - 0.05:
        i = int(k * SR)
        n = min(int(0.03 * SR), len(t) - i)
        tt = t[:n]
        s[i:i + n] += (rng.standard_normal(n) * env_ad(tt, 0.0002, 0.004) * rng.uniform(.5, 1)
                       + 0.3 * np.sin(2 * np.pi * rng.uniform(1800, 2600) * tt) * env_ad(tt, 0.0002, 0.006))
        k += rng.uniform(0.6, 1.4) / rate
    return stereo(norm(s - onepole_lp(s, 900), -6))


BANK = {"whoosh": lambda: whoosh(), "swoosh_up": lambda: whoosh(seed=11, dur=0.5, up=True), "pop": pop,
        "tick": tick, "click": click, "ping": ping, "thud": thud, "riser": riser, "hit": hit, "typing": typing}


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate royalty-free SFX with numpy")
    ap.add_argument("edit_dir", type=Path)
    ap.add_argument("--only", nargs="*", choices=sorted(BANK))
    args = ap.parse_args()
    out = args.edit_dir.expanduser().resolve() / "sfx"
    out.mkdir(parents=True, exist_ok=True)
    names = args.only or sorted(BANK)
    sampler = []
    for name in names:
        pcm = BANK[name]().astype(np.float32)
        write_wav(out / f"{name}.wav", pcm)
        peak_t = np.abs(pcm).max(axis=1).argmax() / SR
        print(f"  {name:<10} {len(pcm) / SR:4.2f}s  peak at {peak_t:.3f}s")
        sampler += [pcm, np.zeros((int(0.35 * SR), 2), dtype=np.float32)]
    if not args.only:
        write_wav(out / "sampler.wav", np.vstack(sampler))
        print(f"-> {out} (+ sampler.wav to listen to all of them)")


if __name__ == "__main__":
    main()
