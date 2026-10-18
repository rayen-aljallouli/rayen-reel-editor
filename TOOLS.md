# rayen-reel-editor · what you need

This is the Claude Code skill that edited the reel: cuts on word boundaries, karaoke captions
(Arabic/Derja + English, right-to-left done right), text cards, generated sound effects, a ducked
music bed, previews, final render. You talk, Claude edits. The full step-by-step guide with the
copy-paste prompts and the feedback rounds comes separately. This page only lists the tools.

## 1. Accounts

| What | Why | Cost |
|---|---|---|
| Claude Code (claude.com/code) | the agent that runs the edit | paid plan or API credits; the free plan has no Claude Code |
| ElevenLabs API key with Speech to Text | every word gets an exact time, the cuts depend on it | free tier for short tests, paid for longer recordings; each recording is transcribed once and cached |

Your video never leaves your computer. Only the audio track goes to ElevenLabs.

## 2. Software

| Tool | Needed for | Install |
|---|---|---|
| ffmpeg + ffprobe, with libass | cutting, captions, render | Ubuntu/WSL2: `sudo apt install -y ffmpeg` · macOS: `brew install ffmpeg` |
| Python 3.10+ with numpy, Pillow, requests | the skill's scripts | `pip install -r requirements.txt` (inside the skill folder) |
| Node.js 22+ (optional) | motion graphics, split screens, background removal, counters: everything HyperFrames does | nodejs.org, or `brew install node`; the skill runs it with `npx hyperframes` |

Windows: use WSL2 (Ubuntu) and follow the Ubuntu lines. The skill is not tested in PowerShell.

## 3. Install the skill (3 minutes)

**Easy way: let Claude Code install it.** Open a terminal in the folder where the ZIP landed
(usually Downloads), start `claude`, paste this and press Enter:

> Install the Claude Code skill from rayen-reel-editor.zip in this folder (if it is not here, ask me where I saved it). Unzip it into ~/.claude/skills/ so that ~/.claude/skills/rayen-reel-editor/SKILL.md exists. In that folder create a Python venv named .venv and install requirements.txt into it. Make sure ffmpeg and ffprobe are installed, if not install them (sudo apt install -y ffmpeg on Ubuntu/WSL2, brew install ffmpeg on macOS). Copy .env.example to .env, ask me for my ElevenLabs API key and write it after ELEVENLABS_API_KEY= without printing it back. Then run .venv/bin/python scripts/check_setup.py --ping and fix every FAIL it reports until the output ends with READY. Node.js is optional, skip it unless I ask. Finally tell me in three lines what you installed and how I start my first edit.

Claude unzips, installs, asks for your key, runs the check and stops at READY. Have the key ready
(elevenlabs.io → Profile → API keys, Speech to Text enabled).

**By hand**, same result:

```bash
mkdir -p ~/.claude/skills
unzip rayen-reel-editor.zip -d ~/.claude/skills/    # gives ~/.claude/skills/rayen-reel-editor
cd ~/.claude/skills/rayen-reel-editor
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                                 # paste your key after ELEVENLABS_API_KEY=
.venv/bin/python scripts/check_setup.py --ping       # must end with READY
```

Then open Claude Code in the folder that holds your recording and say:

> Edit my reel: cut the retakes and pauses, karaoke captions in Derja, keep it under 60 s.

Claude proposes a storyboard first and waits for your OK before it cuts anything.

## 4. What needs what

- Cuts, captions, text cards, sounds, music: ffmpeg + Python only.
- Motion graphics, counters, picture-in-picture, split screen, the "me in a window" reveal,
  background colour behind you (person matte): Node + HyperFrames (`npx hyperframes`, downloads on
  first use; the matte model is ~170 MB, CPU is enough, about 1 to 2 frames per second).
- B-roll clips, photos, logos: you provide the files, Claude places them. Credit the owners.

Problems: `scripts/check_setup.py` prints every missing piece. `references/lessons.md` lists the
mistakes we already made for you (lip sync, iPhone HDR, Arabic letters, captions under the app UI).

Made by Rayen Jallouli (@rayen.aljallouli). Based on video-use by Browser Use (MIT), see CREDITS.md.
