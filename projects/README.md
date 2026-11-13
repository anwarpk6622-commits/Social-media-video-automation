# Projects

Har video ka apna folder: `YYYY-MM-DD-naam/` — `python run.py new "Naam"` se banta hai.

```
2026-11-13-mera-video/
├── project.json        # naam, topic, recordings ke fingerprints
├── input/original/     # aap ki ASAL recordings (read-only, kabhi badli nahi jaatin)
├── input/clips/        # video clips (Phase 4)
├── script/             # prompt.txt, script.md, read_aloud.txt
├── audio/processed/    # saaf awaaz (*_clean.wav, *_clean_preview.m4a, *_report.json)
├── subtitles/          # Phase 3
├── output/             # Phase 5
└── preview/            # preview.html + tasveerein
```

**Privacy:** recordings, videos, audio aur preview **GitHub par nahi jaate** (.gitignore). Sirf
`project.json` aur `script/` ki text files commit ho sakti hain.
