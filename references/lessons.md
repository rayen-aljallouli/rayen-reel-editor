# Lessons from real reels

Each item happened on a real talking-head reel (phone footage, Tunisian Derja + English,
1080x1920). The scripts already contain the fixes; this file explains what to look for when a
render still looks or sounds wrong.

## Picture and sync

- **Voice ahead of the lips by ~0.3 s.** The phone file started its audio track 0.317 s after
  the video (an edit list). The transcript and the extracted wav start at the first audio sample,
  so cutting the picture at the same numbers put it 0.317 s early after every cut. It was only
  noticed on the phone, after eight preview rounds. Fix: `probe.py` reports the offset and
  `build_cut.py` seeks the picture at `t + offset`. After the fix, sync measured −19 / +37 / +9 ms
  at three points. If sync still looks off, measure it (compare a plosive like "p"/"b" in
  `timeline_view.py` of the render and of the source) before changing anything.
- **iPhone HDR: overlays vanished in the real HyperFrames render.** iPhones record HDR HLG by
  default (10-bit, `color_transfer=arib-std-b67`, BT.2020). The cut kept those tags, so HyperFrames
  auto-promoted the render to HDR and used its "layered composite" path, where every overlay that
  is not a `.clip` element is painted UNDER the video. The overlays silently disappeared; the
  snapshots still looked fine, only the real render was wrong. Fix (now in `build_cut.py`): after
  scaling, `format=yuv420p10le,colorspace=ispace=bt2020ncl:iprimaries=bt2020:itrc=bt709:irange=tv`
  `:space=bt709:primaries=bt709:trc=bt709:range=tv:format=yuv420p` and encode with
  `-colorspace bt709 -color_primaries bt709 -color_trc bt709`. HLG is SDR-compatible, so keeping
  the transfer and converting only matrix/primaries looks natural; zscale tone-mapping
  (hable/mobius) looked too orange and dark. PQ/HDR10 footage still gets zscale tone-mapping.
  Check: `probe.py` flags HDR sources, `qc.py` flags HDR tags on a render, and a HyperFrames
  render log must not contain "HDR auto-promotion" or `"useLayeredComposite":true`.
  Simplest: record in SDR (iPhone: Settings > Camera > Record Video > HDR Video off).
- **Variable frame rate.** Phones record ~29.97–30.0 fps that drifts. Output is forced to a
  constant 30 fps per segment; segment lengths are counted in frames, not seconds.
- **Different light within one take.** The first 24 s of a car recording were noticeably more
  yellow than the rest (sunnier moment). Fix: a separate grade for those ranges, chosen from a
  side-by-side still of 2–3 options. Show options as stills before regrading a whole reel.
- **Script glances.** A speaker reading from a phone looks down right after a sentence. Ending
  segments ~0.06–0.12 s after the last word removed most glances. A glance *during* a word cannot
  be cut away without cutting connected speech; say so instead of hiding it badly.

## Cuts and sound

- **Pops at cuts.** Every segment gets 30 ms fades; picture and sound are cut separately and the
  sound is concatenated sample-exactly (an AAC concat drifts and clicks). `qc.py` flags sharp
  jumps at cut points; listen there.
- **Word clipped at a cut.** A last word ("أخيرًا") was cut short because the next sound followed
  after only ~0.2 s. Check the first and last word of every segment in the preview; if a word
  is clipped, use another take or widen the pad on that side.
- **Fillers the transcript left out.** Loud bursts in "silent" gaps turned out to be the speaker's
  own "ääh" fillers, not noise. When a gap stays in the cut, look at its waveform.
- **"Make the pauses more compact."** The most common first feedback. Lead ~0.10 s before the
  first word, tail ~0.06–0.08 s after the last, and remove breaths of 0.4 s or more inside a take
  (`max_gap` 0.35–0.4). Before micro-cutting a pause, confirm it is real silence, not a soft sound.
- **Voice sounded different after loudness processing.** loudnorm fell back to its dynamic mode
  (raw voice at −24 LUFS needed +10 dB and its peaks would have passed −1 dBTP) and audibly
  changed the voice. Fix: plain gain to −16 LUFS + a peak limiter (`mix_audio.py`).
