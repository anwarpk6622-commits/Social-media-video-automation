# Urdu Font — Noto Nastaliq Urdu

| File | Kya hai |
|---|---|
| `NotoNastaliqUrdu-Regular.ttf` | Aam subtitles / text |
| `NotoNastaliqUrdu-Bold.ttf` | Mota text (titles, highlights) |
| `OFL.txt` | License — SIL Open Font License 1.1 |

- **Version:** 3.007 (Google Noto Project, 2022), Arabic-script set (Fontsource 5.3.0 se, WOFF → TTF convert kiya gaya).
- **License:** OFL 1.1 — YouTube/TikTok/Facebook videos mein (commercial bhi) **free** istemal ho sakta hai. Font file ko akela bechna mana hai.
- **English harf / numbers** is font mein nahi; woh khud-ba-khud doosre font mein dikhte hain (yeh normal hai).

## RTL (daayen se baayen) — ahem baat
Nastaliq ki "shaping" (huroof ka jurna) bohat mushkil hai. Humne test kiya ke Ubuntu 24.04 ka
FFmpeg (libass / drawtext) is font ke huroof ki jagah **khaali dabbe** banata hai. Is liye Urdu
text **Chromium browser engine** se banaya jaata hai (`pipeline/urdu_text_render.js`), jo
Nastaliq ko bilkul sahi jorta hai. Test: `python run.py font-test`
