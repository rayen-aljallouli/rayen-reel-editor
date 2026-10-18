"""Word-level transcription with ElevenLabs Scribe (cached).

Based on video-use by Browser Use (MIT, see LICENSE): transcribe.py + transcribe_batch.py,
merged into one script, with a dry-run mode and the API key looked up next to the skill.

Extracts mono 16 kHz audio with ffmpeg, uploads it with verbatim + word timestamps +
audio events + diarization, and writes the raw response to
<footage>/edit/transcripts/<video_stem>.json. A source that already has a transcript is
never uploaded again (Scribe costs credits).

Usage:
    python transcribe.py <video_or_folder> [more videos ...] --language ara
    python transcribe.py <folder> --dry-run          # list what would be uploaded, no API call
    python transcribe.py <video> --audio-track 1     # OBS: mic on track 1

Language: pass an ISO code when you know it (en, de, fr, ar/ara ...). For Tunisian Derja
or any Arabic dialect mixed with French/English, `--language ara` worked better than
auto-detect in real projects.
"""
from __future__ import annotations

import argparse
import array
import json
import math
import os
import subprocess
import sys
import tempfile
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common import SKILL_DIR, edit_dir_for, find_videos

SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"


def load_api_key() -> str:
    """Environment first, then .env next to the skill, then .env in the current folder."""
    v = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if v:
        return v
    for candidate in (SKILL_DIR / ".env", Path.cwd() / ".env"):
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, val = line.split("=", 1)
                if k.strip() == "ELEVENLABS_API_KEY" and val.strip().strip('"').strip("'"):
                    return val.strip().strip('"').strip("'")
    sys.exit("ELEVENLABS_API_KEY not found (environment, <skill>/.env or ./.env). "
             "Create a key at elevenlabs.io (Speech to Text permission) and put it in <skill>/.env")


def count_audio_tracks(video: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                          "-of", "csv=p=0", str(video)], capture_output=True, text=True)
    return len([ln for ln in out.stdout.splitlines() if ln.strip()])


def peak_dbfs(wav_path: Path) -> float:
    peak = 0
    with wave.open(str(wav_path), "rb") as w:
        while frames := w.readframes(1 << 16):
            samples = array.array("h", frames)
            peak = max(peak, max(samples), -min(samples))
    return 20 * math.log10(peak / 32768) if peak > 0 else float("-inf")


def extract_audio(video: Path, dest: Path, audio_track: int = 0) -> None:
    subprocess.run(["ffmpeg", "-y", "-i", str(video), "-map", f"0:a:{audio_track}", "-vn", "-ac", "1",
                    "-ar", "16000", "-c:a", "pcm_s16le", str(dest)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def call_scribe(audio: Path, api_key: str, language: str | None, num_speakers: int | None, model: str) -> dict:
    import requests
    data = {"model_id": model, "diarize": "true", "tag_audio_events": "true", "timestamps_granularity": "word"}
    if language:
        data["language_code"] = language
    if num_speakers:
        data["num_speakers"] = str(num_speakers)
    with open(audio, "rb") as f:
        resp = requests.post(SCRIBE_URL, headers={"xi-api-key": api_key},
                             files={"file": (audio.name, f, "audio/wav")}, data=data, timeout=1800)
    if resp.status_code == 401:
        raise RuntimeError("Scribe 401: the API key is wrong or expired")
    if resp.status_code == 403:
        raise RuntimeError(f"Scribe 403: the key lacks the Speech to Text permission or quota is used up: {resp.text[:300]}")
    if resp.status_code != 200:
        raise RuntimeError(f"Scribe returned {resp.status_code}: {resp.text[:500]}")
    return resp.json()


def transcript_path(edit_dir: Path, video: Path, audio_track: int = 0) -> Path:
    suffix = "" if audio_track == 0 else f".track{audio_track}"
    return edit_dir / "transcripts" / f"{video.stem}{suffix}.json"


def transcribe_one(video: Path, edit_dir: Path, api_key: str, language: str | None, num_speakers: int | None,
                   audio_track: int, model: str) -> Path:
    out_path = transcript_path(edit_dir, video, audio_track)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        return out_path
    n_tracks = count_audio_tracks(video)
    if n_tracks == 0:
        raise RuntimeError(f"{video.name} has no audio track")
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / f"{video.stem}.wav"
        extract_audio(video, audio, audio_track)
        peak = peak_dbfs(audio)
        if peak < -60.0:  # uploading silence costs the same as speech
            raise RuntimeError(f"track {audio_track} of {video.name} is silent (peak {peak:.1f} dBFS), not uploading"
                               + (f"; the file has {n_tracks} audio tracks, try --audio-track" if n_tracks > 1 else ""))
        payload = call_scribe(audio, api_key, language, num_speakers, model)
    out_path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    words = sum(1 for w in payload.get("words", []) if w.get("type") == "word")
    print(f"  + {video.name}: {words} words, language {payload.get('language_code')} "
          f"({payload.get('language_probability', 0):.2f}) in {time.time() - t0:.0f}s -> {out_path.name}")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Word-level transcription with ElevenLabs Scribe (cached per source)")
    ap.add_argument("inputs", nargs="+", type=Path, help="video files and/or folders of videos")
    ap.add_argument("--edit-dir", type=Path, default=None, help="default: <footage folder>/edit")
    ap.add_argument("--language", default=None, help="ISO language code (e.g. en, de, ara). Omit to auto-detect.")
    ap.add_argument("--num-speakers", type=int, default=None)
    ap.add_argument("--audio-track", type=int, default=0, help="zero-based audio track (default 0)")
    ap.add_argument("--model", default="scribe_v1", help="Scribe model id (default scribe_v1)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true", help="only list what would be uploaded")
    args = ap.parse_args()

    videos: list[Path] = []
    for inp in args.inputs:
        inp = inp.expanduser().resolve()
        if not inp.exists():
            sys.exit(f"not found: {inp}")
        videos += find_videos(inp)
    if not videos:
        sys.exit("no video files found")
    edit_dir = edit_dir_for(args.inputs[0].expanduser().resolve(), args.edit_dir)

    cached = [v for v in videos if transcript_path(edit_dir, v, args.audio_track).exists()]
    pending = [v for v in videos if v not in cached]
    for v in cached:
        print(f"  cached: {v.name}")
    if not pending:
        print("nothing to upload, all transcripts cached")
        return
    total_min = 0.0
    for v in pending:
        d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(v)],
                           capture_output=True, text=True).stdout.strip()
        total_min += float(d or 0) / 60
    print(f"to upload: {len(pending)} file(s), {total_min:.1f} min of audio -> {edit_dir / 'transcripts'}")
    if args.dry_run:
        for v in pending:
            print(f"  would upload: {v.name}")
        return

    api_key = load_api_key()
    errors = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(transcribe_one, v, edit_dir, api_key, args.language, args.num_speakers,
                            args.audio_track, args.model): v for v in pending}
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception as e:  # noqa: BLE001
                errors.append((futs[fut], str(e)))
                print(f"  x {futs[fut].name}: {e}")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