- **Music the creator did not like.** A generated bed was removed after the first preview. Ask
  early; voice + SFX without music is a normal result, and licensed music can be added in the app.
- **SFX that mock.** A meme sound was planned on a sentence about someone losing their job; the
  creator moved it elsewhere. Sound effects comment on the content: keep them off sensitive lines.

## Captions and text

- **Arabic letters disconnected or words in reverse order.** Text drawn with tools that do not
  shape Arabic. Everything here goes through libass (HarfBuzz + FriBidi), styles use
  `Encoding -1`, RTL lines start with an RLM mark. Never draw Arabic with PIL.
- **"الـ" glued to an English word flipped the order** ("motivation letter" read backwards).
  `الـ` before a Latin word is now its own unit.
- **A lone "و" next to an English word looked like a "g"** in one Arabic font. Keep "و" with the
  Arabic word it belongs to.
- **ASR spelling vs how the speaker writes.** Brand names ("cloud code" -> Claude Code) and dialect
  spellings (متاع not بتاع) needed fixes in every reel. Collect them in `captions.json` `replace`
  and reuse the list for the next reel.
- **Captions covered.** By the app interface (outside the safe zone) or by an overlay drawn after
  them. Captions are always the last layer, inside y 230–1440, out of the right 230 px.
- **Text hanging over a layout change.** A caption block that stays on screen while the layout
  moves looks broken. End blocks before big changes (`hide` windows) or let them follow.
- **Emoji.** libass and headless browsers often have no colour emoji. Avoid emoji in burned-in
  text; draw icons as images or shapes.

## Process

- **Reels take several rounds.** One reel went through 9 renders: framing changed and changed
  back, a sound was replaced twice, the ending was extended and removed again, and the lip-sync
  issue above was found last. Keep every version (`preview_vN`, `final_vN`): twice the creator
  asked for the previous version back.
- **Ask before deciding** things that change the reel's message or length. Decide the technical
  rest yourself and list those decisions in the hand-off message.
- **Mock-ups use fictional names** (companies, people) unless the real one is the point and the
  user confirmed it.
- **Videos fed into HyperFrames** render more reliably with frequent keyframes: re-encode assets
  with `-g 30` before using them in a composition.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Lips and voice drift apart after cuts | A/V start offset ignored, or segments with a different frame rate | `probe.py` (offset), rebuild with `build_cut.py`; never mix in clips cut elsewhere |
| Click/pop at a cut | Cut in connected speech, or a fade missing | Read `build_cut.py` warnings, move the cut into a pause, check `qc.py` click score |
| Arabic letters disconnected | Text drawn without shaping (PIL, old libass) | Use `captions.py`/`render.py` text; `check_setup.py` for libass + HarfBuzz |
| Arabic words in the wrong order | Style without `Encoding -1`, no RLM | Regenerate with `captions.py` (both are built in) |
| Captions hidden behind the app UI | Outside the safe zone | `bottom` ≤ 1440, keep x ≤ 850; check `qc_safe_*.jpg` |
| Captions hidden by an overlay | Overlay drawn after captions | Only render via `render.py` (captions last) |
| Washed out / neon / too orange picture | iPhone HDR not converted, or tone-mapped | Rebuild with `build_cut.py` (HLG -> BT.709 colorspace conversion), or record SDR |
| Overlays missing in a HyperFrames render, snapshots fine | HDR/HLG-tagged video in the composition -> HDR auto-promotion -> layered composite paints overlays under the video | Use the BT.709 `base.mp4` from `build_cut.py`; render log must show `"useLayeredComposite":false` |
| Voice sounds pumped or different | Dynamic loudness processing | `mix_audio.py` (plain gain + limiter) |
| `ffmpeg: command not found` | ffmpeg not installed / not on PATH | Install it (see the guide), open a new terminal |
| 401 from ElevenLabs | Wrong or expired key | New key in `<skill>/.env`, `check_setup.py --ping` |
| 403 from ElevenLabs | Key without Speech to Text permission, or quota used | Edit the key's permissions / plan on elevenlabs.io |
| Transcript in the wrong language | Auto-detect on mixed speech | Delete that transcript, re-run with `--language` (costs credits again) |
| Render very slow | 4K HEVC decode | Normal for 4K; use `build_cut.py --draft` for cut checks |
