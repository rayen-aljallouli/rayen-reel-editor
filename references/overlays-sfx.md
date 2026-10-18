# Overlays, SFX and music

## overlays.json (in `edit/`, output-timeline seconds)

```json
[
  {"type": "text", "text": "Who is the richest man?", "start": 0.0, "end": 2.4, "style": "hook",
   "y": 420, "accent_words": ["richest"], "sfx": "whoosh"},
  {"type": "text", "text": "FREE", "start": 5.1, "end": 6.8, "style": "pill", "x": 540, "y": 560, "sfx": "pop"},
  {"type": "image", "file": "assets/logo.png", "start": 8.0, "end": 10.5, "x": 540, "y": 480,
   "width": 320, "anim": "pop", "sfx": "pop"},
  {"type": "video", "file": "animations/slot_1/render.webm", "start": 12.0, "end": 16.0,
   "x": 540, "y": 960, "width": 1080}
]
```

Common keys: `start`, `end`, `x`/`y` (centre of the element, px), `sfx` (+ `sfx_gain`,
`sfx_offset`), `anim`. Files are relative to `edit/`.

### Text styles (drawn by libass, so RTL text is shaped correctly)

| Style | Look | Use |
|---|---|---|
| `hook` | 92 px white, dark outline + shadow, accent words in the accent colour, wraps to the safe width | the first 1–3 s: the line that stops the scroll |
| `title` | 64 px white on a dark box | a topic, a name, a tool |
| `pill` | 54 px dark text on an accent box, pops in | one word: FREE, 3 STEPS, ✓ DONE |
| `label` | 44 px white on a dark box | small notes, sources |

`anim`: `pop` (default for pill/title), `fade` (default for hook/label), `slide`, `none`.
`accent_words`: words drawn in the accent colour (`render.py --accent "#E9C46A"`).
`max_width`: px; default is the widest box centred on `x` that stays inside x 60–850.

### Images

PNG with transparency. `width` in px, height follows. `anim`: `pop` (scale with a small
overshoot + fade), `fade`, `none`. Logos only from official files the user provides; never draw
or recreate a logo.

### Motion overlays (HyperFrames, optional, Node 22+)

For anything that moves beyond pop/fade (a UI mock-up, a counter, a chart, a typed terminal),
build a small HTML composition and render it with transparency:

```bash
mkdir -p <edit>/animations/slot_1 && cd <edit>/animations/slot_1
npx hyperframes init . --resolution portrait --non-interactive
# write the composition (index.html), keep it inside the safe zone, transparent background
npx hyperframes lint
npx hyperframes render --format webm --output render.webm
```

Then add `{"type": "video", "file": "animations/slot_1/render.webm", ...}` to overlays.json.

If you put footage inside a HyperFrames composition (instead of overlaying a transparent render
in `render.py`), use the BT.709 `edit/base.mp4`, never the camera file: an HDR/HLG-tagged video
makes HyperFrames auto-promote to HDR and paint non-`.clip` overlays UNDER the video. Snapshots
still look right; only the real render is wrong. After every HyperFrames render, check its log:
"HDR auto-promotion" or `"useLayeredComposite":true` means this happened.
If HyperFrames' own Claude Code skills are installed, follow them for the composition. Several
independent animations can be built in parallel by sub-agents, one folder each. Time the
animation's key moment to the spoken word: look the word up in timeline.json and start the
overlay `reveal_time` earlier.

### Placement and timing

- The head space (y 230–600) is the natural place for overlays; beside the head works too.
  Never cover the face or the mouth.
- One new element at a time. Give text time to be read: about 1 s per 3 words, minimum 1 s.
- Captions sit at the bottom of the zone; hide them (`captions.json` `hide`) while a big card
  covers that area, rather than stacking text on text.
- Enter on the word that names the thing, leave before the next idea.
- Every overlay must stay inside the safe zone (`render.py` warns, `qc.py` shows it).

## SFX

`make_sfx.py <edit>` generates (numpy, deterministic, royalty-free) into `edit/sfx/`:

| Sound | Length | Typical use |
|---|---|---|
| `hit` | 1.2 s | the very first frame of the hook |
| `whoosh` | 0.6 s | layout changes, a card flying in, a punch-in |
| `swoosh_up` | 0.5 s | something rising or appearing from below |
| `riser` | 1.6 s, peak at the end | build-up into a payoff word (cue `t` = the word) |
| `pop` | 0.14 s | pills, stickers, images popping in |
| `tick` | 0.04 s | counters, list items |
| `click` | 0.14 s | a cursor click in a UI mock-up |
| `typing` | 1.0 s | typed text |
| `ping` | 0.9 s | a check mark, success |
| `thud` | 0.45 s | a stamp, a big number landing |

`sfx/sampler.wav` plays them all in a row. Users can drop their own wav files into `edit/sfx/`
and cue them by file name (only sounds they have the rights to).

`cues.json`: `[{"t": 0.0, "sfx": "hit", "gain": 0.8}, {"t": 4.13, "sfx": "whoosh"}]`.
`t` is when the loudest moment of the sound lands. Keep it sparse: a sound per visual event,
not per word. Gains 0.3–1.0 on top of `--sfx-db -13`.

## Music

- Only a track the user is allowed to use (their own, a licensed library, a royalty-free track
  whose licence covers social media). Otherwise recommend adding music inside Instagram/TikTok
  (licensed there, volume slider in the app) and deliver voice + SFX.
- `mix_audio.py <edit> --music track.mp3 --music-db -24 --duck 0.45 [--music-start 12.0]`:
  the bed is looped if short, faded out over the last 1.5 s and pushed down to ~55 % under speech.
- If the user dislikes the music, remove it (`mix_audio.py` without `--music`); a reel with clean
  voice + SFX is a normal result.
