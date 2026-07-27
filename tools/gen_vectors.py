#!/usr/bin/env python3
"""Generate language-neutral conformance vectors from the real Python atoms.

The vectors are the ground truth of the differential oracle: each is produced
by running this repo's real `atoms` implementation. Both this generator and the
Go decoder (loops-go/atoms/decode.go) build their native op from the SAME
canonical JSON op-encoding — that agreement is the conformance contract.

Provenance is pinned: the source commit is recorded, and every vector carries
`check` assertions lifted verbatim from the pytest suite. We assert those hold
against the computed output before writing — catching a Spec mis-built *here*
before it becomes false ground truth (advisor point 3).

Run:  uv run python tools/gen_vectors.py --loops-go ~/Code/loops-go
"""

from __future__ import annotations

import argparse
import json
from itertools import permutations

from _conformance import add_destination_arg, loops_commit, testdata_dir

from atoms import (
    Avg, Coerce, Collect, Count, Explode, Flatten, Latest, Max, Min, Pick,
    Project, Rename, Select, Skip, Split, Sum, TopN, Transform,
    Upsert, Where, Window, Spec, run_parse, run_parse_many,
)

GENERATED_BY = "loops:tools/gen_vectors.py"


# --- canonical encoding -> Python atoms op (mirror of atoms/decode.go) ---

def build_fold(d):
    op = d["op"]
    if op == "latest":  return Latest(target=d["target"])
    if op == "count":   return Count(target=d["target"])
    if op == "sum":     return Sum(target=d["target"], field=d["field"])
    if op == "collect": return Collect(target=d["target"], max=d.get("max", 0))
    if op == "upsert":  return Upsert(target=d["target"], key=d["key"])
    if op == "topn":    return TopN(target=d["target"], key=d["key"], by=d["by"], n=d["n"], desc=d.get("desc", True))
    if op == "min":     return Min(target=d["target"], field=d["field"])
    if op == "max":     return Max(target=d["target"], field=d["field"])
    if op == "avg":     return Avg(target=d["target"], field=d["field"])
    if op == "window":  return Window(target=d["target"], field=d["field"], size=d["size"])
    raise ValueError(f"unknown fold op {op!r}")


_PYTYPES = {"int": int, "float": float, "bool": bool, "str": str}


def build_parse(d):
    op = d["op"]
    if op == "skip":      return Skip(startswith=d.get("startswith"), contains=d.get("contains"), equals=d.get("equals"), field=d.get("field"))
    if op == "split":     return Split(delim=d.get("delim"), max=d.get("max"))
    if op == "pick":      return Pick(*d["indices"])
    if op == "rename":    return Rename({int(k): v for k, v in d["mapping"].items()})
    if op == "transform": return Transform(d["field"], strip=d.get("strip"), lstrip=d.get("lstrip"), rstrip=d.get("rstrip"), replace=tuple(d["replace"]) if d.get("replace") else None)
    if op == "coerce":    return Coerce({k: _PYTYPES[v] for k, v in d["types"].items()})
    if op == "select":    return Select(*d["fields"])
    if op == "explode":   return Explode(path=d["path"], carry=d.get("carry"))
    if op == "project":   return Project(fields=d["fields"])
    if op == "where":     return Where(path=d["path"], op=d["where_op"], value=d.get("value"), values=tuple(d.get("values", [])))
    if op == "flatten":   return Flatten(field=d["field"], into=d["into"], extract=tuple(d["extract"]))
    raise ValueError(f"unknown parse op {op!r}")


def resolve(obj, path):
    cur = obj
    for k in path.split("."):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        elif isinstance(cur, list) and k.lstrip("-").isdigit() and -len(cur) <= int(k) < len(cur):
            cur = cur[int(k)]
        else:
            return KeyError
    return cur


def check_assertions(name, output, checks):
    for path, expected in checks:
        got = resolve(output, path)
        if got != expected:
            raise AssertionError(
                f"[{name}] check failed: {path!r} -> {got!r} != {expected!r}\n  full output: {output!r}"
            )


def run_fold(folds, initial, payloads):
    spec = Spec(name="vec", folds=tuple(build_fold(f) for f in folds))
    state = initial
    for p in payloads:
        state = spec.apply(state, p)
    return state


