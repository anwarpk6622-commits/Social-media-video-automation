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
