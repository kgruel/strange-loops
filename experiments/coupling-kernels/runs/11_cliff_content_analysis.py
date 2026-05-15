"""Forensic analysis: WHAT KIND of content lives in the cliff zone?

Run 09 + 10 confirmed truncation-as-coupling-function with cliff at B=1120→560
(persist_frac drop 0.44). This run dives into which specific baseline clusters
survive vs fail at that transition — does the cliff have a content signature?

Loads:
  - Run 09's ∞-baseline query-run (components)
  - Run 09's B=560 query-run (components)
  - Their lineage comparison (matches)
  - Fixture manifest (row contents)

Categorizes each baseline cluster as survivor (j>=0.5) or failure (j<0.5),
then characterizes by: cluster size, avg message length, kind distribution,
topic-prefix distribution, status distribution.

Emits an observation summarizing what distinguishes survivors from failures.
"""
from __future__ import annotations
import json
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core.emit import _emit                                             # noqa: E402

DB = ROOT / "data" / "coupling-kernels.db"
MANIFEST = ROOT / "fixtures" / "project_all_kinds_manifest.json"
VERTEX_PATH = ROOT / "coupling-kernels.vertex"

BASELINE_RUN_ID = "run_1875551f703a_1778456382191"  # run 09 ∞-baseline
TRUNCATED_RUN_ID = "run_1875551f703a_1778456384009"  # run 09 B=560


