"""Tick-signing composition — where libs/sign meets the engine's injection points.

The engine takes callables, never imports sign (design/tick-key-custody-
colocated: INJECTION NOT IMPORT). This module is the composition layer:

- the domain-separation constant ``loops-tick-v1`` lives HERE, not in
  libs/sign (which stays loops-agnostic) and not in engine (which never
  sees the algorithm);
- key custody is co-located with the store: the private key lives at
  ``<vertex dir>/keys/ed25519.key`` next to the .vertex and its db —
  slice/merge already strip chain+signature columns, so the key dies with
  the store's home (new custody context semantics);
- the verification registry IS the vertex file (design/observer-key-
  registry): observer declarations carry a ``key`` field (raw-32-byte
  base64), and the verifier accepts a signature matching ANY declared key
  (anticipates rotation and multi-writer without a key-id column today).

Progressive policy is structural: no key material → tick_signer_for
returns None → ticks append unsigned (honest pre-signature era). Key
generation + gitignoring happens only through ``ensure_signing_key``
(reached via ``loops init`` or ``loops add <v> observer --keygen``);
the load-side helpers never generate implicitly.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

TICK_DOMAIN = "loops-tick-v1"
FACT_DOMAIN = "loops-fact-v1"

_KEY_FILE = "ed25519.key"


def keys_dir_for(vertex_path: Path) -> Path:
    """The custody-co-located key directory for a vertex file."""
    return vertex_path.parent / "keys"


def ensure_signing_key(vertex_path: Path, observer: str | None = None):
    """Generate (or load) the custody-co-located keypair for a vertex.

    design/tick-key-custody-colocated: the private key lives at
    ``<vertex dir>/keys/`` next to the store it signs, and key CREATION
    owns gitignoring that directory (convenience is the mitigation for
    the committed-key failure mode, not discipline). Idempotent: an
    existing key loads untouched. This is the single entry point for
    minting custody — ``loops init`` and ``loops add ... observer
    --keygen`` both ride it; everything else only LOADS.

    ``observer`` (delta 3): mint into the per-observer layout
    ``keys/<observer>/`` instead of the flat (self-observer) layout.
    The self-observer keeps the flat layout — fact_signer_for resolves
    both, and the flat key remains what tick_signer_for loads.
    """
    from sign import ed25519

    key_dir = keys_dir_for(vertex_path)
    if observer is not None and observer != vertex_path.stem:
        key_dir = key_dir / observer
    keypair = ed25519.load_or_generate(key_dir)

    gitignore = vertex_path.parent / ".gitignore"
    if gitignore.exists():
        lines = gitignore.read_text().splitlines()
        if "keys/" not in (ln.strip() for ln in lines):
            gitignore.write_text(gitignore.read_text().rstrip("\n") + "\nkeys/\n")
    else:
        gitignore.write_text("keys/\n")

    return keypair


def tick_signer_for(vertex_path: Path) -> Callable[[str], str] | None:
    """Build the tick signer for a vertex, or None when no key exists.

    None is not an error — it is the pre-signature era. Key generation is
    init's job; an absent key here means this vertex has not opted into
    signing yet.
    """
    key_dir = keys_dir_for(vertex_path)
    if not (key_dir / _KEY_FILE).exists():
        return None
    from sign import ed25519

    keypair = ed25519.load_or_generate(key_dir)  # exists → pure load
    return lambda digest: ed25519.sign(keypair, digest.encode(), domain=TICK_DOMAIN)


def observer_keys_dir_for(vertex_path: Path, observer: str) -> Path:
    """Per-observer key directory (delta 3) — ``keys/<observer>/``.

    Observer names may carry slashes (``kyle/loops-claude``); they nest
    as directories. The FLAT layout (``keys/ed25519.key``, delta 2) is
    the SELF-observer's key — fact_signer_for falls back to it for the
    vertex's own name, so existing single-key vertices sign facts
    without a key migration.
    """
    return keys_dir_for(vertex_path) / observer


def fact_signer_for(vertex_path: Path):
    """Build the per-observer fact signer for a vertex, or None when the
    vertex has no key material at all.

    Returns a callable (observer str, content digest str) -> signature
    str | None, matching engine's fact_signer contract
    (design/fact-signing-per-observer-keys). Key resolution per observer:

    1. ``keys/<observer>/ed25519.key`` — the per-observer layout;
    2. flat ``keys/ed25519.key`` — ONLY for the self-observer (the
       vertex's own name), delta-2 back-compat;
    3. otherwise None — that observer's facts append unsigned (honest
       per-observer pre-signature era).

    Keypairs are loaded lazily and cached per observer for the life of
    the signer (one CLI invocation). Returns None (no signer at all)
    when the keys/ directory doesn't exist — structurally identical to
    the pre-signature era, same posture as tick_signer_for.
    """
    keys_root = keys_dir_for(vertex_path)
    if not keys_root.exists():
        return None
    from sign import ed25519

    self_observer = vertex_path.stem
    cache: dict[str, ed25519.Keypair | None] = {}

    def _keypair(observer: str):
        # An empty observer must never sign: ``keys_root / ""`` collapses
        # to the flat layout, which would mint the VERTEX key's authorship
        # claim for an anonymous writer. Same guard for path traversal —
        # an observer name is a key, not a path expression.
        if not observer or ".." in observer.split("/"):
            return None
        if observer in cache:
            return cache[observer]
        key_dir = keys_root / observer
        if not (key_dir / _KEY_FILE).exists():
            if observer == self_observer and (keys_root / _KEY_FILE).exists():
                key_dir = keys_root  # flat delta-2 layout = self-observer
            else:
                cache[observer] = None
                return None
        cache[observer] = ed25519.load_or_generate(key_dir)  # exists → pure load
        return cache[observer]

    def signer(observer: str, digest: str) -> str | None:
        keypair = _keypair(observer)
        if keypair is None:
            return None
        return ed25519.sign(keypair, digest.encode(), domain=FACT_DOMAIN)

    return signer


def fact_verifier_for(
    vertex_path: Path,
) -> tuple[Callable[[str, str, str], bool] | None, dict[str, str]]:
    """Build the fact verifier from a vertex's observer-key registry.

    Returns (verifier, declared_keys). verifier is a callable
    (observer, signature, content digest) -> bool that checks against
    THAT observer's declared key EXACTLY — authorship is a per-observer
    claim, so the tick path's any-key relaxation (a receipt-claim
    affordance) deliberately does not apply here. An observer with no
    declared key fails verification of any signature attributed to it
    (a signed fact from an unregistered observer is unverifiable, which
    verify reports as a break — the registry is the trust anchor).
    None when the registry declares no keys.
    """
    keys = declared_observer_keys(vertex_path)
    if not keys:
        return None, keys
    from sign import ed25519

    publics = {}
    for name, b64 in keys.items():
        try:
            publics[name] = ed25519.public_key_from_b64(b64)
        except ValueError:
            continue  # malformed declared key: cannot verify against it

    def verifier(observer: str, signature: str, digest: str) -> bool:
        pub = publics.get(observer)
        if pub is None:
            return False
        return ed25519.verify(pub, signature, digest.encode(), domain=FACT_DOMAIN)

    return verifier, keys


def declared_observer_keys(vertex_path: Path) -> dict[str, str]:
    """Read the observer-key registry from a vertex's resolved declaration.

    Routes through the store-backed resolver (SPEC §9.5): once a lineage is
    opened, the current-head keys come from the store's declaration, not the
    file. (Key-as-of-witness-position — verifying a historical tick under the
    key that was current AT that tick — is S7, not here; this is the
    current-head registry.)

    Returns {observer_name: base64_public_key} for observers declaring a
    key field. Empty dict when there is no observers block, no keys, or
    the file is not parseable as a vertex (e.g. a raw .db target).
    """
    if vertex_path.suffix != ".vertex" or not vertex_path.exists():
        return {}
    try:
        from engine import load_declaration

        ast = load_declaration(vertex_path)
    except Exception:  # noqa: BLE001 — no registry is an answer, not a crash
        return {}
    if not getattr(ast, "observers", None):
        return {}
    return {o.name: o.key for o in ast.observers if o.key}


def tick_verifier_for(
    vertex_path: Path,
) -> tuple[Callable[[str, str], bool] | None, dict[str, str]]:
    """Build the tick verifier from a vertex's observer-key registry.

    Returns (verifier, declared_keys). verifier is None when the registry
    declares no keys — verify_chain then skips signature checks and the
    caller can render the honest 'unchecked' state. A signature passes if
    it verifies under ANY declared key.
    """
    keys = declared_observer_keys(vertex_path)
    if not keys:
        return None, keys
    from sign import ed25519

    publics = []
    for b64 in keys.values():
        try:
            publics.append(ed25519.public_key_from_b64(b64))
        except ValueError:
            continue  # malformed declared key: cannot verify against it

    def verifier(signature: str, digest: str) -> bool:
        return any(
            ed25519.verify(pub, signature, digest.encode(), domain=TICK_DOMAIN)
            for pub in publics
        )

    return verifier, keys
