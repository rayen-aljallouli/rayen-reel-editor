# edl.json and timeline.json

## edl.json (you write it, in `edit/`)

```json
{
  "sources": {"A": "../IMG_4246.MOV", "B": "../broll.mp4"},
  "speed": 1.06,
  "pad": [0.06, 0.08],
  "max_gap": 0.35,
  "zoom": {"center_x": 0.5, "center_y": 0.4},
  "grade": "none",
  "denoise": false,
  "audio_track": 0,
  "ranges": [
    {"source": "A", "start": 7.30, "end": 11.00, "beat": "HOOK", "quote": "...", "reason": "last clean take"},
    {"source": "A", "start": 41.20, "end": 56.98, "beat": "POINT", "zoom": 1.08},
    {"source": "A", "start": 241.94, "end": 246.30, "beat": "CTA", "hold": 0.6},
    {"source": "B", "start": 60.0, "end": 63.0, "beat": "OUTRO", "snap": false, "mute": true}
  ]
}
```

Ranges play in list order (beat order, not source order). Times are **source seconds from
takes_packed.md**; you do not need to be exact, `build_cut.py` snaps them.

| Field | Default | Meaning |
|---|---|---|
| `sources` | required | id -> path (relative to `edit/` or absolute) |
| `transcripts` | `transcripts/<stem>.json` | id -> transcript path, if named differently |
| `speed` | 1.0 | whole-reel speed. atempo keeps the pitch. 1.06–1.08 worked on real reels |
| `pad` | [0.06, 0.08] | seconds kept before the first / after the last word of a range (30–200 ms window) |
| `max_gap` | null | split ranges at inner silences longer than this (0.3–0.4 = snappy). null keeps pauses |
| `zoom` | 0.5 / 0.4 | crop centre for every range (0–1). 0.4 keeps eyes in the upper third |
| `grade` | none | `none`, `lift` (brighter midtones), `punch`, `warm`, `cool`, or a raw ffmpeg filter |
| `denoise` | false | highpass 80 Hz + afftdn on the voice. A/B it first; it can sound watery |
| `audio_track` | 0 | which audio track carries the voice |
| `hdr` | auto | HDR sources: `auto` (HLG -> colorspace conversion, PQ -> zscale tone-map), `convert`, `tonemap`. Output is always tagged BT.709 |

Per range:

| Field | Default | Meaning |
|---|---|---|
| `source`, `start`, `end` | required | where the range comes from |
| `beat`, `quote`, `reason` | | for you and the log; `beat` names the segment in timeline.json |
| `zoom` | 1.0 | punch-in factor (1.08 subtle, 1.15–1.3 emphasis) |
| `center_x`, `center_y` | global | per-range crop centre (e.g. speaker sits off-centre in one take) |
| `snap` | true | false = take start/end exactly as written (B-roll, gestures, no transcript) |
| `keep_pauses` | false | true = ignore `max_gap` for this range (dramatic pause) |
| `hold` | 0 | keep up to N s after the last word (room for an end card, a smile) |
| `freeze_tail` | 0 | freeze the last frame N s (silent), e.g. under a follow card |
| `mute` | false | silence this range (B-roll under music) |

### What build_cut.py does with it

1. Finds the words whose middle lies inside each range, puts the start `pad[0]` before the
   first word and the end `pad[1]` (or `hold`) after the last, but never into the neighbouring
   word. Warns when neighbours touch (connected speech: the cut may click or chop a sound).
2. With `max_gap`, splits the range at longer inner silences (beats become `POINT_1`, `POINT_2`).
3. Rounds every segment to whole frames at 30 fps.
4. Picture: seeks the camera file at `start + av_offset`, crops to 9:16 with the zoom, scales to
   1080x1920, converts HDR to SDR Rec.709 (iPhone HLG: matrix/primaries conversion, transfer kept),
   tags BT.709, constant 30 fps, libx264 CRF 17 (`--draft`: ultrafast CRF 26).
   Segments are cached by their parameters; changing one range rebuilds only that segment.
5. Sound: the source's audio track as a 48 kHz wav (`edit/audio_src/`), sliced per segment,
   30 ms fades, atempo for speed, concatenated sample-exactly.
6. Writes `edl.snapped.json` (what was actually cut, with warnings), `base.mp4` (picture only),
   `audio.wav`, `cut.mp4` (rough cut with sound, for a quick look) and `timeline.json`.

Punch-in tips: a jump cut inside one take is less visible when the zoom changes across it
(1.0 -> 1.08 -> 1.0). Two consecutive ranges with the same zoom and similar framing look like a
glitch; either change the zoom or cover the cut with an overlay entrance.

## timeline.json (written by build_cut.py)

```json
{"total": 49.6, "fps": 30, "speed": 1.06, "width": 1080, "height": 1920,
 "cuts":  [{"i": 0, "beat": "HOOK", "source": "A", "src_start": 7.24, "src_end": 11.08,
            "out_start": 0.0, "out_end": 3.6233, "zoom": 1.0}],
 "words": [{"text": "يا", "cut": 0, "beat": "HOOK", "src": 7.30, "start": 0.057, "end": 0.132}]}
```

Everything after the cut is timed from this file: captions use `words`, overlays and SFX cues
use output seconds. To time an overlay on a word, look the word up here (`start`). After any
EDL change, re-run captions and re-check overlay/cue times: output times move, source times
(`src`) do not.