def order_sensitive(folds, initial, payloads, cap=720):
    """True if any permutation of payloads yields a different final state.

    Uses Python == (value-equality: 15 == 15.0). Payloads here are integer-
    valued so float reassociation cannot spuriously flip the verdict.
    """
    if len(payloads) > 6:
        return None  # too many to enumerate; not classified
    base = run_fold(folds, initial, payloads)
    for perm in permutations(payloads):
        if run_fold(folds, initial, list(perm)) != base:
            return True
    return False


# =============================================================================
# Fold scenarios — lifted from libs/atoms/tests/test_fold_typed.py
# `check` pairs are copied verbatim from the pytest assertions.
# =============================================================================

FOLD_VECTORS = [
    dict(name="latest_with_ts",
         folds=[dict(op="latest", target="last_ts")],
         initial={"last_ts": None}, payloads=[{"_ts": 1234567890}],
         check=[("last_ts", 1234567890)]),
    dict(name="count_increments",
         folds=[dict(op="count", target="n")],
         initial={"n": 0}, payloads=[{}, {}, {}],
         check=[("n", 3)]),
    dict(name="sum_accumulates",
         folds=[dict(op="sum", target="total", field="amount")],
         initial={"total": 0}, payloads=[{"amount": 10}, {"amount": 5}],
         check=[("total", 15)]),
    dict(name="sum_missing_field_adds_zero",
         folds=[dict(op="sum", target="total", field="amount")],
         initial={"total": 7}, payloads=[{"other": 99}],
         check=[("total", 7)]),
    dict(name="collect_appends",
         folds=[dict(op="collect", target="items")],
         initial={"items": []}, payloads=[{"x": 1}, {"x": 2}],
         check=[("items.0.x", 1), ("items.1.x", 2)]),
    dict(name="collect_bounded",
         folds=[dict(op="collect", target="items", max=2)],
         initial={"items": []}, payloads=[{"v": 1}, {"v": 2}, {"v": 3}],
         check=[("items.0.v", 2), ("items.1.v", 3)]),
    dict(name="collect_extracts_refs",
         folds=[dict(op="collect", target="items")],
         initial={"items": []},
         payloads=[{"ref": "design/a,thread/b"}, {"ref": "rendering/c"}, {"other": "no refs"}],
         check=[("items.0._refs", ["design/a", "thread/b"]), ("items.1._refs", ["rendering/c"])]),
    dict(name="upsert_insert_and_update",
         folds=[dict(op="upsert", target="users", key="id")],
         initial={"users": {}},
         payloads=[{"id": "a", "name": "Alice"}, {"id": "b", "name": "Bob"}, {"id": "a", "name": "Alicia"}],
         check=[("users.a.name", "Alicia"), ("users.b.name", "Bob"), ("users.a._n", 2)]),
    dict(name="upsert_partial_payload_preserves_prior",
         folds=[dict(op="upsert", target="tasks", key="name")],
         initial={"tasks": {}},
         payloads=[{"name": "demo", "status": "open", "priority": "high", "message": "initial body"},
                   {"name": "demo", "status": "in_progress"}],
         check=[("tasks.demo.status", "in_progress"), ("tasks.demo.priority", "high"),
                ("tasks.demo.message", "initial body"), ("tasks.demo._n", 2)]),
    dict(name="upsert_accumulates_refs",
         folds=[dict(op="upsert", target="items", key="id")],
         initial={"items": {}},
         payloads=[{"id": "x", "ref": "a,b"}, {"id": "x", "ref": "c"}],
         check=[("items.x._refs", ["a", "b", "c"])]),
    dict(name="upsert_ignores_missing_key",
         folds=[dict(op="upsert", target="users", key="id")],
         initial={"users": {}}, payloads=[{"name": "NoId"}],
         check=[("users", {})]),
    dict(name="topn_keeps_highest",
         folds=[dict(op="topn", target="procs", key="pid", by="cpu", n=3)],
         initial={"procs": {}},
         payloads=[{"pid": "a", "cpu": 10}, {"pid": "b", "cpu": 30}, {"pid": "c", "cpu": 20}, {"pid": "d", "cpu": 50}],
         check=[("procs.b.cpu", 30), ("procs.c.cpu", 20), ("procs.d.cpu", 50)]),
    dict(name="topn_ascending",
         folds=[dict(op="topn", target="procs", key="pid", by="cpu", n=2, desc=False)],
         initial={"procs": {}},
         payloads=[{"pid": "a", "cpu": 10}, {"pid": "b", "cpu": 30}, {"pid": "c", "cpu": 20}],
         check=[("procs.a.cpu", 10), ("procs.c.cpu", 20)]),
    dict(name="topn_ignores_missing_fields",
         folds=[dict(op="topn", target="procs", key="pid", by="cpu", n=2)],
         initial={"procs": {}},
         payloads=[{"pid": "a", "cpu": 10}, {"pid": "b"}, {"cpu": 20}],
         check=[("procs.a.cpu", 10)]),
    dict(name="min_tracks_minimum",
         folds=[dict(op="min", target="coldest", field="temp")],
         initial={"coldest": None}, payloads=[{"temp": 20}, {"temp": 15}, {"temp": 25}],
         check=[("coldest", 15)]),
    dict(name="max_tracks_maximum",
         folds=[dict(op="max", target="hottest", field="temp")],
         initial={"hottest": None}, payloads=[{"temp": 20}, {"temp": 25}, {"temp": 15}],
         check=[("hottest", 25)]),
    dict(name="min_ignores_missing_field",
         folds=[dict(op="min", target="min", field="value")],
         initial={"min": None}, payloads=[{"other": 10}],
         check=[("min", None)]),
    dict(name="avg_running_average",
         folds=[dict(op="avg", target="rate", field="latency")],
         initial={"rate": None}, payloads=[{"latency": 10}, {"latency": 20}, {"latency": 30}],
         check=[("rate", 20.0)]),
    dict(name="avg_maintains_hidden_state",
         folds=[dict(op="avg", target="rate", field="latency")],
         initial={"rate": None}, payloads=[{"latency": 10}, {"latency": 20}],
         check=[("rate_sum", 30.0), ("rate_count", 2), ("rate", 15.0)]),
    dict(name="window_drops_oldest",
         folds=[dict(op="window", target="intervals", field="interval", size=3)],
         initial={"intervals": []}, payloads=[{"interval": i} for i in [1, 2, 3, 4, 5]],
         check=[("intervals", [3, 4, 5])]),
    dict(name="window_ignores_missing_field",
         folds=[dict(op="window", target="intervals", field="interval", size=3)],
         initial={"intervals": [1, 2]}, payloads=[{"other": 10}],
         check=[("intervals", [1, 2])]),
    dict(name="multiple_typed_folds",
         folds=[dict(op="count", target="n"), dict(op="sum", target="total", field="amount"), dict(op="latest", target="last_ts")],
         initial={"n": 0, "total": 0, "last_ts": None}, payloads=[{"amount": 42, "_ts": 1000}],
         check=[("n", 1), ("total", 42), ("last_ts", 1000)]),

    # --- R2 off-type rule: skip + {target}_rejected counter (SPEC §4.4) ---
    # Lifted from libs/atoms/tests/test_fold_rejection.py
    # (decision design/fold-off-type-skip-with-counter, loops 14eb723).
    dict(name="sum_bool_is_off_type",
         folds=[dict(op="sum", target="total", field="v")],
         initial={}, payloads=[{"v": True}],
         check=[("total_rejected", 1)]),  # bool is off-type: NOT folded as 1
    dict(name="sum_numeric_string_is_off_type",
         folds=[dict(op="sum", target="total", field="v")],
         initial={"total": 10}, payloads=[{"v": "5"}],
         check=[("total", 10), ("total_rejected", 1)]),  # no coercion
    dict(name="sum_string_skipped_and_counted",
         folds=[dict(op="sum", target="total", field="v")],
         initial={"total": 10}, payloads=[{"v": "high"}],
         check=[("total", 10), ("total_rejected", 1)]),
    dict(name="avg_rejected_does_not_bump_denominator",
         folds=[dict(op="avg", target="avg", field="v")],
         initial={}, payloads=[{"v": 10}, {"v": True}, {"v": "n/a"}, {"v": 20}],
         check=[("avg", 15.0), ("avg_count", 2), ("avg_rejected", 2)]),
    dict(name="min_bool_rejected",
         folds=[dict(op="min", target="lo", field="v")],
         initial={}, payloads=[{"v": 5}, {"v": True}],
         check=[("lo", 5), ("lo_rejected", 1)]),
    dict(name="max_string_rejected_no_raise",
         folds=[dict(op="max", target="hi", field="v")],
         initial={}, payloads=[{"v": 5}, {"v": "low"}],
         check=[("hi", 5), ("hi_rejected", 1)]),
    dict(name="topn_off_type_by_rejected",
         folds=[dict(op="topn", target="top", key="name", by="score", n=3)],
         initial={"top": {}}, payloads=[{"name": "a", "score": 9}, {"name": "b", "score": "best"}],
         check=[("top.a.score", 9), ("top_rejected", 1)]),
    dict(name="latest_missing_ts_rejected",
         folds=[dict(op="latest", target="last_seen")],
         initial={}, payloads=[{}],
         check=[("last_seen_rejected", 1)]),  # never wall-clock
]


