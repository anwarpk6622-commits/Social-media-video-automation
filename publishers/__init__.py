"""Phase 6 publishing framework (6.1: platform-independent core, NO network).

Modules
-------
models       Job data + allowed status transitions
store        jobs on disk (atomic writes, lock) — idempotent
fingerprint  SHA-256 of video / thumbnail / metadata (approval is bound to these)
plan         build publishing jobs from the Phase 5 publishing kit
validate     dry-run validation against conservative platform specs
approval     manual approval (typed phrase), separate PUBLIC confirmation
redact       remove tokens / keys from anything that is logged or shown
secrets      credential storage interface (keyring later; disabled in 6.1)
retry        retry with backoff + resumable chunked upload framework
adapters     platform adapter interface; offline FakeAdapter for simulation
runner       idempotent execution: verify approval → upload → processing → done
log          redacted JSONL log + report
secret_scan  scan files / staged changes for secrets before commits

Safety in 6.1: `publishing.live_enabled` is false and no real adapters exist,
so nothing can be uploaded. Simulations never change the real job state.
"""

PHASE = "6.1"
