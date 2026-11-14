"""Phase 6.2: YouTube Data API v3 adapter (regular videos + Shorts).

Verified against the official docs (developers.google.com/youtube/v3, read 2026-11-14):
- videos.insert: POST https://www.googleapis.com/upload/youtube/v3/videos, scope youtube.upload;
  quota: 1 unit in the "Video Uploads" bucket (default 100 uploads/day).
- If status.privacyStatus is NOT sent, the video defaults to PUBLIC, and videos from
  unverified API projects are NOT restricted to private any more → we ALWAYS send it.
- status.publishAt can be set only for private videos — and it makes them public at that
  time, so it counts as public publishing (needs separate public confirmation).
- Resumable protocol: POST (…?uploadType=resumable) with X-Upload-Content-Length /
  X-Upload-Content-Type → session URI in the Location header; PUT chunks with
  Content-Range; 308 Resume Incomplete + Range header = bytes the server has; chunk size a
  multiple of 256 KB (except the last); status query with Content-Range: bytes */TOTAL;
  an expired session returns 404 → start a NEW upload from the beginning; retry 5xx.
- thumbnails.set: POST …/upload/youtube/v3/thumbnails/set?videoId=, ~50 units, JPEG/PNG.
- captions.insert: POST …/upload/youtube/v3/captions, 400 units, scope youtube.force-ssl.
- videos.list: status.uploadStatus (deleted/failed/processed/rejected/uploaded),
  processingDetails.processingStatus (failed/processing/succeeded/terminated).

Security: OAuth happens ONLY on Google's own consent page (InstalledAppFlow, loopback
redirect). Tokens live only in the OS keyring. Nothing here logs headers or tokens.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from .adapters import PlatformAdapter
from .models import PRIVACY, Job
from .retry import FatalError, SessionLost, TransientError

UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
THUMB_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
CAPTIONS_URL = "https://www.googleapis.com/upload/youtube/v3/captions"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"

SCOPE_UPLOAD = "https://www.googleapis.com/auth/youtube.upload"
SCOPE_CAPTIONS = "https://www.googleapis.com/auth/youtube.force-ssl"
CHUNK = 8 * 1024 * 1024            # 32 × 256 KB
assert CHUNK % (256 * 1024) == 0

RETRYABLE_STATUS = {500, 502, 503, 504}
RETRYABLE_403 = {"rateLimitExceeded", "userRateLimitExceeded", "backendError"}


def scopes(captions: bool) -> list[str]:
    """Least privilege: upload only; the broader caption scope only if captions are on."""
    return [SCOPE_UPLOAD, SCOPE_CAPTIONS] if captions else [SCOPE_UPLOAD]


# ------------------------------------------------------------------ OAuth (Google's page only)
def credentials_key(account: str) -> str:
    from .secrets import secret_key
    return secret_key("youtube", account, "oauth")


def login(client_secrets_file: Path, store, account: str, *, captions: bool, flow_factory=None) -> dict:
    """Open Google's official consent page in the browser; save the token in the OS keyring.

    The user's Google password is typed only on accounts.google.com — never here."""
    if not Path(client_secrets_file).is_file():
        raise FileNotFoundError(f"OAuth client file nahi mili: {client_secrets_file} (Google Cloud Console se download karein)")
    if flow_factory is None:
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow_factory = InstalledAppFlow.from_client_secrets_file
    flow = flow_factory(str(client_secrets_file), scopes=scopes(captions))
    creds = flow.run_local_server(port=0, open_browser=True, prompt="consent",
                                  authorization_prompt_message="Google ka official login page browser mein khul raha hai…",
                                  success_message="Login mukammal. Yeh tab band kar ke terminal par wapas jaayein.")
    store.set(credentials_key(account), creds.to_json())
    granted = sorted(getattr(creds, "granted_scopes", None) or getattr(creds, "scopes", None) or [])
    return {"account": account, "scopes": granted}


