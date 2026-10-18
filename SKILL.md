---
name: rayen-reel-editor
description: >-
  Edits vertical talking-head reels (1080x1920 for Instagram Reels, TikTok, YouTube Shorts) from
  raw phone footage, by conversation. Transcribes word by word, proposes a storyboard and waits
  for approval, cuts retakes, fillers and pauses on word boundaries, burns in karaoke captions
  (any language, including Arabic or Tunisian Derja mixed with English, right-to-left done
  right), adds simple text/image overlays, generated sound effects and an optional ducked music
  bed, then renders previews, checks them itself and iterates to a final file. Use it whenever
  someone wants to edit, cut, caption or finish a short vertical video of themselves talking:
  "edit my reel", "cut this take", "remove the retakes", "add captions to my video", "make this
  shorter", "turn this recording into a TikTok", or when they drop .MOV/.MP4 phone footage and
  ask for a short-form video.
---

# Talking-head reel editor

You edit like a careful human editor who can read the transcript to the hundredth of a second.
The user brings raw footage (usually one phone recording with several takes per sentence); you
deliver a 1080x1920 reel with tight cuts, captions, a few overlays and clean sound.

`S` = the folder that contains this file. `PY` = `S/.venv/bin/python` if it exists, else `python3`.
Run every script as `$PY $S/scripts/<name>.py`. All outputs go to `<footage folder>/edit/`,
never into `S`.

## Hard rules

1. **No cut before the storyboard is approved.** Step 2 ends with a question and you stop.
2. **Word-level transcript, cached.** Never re-transcribe a source that already has
   `edit/transcripts/<name>.json`. Never call the API just to test. Transcription costs money:
   say how many minutes you will upload before the first upload.
3. **Cut on word boundaries with padding** (default 60 ms before, 80 ms after), never inside a
   word. `build_cut.py` snaps every edge; read its warnings about connected speech.
4. **Sound:** 30 ms fades at every edge, sample-exact PCM concat, picture and sound the same
   length to the frame. `build_cut.py` does this; never hand-roll a single-pass cut.
5. **Lip sync and HDR:** always run `probe.py`. Phones often start the audio track a few hundred
   ms after the video; `build_cut.py` shifts the picture by that offset. iPhones record HDR HLG;
   `build_cut.py` converts it to SDR and tags BT.709. Never feed the raw camera file to
   HyperFrames (HDR auto-promotion paints overlays under the video). If lips look early/late,
   measure (`timeline_view.py` on the render vs the source), do not guess.
6. **Captions last, inside the safe zone.** Nothing important above y=230, below y=1440 or in
   the right 230 px. Captions are the last filter, after every overlay.
7. **Right-to-left text only through libass** (`captions.py`, `render.py` text overlays) or a
   browser (HyperFrames). Never draw Arabic with PIL: letters come out disconnected.
8. **The speaker's words stay their words.** Shorten by dropping whole sentences or takes,
   never by rewording. Caption fixes only correct transcription errors and spelling.
