# 🎬 Urdu Video Automation System

**YouTube, Facebook aur TikTok ke liye Urdu videos banane ka system — aap ki apni awaaz ke saath.**

> **Abhi kya tayyar hai:** Phase 1 (bunyaad) + Phase 2 (AI Urdu script + awaaz ki safai)
> **Yeh system kuch bhi upload ya publish NAHI karta.** Social media APIs abhi connect nahi hain.

---

## 📋 Fehrist

1. [Yeh system kya karta hai](#1-yeh-system-kya-karta-hai)
2. [Zaroori software install karein](#2-zaroori-software-install-karein-sirf-ek-dafa)
3. [Pehli dafa setup](#3-pehli-dafa-setup)
4. [Pehli video — qadam ba qadam](#4-pehli-video--qadam-ba-qadam)
5. [Achhi recording ke tips](#5-achhi-recording-ke-tips)
6. [Sab commands](#6-sab-commands)
7. [Lagat (cost)](#7-lagat-cost--kya-free-hai-kya-paid)
8. [Hifazat aur privacy](#8-hifazat-aur-privacy)
9. [Masle aur hal](#9-masle-aur-hal)
10. [Aage kya aayega](#10-aage-kya-aayega)

---

## 1. Yeh system kya karta hai

| Kaam | Phase | Haalat |
|---|---|---|
| Folder structure, settings, Urdu font | 1 | ✅ Tayyar |
| AI se Urdu script (FREE mode + optional PAID mode) | 2 | ✅ Tayyar |
| Aap ki asal awaaz ki safai (shor, volume, clarity) | 2 | ✅ Tayyar |
| Preview page (sun kar / dekh kar check) | 2 | ✅ Tayyar |
| Urdu subtitles | 3 | ⏳ Agla |
| Video editing (transitions, color, music) | 4 | ⏳ |
| YouTube / TikTok / Facebook versions | 5 | ⏳ |
| Official publishing (aap ki approval ke saath) | 6 | ⏳ |

**Aap ki awaaz aur chehra kabhi nahi badle jaate.** Koi AI voice, koi voice cloning nahi.
Sirf shor kam hota hai aur volume barabar hota hai.

---

## 2. Zaroori software install karein (sirf ek dafa)

Teeno **free** hain.

### (a) Python 3.10 ya naya
- **Windows:** https://www.python.org/downloads/ → install karte waqt ✅ **"Add Python to PATH"** zaroor tick karein.
- **Mac:** https://www.python.org/downloads/
- **Check:** terminal mein `python --version` (Mac/Linux par `python3 --version`)

### (b) FFmpeg (awaaz aur video ka engine)
- **Windows:** terminal (PowerShell) mein: `winget install Gyan.FFmpeg` → phir terminal band kar ke dobara kholein
- **Mac:** `brew install ffmpeg`
- **Ubuntu/Linux:** `sudo apt install ffmpeg`
- **Check:** `ffmpeg -version`

### (c) Node.js + Chromium (Urdu Nastaliq likhai ke liye)
- https://nodejs.org se **LTS** version install karein.
- Phir is project ke folder mein:
  ```
  npm install
  npm run setup-browser
  ```

> **Kyun Chromium?** Nastaliq ke huroof ka jurna bohat mushkil hai. Humne test kiya ke kuch FFmpeg
> versions Urdu ki jagah **khaali dabbe □□□** banate hain. Browser engine Nastaliq bilkul sahi likhta hai.

---

## 3. Pehli dafa setup

```bash
# 1) Project download karein (GitHub se)
git clone https://github.com/anwarpk6622-commits/Social-media-video-automation.git
cd Social-media-video-automation

# 2) Secrets ki file banayein (abhi khaali chhor sakte hain)
cp .env.example .env          # Windows PowerShell: copy .env.example .env

# 3) System check
python run.py doctor
```

`doctor` har cheez ke aage ✅ ya ❌ dikhayega. Sab ✅ hon to aap tayyar hain.
(➖ wali cheezein optional hain.)

**Apne channel ki settings** `config/settings.json` mein badlein: channel ka naam, audience, tone,
call-to-action.

---

## 4. Pehli video — qadam ba qadam

### Qadam 1 — Naya project
```bash
python run.py new "Mobile Video Tips" --topic "Mobile se professional video kaise banayein"
```
Is se `projects/2026-11-13-mobile-video-tips/` folder banega. Aage project ka **chhota naam**
(jaise `mobile-video-tips`) likh sakte hain.

### Qadam 2 — AI se Urdu script (FREE)
```bash
python run.py script mobile-video-tips --minutes 3 --notes "beginners ke liye"
```
1. `projects/.../script/prompt.txt` kholein → **sara text copy** karein.
2. https://claude.ai par **nayi chat** mein paste karein.
3. Jawab ke neeche **Copy button** dabayein → `projects/.../script/script.md` mein paste karein (us line ke neeche jo kehti hai "paste karein").
4. Check karein:
   ```bash
   python run.py script-check mobile-video-tips
   ```
   Yeh batayega: kitne minute ki script hai, Short version 60 second se kam hai ya nahi, aur
   kaun si baatein (🔎 `[CHECK: ...]`) aap ko **khud confirm** karni hain.
5. `script/read_aloud.txt` ban jaayegi — sirf woh alfaaz jo aap ne bolne hain (`⏸` = saans lein).

> Script ko zaroor parh kar apne andaaz mein theek karein. AI madadgaar hai, lekin aakhri faisla aap ka.

### Qadam 3 — Apni awaaz record karein
Phone ki voice recorder app ya camera se record karein (tips neeche section 5 mein).
**WAV, M4A, MP3, MP4, MOV** — sab chalte hain. Video file se awaaz khud nikaal li jaati hai.

### Qadam 4 — Recording project mein daalein
```bash
python run.py add-recording mobile-video-tips "C:\Users\Aap\Downloads\recording.m4a"
```
- Recording ki **copy** banti hai (asal file wahin rehti hai).
- Copy **read-only** ho jaati hai aur us ka **fingerprint (SHA-256)** save hota hai.

### Qadam 5 — Awaaz saaf karein
```bash
python run.py audio mobile-video-tips
```
Yeh 8 kaam karta hai: mono → (optional) khamoshi chhoti → 80Hz se neeche ki goonj hatana →
**shor kam** → EQ (saaf awaaz) → de-esser ("س/ش" ki seeti narm) → compressor (awaaz barabar) →
**-14 LUFS** (YouTube/TikTok/Facebook ka volume standard) + peak limiter.

Mazeed options:
```bash
python run.py audio mobile-video-tips --noise strong        # zyada shor ho (pankha, traffic)
python run.py audio mobile-video-tips --noise light         # pehle se saaf recording
python run.py audio mobile-video-tips --trim-silence        # lambe waqfe chhote karein
python run.py audio mobile-video-tips --recording take2.m4a # koi khaas recording
```

### Qadam 6 — Sun kar aur dekh kar check karein
```bash
python run.py preview mobile-video-tips --serve
```
Browser mein di gayi link kholein (`http://127.0.0.1:8000/...`). Page par:
- 🔒 Original recordings "Bilkul unchanged" ✅
- 🎙️ **Pehle / Baad** players — headphones laga kar dono sunein
- Loudness ke numbers + waveform + spectrogram tasveerein
- 📝 Script Nastaliq mein
- 🔤 Urdu font test frame

Band karne ke liye terminal mein **Ctrl + C**.

---

## 5. Achhi recording ke tips

1. **Khamosh kamra** — pankha/AC band, darwaza band. Parday aur bistar wala kamra goonj kam karta hai.
2. **Mic/phone munh se 15–20 cm door**, thora side par (saans ki "phoo" se bachne ke liye).
3. Pehle **5 second khamosh** rahein — yeh shor pehchanne mein madad karta hai.
4. Ghalti ho to ruk kar **poora jumla dobara** bolein (baad mein kaata ja sakta hai).
5. Phone ko **Airplane mode** par rakhein (notification ki awaaz na aaye).
6. Bahut tez na bolein — Urdu ke liye ~130 alfaaz fi minute achha hai.

---

## 6. Sab commands

| Command | Kaam |
|---|---|
| `python run.py doctor` | System check |
| `python run.py new "Naam" --topic "..."` | Naya video project |
| `python run.py list` | Sab projects |
| `python run.py script <project> [--minutes 3] [--notes "..."]` | FREE: Claude ke liye ready prompt |
| `python run.py script <project> --use-api` | PAID: Claude API se seedha script (pehle lagat batayega) |
| `python run.py script-check <project>` | Script ke hisse, lambai, fact-checks |
| `python run.py add-recording <project> <file>` | Recording ki mehfooz copy |
| `python run.py verify <project>` | Originals unchanged hain? |
| `python run.py audio <project> [options]` | Awaaz saaf karein |
| `python run.py preview <project> [--serve]` | Preview page |
| `python run.py font-test` | Urdu Nastaliq render test |
| `python -m unittest discover -s tests -v` | Automated tests (developer check) |

---

## 7. Lagat (cost) — kya free hai, kya paid

| Cheez | Lagat |
|---|---|
| Python, FFmpeg, Node.js, Chromium | **Free** (open-source) |
| Noto Nastaliq Urdu font | **Free** (OFL license, commercial videos mein bhi) |
| Script — FREE mode (claude.ai chat) | **Free** (claude.ai free plan ki rozana had ke andar) |
| Script — PAID API mode (`--use-api`) | **~$0.05–$0.15 fi script** (andaza; zyada se zyada ~$0.33) |
| Awaaz ki safai, preview | **Free** (aap ke computer par chalta hai) |

### Paid API mode (optional) — kab aur kaise
Sirf tab, jab aap bohat saari scripts automatic banana chahein.
1. https://console.anthropic.com par account → **Billing** mein credit (minimum $5) → **API Keys** → nayi key.
2. `.env` file kholein → `ANTHROPIC_API_KEY=` ke aage key paste karein. (**Kabhi chat/GitHub/screenshot mein share na karein.**)
3. `pip install -r requirements-optional.txt`
4. `python run.py script <project> --use-api`

System **pehle lagat ka andaza dikhata hai** aur aap ke `yes` likhne tak **ek paisa bhi kharch nahi hota.**
Har call ki asal lagat `script/api_log.jsonl` mein likhi jaati hai.
Default model: `claude-opus-5-5` ($4 / $20 fi million tokens). Agar woh model kisi request se inkar kare, to API khud
ek munasib doosra model istemal karti hai (server-side fallback) — us ki lagat us model ke rate par hoti hai.

---

## 8. Hifazat aur privacy

- 🔒 **Asal recordings kabhi nahi badalti.** Copy read-only hoti hai, aur har processing se **pehle aur baad**
  fingerprint check hota hai. Badli hui file mili to system **rok deta hai** ("KHABARDAR").
- 💾 Phir bhi apni asal recordings ka **backup** apne phone/computer/Google Drive par rakhein.
- 🙈 Recordings, videos, audio aur `.env` (keys) **GitHub par nahi jaate** — `.gitignore` inhein rokta hai.
- 🚫 Koi social media connection nahi, koi auto-upload nahi.

---

## 9. Masle aur hal

| Masla | Hal |
|---|---|
| `python` command nahi milti | Windows: Python dobara install karein, "Add to PATH" tick karein. Mac: `python3` likhein |
| `ffmpeg nahi mila` | Section 2(b). Install ke baad terminal band kar ke dobara kholein |
| Font test mein □□□ dabbe | `npm install` aur `npm run setup-browser` chalayein |
| `Kai projects milte hain` | Project ka poora naam likhein (`python run.py list` se dekhein) |
| ⚠️ Loudness target tak nahi pahunchi | Recording mein bohat tez peaks hain. Mic thora door rakh kar record karein. Awaaz phir bhi istemal ho sakti hai |
| Awaaz "robot" jaisi lagti hai | `--noise light` ya `--noise off` try karein |
| `script-check` hisse nahi pehchanta | claude.ai ka **Copy button** istemal karein, `## [HOOK]` jaisi headings mat badlein |

---

## 10. Aage kya aayega

- **Phase 3:** Urdu subtitles — Whisper AI se transcription + aap ki script se match (sahi spelling), Nastaliq style, lafz-ba-lafz highlight
- **Phase 4:** Cinematic editing — transitions, color grading, music ducking, sound effects
- **Phase 5:** YouTube 16:9, Shorts, TikTok, Facebook Reel versions + thumbnail
- **Phase 6:** Official APIs se publishing — sirf aap ki approval ke baad

---

### Folder structure
```
├── run.py                 # sab commands yahan se
├── config/settings.json   # channel + audio + script settings
├── .env.example           # keys ka namoona (asal .env GitHub par nahi jaati)
├── pipeline/              # system ka code
│   ├── project.py         #   projects + originals ki hifazat
│   ├── script_writer.py   #   Urdu script (free / paid)
│   ├── audio.py           #   awaaz ki safai (FFmpeg)
│   ├── preview.py         #   preview page
│   ├── urdu_text_render.js#   Nastaliq → tasveer (Chromium)
│   └── doctor.py          #   system check
├── assets/                # fonts, music, sfx, luts, branding
├── projects/              # har video ka folder
├── publishers/            # Phase 6 (abhi khaali)
└── tests/                 # automated tests
```
