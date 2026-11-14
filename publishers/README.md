# Publishers — Phase 6

**Phase 6.1 (yeh):** platform se azaad publishing framework. **Koi asal upload mumkin nahi**
(`publishing.live_enabled = false`, aur koi asal platform adapter mojood nahi). Koi credential nahi maanga
ya rakha jaata. Asal integrations aap ki manzoori ke baad aayengi: 6.2 YouTube · 6.3 Facebook Reels · 6.4 TikTok.

## Workflow

```
publish-plan  →  publish-check  →  publish-approve  →  (6.2+: publish-run)
  pending          validated          approved            uploading → processing → completed / failed
```

| Command | Kaam |
|---|---|
| `python run.py publish-plan <p> [--platform youtube] [--privacy youtube=unlisted] [--schedule 2026-12-02T19:00]` | Phase 5 files se har platform ka job. Default privacy: **private / draft / only-me** |
| `python run.py publish-check <p>` | Dry-run validation: format, codec, size, lambai, aspect, fps, thumbnail, metadata, schedule |
| `python run.py publish-approve <p>` | Har job ki summary, phir `APPROVE` likhna; public ke liye alag `PUBLIC` |
| `python run.py publish-status <p>` | Haalat + kya manzoori ke baad koi file badli |
| `python run.py publish-run <p> --simulate [--fail transient,rate_limit,fatal]` | Offline nakal (asal job ki haalat nahi badalti) |
| `python run.py publish-report <p>` | `publish/report.md` + preview page |
| `python run.py secret-scan [--all]` | Secrets dhoondna (default: staged files) |
| `python run.py install-hooks` | Har commit se pehle khud secret scan |

## Hifazat ke usool

- **Manzoori fingerprints se bandhi hai:** video, thumbnail, metadata, privacy, schedule ka SHA-256. Ek byte bhi
  badla → manzoori radd, job wapas `pending`.
- **Status ke sirf allowed raaste** (`models.TRANSITIONS`); `completed` aakhri hai — kabhi dobara upload nahi.
- **Idempotent:** plan dobara chalana kuch nahi badalta; toota upload aakhri tasdeeq shuda byte se chalta hai;
  upload ho chuka ho to sirf status check hota hai.
- **Retry:** network / 5xx / 429 → barhta intezar + jitter (max 5); 4xx (permission / policy) → foran ruk jaana.
- **Secrets:** logs, job files, report aur preview hamesha redacted; upload sessions sirf `publish/private/`
  (GitHub se bahar). Tokens future mein sirf OS keyring mein (Windows Credential Manager / macOS Keychain).

## Files (har project mein)

```
publish/jobs/<platform>.json   job: status, files + fingerprints, metadata, validation, approval, history
publish/log.jsonl              har qadam (redacted)
publish/report.md              report
publish/private/               resumable upload session (gitignored, kaam ke baad saaf)
publish/simulations/           simulation natije (gitignored)
```

## Naya platform jodna (6.2+)

`adapters.PlatformAdapter` ke 4 methods: `start` (upload session), `send_chunk` (ek tukda, naya offset wapas),
`finish` (metadata / privacy / thumbnail, `remote_id` wapas), `status` (`processing` / `completed` / `failed`).
Baaqi sab — manzoori, fingerprints, retry, resume, logs — framework khud karta hai.

## Phase 6.2 — teen hifazati sudhaar

1. **HMAC dastakhat:** har manzoori HMAC-SHA256 se sign hoti hai. Key sirf OS keyring mein
   (Windows Credential Manager / macOS Keychain / Linux Secret Service) — kisi file ya Git mein nahi.
   Keyring na ho → manzoori aur upload dono **band** (fail closed). Job file badli → dastakhat ghalat → manzoori radd.
2. **Upload ke dauran SHA-256:** har bheja gaya hissa (range) ka SHA-256 record hota hai; upload ke shuru,
   resume aur aakhir mein poori file + har hissa dobara check. File badli (chahe wapas theek kar di jaye) → `finish` kabhi nahi.
3. **Alag platform switches** (`config/publishing.json`): master `live_enabled` (yahan **aur** `config/settings.json`
   dono mein `true` chahiye), har platform ka switch, `private_only: true`. Facebook/TikTok code mein **hard-blocked**.

## YouTube setup (aap ke apne computer par — cloud se Google API band hai)

1. https://console.cloud.google.com → naya project.
2. *APIs & Services → Library* → **YouTube Data API v3** → Enable.
3. *OAuth consent screen*: External, app name, apna email; Scopes: `youtube.upload` (+ `youtube.force-ssl` agar captions);
   *Test users* mein apna Google account. (Testing mode mein refresh token ~7 din baad expire → dobara login.)
4. *Credentials → Create credentials → OAuth client ID → **Desktop app*** → JSON download →
   `secrets/youtube_client_secret.json` (Git mein kabhi nahi jaata).
5. `pip install -r requirements-publishing.txt`
6. `python run.py youtube-status` → `python run.py youtube-login` (browser mein **Google ka apna** page khulta hai;
   password hum kabhi nahi maangte; token sirf keyring mein).
7. Upload sirf tab: `live_enabled` dono jagah `true` + `publish-approve` + `publish-run --platform youtube` +
   typed `UPLOAD youtube`. Privacy hamesha **private** (YouTube ka default PUBLIC hai — is liye har dafa explicit bheji jaati hai).

Quota: videos.insert ~1 unit (Video Uploads bucket, 100/din), thumbnails.set ~50, captions.insert 400, videos.list 1;
roz ka default 10,000 units (reset: aadhi raat Pacific time). Har request (ghalat bhi) kam az kam 1 unit.
Shorts thumbnail: API ab (3 Nov 2026 se) processing ke baad support karti hai — hum abhi bhi skip karte hain (ihtiyat).
Test upload `notifySubscribers=false` ke saath hota hai (API ka default true hai).
Adapter Phase 6.2 mein **sirf private** qubool karta hai (public / unlisted / schedule code mein band) aur upload ke
baad YouTube ki batayi hui privacy check karta hai — 'private' na ho to thumbnail/captions roke jaate hain aur alert.
Login ke baad client secret bhi keyring ke token mein shamil hota hai — chahein to `secrets/` wali JSON file hata sakte hain.

## Pehla PRIVATE test upload — Windows PC (manzoor shuda: sirf `youtube.upload`)

Hifazati intezam is test ke liye:
- `upload_captions: false` → login sirf `youtube.upload` maangta hai; Google zyada/kam ijazat de to login **mehfooz nahi** hota.
- `youtube_shorts` switch OFF · `max_live_uploads: 1` (sab projects mila kar) · `private_only: true`.
- Upload se pehle `channels.list?mine=true` se channel dobara check (aap ne `youtube-channel` mein jo tasdeeq kiya).
- `live-switch on` sirf EK run ke liye — `publish-run` ke baad (kamyab ho ya nakaam) khud OFF.
- Upload ke baad aur har processing check par privacy `private` honi chahiye, warna foran stop + ⚠️ alert.

Commands tarteeb se:
```
python run.py youtube-status
python run.py youtube-login                 # LOGIN likhein → Google ka apna page → sirf wahin password
python run.py youtube-channel               # channel dekh kar HAAN
python run.py publish-approve 2026-11-14-dubai-national-day --platform youtube     # APPROVE
python run.py live-switch on                # LIVE ON
python run.py publish-run 2026-11-14-dubai-national-day --platform youtube         # UPLOAD youtube
```
