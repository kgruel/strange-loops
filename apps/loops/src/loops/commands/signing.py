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

_KEY_FILE = "ed25519.key"


def keys_dir_for(vertex_path: Path) -> Path:
    """The custody-co-located key directory for a vertex file."""
    return vertex_path.parent / "keys"


def ensure_signing_key(vertex_path: Path):
    """Generate (or load) the custody-co-located keypair for a vertex.

    design/tick-key-custody-colocated: the private key lives at
    ``<vertex dir>/keys/`` next to the store it signs, and key CREATION
    owns gitignoring that directory (convenience is the mitigation for
    the committed-key failure mode, not discipline). Idempotent: an
    existing key loads untouched. This is the single entry point for
    minting custody — ``loops init`` and ``loops add ... observer
    --keygen`` both ride it; everything else only LOADS.
    """
    from sign import ed25519

    keypair = ed25519.load_or_generate(keys_dir_for(vertex_path))

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


def declared_observer_keys(vertex_path: Path) -> dict[str, str]:
    """Read the observer-key registry from a .vertex file.

    Returns {observer_name: base64_public_key} for observers declaring a
    key field. Empty dict when there is no observers block, no keys, or
    the file is not parseable as a vertex (e.g. a raw .db target).
    """
    if vertex_path.suffix != ".vertex" or not vertex_path.exists():
        return {}
    try:
        from lang import parse_vertex_file

        ast = parse_vertex_file(vertex_path)
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