# =============================================================================
# Parse scenarios — lifted from libs/atoms/tests/test_parse.py
# mode: "single" -> run_parse, "many" -> run_parse_many
# =============================================================================

PARSE_VECTORS = [
    dict(name="skip_startswith", mode="single",
         pipeline=[dict(op="skip", startswith="Filesystem"), dict(op="split"), dict(op="rename", mapping={"0": "a"})],
         inputs=[{"in": "Filesystem  Size", "out": None}, {"in": "/dev/sda1  100G", "out": {"a": "/dev/sda1"}}]),
    dict(name="skip_field_equals", mode="single",
         pipeline=[dict(op="split"), dict(op="rename", mapping={"0": "name", "1": "cpu"}), dict(op="skip", field="cpu", equals="0")],
         inputs=[{"in": "idle_proc 0", "out": None}, {"in": "busy_proc 50", "out": {"name": "busy_proc", "cpu": "50"}}]),
    dict(name="skip_field_missing_passes", mode="single",
         pipeline=[dict(op="split"), dict(op="rename", mapping={"0": "a"}), dict(op="skip", field="missing", equals="x")],
         inputs=[{"in": "value", "out": {"a": "value"}}]),
    dict(name="split_whitespace_collapses", mode="single",
         pipeline=[dict(op="split"), dict(op="pick", indices=[0, 1, 2]), dict(op="rename", mapping={"0": "a", "1": "b", "2": "c"})],
         inputs=[{"in": "hello   world  test", "out": {"a": "hello", "b": "world", "c": "test"}}]),
    dict(name="split_max", mode="single",
         pipeline=[dict(op="split", delim="=", max=1), dict(op="pick", indices=[0, 1]), dict(op="rename", mapping={"0": "key", "1": "val"})],
         inputs=[{"in": "name=a=b=c", "out": {"key": "name", "val": "a=b=c"}}]),
    dict(name="split_empty_fields_preserved", mode="single",
         pipeline=[dict(op="split", delim=":"), dict(op="rename", mapping={"0": "a", "1": "b", "2": "c"})],
         inputs=[{"in": "a::c", "out": {"a": "a", "b": "", "c": "c"}}]),
    dict(name="pick_negative_index", mode="single",
         pipeline=[dict(op="split"), dict(op="pick", indices=[0, -1]), dict(op="rename", mapping={"0": "first", "1": "last"})],
         inputs=[{"in": "a b c d", "out": {"first": "a", "last": "d"}}]),
    dict(name="pick_out_of_range", mode="single",
         pipeline=[dict(op="split"), dict(op="pick", indices=[0, 99]), dict(op="rename", mapping={"0": "a", "1": "b"})],
         inputs=[{"in": "hello world", "out": None}]),
    dict(name="transform_strip", mode="single",
         pipeline=[dict(op="split"), dict(op="pick", indices=[0, 1]), dict(op="rename", mapping={"0": "name", "1": "pct"}), dict(op="transform", field="pct", strip="%")],
         inputs=[{"in": "disk1 27%", "out": {"name": "disk1", "pct": "27"}}]),
    dict(name="transform_combined", mode="single",
         pipeline=[dict(op="split"), dict(op="rename", mapping={"0": "val"}), dict(op="transform", field="val", strip=" ", replace=["," , ""])],
         inputs=[{"in": " 1,234 ", "out": {"val": "1234"}}]),
    dict(name="coerce_int_float", mode="single",
         pipeline=[dict(op="split"), dict(op="rename", mapping={"0": "name", "1": "count", "2": "price"}), dict(op="coerce", types={"count": "int", "price": "float"})],
         inputs=[{"in": "item 5 9.99", "out": {"name": "item", "count": 5, "price": 9.99}}]),
    dict(name="coerce_bool", mode="single",
         pipeline=[dict(op="split"), dict(op="rename", mapping={"0": "flag"}), dict(op="coerce", types={"flag": "bool"})],
         inputs=[{"in": "true", "out": {"flag": True}}, {"in": "no", "out": {"flag": False}}, {"in": "maybe", "out": None}]),
    dict(name="coerce_failure_none", mode="single",
         pipeline=[dict(op="split"), dict(op="rename", mapping={"0": "count"}), dict(op="coerce", types={"count": "int"})],
         inputs=[{"in": "not_a_number", "out": None}]),
    dict(name="select_subset", mode="single",
         pipeline=[dict(op="select", fields=["Name", "State"])],
         inputs=[{"in": {"Name": "x", "State": "running", "Other": "y"}, "out": {"Name": "x", "State": "running"}}]),
    dict(name="full_df_pipeline", mode="single",
         pipeline=[dict(op="split"), dict(op="pick", indices=[0, 1, 2, 3, 4, 8]),
                   dict(op="rename", mapping={"0": "fs", "1": "size", "2": "used", "3": "avail", "4": "pct", "5": "mount"}),
                   dict(op="transform", field="pct", strip="%"), dict(op="coerce", types={"pct": "int"})],
         inputs=[{"in": "/dev/disk3s1s1  466Gi  8.8Gi  211Gi     5%   96Ki  2213694528    0%   /",
                  "out": {"fs": "/dev/disk3s1s1", "size": "466Gi", "used": "8.8Gi", "avail": "211Gi", "pct": 5, "mount": "/"}}]),
    dict(name="empty_pipeline_none", mode="single", pipeline=[],
         inputs=[{"in": "hello", "out": None}]),
    dict(name="pipeline_not_dict_none", mode="single", pipeline=[dict(op="split")],
         inputs=[{"in": "hello world", "out": None}]),
    dict(name="unicode", mode="single",
         pipeline=[dict(op="split"), dict(op="rename", mapping={"0": "emoji", "1": "text"})],
         inputs=[{"in": "🎉 celebration", "out": {"emoji": "🎉", "text": "celebration"}}]),
    # --- Where / Explode / Project / Flatten ---
    dict(name="where_equals", mode="single",
         pipeline=[dict(op="where", path="status", where_op="equals", value="success")],
         inputs=[{"in": {"status": "success", "data": [1]}, "out": {"status": "success", "data": [1]}},
                 {"in": {"status": "error", "data": []}, "out": None}]),
    dict(name="where_exists", mode="single",
         pipeline=[dict(op="where", path="labels", where_op="exists")],
         inputs=[{"in": {"labels": {"severity": "critical"}}, "out": {"labels": {"severity": "critical"}}},
                 {"in": {"name": "test"}, "out": None}]),
    dict(name="where_equals_bool", mode="single",  # str(True)=="True" — exercises bool stringification
         pipeline=[dict(op="where", path="enabled", where_op="equals", value="True")],
         inputs=[{"in": {"enabled": True}, "out": {"enabled": True}},
                 {"in": {"enabled": False}, "out": None}]),
    dict(name="where_in_nested", mode="single",
         pipeline=[dict(op="where", path="message.role", where_op="in_", values=["user", "assistant"])],
         inputs=[{"in": {"message": {"role": "assistant"}, "id": "123"}, "out": {"message": {"role": "assistant"}, "id": "123"}}]),
    dict(name="project_missing_path_none", mode="single",
         pipeline=[dict(op="project", fields={"name": "labels.alertname", "state": "state"})],
         inputs=[{"in": {"state": "firing"}, "out": {"name": None, "state": "firing"}}]),
    dict(name="flatten_multi_extract", mode="single",
         pipeline=[dict(op="flatten", field="tool_calls", into="tool_text", extract=["name", "input"])],
         inputs=[{"in": {"prompt": "hello", "tool_calls": [{"name": "read_file", "input": "foo.py"}]},
                  "out": {"prompt": "hello", "tool_calls": [{"name": "read_file", "input": "foo.py"}], "tool_text": "name: read_file\ninput: foo.py"}}]),
    dict(name="flatten_single_extract", mode="single",
         pipeline=[dict(op="flatten", field="items", into="names", extract=["name"])],
         inputs=[{"in": {"items": [{"name": "a"}, {"name": "b"}]}, "out": {"items": [{"name": "a"}, {"name": "b"}], "names": "a\nb"}}]),
    # --- stream mode ---
    dict(name="stream_where_explode_project", mode="many",
         pipeline=[dict(op="where", path="status", where_op="equals", value="success"),
                   dict(op="explode", path="data.alerts"),
                   dict(op="project", fields={"alertname": "labels.alertname", "state": "state"})],
         inputs=[{"in": {"status": "success", "data": {"alerts": [
             {"labels": {"alertname": "HighCPU"}, "state": "firing"},
             {"labels": {"alertname": "DiskFull"}, "state": "pending"}]}},
             "out": [{"alertname": "HighCPU", "state": "firing"}, {"alertname": "DiskFull", "state": "pending"}]}]),
    dict(name="stream_double_explode_carry", mode="many",
         pipeline=[dict(op="explode", path="data.groups"),
                   dict(op="explode", path="rules", carry={"name": "group_name"})],
         inputs=[{"in": {"data": {"groups": [
             {"name": "g1", "rules": [{"rule": "r1"}, {"rule": "r2"}]},
             {"name": "g2", "rules": [{"rule": "r3"}]}]}},
             "out": [{"rule": "r1", "group_name": "g1"}, {"rule": "r2", "group_name": "g1"}, {"rule": "r3", "group_name": "g2"}]}]),
    dict(name="stream_explode_scalar", mode="many",
         pipeline=[dict(op="explode", path="items")],
         inputs=[{"in": {"items": [1, 2, 3]}, "out": [{"_value": 1}, {"_value": 2}, {"_value": 3}]}]),
]


