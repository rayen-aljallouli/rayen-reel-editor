# Captions

`captions.py <edit>` reads `timeline.json` (+ optional `captions.json`) and writes
`captions.ass`. `render.py` burns it in as the very last filter.

## Styles

| Style | Looks like | Good for |
|---|---|---|
| `karaoke` (default) | block of up to 4 words shown dimmed (~38 %), each word lights up when spoken, one keyword in the accent colour, slightly bigger | talking heads, the style of the reels this skill was built on |
| `plain` | whole block at once, keyword highlighted | calmer, educational |
| `word` | one big word at a time | very fast, punchy hooks |

Ask once (in the storyboard questions) if the user has no preference; default to karaoke.

## captions.json

```json
{
  "style": "karaoke",
  "keywords": ["Claude Code", "مجاني", "CV"],
  "auto_keyword": true,
  "replace": {"cloud code": "Claude Code", "بتاع": "متاع"},
  "at": {"50.50": "متع", "12.04": ""},
  "hide": [[0.0, 2.4]],
  "size": 66, "key_size": 74,
  "accent": "#E9C46A", "color": "#FFFFFF",
  "bottom": 1440, "left": 230, "right": 850,
  "max_units": 4, "max_chars": 22,
  "upper": false,
  "font": "Tajawal ExtraBold", "font_file": null
}
```

- `keywords`: checked in order; the first that appears in a block is highlighted. Without a
  match, `auto_keyword` highlights the longest non-function word. One keyword per block.
- `replace`: exact word replacements (after punctuation is stripped). Use for words the
  transcriber always gets wrong (brand names, dialect spellings the speaker prefers).
- `at`: fix one occurrence, keyed by the word's **source** time (`src` in timeline.json, two
  decimals). Empty string drops the word. Source keys survive re-cuts.
- `hide`: output-time windows without captions (e.g. while a big hook card covers the zone).
- Sizes are like CSS font sizes at 1080x1920 (the script converts to ASS units).
- `font`/`font_file`: any TTF/OTF; put the file path in `font_file` and the family name in
  `font`. It must contain every script used (Tajawal covers Arabic + Latin).
- `upper`: uppercase Latin-only words (Arabic has no case).

Flags override the file: `--style`, `--keywords "a,b"`, `--accent`, `--size`, `--bottom`,
`--no-auto-keyword`.

## Chunking rules (built in)

- Break on punctuation, at every cut, on pauses longer than 0.6 s, at 4 units or ~22 characters.
- A function word (في, على, باش, the, of, to, de…) never ends a block; it moves to the next one.
- `الـ` + Arabic word stay one unit. `الـ` before an English word is its own unit.
- Consecutive English words merge into one unit ("Claude Code", "motivation letter").
- Lines are measured with the real font; a block that does not fit becomes two lines, and if a
  line is still too wide the whole block shrinks (never below 60 %).
- Timing: a block appears 50 ms before its first word and stays until the next block, or 0.5 s
  after its last word when the next one is more than 0.9 s away.

## Right-to-left (Arabic, Derja, Hebrew, Persian, Urdu)

What makes RTL captions render correctly, all handled by the scripts:
1. Text is drawn by libass, which shapes with HarfBuzz (joined letters, correct forms) and orders
   with FriBidi. PIL without raqm, or ImageMagick without the right setup, draw Arabic as
   disconnected letters in reverse order. Do not draw Arabic text in Python images.
2. Every style uses `Encoding -1` (libass then detects the base direction; with the usual `1`
   it forces left-to-right and a mixed line reads in the wrong order).
3. Every RTL line starts with an RLM mark (U+200F), so a line that begins with an English word
   ("Claude Code باش…") still runs right-to-left.
4. The karaoke colour changes sit between words, never inside one, so shaping is not broken.

If a caption still looks wrong, render one frame and look at it at full size:
`ffmpeg -ss <t> -i preview_vN.mp4 -frames:v 1 check.png`. Disconnected letters mean the ffmpeg
build lacks HarfBuzz in libass (`check_setup.py` warns); reversed word order means a style
without `Encoding -1` or a missing RLM.

Spelling: write the dialect the way the speaker writes it. Ask them for their usual spellings of
recurring words once and put them in `replace`.

## Safe zone

1080x1920: keep captions between y=230 and y=1440 and out of the right 230 px. The default box
is x 230–850 (centred) with the bottom edge at y=1440. Raise `bottom` (e.g. 1300) if the
speaker's hands or a product sit there; never go lower than 1440. `qc.py` draws the zone on
sample frames; check it on every preview.
