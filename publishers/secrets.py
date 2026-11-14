"""Credential storage ARCHITECTURE (Phase 6.1: storing is disabled on purpose).

Future (6.2+): OAuth tokens go to the operating system's secure store via the
`keyring` package — Windows Credential Manager, macOS Keychain, or Secret Service
on Linux. Never into the project, never into Git, never into logs or the preview.

Phase 6.1 rules
---------------
- `get_store()` returns a store whose `set()` refuses (no credentials yet).
- `MemoryStore` exists only for automated tests.
- Secret names are namespaced per platform and account: "urdu-video/youtube/<account>".
"""

from __future__ import annotations

from .redact import MASK

SERVICE = "urdu-video-automation"


class SecretStoreDisabled(RuntimeError):
    pass


class SecretStore:
    name = "base"

    def get(self, key: str) -> str | None:
        raise NotImplementedError

    def set(self, key: str, value: str) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    def describe(self, key: str) -> str:
        """Safe for printing: never the value itself."""
        return f"{key}: {'set' if self.get(key) else 'not set'}"

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name} (values hidden)>"


class DisabledStore(SecretStore):
    """Phase 6.1: no credentials may be requested or stored."""
    name = "disabled (Phase 6.1)"

    def get(self, key: str) -> str | None:
        return None

    def set(self, key: str, value: str) -> None:
        raise SecretStoreDisabled("Phase 6.1 mein koi credential store nahi hota. Yeh Phase 6.2 mein aayega.")

    def delete(self, key: str) -> None:
        return None


class KeyringStore(SecretStore):
    """OS secure store (Windows Credential Manager / macOS Keychain / Secret Service)."""
    name = "os-keyring"

    def __init__(self):
        import keyring  # optional dependency, only from Phase 6.2
        self._kr = keyring

    def get(self, key: str) -> str | None:
        return self._kr.get_password(SERVICE, key)

    def set(self, key: str, value: str) -> None:
        self._kr.set_password(SERVICE, key, value)

    def delete(self, key: str) -> None:
        try:
            self._kr.delete_password(SERVICE, key)
        except Exception:
            pass


class MemoryStore(SecretStore):
    """Tests only — values live in memory and disappear with the process."""
    name = "memory (tests)"

    def __init__(self):
        self._d: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._d.get(key)

    def set(self, key: str, value: str) -> None:
        self._d[key] = value

    def delete(self, key: str) -> None:
        self._d.pop(key, None)

    def __str__(self) -> str:
        return f"MemoryStore({ {k: MASK for k in self._d} })"


def secret_key(platform: str, account: str = "default", kind: str = "oauth") -> str:
    return f"{SERVICE}/{platform}/{account}/{kind}"


class KeyringUnavailable(RuntimeError):
    pass


def secure_store() -> SecretStore:
    """The OS secure store (Windows Credential Manager / macOS Keychain / Secret Service).

    Fails closed: no `keyring` package, or only keyring's insecure/'fail' backend → error.
    There is NO fallback to files or environment variables."""
    try:
        import keyring
    except ImportError:
        raise KeyringUnavailable("Secure keyring install nahi: pip install -r requirements-publishing.txt") from None
    try:
        backend = keyring.get_keyring()
    except Exception as e:
        raise KeyringUnavailable(f"OS keyring khul nahi saka ({type(e).__name__}).") from None
    mod = type(backend).__module__.lower()
    if any(bad in mod for bad in ("fail", "null", "plaintext", "keyrings.alt")):
        raise KeyringUnavailable("Is computer par mehfooz OS keyring nahi mila (Windows Credential Manager / "
                                 "macOS Keychain / Secret Service).")
    return KeyringStore()


def get_store(live_enabled: bool = False) -> SecretStore:
    if not live_enabled:
        return DisabledStore()
    try:
        return KeyringStore()
    except ImportError as e:
        raise RuntimeError("Secure keyring install nahi: pip install keyring (Phase 6.2 mein).") from e
