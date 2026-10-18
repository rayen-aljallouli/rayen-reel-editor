# Storyboard (step 2)

The storyboard is the plan the user approves before anything is cut. It is cheap to change;
a rendered cut is not.

## Reading the material

- `edit/takes_packed.md`: one line per phrase, `[start-end]` in source seconds. Phrases break on
  silences of 0.5 s or more, so a retake usually starts a new line with the same words.
- `edit/inventory.json` notes (A/V offset, HDR, landscape).
- `edit/project.md` from earlier sessions, if any.

## Choosing takes

- People repeat a sentence until they are happy. **The last complete take is usually the best**,
  but read them all: an earlier take can be the only one without a slip.
- A take that restarts mid-sentence ("so the… so the thing is") is a false start: keep only the
  restart, or splice the clean half of one take with the clean half of another at a pause.
- Fillers (euh, ääh, um, يعني used as a filler) go when they sit in a pause. Inside connected
  speech they stay; cutting there clicks or sounds chopped.
- **Gaps can hide sounds.** The transcript can leave out fillers, breaths, coughs and lip smacks.
  When a pause will stay in the cut, look at it with `timeline_view.py` (loud waveform in a
  "silent" gap = a sound you would keep by accident).
- Script glances: speakers reading from a phone look down after a sentence. Ending the cut a
  little earlier (about 0.1 s after the last word) removes most of them; check suspicious tails
  with `timeline_view.py`.
- Keep the speaker's words. Shorten by dropping whole sentences or points, never by rewording.

## Length

Ask for a target if the user has not given one (most talking-head reels land at 30–60 s).
Runtime ≈ sum of kept speech ÷ speed, plus the tails. Offer concrete options when over target:
"drop beat 5 (−6 s) or beat 7 (−4 s)".

## Template (write to edit/storyboard.md)

```markdown
# Storyboard: <title>

Source: <file(s)>, <duration>, <resolution>, A/V offset <ms>, HDR <yes/no>
Target: ~<N> s · speed <1.0-1.1> · captions: <karaoke/plain/word> · music: <none/user track>

| # | Beat  | Take (source @ start-end) | Says                         | Cut                       | Screen / sound          |
|---|-------|---------------------------|------------------------------|---------------------------|-------------------------|
| 1 | HOOK  | IMG_01 @ 7.30-11.00       | "<exact words>"              | take 1 (stumbled at 3.1)  | hook text, hit at 0     |
| 2 | POINT | IMG_01 @ 41.20-56.98      | "<exact words>"              | 2 pauses > 0.4 s, "euh"   | pill "FREE" + pop       |
| … |       |                           |                              |                           |                         |

Estimated runtime: ~<N> s (<M> cuts)
Cut overall: <retakes>, <false starts>, <fillers>, pauses longer than <max_gap> s

Open questions (max 3):
1. …
```

Then tell the user, in two or three sentences, what the reel will look like and ask:
"OK like this, or what should change?" **Stop there.** Do not write the EDL until they answer.

Mixed right-to-left text renders in the wrong order in many chats and terminals. Keep the
Arabic/Hebrew quotes in the file, and in chat refer to beats by number and a short gloss.