9. **Loudness:** about −16 LUFS integrated, true peak ≤ −1 dBTP, via `mix_audio.py` (plain gain
   + limiter; loudnorm's dynamic mode audibly changed a voice once).
10. **Check before you show.** Run `qc.py` on every render and Read both sheets it writes.
    Fix and re-render up to 3 times; then show the result and list what is still off.
11. **Every render is a new file** (`preview_vN.mp4`, `final_vN.mp4`). Never overwrite a
    version the user has seen. Log each round in `edit/project.md`.
12. **No copyrighted audio.** SFX come from `make_sfx.py` (or files the user gives you). Music
    only if the user supplies a track they may use; otherwise suggest adding it in the app.
13. **Never invent facts on screen** (numbers, names, quotes, logos). On-screen text is the
    user's words or text they approved; logos only from files they provide.

## Cold start

1. If `edit/project.md` exists, read it and summarise the last session in one sentence.
2. First run on a machine, or when anything fails: `$PY $S/scripts/check_setup.py`. If it says
   NOT READY, fix what it lists (guide the user; never print the API key).

## The flow

### Step 1: Inventory and transcript

```bash
$PY $S/scripts/probe.py <footage>                      # A/V offset, HDR, fps, size -> edit/inventory.json
$PY $S/scripts/transcribe.py <footage> --dry-run       # what would be uploaded, minutes
$PY $S/scripts/transcribe.py <footage> --language <code>   # cached; e.g. en, de, fr, ara
$PY $S/scripts/pack_transcripts.py --edit-dir <footage>/edit   # -> edit/takes_packed.md
```
Ask for the language if you cannot tell (Arabic dialect mixed with French/English: `ara`).
Read `takes_packed.md` fully. Use `timeline_view.py <video> <start> <end>` only at decision
points (which of two takes, is there a glance at the script, a cough in a gap).

### Step 2: Storyboard, then wait

Write `edit/storyboard.md` using `references/storyboard.md`: beats in order, the chosen take
for each with source timestamps, the quote, what gets cut (retakes, false starts, fillers,
long pauses) and the overlay/SFX idea per beat; estimated runtime; at most three open
questions (target length, caption style, music). Show a short summary and the file path, then
**stop and wait for the user's OK or changes.** Apply changes to the storyboard, not to video.

### Step 3: Build the cut

Write `edit/edl.json` from the approved storyboard (schema: `references/edl.md`).
```bash
$PY $S/scripts/build_cut.py <footage>/edit/edl.json --dry-run    # snapped ranges, runtime, warnings
$PY $S/scripts/build_cut.py <footage>/edit/edl.json              # base.mp4, audio.wav, cut.mp4, timeline.json
```
`max_gap` tightens pauses inside a take (0.3–0.4 s feels snappy). Punch-ins are per range
(`zoom` 1.08–1.3); alternating 1.0/1.08 across a jump cut hides it. Speed 1.0–1.1 (1.06 sounded
natural). If the dry run warns about connected speech, look at that cut before building.

### Step 4: Captions

```bash
$PY $S/scripts/captions.py <footage>/edit --style karaoke --keywords "word1,word2"
```
Defaults: Tajawal ExtraBold, white, one accent keyword per block (calm yellow `#E9C46A`),
blocks of up to 4 words, bottom edge at y=1440. Spelling fixes, hidden ranges, colours and
sizes go in `edit/captions.json`. Details and RTL rules: `references/captions.md`.

### Step 5: Overlays, SFX, music

- Overlays in `edit/overlays.json`: text cards (`hook`, `title`, `pill`, `label`), PNG images,
  alpha videos. Keep them above the head (y 230–600) or beside it, never on the face, one new
  element at a time. Schema and placement: `references/overlays-sfx.md`.
- `$PY $S/scripts/make_sfx.py <footage>/edit` writes whoosh, pop, tick, click, ping, thud,
  riser, hit, typing to `edit/sfx/`. Cue them in `edit/cues.json` or with `"sfx"` on an overlay.
- Motion graphics beyond that: build them with HyperFrames (`npx hyperframes`, Node 22+), render
  a transparent WebM and add it as a `video` overlay. If footage goes into a composition, use
  `edit/base.mp4` and check the render log has no "HDR auto-promotion". See `references/overlays-sfx.md`.
- `$PY $S/scripts/mix_audio.py <footage>/edit [--music <file>]` -> `edit/mix.wav` at −16 LUFS.

### Step 6: Preview, self-check, iterate, final

```bash
$PY $S/scripts/render.py <footage>/edit --preview       # -> edit/preview_vN.mp4
$PY $S/scripts/qc.py <footage>/edit/preview_vN.mp4      # numbers + verify/qc_cuts_*.jpg + qc_safe_*.jpg
```
Read both QC images: flashes or jumps at cuts, a click score flagged, text outside the zone,
captions covered, overlays on the face. Fix, re-render, re-check. Then give the user the file
path (on WSL also the Windows path `\\wsl.localhost\<distro>\...`), the duration, the number of
cuts and the loudness, and ask for feedback.

**Feedback rounds.** Apply exactly what was asked, nothing else. Re-run only the steps that
depend on the change (EDL change: build_cut, captions, mix, render; caption change: captions,
render; SFX/music: mix, render). Expect several rounds; that is normal. When the user says it is
final: `render.py --final`, `qc.py` on it, append the session to `edit/project.md`
(`references/project-log.md`), and report the final path.

## When something looks wrong

`references/lessons.md` lists the failures seen on real reels and their fixes: lip-sync drift,
pops at cuts, disconnected Arabic letters, captions hidden by the app UI or by overlays, iPhone
HDR (orange picture, overlays vanishing in HyperFrames), voice that sounds changed after
loudness processing, fillers the transcript left out, script glances, frame-rate mismatches.

## Files

```
scripts/check_setup.py      requirements check (exit 1 if not ready)
scripts/probe.py            inventory, A/V offset, HDR/VFR flags
scripts/transcribe.py       ElevenLabs Scribe, word level, cached, --dry-run
scripts/pack_transcripts.py transcripts -> takes_packed.md (phrase lines with times)
scripts/timeline_view.py    filmstrip + waveform PNG for one time range (drill-down)
scripts/build_cut.py        EDL -> base.mp4, audio.wav, cut.mp4, timeline.json
scripts/captions.py         timeline.json -> captions.ass (karaoke / plain / word)
scripts/make_sfx.py         generated SFX bank (numpy, royalty-free)
scripts/mix_audio.py        voice + SFX + music (ducked) -> mix.wav at -16 LUFS
scripts/render.py           base + overlays + captions (last) + mix -> preview/final mp4
scripts/qc.py               duration, loudness, cut sheet, safe-zone sheet
references/storyboard.md    storyboard template and how to choose takes
references/edl.md           edl.json and timeline.json fields
references/captions.md      caption styles, config, RTL/Arabic rules
references/overlays-sfx.md  overlays.json, text styles, SFX use, music, HyperFrames
references/lessons.md       real failures and fixes, troubleshooting
references/project-log.md   project.md template
```
