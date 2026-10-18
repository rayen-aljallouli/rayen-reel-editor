"""Requirements check: is this machine ready to edit reels?

Required: Python 3.10+, numpy, Pillow, requests, ffmpeg + ffprobe with libass (captions),
loudnorm and alimiter, the bundled fonts, an ElevenLabs API key.
Optional: zscale (PQ/HDR10 footage), Node.js 22+ and npx (motion overlays with HyperFrames).

It never calls the ElevenLabs API unless you pass --ping (a free account lookup, no credits).

Usage:
    python check_setup.py
    python check_setup.py --ping       # also test the API key against ElevenLabs
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent
OK, WARN, FAIL = "ok  ", "warn", "FAIL"
results: list[tuple[str, str, str]] = []


def add(status: str, what: str, detail: str = "") -> None:
    results.append((status, what, detail))


def cmd_out(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return ""


def check_python() -> None:
    v = sys.version_info
    add(OK if v >= (3, 10) else FAIL, "Python", f"{v.major}.{v.minor}.{v.micro} ({sys.executable})"
        + ("" if v >= (3, 10) else " - need 3.10 or newer"))
    for mod, pip in (("numpy", "numpy"), ("PIL", "pillow"), ("requests", "requests")):
        try:
            m = __import__(mod)
            add(OK, f"python: {pip}", getattr(m, "__version__", ""))
        except ImportError:
            add(FAIL, f"python: {pip}", f"missing -> {sys.executable} -m pip install -r {SKILL_DIR / 'requirements.txt'}")
    try:
        from PIL import features
        add(OK if features.check("raqm") else WARN, "Pillow raqm (exact text measuring)",
            "yes" if features.check("raqm") else "no - captions still render right (libass), line widths are estimated")
    except Exception:  # noqa: BLE001
        pass


def check_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        if not path:
            add(FAIL, tool, "not found on PATH -> macOS: brew install ffmpeg | Ubuntu/WSL: sudo apt install ffmpeg")
            return
        first = cmd_out([tool, "-version"]).splitlines()[:1]
        add(OK, tool, (first[0] if first else path)[:80])
    filters = cmd_out(["ffmpeg", "-hide_banner", "-filters"])
    need = {"ass": "captions (needs ffmpeg built with libass)", "loudnorm": "loudness measuring",
            "alimiter": "peak limiter", "atempo": "speed-up without pitch change",
            "colorspace": "iPhone HLG -> SDR BT.709"}
    for f, why in need.items():
        add(OK if re.search(rf"\s{f}\s", filters) else FAIL, f"ffmpeg filter: {f}", why)
    add(OK if re.search(r"\szscale\s", filters) else WARN, "ffmpeg filter: zscale",
        "PQ/HDR10 -> SDR tone-mapping" if re.search(r"\szscale\s", filters) else
        "missing: only needed for PQ/HDR10 footage (iPhone HLG works without it)")
    enc = cmd_out(["ffmpeg", "-hide_banner", "-encoders"])
    add(OK if "libx264" in enc else FAIL, "ffmpeg encoder: libx264", "H.264 output")
    conf = cmd_out(["ffmpeg", "-hide_banner", "-buildconf"])
    if conf and "harfbuzz" not in conf and "libass" in conf:
        add(WARN, "libass shaping", "ffmpeg build does not list harfbuzz; check that Arabic letters join in a test render")


def check_fonts() -> None:
    fonts = sorted(p.name for p in (SKILL_DIR / "assets" / "fonts").glob("*.ttf"))
    add(OK if fonts else FAIL, "bundled fonts", ", ".join(fonts) or "assets/fonts/ is empty")


def find_key() -> tuple[str, str]:
    if os.environ.get("ELEVENLABS_API_KEY", "").strip():
        return os.environ["ELEVENLABS_API_KEY"].strip(), "environment"
    for p in (SKILL_DIR / ".env", Path.cwd() / ".env"):
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip().startswith("ELEVENLABS_API_KEY="):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v, str(p)
    return "", ""


def check_key(ping: bool) -> None:
    key, where = find_key()
    if not key:
        add(FAIL, "ELEVENLABS_API_KEY", f"not set -> put ELEVENLABS_API_KEY=... into {SKILL_DIR / '.env'}")
        return
    add(OK, "ELEVENLABS_API_KEY", f"found in {where} (…{key[-4:]})")
    if ping:
        try:
            import requests
            r = requests.get("https://api.elevenlabs.io/v1/user", headers={"xi-api-key": key}, timeout=20)
            add(OK if r.status_code == 200 else FAIL, "ElevenLabs key test",
                {200: "key works", 401: "401: key wrong or expired"}.get(r.status_code, f"HTTP {r.status_code}"))
        except Exception as e:  # noqa: BLE001
            add(WARN, "ElevenLabs key test", f"could not reach the API: {e}")


def check_node() -> None:
    node = shutil.which("node")
    if not node:
        add(WARN, "Node.js (optional)", "not found; only needed for motion overlays with HyperFrames (Node 22+)")
        return
    v = cmd_out(["node", "--version"]).strip()
    major = int(re.sub(r"[^0-9.]", "", v).split(".")[0] or 0)
    add(OK if major >= 22 else WARN, "Node.js (optional)", v + ("" if major >= 22 else " - HyperFrames needs 22+"))
    add(OK if shutil.which("npx") else WARN, "npx (optional)", "for `npx hyperframes`")


def check_disk() -> None:
    free = shutil.disk_usage(Path.cwd()).free / 1e9
    add(OK if free >= 10 else WARN, "free disk here", f"{free:.0f} GB" + ("" if free >= 10 else " - 4K footage + renders can need 10+ GB"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Check everything the skill needs")
    ap.add_argument("--ping", action="store_true", help="test the ElevenLabs key (free account lookup)")
    args = ap.parse_args()
    check_python()
    check_ffmpeg()
    check_fonts()
    check_key(args.ping)
    check_node()
    check_disk()
    for st, what, detail in results:
        print(f"[{st}] {what:<36} {detail}")
    fails = [r for r in results if r[0] == FAIL]
    print("\nREADY" if not fails else f"\nNOT READY: {len(fails)} required item(s) missing")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
