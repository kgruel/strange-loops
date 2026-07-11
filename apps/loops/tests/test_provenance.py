"""Unit tests for the diff-replay provenance engine (loops.provenance).

Attribution is faithful by construction — it drives the REAL fold op. These
lock the attribution contract: last-set-wins per field, cleared fields,
multi-observer, single fact, twice-superseded history order, the collect
degrade, and the missing-source-facts case.
"""
from __future__ import annotations

from atoms.fold import Collect, Upsert

from loops.provenance import replay_attribution, to_dict

TOPIC = Upsert(target="s", key="topic")


def _fact(ts, observer, **fields):
    return {"_ts": ts, "_observer": observer, **fields}


def _attr(prov, field):
    return next(a for a in prov.fields if a.field == field)


def test_single_fact_attributes_to_it():
    facts = [_fact(100.0, "alice", topic="x", message="hello", status="open")]
    prov = replay_attribution(TOPIC, facts, kind="decision", key="x", key_field="topic")
    assert prov.mode == "upsert"
    assert prov.total_facts == 1
    assert {a.field for a in prov.fields} == {"message", "status"}  # topic is the key
    msg = _attr(prov, "message")
    assert msg.value == "hello"
    assert msg.setter.index == 1 and msg.setter.total == 1
    assert msg.setter.observer == "alice"
    assert msg.priors == ()


def test_last_set_wins_only_records_changes():
    # status: open(1) open(2) review(3) open(4). Facts 2 and 4 don't change the
    # value relative to the prior step, so they are NOT attribution steps.
    facts = [
        _fact(1.0, "a", topic="x", status="open"),
        _fact(2.0, "a", topic="x", status="open"),
        _fact(3.0, "b", topic="x", status="review"),
        _fact(4.0, "c", topic="x", status="open"),
    ]
    prov = replay_attribution(TOPIC, facts, kind="thread", key="x", key_field="topic")
    st = _attr(prov, "status")
    assert st.value == "open"
    assert st.setter.index == 4  # last CHANGE back to open
    # History newest-first: review@3, open@1 (the fact-2 no-op is absent).
    assert [(p.value, p.fact.index) for p in st.priors] == [("review", 3), ("open", 1)]


def test_field_persists_until_resupplied():
    # message set at fact 1, never re-supplied; a later fact touches status only.
    facts = [
        _fact(1.0, "a", topic="x", message="body", status="open"),
        _fact(2.0, "b", topic="x", status="done"),
    ]
    prov = replay_attribution(TOPIC, facts, kind="thread", key="x", key_field="topic")
    msg = _attr(prov, "message")
    assert msg.value == "body" and msg.setter.index == 1  # merge kept it
    assert _attr(prov, "status").setter.index == 2


def test_field_cleared_by_empty_sentinel():
    # field= supplies "" → merge overlays it → an honest change to empty.
    facts = [
        _fact(1.0, "a", topic="x", label="draft"),
        _fact(2.0, "b", topic="x", label=""),
    ]
    prov = replay_attribution(TOPIC, facts, kind="thread", key="x", key_field="topic")
    lbl = _attr(prov, "label")
    assert lbl.value == ""
    assert lbl.setter.index == 2
    assert [(p.value, p.fact.index) for p in lbl.priors] == [("draft", 1)]


def test_value_superseded_twice_history_order():
    facts = [
        _fact(1.0, "a", topic="x", v="one"),
        _fact(2.0, "b", topic="x", v="two"),
        _fact(3.0, "c", topic="x", v="three"),
    ]
    prov = replay_attribution(TOPIC, facts, kind="d", key="x", key_field="topic")
    v = _attr(prov, "v")
    assert v.value == "three" and v.setter.index == 3
    # newest-first supersession history
    assert [(p.value, p.fact.index) for p in v.priors] == [("two", 2), ("one", 1)]


def test_multi_observer_carried_in_order():
    facts = [
        _fact(1.0, "alice", topic="x", v="a"),
        _fact(2.0, "bob", topic="x", v="b"),
    ]
    prov = replay_attribution(TOPIC, facts, kind="d", key="x", key_field="topic")
    assert prov.observers == ("alice", "bob")
    assert _attr(prov, "v").setter.observer == "bob"


def test_meta_and_key_fields_excluded():
    facts = [_fact(1.0, "a", topic="x", message="m")]
    prov = replay_attribution(TOPIC, facts, kind="d", key="x", key_field="topic")
    fields = {a.field for a in prov.fields}
    assert "topic" not in fields  # the key
    assert not any(f.startswith("_") for f in fields)  # engine metadata


def test_collect_fold_degrades_to_chronology():
    facts = [_fact(1.0, "a", context="c1"), _fact(2.0, "b", context="c2")]
    prov = replay_attribution(
        Collect(target="log"), facts, kind="cite", key="any", key_field=None,
    )
    assert prov.mode == "collect"
    assert prov.fields == ()
    assert prov.total_facts == 2
    assert len(prov.facts) == 2  # raw ledger preserved chronologically


def test_none_fold_op_degrades_to_collect():
    prov = replay_attribution(None, [_fact(1.0, "a", v="x")], kind="k", key="y", key_field=None)
    assert prov.mode == "collect"


def test_empty_source_facts():
    prov = replay_attribution(TOPIC, [], kind="d", key="missing", key_field="topic")
    assert prov.mode == "empty"
    assert prov.total_facts == 0
    assert prov.fields == ()


def test_non_dict_payloads_skipped():
    facts = [_fact(1.0, "a", topic="x", v="ok"), "garbage", None]
    prov = replay_attribution(TOPIC, facts, kind="d", key="x", key_field="topic")
    assert prov.total_facts == 1
    assert _attr(prov, "v").value == "ok"


def test_to_dict_shape():
    facts = [
        _fact(1.0, "a", topic="x", v="one"),
        _fact(2.0, "b", topic="x", v="two"),
    ]
    prov = replay_attribution(TOPIC, facts, kind="d", key="x", key_field="topic")
    d = to_dict(prov)
    assert d["mode"] == "upsert"
    assert d["kind"] == "d" and d["key"] == "x" and d["key_field"] == "topic"
    assert d["total_facts"] == 2
    v = next(f for f in d["fields"] if f["field"] == "v")
    assert v["value"] == "two"
    assert v["setter"]["index"] == 2 and v["setter"]["observer"] == "b"
    assert v["priors"] == [{"value": "one", "setter": {
        "index": 1, "total": 2, "ts": 1.0, "observer": "a"}}]
    # upsert mode carries attribution in fields, not a raw facts dump
    assert d["facts"] == []


def test_to_dict_collect_carries_facts():
    prov = replay_attribution(
        Collect(target="log"), [_fact(1.0, "a", context="c")], kind="cite",
        key="any", key_field=None,
    )
    d = to_dict(prov)
    assert d["mode"] == "collect"
    assert len(d["facts"]) == 1 and d["facts"][0]["context"] == "c"
