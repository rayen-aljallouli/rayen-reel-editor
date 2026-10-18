# rayen-reel-editor

A Claude Code skill that edits vertical talking-head reels (1080x1920) from raw phone footage,
by conversation: word-level transcript, storyboard you approve first, cuts on word boundaries,
karaoke captions (Arabic / Tunisian Derja + English, right-to-left done right), text cards,
generated sound effects, a ducked music bed, previews with self-check, final render.

- **Setup and install:** [TOOLS.md](TOOLS.md) (same as PDF: [TOOLS.pdf](TOOLS.pdf))
- **How the skill works (what Claude follows):** [SKILL.md](SKILL.md)
- **Credits and licences:** [CREDITS.md](CREDITS.md), [LICENSE](LICENSE) (MIT)

Quick install:

```bash
git clone https://github.com/rayen-aljallouli/rayen-reel-editor ~/.claude/skills/rayen-reel-editor
cd ~/.claude/skills/rayen-reel-editor
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # paste your ElevenLabs API key after ELEVENLABS_API_KEY=
.venv/bin/python scripts/check_setup.py --ping   # must end with READY
```

Then open Claude Code in the folder with your recording and say:
"Edit my reel: cut the retakes and pauses, karaoke captions, keep it under 60 s."

Made by Rayen Jallouli ([@rayen.aljallouli](https://instagram.com/rayen.aljallouli)).
