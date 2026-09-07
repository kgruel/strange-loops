"""Malformed provider evidence remains a serializable precommit refusal."""

import json

import pytest
from engine.credentials import (
    CredentialBindingEvidence,
    CredentialBindingRefused,
    CredentialPurpose,
    CredentialRequest,
    SigningDomain,
)

from sdk.errors import ArrivalRefusal, normalize_exception


@pytest.mark.parametrize("field", ["key_ref", "algorithm", "public_key", "provenance"])
def test_malformed_binding_field_does_not_break_refusal_serialization(field):
    request = CredentialRequest(
        "work", "alice", SigningDomain.FACT, CredentialPurpose.AUTHORSHIP
    )
    values = dict(
        key_ref="opaque-ref", algorithm="ed25519", public_key="public", provenance="created"
    )
    values[field] = object()
    evidence = CredentialBindingEvidence(request=request, **values)
    result = normalize_exception(
        CredentialBindingRefused("corrupt-binding", request=request, evidence=evidence)
    )
    assert isinstance(result, ArrivalRefusal)
    encoded = json.loads(json.dumps(result.as_dict()))
    details = encoded["details"]["credential_binding"]
    assert details["binding"][field] is None
    assert details["request"]["observer"] == "alice"
    assert details["reason"] == "corrupt-binding"