def load_credentials(store, account: str, *, captions: bool):
    from google.oauth2.credentials import Credentials
    raw = store.get(credentials_key(account))
    if not raw:
        raise FatalError("YouTube login nahi hua. Pehle: python run.py youtube-login")
    creds = Credentials.from_authorized_user_info(json.loads(raw), scopes(captions))
    if not creds.valid:
        if not creds.refresh_token:
            raise FatalError("YouTube login expire ho gaya. Dobara: python run.py youtube-login")
        from google.auth.transport.requests import Request
        try:
            creds.refresh(Request())
        except Exception as e:
            raise FatalError(f"YouTube token refresh nakaam ({type(e).__name__}) — dobara youtube-login") from None
        store.set(credentials_key(account), creds.to_json())
    return creds


def logout(store, account: str, http_post=None) -> bool:
    raw = store.get(credentials_key(account))
    if not raw:
        return False
    token = json.loads(raw).get("refresh_token") or json.loads(raw).get("token")
    if token:
        try:
            if http_post is None:
                import requests
                http_post = requests.post
            http_post(REVOKE_URL, params={"token": token}, timeout=20)   # ask Google to revoke access
        except Exception:
            pass                                    # local removal still happens
    store.delete(credentials_key(account))
    return True


def authorized_session(creds):
    from google.auth.transport.requests import AuthorizedSession
    return AuthorizedSession(creds)


# ------------------------------------------------------------------ errors
def _reason(resp) -> str:
    try:
        errs = resp.json().get("error", {})
        return (errs.get("errors") or [{}])[0].get("reason") or errs.get("status") or ""
    except Exception:
        return ""


def raise_for(resp, what: str, *, session: bool = False) -> None:
    """Map an HTTP response to TransientError (retry) / SessionLost / FatalError (stop)."""
    code = resp.status_code
    if code < 400:
        return
    reason = _reason(resp)
    retry_after = None
    try:
        retry_after = float(resp.headers.get("Retry-After")) if resp.headers.get("Retry-After") else None
    except ValueError:
        pass
    if code in RETRYABLE_STATUS or code == 429 or (code == 403 and reason in RETRYABLE_403):
        raise TransientError(f"{what}: HTTP {code} {reason}".strip(), retry_after=retry_after)
    if session and code in (404, 410):
        raise SessionLost(f"{what}: upload session expire (HTTP {code}) — naya session shuru se.")
    if code == 401:
        raise FatalError(f"{what}: login ki ijazat khatam (401) — dobara youtube-login")
    if code == 403 and reason in ("quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded"):
        raise FatalError(f"{what}: YouTube ka rozana quota / upload limit khatam ({reason}) — kal dobara.")
    raise FatalError(f"{what}: HTTP {code} {reason}".strip())


