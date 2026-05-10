"""Triage readout — apparatus_era_fraction + cross_reference_density (ripgrep).

Renamed from `code_hits` → `cross_reference_density` to match what it
actually measures (literal-string occurrences in the repo, not embedded code
presence). Behavior preserved verbatim from triage.py.

Side-data via ctx: ctx.sqlite_conn (for fact-history lookup), ctx.repo_path
(for ripgrep root).
"""
from __future__ import annotations
import subprocess
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional


# Empirical apparatus-maturity timestamp from triage.py:42
APPARATUS_MATURE_TS_DEFAULT = 1777176000.0  # 2026-04-25 ~23:00 UTC


@dataclass(frozen=True)
class TriageParams:
    min_size: int = 3
    apparatus_mature_ts: float = APPARATUS_MATURE_TS_DEFAULT
    rg_timeout: float = 10.0
    skip_code_grep: bool = False


def _cluster_temporal_profile(comp, rows, conn, apparatus_ts):
    decision_topics = [rows[i]["topic"] for i in comp if rows[i]["kind"] == "decision"]
    thread_names = [rows[i]["key"] for i in comp if rows[i]["kind"] == "thread"]
    task_names = [rows[i]["key"] for i in comp if rows[i]["kind"] == "task"]
    plan_names = [rows[i]["key"] for i in comp if rows[i]["kind"] == "plan"]
    obs_names = [rows[i]["key"] for i in comp if rows[i]["kind"] == "observation"]
    hyp_names = [rows[i]["key"] for i in comp if rows[i]["kind"] == "hypothesis"]

    all_ts = []
    by_kind_ts = defaultdict(list)

    def query(kind, key_field, keys):
        if not keys or conn is None:
            return
        placeholders = ",".join("?" for _ in keys)
        cur = conn.execute(
            f"SELECT ts FROM facts WHERE kind=? AND "
            f"json_extract(payload,'$.{key_field}') IN ({placeholders})",
            (kind, *keys),
        )
        for (ts,) in cur:
            all_ts.append(ts)
            by_kind_ts[kind].append(ts)

    query("decision", "topic", decision_topics)
    query("thread", "name", thread_names)
    query("task", "name", task_names)
    query("plan", "name", plan_names)
    query("observation", "name", obs_names)
    query("hypothesis", "name", hyp_names)

    for i in comp:
        all_ts.append(rows[i]["ts"])
        by_kind_ts[rows[i]["kind"]].append(rows[i]["ts"])

    if not all_ts:
        return {}

    apparatus_era = sum(1 for t in all_ts if t >= apparatus_ts)
    return {
        "first_ts": min(all_ts),
        "last_ts": max(all_ts),
        "n_facts": len(all_ts),
        "apparatus_era_facts": apparatus_era,
        "apparatus_era_fraction": apparatus_era / len(all_ts),
        "decision_apparatus_era_fraction": (
            sum(1 for t in by_kind_ts.get("decision", []) if t >= apparatus_ts)
            / len(by_kind_ts["decision"]) if by_kind_ts.get("decision") else 0.0
        ),
        "engagement_kinds_present": [
            k for k in ("plan", "cite", "task", "thread", "observation", "handoff")
            if by_kind_ts.get(k)
        ],
    }


def _cross_reference_density(topic_keys, repo_path, timeout):
    """For each topic key, count occurrences in repo source/docs (excluding
    project store, git, embedding caches). Renamed from code_hits."""
    out = {}
    for tk in topic_keys:
        try:
            r = subprocess.run(
                ["rg", "-c", "--no-ignore-vcs", "--glob", "!.loops/**",
                 "--glob", "!.git/**", "--glob", "!experiments/coupling-kernels/cache/**",
                 "--glob", "!**/*.npz", "--glob", "!**/*.json",
                 "--", tk, str(repo_path)],
                capture_output=True, text=True, timeout=timeout,
            )
            n = sum(int(line.split(":")[-1]) for line in r.stdout.splitlines()
                    if line.strip() and ":" in line)
        except Exception:
            n = 0
        out[tk] = n
    return out


def _classify(profile, kind_mix, code_hits, total_decisions, apparatus_ts):
    n_kinds_with_2plus = sum(1 for c in kind_mix.values() if c >= 2)
    if n_kinds_with_2plus >= 2:
        return "healthy"
    if total_decisions == 0:
        return "non-decision"
    era = profile.get("decision_apparatus_era_fraction", 0.0)
    last_ts = profile.get("last_ts", 0)
    if era < 0.3 and last_ts < apparatus_ts:
        return "finished" if code_hits > 0 else "dissolved-or-unimplemented"
    if era < 0.3 and code_hits > 0:
        return "finished"
    if era >= 0.3 and code_hits == 0:
        return "stale"
    if era >= 0.3 and code_hits > 0:
        return "stale-but-implemented"
    return "inconclusive"


def triage_readout(rows, comps, ctx, params: TriageParams, *,
                   E=None, D=None, sigma=None):
    non_trivial = sorted(
        [c for c in comps if len(c) >= params.min_size],
        key=len, reverse=True,
    )
    conn = ctx.sqlite_conn if ctx else None
    repo_path = ctx.repo_path if ctx else None

    out_clusters = []
    summary = defaultdict(int)
    for ci, comp in enumerate(non_trivial, 1):
        kind_mix = Counter(rows[i]["kind"] for i in comp)
        prof = _cluster_temporal_profile(comp, rows, conn, params.apparatus_mature_ts)
        decision_topics = [rows[i]["topic"] for i in comp
                           if rows[i]["kind"] == "decision"]
        n_decisions = len(decision_topics)

        if not params.skip_code_grep and n_decisions >= 2 and repo_path:
            code_hits_per = _cross_reference_density(
                decision_topics, repo_path, params.rg_timeout,
            )
            n_with_code = sum(1 for v in code_hits_per.values() if v > 0)
            total_code_hits = sum(code_hits_per.values())
        else:
            code_hits_per = {}
            n_with_code = 0
            total_code_hits = 0

        verdict = _classify(prof, kind_mix, total_code_hits, n_decisions,
                            params.apparatus_mature_ts)
        summary[verdict] += 1
        out_clusters.append({
            "id": f"C{ci}",
            "size": len(comp),
            "verdict": verdict,
            "kinds": dict(kind_mix.most_common()),
            "profile": prof,
            "decision_topics": decision_topics,
            "cross_reference_density": code_hits_per,
            "n_with_code": n_with_code,
            "total_code_hits": total_code_hits,
            "members": comp,
        })
    return {
        "clusters": out_clusters,
        "summary": dict(summary),
    }
