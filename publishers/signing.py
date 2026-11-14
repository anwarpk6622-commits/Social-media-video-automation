"""HMAC-SHA256 signatures on approvals (security fix 1).

Why: before this fix, someone with access to the project files could edit a job's
fingerprints AND its approval record together and forge an approval. Now every
approval is signed with a secret key that lives ONLY in the operating system's
secure store (Windows Credential Manager / macOS Keychain / Secret Service via the
`keyring` package). Without that key a valid approval cannot be created or forged.

Fail closed: if the keyring is missing or broken, approving and uploading stop
with a clear message. Nothing falls back to a weaker storage silently.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets as _secrets

from .secrets import SERVICE, SecretStore, secret_key

KEY_NAME = secret_key("approval-signing", "local", "hmac-key")
SIGNATURE_VERSION = "approval-v1"


class SigningUnavailable(RuntimeError):
    """The signing key cannot be read or created (keyring missing / locked / broken)."""


class Signer:
    def __init__(self, store: SecretStore):
        self.store = store

    # --- key -----------------------------------------------------------------
    def _key(self, create: bool) -> bytes:
        try:
            value = self.store.get(KEY_NAME)
        except Exception as e:                                   # keyring backend errors
            raise SigningUnavailable(f"Secure keyring se signing key parhi nahi ja saki ({type(e).__name__}).") from None
        if not value:
            if not create:
                raise SigningUnavailable("Signing key mojood nahi — is computer par koi manzoori sign hi nahi hui.")
            value = _secrets.token_hex(32)                        # 256-bit random key, never printed
            try:
                self.store.set(KEY_NAME, value)
                if self.store.get(KEY_NAME) != value:
                    raise RuntimeError("read-back mismatch")
            except Exception as e:
                raise SigningUnavailable(f"Secure keyring mein signing key mehfooz nahi ho saki ({type(e).__name__}).") from None
        try:
            key = bytes.fromhex(value)
        except ValueError:
            raise SigningUnavailable("Keyring mein signing key kharab hai.") from None
        if len(key) < 32:
            raise SigningUnavailable("Keyring mein signing key bohat chhoti hai.")
        return key

    def ensure_key(self) -> str:
        """Create the key if needed; return its public id (safe to show)."""
        return self.key_id(self._key(create=True))

    @staticmethod
    def key_id(key: bytes) -> str:
        return hashlib.sha256(b"key-id:" + key).hexdigest()[:12]

    # --- signing ---------------------------------------------------------------
    @staticmethod
    def payload(job, approval: dict) -> bytes:
        """Everything the approval vouches for. Changing ANY of it breaks the signature."""
        body = {
            "v": SIGNATURE_VERSION,
            "job": job.id, "project": job.project, "platform": job.platform,
            "fingerprints": approval.get("fingerprints"),
            "privacy": approval.get("privacy"), "schedule": approval.get("schedule"),
            "public_confirmed": bool(approval.get("public_confirmed")),
            "time": approval.get("time"), "by": approval.get("by"),
        }
        return json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def sign(self, job, approval: dict) -> dict:
        key = self._key(create=True)
        sig = hmac.new(key, self.payload(job, approval), hashlib.sha256).hexdigest()
        return {"signature": sig, "key_id": self.key_id(key), "alg": "HMAC-SHA256", "v": SIGNATURE_VERSION}

    def verify(self, job) -> tuple[bool, str]:
        """(True, '') if the job's approval carries a valid signature for its CURRENT contents.

        Raises SigningUnavailable if the key cannot be read (caller must stop, not revoke)."""
        a = job.approval or {}
        sig = a.get("signature")
        if not sig:
            return False, "manzoori par dastakhat (signature) mojood nahi"
        key = self._key(create=False)
        if a.get("key_id") != self.key_id(key):
            return False, "manzoori kisi aur key se sign hui thi"
        # The signed fingerprints must also be the job's own current plan.
        from .fingerprint import approved_fingerprints
        if a.get("fingerprints") != approved_fingerprints(job) or a.get("privacy") != job.privacy \
                or a.get("schedule") != job.schedule:
            return False, "job ka mawaad manzoori se mukhtalif hai"
        expected = hmac.new(key, self.payload(job, a), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, str(sig)):
            return False, "manzoori ka dastakhat ghalat hai (job file chhedi gayi?)"
        return True, ""


def get_signer() -> Signer:
    """The real signer: OS keyring only. Fails closed with a clear message."""
    from .secrets import KeyringUnavailable, secure_store
    try:
        return Signer(secure_store())
    except KeyringUnavailable as e:
        raise SigningUnavailable(f"{e} Manzoori ke dastakhat ke liye zaroori hai.") from None


__all__ = ["Signer", "SigningUnavailable", "get_signer", "KEY_NAME", "SERVICE"]
