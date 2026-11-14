# 🎬 Urdu Video Automation System

**YouTube, Facebook aur TikTok ke liye Urdu videos banane ka system — aap ki apni awaaz ke saath.**

> **Abhi kya tayyar hai:** Phase 1 (bunyaad) + Phase 2 (AI Urdu script + awaaz ki safai) + Phase 3 (Urdu subtitles)
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
| Urdu subtitles (.srt + video par Nastaliq, bolta lafz highlight) | 3 | ✅ Tayyar |
| Video editing (trim, stabilization, color grade, transition, title, 9:16 + 16:9) | 4 | ✅ Tayyar (music baad mein) |
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

### (d) Python packages (Whisper AI — subtitles ke liye)
```
pip install -r requirements.txt
```
Pehli dafa subtitles banate waqt Whisper ka Urdu model khud download hoga (**medium ≈ 1.5 GB**, sirf ek dafa,
`models/` folder mein). Us ke baad internet ki zaroorat nahi, aur aap ki awaaz kahin upload nahi hoti.

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

### Qadam 7 — Urdu subtitles banayein
```bash
python run.py subtitles mobile-video-tips
```
Kya hota hai:
1. **Whisper AI** aap ki saaf awaaz sunta hai aur har lafz ka **waqt** nikaalta hai (aap ke computer par).
2. System sune hue alfaaz ko aap ki **script** se milata hai: **likhai script se** (100% sahi spelling),
   **waqt awaaz se**. Is liye Whisper ki spelling ki ghaltiyan subtitles mein nahi aatin.
3. Do files banti hain:
   - `subtitles/urdu.srt` — **16:9 / YouTube** (lambi lines). YouTube Studio → Subtitles → Upload file
   - `subtitles/urdu_vertical.srt` — **9:16 / Shorts, TikTok, Reels** (chhoti, 2–4 alfaaz)
4. Report batati hai kitne alfaaz match hue aur 🔎 kaun se alfaaz aap khud check karein.

Agar recording script se thori mukhtalif ho, to system khud sambhal leta hai:
- Aap ne script ka koi **hissa chhod diya** → woh alfaaz subtitle mein **nahi** aate (report mein "chhoote" list).
- Aap ne **apni taraf se** koi lafz bola (jaise «دوستو») → agar Whisper ko yaqeen ho to subtitle mein aata hai, warna sirf check list mein.
- Shor / goonj ki wajah se Whisper ne kuch alfaaz **ghalat** sune → phir bhi script ki sahi likhai, sahi waqt par
  (milti julti awaazein jaise ص/س/ش aur ز/ذ/ض pehchani jaati hain).

Lines todte waqt system Urdu grammar ka khayal rakhta hai: «کا، کی، میں، سے، ہے» jaise alfaaz se nayi line
shuru nahi hoti, aur jumle ka aakhri lafz akela screen par nahi chhoda jaata.

Options:
```bash
python run.py subtitles mobile-video-tips --model small     # purana / kamzor computer (tez, kam durust)
python run.py subtitles mobile-video-tips --model large-v3  # sab se durust (3 GB, dheema)
python run.py subtitles mobile-video-tips --no-script       # script ke baghair (sirf Whisper ki likhai)
python run.py subtitles mobile-video-tips --retranscribe    # awaaz dobara sunein
```

### Qadam 8 — Subtitles wali test video
```bash
python run.py subtitle-video mobile-video-tips
python run.py subtitle-video mobile-video-tips --background "meri-clip.mp4"   # apni clip ke upar
```
`preview/subtitles_16x9.mp4` aur `preview/subtitles_9x16.mp4` banti hain: aap ki awaaz + Nastaliq subtitles,
aur **bolta hua lafz peela** highlight. Preview page (Qadam 6) par dono videos chalti hain.

### Qadam 9 — Ghalti theek karna (bohat aasan)
1. `subtitles/urdu.srt` **Notepad** (ya koi text editor) mein kholein.
2. Ghalat lafz theek karein, ya waqt (`00:00:03,160 --> 00:00:07,380`) badlein. Save karein (UTF-8).
3. `python run.py subtitle-video mobile-video-tips` dobara chalayein.

