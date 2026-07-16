"""custody — loops signing composition, the store's at-rest signing format.

The format definition two writers must agree on: domain constants, key
layout, signer/verifier construction. Promoted from apps/loops (design/
architecture/custody-lib-extraction) when tasked became the second
consumer — a format definition sits below every writer.
"""

from custody.signing import (
    FACT_DOMAIN,
    TICK_DOMAIN,
    declared_observer_keys,
    ensure_signing_key,
    fact_signer_for,
    fact_verifier_for,
    keys_dir_for,
    observer_keys_dir_for,
    tick_signer_for,
    tick_verifier_for,
)

__all__ = [
    "FACT_DOMAIN",
    "TICK_DOMAIN",
    "declared_observer_keys",
    "ensure_signing_key",
    "fact_signer_for",
    "fact_verifier_for",
    "keys_dir_for",
    "observer_keys_dir_for",
    "tick_signer_for",
    "tick_verifier_for",
]