def gen_folds(commit):
    out = []
    for v in FOLD_VECTORS:
        result = run_fold(v["folds"], v["initial"], v["payloads"])
        check_assertions(v["name"], result, v["check"])
        out.append({
            "name": v["name"],
            "folds": v["folds"],
            "initial": v["initial"],
            "payloads": v["payloads"],
            "expected": result,
            "order_sensitive": order_sensitive(v["folds"], v["initial"], v["payloads"]),
        })
    return {"kind": "fold", "python_commit": commit, "generated_by": GENERATED_BY, "vectors": out}


def gen_parse(commit):
    out = []
    for v in PARSE_VECTORS:
        pipeline = [build_parse(d) for d in v["pipeline"]]
        cases = []
        for case in v["inputs"]:
            if v["mode"] == "many":
                got = run_parse_many(case["in"], pipeline)
            else:
                got = run_parse(case["in"], pipeline)
            if got != case["out"]:
                raise AssertionError(
                    f"[{v['name']}] input {case['in']!r} -> {got!r} != expected {case['out']!r}"
                )
            cases.append({"input": case["in"], "expected": got})
        out.append({"name": v["name"], "mode": v["mode"], "pipeline": v["pipeline"], "cases": cases})
    return {"kind": "parse", "python_commit": commit, "generated_by": GENERATED_BY, "vectors": out}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    add_destination_arg(parser)
    args = parser.parse_args()
    out = testdata_dir(args.loops_go, "vectors")

    commit = loops_commit()
    folds = gen_folds(commit)
    parse = gen_parse(commit)
    (out / "fold_vectors.json").write_text(json.dumps(folds, indent=2, ensure_ascii=False) + "\n")
    (out / "parse_vectors.json").write_text(json.dumps(parse, indent=2, ensure_ascii=False) + "\n")
    nf = len(folds["vectors"])
    nps = sum(len(v["cases"]) for v in parse["vectors"])
    print(f"wrote {nf} fold vectors, {len(parse['vectors'])} parse scenarios ({nps} cases) @ {commit[:9]}")


if __name__ == "__main__":
    main()