# ------------------------------------------------------------------ adapter
class YouTubeAdapter(PlatformAdapter):
    """Real YouTube uploads. Constructed only by get_live_adapter() after every guard."""
    offline = False
    chunk_size = CHUNK

    def __init__(self, platform: str, project_root: Path, http, cfg: dict):
        if platform not in ("youtube", "youtube_shorts"):
            raise ValueError("YouTubeAdapter sirf youtube / youtube_shorts ke liye")
        self.platform = platform
        self.root = Path(project_root)
        self.http = http                  # google-auth AuthorizedSession (tests: a fake)
        self.cfg = cfg
        self.extras: dict = {}

    # ---- safety (second layer, besides guard.py)
    def _privacy_body(self, job: Job) -> dict:
        priv = job.privacy
        if priv not in PRIVACY[self.platform]:
            raise FatalError(f"Ghalat privacy: {priv}")
        public_ok = bool((job.approval or {}).get("public_confirmed"))
        if priv != "private" and not public_ok:
            raise FatalError(f"'{priv}' ke liye alag PUBLIC tasdeeq nahi — upload roka gaya.")
        status = {"privacyStatus": priv,                                 # ALWAYS explicit (default would be public)
                  "selfDeclaredMadeForKids": bool(self.cfg.get("made_for_kids", False))}
        if job.schedule:
            if not public_ok:
                raise FatalError("Schedule (publishAt) video ko khud PUBLIC kar deta hai — alag PUBLIC tasdeeq zaroori.")
            status["privacyStatus"] = "private"
            status["publishAt"] = job.schedule
        return status

    def video_body(self, job: Job) -> dict:
        m = job.metadata
        title = (m.get("title") or "").strip()
        if not title or len(title) > 100 or "<" in title or ">" in title:
            raise FatalError("Title ghalat ya 100 haroof se lamba")
        tags = m.get("tags") or [h.lstrip("#") for h in m.get("hashtags", [])]
        return {
            "snippet": {"title": title, "description": m.get("description", "")[:5000], "tags": tags,
                        "categoryId": str(self.cfg.get("category_id", "22")),
                        "defaultLanguage": self.cfg.get("language", "ur"),
                        "defaultAudioLanguage": self.cfg.get("language", "ur")},
            "status": self._privacy_body(job),
        }

    # ---- resumable upload
    def start(self, job: Job) -> dict:
        size = (self.root / job.files["video"]["path"]).stat().st_size
        resp = self.http.request("POST", UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"},
                                 headers={"Content-Type": "application/json; charset=UTF-8",
                                          "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/*"},
                                 data=json.dumps(self.video_body(job), ensure_ascii=False).encode("utf-8"), timeout=60)
        raise_for(resp, "upload session")
        loc = resp.headers.get("Location")
        if not loc or not loc.startswith("https://"):
            raise FatalError("YouTube ne upload session ka address nahi diya")
        return {"upload_url": loc}

    @staticmethod
    def _range_end(resp) -> int:
        m = re.match(r"bytes=0-(\d+)", resp.headers.get("Range", "") or "")
        return int(m.group(1)) + 1 if m else 0

    def send_chunk(self, data: bytes, offset: int, total: int, session: dict) -> int:
        end = offset + len(data) - 1
        resp = self.http.request("PUT", session["upload_url"], data=data, timeout=300,
                                 headers={"Content-Length": str(len(data)), "Content-Range": f"bytes {offset}-{end}/{total}"})
        if resp.status_code == 308:
            got = self._range_end(resp)
            if got <= offset:
                raise TransientError("YouTube ne yeh tukda tasleem nahi kiya", retry_after=_ra(resp))
            return got
        if resp.status_code in (200, 201):
            session["video"] = _video_summary(resp.json())
            return total
        raise_for(resp, "chunk upload", session=True)
        raise FatalError(f"chunk upload: ghair mutawaqqa jawab {resp.status_code}")

    def sync_offset(self, session: dict, total: int) -> int:
        """Ask YouTube how many bytes it has (Content-Range: bytes */TOTAL)."""
        resp = self.http.request("PUT", session["upload_url"], data=b"", timeout=60,
                                 headers={"Content-Length": "0", "Content-Range": f"bytes */{total}"})
        if resp.status_code == 308:
            return self._range_end(resp)
        if resp.status_code in (200, 201):
            session["video"] = _video_summary(resp.json())
            return total
        raise_for(resp, "upload status", session=True)
        raise FatalError(f"upload status: ghair mutawaqqa jawab {resp.status_code}")

    def finish(self, job: Job, session: dict) -> dict:
        v = session.get("video") or {}
        vid = v.get("id")
        if not vid:
            raise FatalError("Upload ke baad YouTube video ID nahi mili")
        if v.get("privacyStatus") not in (None, job.privacy) and not job.schedule:
            raise FatalError(f"YouTube par privacy '{v.get('privacyStatus')}' — manzoor shuda '{job.privacy}' nahi!")
        self.extras = {"thumbnail": self._thumbnail(job, vid), "captions": self._captions(job, vid)}
        url = f"https://youtu.be/{vid}" if self.platform == "youtube_shorts" else f"https://www.youtube.com/watch?v={vid}"
        return {"remote_id": vid, "url": url, "extras": self.extras}

    # ---- extras (failures do not undo the private upload; they are reported)
    def _thumbnail(self, job: Job, vid: str) -> str:
        f = job.files.get("thumbnail")
        if not f or not self.cfg.get("upload_thumbnail", True):
            return "skipped"
        if self.platform == "youtube_shorts":
            return "skipped (Shorts ke liye YouTube custom thumbnail aksar istemal nahi karta)"
        p = self.root / f["path"]
        ctype = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        try:
            resp = self.http.request("POST", THUMB_URL, params={"videoId": vid, "uploadType": "media"},
                                     headers={"Content-Type": ctype}, data=p.read_bytes(), timeout=120)
            raise_for(resp, "thumbnail")
            return "uploaded"
        except (TransientError, FatalError) as e:
            return f"failed: {e}"

    def _captions(self, job: Job, vid: str) -> str:
        f = job.files.get("captions")
        if not f or not self.cfg.get("upload_captions", True):
            return "skipped"
        p = self.root / f["path"]
        boundary = "urdu-video-" + uuid.uuid4().hex
        meta = json.dumps({"snippet": {"videoId": vid, "language": self.cfg.get("language", "ur"),
                                       "name": "اردو", "isDraft": False}}, ensure_ascii=False)
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{meta}\r\n"
                f"--{boundary}\r\nContent-Type: application/octet-stream\r\n\r\n").encode("utf-8") + \
            p.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
        try:
            resp = self.http.request("POST", CAPTIONS_URL, params={"part": "snippet", "uploadType": "multipart"},
                                     headers={"Content-Type": f"multipart/related; boundary={boundary}"},
                                     data=body, timeout=120)
            raise_for(resp, "captions")
            return "uploaded"
        except (TransientError, FatalError) as e:
            return f"failed: {e}"

    # ---- processing
    def status(self, job: Job, remote_id: str) -> tuple[str, dict]:
        resp = self.http.request("GET", VIDEOS_URL, params={"part": "status,processingDetails", "id": remote_id}, timeout=60)
        raise_for(resp, "status")
        items = resp.json().get("items") or []
        if not items:
            return "processing", {"note": "video abhi list mein nahi"}
        st = items[0].get("status", {})
        pd = items[0].get("processingDetails", {})
        up, proc = st.get("uploadStatus"), pd.get("processingStatus")
        info = {"uploadStatus": up, "processingStatus": proc, "privacyStatus": st.get("privacyStatus")}
        if up in ("failed", "rejected", "deleted") or proc in ("failed", "terminated"):
            info.update({"failureReason": st.get("failureReason"), "rejectionReason": st.get("rejectionReason")})
            return "failed", info
        if proc == "succeeded" or up == "processed":
            return "completed", info
        return "processing", info


def _ra(resp):
    try:
        return float(resp.headers.get("Retry-After")) if resp.headers.get("Retry-After") else None
    except ValueError:
        return None


def _video_summary(v: dict) -> dict:
    """Keep only non-sensitive fields of the API response."""
    return {"id": v.get("id"), "privacyStatus": (v.get("status") or {}).get("privacyStatus"),
            "uploadStatus": (v.get("status") or {}).get("uploadStatus")}


def get_live_adapter(platform: str, project_root: Path, *, store=None):
    """Real adapter — only after guard checks pass AND credentials exist in the OS keyring."""
    from .guard import check_live, load_config
    from .secrets import secure_store
    cfg = load_config()
    dummy = Job(id=platform, project=Path(project_root).name, platform=platform, privacy=PRIVACY[platform][0])
    check_live(dummy, cfg)                                  # master + platform switch + hard blocks
    ycfg = json.loads((Path(__file__).resolve().parent.parent / "config" / "publishing.json").read_text(
        encoding="utf-8")).get("youtube", {})
    store = store or secure_store()
    creds = load_credentials(store, ycfg.get("account", "default"), captions=bool(ycfg.get("upload_captions", True)))
    return YouTubeAdapter(platform, project_root, authorized_session(creds), ycfg)