def get_components(conn, run_id: str) -> list[list[int]]:
    cur = conn.execute(
        """SELECT payload FROM facts
           WHERE kind = 'query-run'
             AND json_extract(payload, '$.run_id') = ?""",
        (run_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"no query-run found for {run_id}")
    payload = json.loads(row["payload"])
    return json.loads(payload["components"])


def get_lineage_matches(conn, run_a: str, run_b: str) -> list[tuple[int, int, float]]:
    cmp_id = f"cmp_{run_a}_{run_b}_lineage"
    cur = conn.execute(
        """SELECT payload FROM facts
           WHERE kind = 'query-comparison'
             AND json_extract(payload, '$.comparison_id') = ?""",
        (cmp_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"no comparison found for {cmp_id}")
    payload = json.loads(row["payload"])
    return [tuple(m) for m in json.loads(payload["payload"])]


def topic_prefix(topic: str) -> str:
    if not topic:
        return "(none)"
    return topic.split("/", 1)[0] if "/" in topic else topic


def characterize(cluster_rows: list[dict]) -> dict:
    msgs = [r.get("message", "") for r in cluster_rows]
    kinds = [r["kind"] for r in cluster_rows]
    topics = [r.get("topic", "") for r in cluster_rows]
    statuses = [r.get("status", "") for r in cluster_rows]
    return {
        "size": len(cluster_rows),
        "avg_msg_len": statistics.mean(len(m) for m in msgs) if msgs else 0,
        "median_msg_len": statistics.median(len(m) for m in msgs) if msgs else 0,
        "kinds": dict(Counter(kinds)),
        "topic_prefixes": dict(Counter(topic_prefix(t) for t in topics)),
        "statuses": dict(Counter(statuses)),
    }


def main() -> int:
    rows = json.load(open(MANIFEST))
    print(f"# corpus: {len(rows)} items")

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    baseline_comps = get_components(conn, BASELINE_RUN_ID)
    truncated_comps = get_components(conn, TRUNCATED_RUN_ID)
    matches = get_lineage_matches(conn, BASELINE_RUN_ID, TRUNCATED_RUN_ID)

    # Replicate compare's filter+sort to align indices.
    big_baseline = sorted(
        [c for c in baseline_comps if len(c) >= 3], key=len, reverse=True
    )

    print(f"# baseline: {len(big_baseline)} non-trivial clusters")
    print(f"# matches: {len(matches)}")

    survivors: list[tuple[float, list[dict]]] = []
    failures: list[tuple[float, list[dict]]] = []

    for now_idx, prev_idx, j in matches:
        cluster = big_baseline[now_idx]
        cluster_rows = [rows[i] for i in cluster]
        if j >= 0.5:
            survivors.append((j, cluster_rows))
        else:
            failures.append((j, cluster_rows))

    print(f"\n## SURVIVORS ({len(survivors)} clusters, j >= 0.5)")
    for j, crows in survivors:
        c = characterize(crows)
        sample_topics = [r.get("topic", r.get("key", "?")) for r in crows[:3]]
        print(f"  size={c['size']:>2}  j={j:.2f}  "
              f"med_len={c['median_msg_len']:.0f}  "
              f"kinds={c['kinds']}")
        for t in sample_topics:
            print(f"    - {t}")

    print(f"\n## FAILURES ({len(failures)} clusters, j < 0.5)")
    for j, crows in failures:
        c = characterize(crows)
        sample_topics = [r.get("topic", r.get("key", "?")) for r in crows[:3]]
        print(f"  size={c['size']:>2}  j={j:.2f}  "
              f"med_len={c['median_msg_len']:.0f}  "
              f"kinds={c['kinds']}")
        for t in sample_topics:
            print(f"    - {t}")

    # Aggregate stats
    surv_sizes = [len(crows) for _, crows in survivors]
    fail_sizes = [len(crows) for _, crows in failures]
    surv_lens = [statistics.median(len(r.get("message", "")) for r in crows)
                 for _, crows in survivors]
    fail_lens = [statistics.median(len(r.get("message", "")) for r in crows)
                 for _, crows in failures]

    surv_kinds = Counter(r["kind"] for _, crows in survivors for r in crows)
    fail_kinds = Counter(r["kind"] for _, crows in failures for r in crows)
    surv_prefixes = Counter(topic_prefix(r.get("topic", ""))
                            for _, crows in survivors for r in crows)
    fail_prefixes = Counter(topic_prefix(r.get("topic", ""))
                            for _, crows in failures for r in crows)

    print("\n## AGGREGATE COMPARISON")
    print(f"  cluster size      survivors avg={statistics.mean(surv_sizes):.1f}  "
          f"failures avg={statistics.mean(fail_sizes):.1f}")
    print(f"  median msg len    survivors avg={statistics.mean(surv_lens):.0f}  "
          f"failures avg={statistics.mean(fail_lens):.0f}")
    print(f"  survivor kinds:   {dict(surv_kinds.most_common(6))}")
    print(f"  failure  kinds:   {dict(fail_kinds.most_common(6))}")
    print(f"  survivor prefixes: {dict(surv_prefixes.most_common(8))}")
    print(f"  failure  prefixes: {dict(fail_prefixes.most_common(8))}")

    # Build the observation
    msg_parts = [
        f"At cliff B=1120→560 (run 09): {len(survivors)} survivors, "
        f"{len(failures)} failures.",
        f"Cluster size: survivors avg={statistics.mean(surv_sizes):.1f}, "
        f"failures avg={statistics.mean(fail_sizes):.1f}.",
        f"Median message length: survivors avg="
        f"{statistics.mean(surv_lens):.0f} chars, "
        f"failures avg={statistics.mean(fail_lens):.0f} chars.",
        f"Survivor kinds: {dict(surv_kinds.most_common(4))}.",
        f"Failure kinds: {dict(fail_kinds.most_common(4))}.",
    ]
    observation_msg = " ".join(msg_parts)
    print(f"\n## EMITTING OBSERVATION")
    print(f"  {observation_msg}")

    _emit(
        "observation",
        {
            "topic": "observation/cliff-content-signature",
            "message": observation_msg,
            "ref": "hypothesis:truncation-as-coupling-function,query-comparison:" +
                   f"cmp_{BASELINE_RUN_ID}_{TRUNCATED_RUN_ID}_lineage",
        },
        observer="loops-claude",
        vertex_path=VERTEX_PATH,
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