Aap ki tabdeeliyan **mehfooz** hain: agar baad mein `subtitles` dobara chalayein to system inkar karega taake
edit na mitey. Zabardasti naya banana ho to `--force` (purani file ka backup khud ban jaata hai).

### Qadam 10 — Apni video ki cinematic editing (Phase 4)
```bash
python run.py new "Dubai Video"
python run.py add-recording dubai-video "VID-20261114.mp4"        # mehfooz read-only copy
python run.py edit-init dubai-video --title "دبئی نیشنل ڈے کی تیاری" --tag "برج العرب، دبئی" \
       --trim-start 2.0 --soft-range 29.7-35.5                      # plan → edit.json
python run.py audio dubai-video --noise medium                     # aawaz saaf (lip-sync khud theek)
python run.py subtitles dubai-video                                # Urdu subtitles
python run.py edit-preview dubai-video                             # PREVIEW (9:16 + 16:9)
python run.py export dubai-video                                   # sirf aap ke "yes" ke baad
```
- `--trim-start`: shuru se kitne second kaatne hain · `--soft-range`: jahan chehra ho, wahan halka color grade
- **edit.json** ek aam text file hai — title, kaat, stabilization, grade, end card sab yahan badal sakte hain.
- Kya hota hai: scene cuts khud dhoonde jaate hain → har clip **stabilize** (adaptive zoom, kinare kabhi
  khaali nahi) → **cinematic warm grade** (chehre par halka) → 1080p upscale + sharpen → cut par
  **zoom-punch transition** → Nastaliq **title**, **subtitles**, **end card** → 9:16 aur 16:9 (dono taraf blur).
- `export` tab hi chalta hai jab preview bana ho aur us ke baad `edit.json` na badla ho.
  Final files: `output/final_9x16.mp4`, `output/final_16x9.mp4`. **Kuch bhi upload / publish nahi hota.**
- ⚠️ WhatsApp wali video kam quality (480p) ki hoti hai. Behtar natije ke liye phone se **asal file** bhejein.

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
| `python run.py subtitles <project> [--model medium] [--no-script]` | Urdu subtitles (.srt) |
| `python run.py subtitle-video <project> [--background clip.mp4]` | Subtitles wali test video (16:9 + 9:16) |
| `python run.py edit-init <project> --title "..." [--trim-start 2]` | Editing plan (edit.json) |
| `python run.py edit-preview <project>` | Editing PREVIEW (9:16 + 16:9) |
| `python run.py export <project>` | Final files — preview approve karne ke baad |
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
| Urdu subtitles (Whisper AI) | **Free** — ek dafa ~1.5 GB download; 5 minute ki awaaz ≈ 3–6 minute CPU par |

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
| Subtitles mein ajeeb alfaaz / kam match % | Kya recording isi script ki hai? Report ke 🔎 alfaaz check karein, ya `--model large-v3` |
| `haath se edit ki hai` error | Aap ki SRT tabdeeliyan bachane ke liye hai. Naya banana ho to `--force` |
| Whisper model download nahi hota | Internet check karein; pehli dafa ~1.5 GB download hota hai |
| Subtitles bohat dheemay | `--model small` istemal karein |

---

## 10. Aage kya aayega

- ~~**Phase 3:** Urdu subtitles~~ ✅ ho gaya
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
│   ├── transcribe.py      #   Whisper AI: awaaz → alfaaz + waqt
│   ├── subtitles.py       #   script ↔ awaaz match, subtitle hisse, SRT
│   ├── subtitle_render.py #   video par Nastaliq subtitles
│   ├── urdu_text.py       #   Urdu likhai ke helpers
│   ├── preview.py         #   preview page
│   ├── urdu_text_render.js#   Nastaliq → tasveer (Chromium)
│   └── doctor.py          #   system check
├── assets/                # fonts, music, sfx, luts, branding
├── models/                # Whisper AI model (khud download, GitHub par nahi)
├── projects/              # har video ka folder
├── publishers/            # Phase 6 (abhi khaali)
└── tests/                 # automated tests
```
