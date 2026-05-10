"""Triage frozen clusters: distinguish (a) correctly-finished from (b) stale
from (c) pre-apparatus.

Adds three axes to the kind-mix diagnostic:

  1. apparatus_era_fraction — fraction of the cluster's underlying FACTS
     (full history, not just fold-deduped items) emitted after apparatus
     maturity (cite/plan in substantive use, ≈ 2026-04-25). Low fraction →
     cluster predates the engagement-kinds being practice; absence of
     engagement is uninformative.

  2. last_engagement_ts — most recent fact across all kinds in cluster.
     Old + low-apparatus-era → pre-apparatus.
     Recent + decision-only → stale.

  3. code_presence — does the cluster's topic-key appear in the repo's
     source/docs (outside the project store and cache)? Alive in code +
     no engagement → finished. Absent from code + no engagement → either
     dissolved-and-removed or never-implemented (decision but no carry-out).

Combines these with the existing kind-mix to classify each cluster.
"""
from __future__ import annotations
import sqlite3
import json
import subprocess
import time
from pathlib import Path
from collections import Counter, defaultdict

import numpy as np


REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "experiments" / "coupling-kernels" / "cache"
DB = REPO / ".loops" / "data" / "project.db"

# Apparatus maturity: when cite-as-attention and plan-as-substantive-kind
# became practice. Empirically: first substantive cite at 2026-04-25 22:56,
# first substantive plan at 2026-04-25 12:49. Use end-of-day as the
# practice-mature watershed.
APPARATUS_MATURE_TS = 1777176000.0  # 2026-04-25 ~23:00 UTC

INSTRUCTIONS = {
    "mechanism": "Group these items by the underlying mechanism or "
                 "primitive they describe.",
    "concern": "Group these items by the design concern or area of work "
               "each item participates in.",
}

KINDS_UPSERT = {"decision", "thread", "task", "plan", "observation", "hypothesis"}
KINDS_COLLECT = {"cite", "handoff"}


def load_manifest() -> list[dict]:
    return json.load(open(CACHE / "project_all_kinds_manifest.json"))


def cosine_dist(E):
    norm = E / np.linalg.norm(E, axis=1, keepdims=True)
    return 1.0 - (norm @ norm.T)


def dog_kernel(D, sigma_e, ratio=2.0):
    sigma_i = ratio * sigma_e
    return (np.exp(-(D**2) / (2 * sigma_e**2))
            - (sigma_e / sigma_i) * np.exp(-(D**2) / (2 * sigma_i**2)))


def positive_components(K):
    n = K.shape[0]
    K = K.copy()
    np.fill_diagonal(K, 0)
    visited = [False] * n
    comps = []
    for start in range(n):
        if visited[start]:
            continue
        stack, comp = [start], []
        while stack:
            v = stack.pop()
            if visited[v]:
                continue
            visited[v] = True
            comp.append(v)
            for u in range(n):
                if not visited[u] and K[v, u] > 0:
                    stack.append(u)
        comps.append(sorted(comp))
    return comps


def find_richness_scale(D):
    off = D[np.triu_indices(D.shape[0], k=1)]
    pcts = [0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5]
    best_s, best_richness, best_comps = None, -1, None
    for p in pcts:
        s = float(np.percentile(off, p))
        K = dog_kernel(D, s)
        comps = positive_components(K)
        non_trivial = [c for c in comps if len(c) >= 3]
        if len(non_trivial) > best_richness:
            best_richness = len(non_trivial)
            best_s = s
            best_comps = comps
    return best_s, best_comps


def cluster_temporal_profile(comp: list[int], rows: list[dict],
                              conn: sqlite3.Connection) -> dict:
    """Pull underlying facts for cluster items; compute temporal stats."""
    decision_topics = [rows[i]["topic"] for i in comp if rows[i]["kind"] == "decision"]
    thread_names = [rows[i]["key"] for i in comp if rows[i]["kind"] == "thread"]
    task_names = [rows[i]["key"] for i in comp if rows[i]["kind"] == "task"]
    plan_names = [rows[i]["key"] for i in comp if rows[i]["kind"] == "plan"]
    obs_names = [rows[i]["key"] for i in comp if rows[i]["kind"] == "observation"]
    hyp_names = [rows[i]["key"] for i in comp if rows[i]["kind"] == "hypothesis"]
    cite_ids = [rows[i]["id"] for i in comp if rows[i]["kind"] == "cite"
                and "id" in rows[i]]
    handoff_ids = [rows[i]["id"] for i in comp if rows[i]["kind"] == "handoff"
                   and "id" in rows[i]]

    all_ts = []
    by_kind_ts = defaultdict(list)

    def query(kind, key_field, keys):
        if not keys:
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
    # collect-fold members are individual facts; we don't have id reuse here
    # but we still want their ts captured (already in rows)

    # Add ts from rows (covers cite/handoff and is a backstop)
    for i in comp:
        all_ts.append(rows[i]["ts"])
        by_kind_ts[rows[i]["kind"]].append(rows[i]["ts"])

    if not all_ts:
        return {}

    apparatus_era = sum(1 for t in all_ts if t >= APPARATUS_MATURE_TS)
    profile = {
        "first_ts": min(all_ts),
        "last_ts": max(all_ts),
        "n_facts": len(all_ts),
        "apparatus_era_facts": apparatus_era,
        "apparatus_era_fraction": apparatus_era / len(all_ts),
        "decision_apparatus_era_fraction": (
            sum(1 for t in by_kind_ts.get("decision", []) if t >= APPARATUS_MATURE_TS)
            / len(by_kind_ts["decision"]) if by_kind_ts.get("decision") else 0.0
        ),
        "engagement_kinds_present": [
            k for k in ("plan", "cite", "task", "thread", "observation", "handoff")
            if by_kind_ts.get(k)
        ],
    }
    return profile


def code_presence(topic_keys: list[str]) -> dict[str, int]:
    """For each topic key, count occurrences in repo source/docs (excluding
    project store, git, embedding caches, and the experiment itself).
    """
    out = {}
    for tk in topic_keys:
        # use the last hyphen-segment if topic is namespaced
        # also try the full topic
        full = tk
        # search the full identifier as a literal string
        try:
            r = subprocess.run(
                ["rg", "-c", "--no-ignore-vcs", "--glob", "!.loops/**",
                 "--glob", "!.git/**", "--glob", "!experiments/coupling-kernels/cache/**",
                 "--glob", "!**/*.npz", "--glob", "!**/*.json",
                 "--", full, str(REPO)],
                capture_output=True, text=True, timeout=10,
            )
            n = sum(int(line.split(":")[-1]) for line in r.stdout.splitlines()
                    if line.strip() and ":" in line)
        except Exception:
            n = 0
        out[tk] = n
    return out


def classify(profile: dict, kind_mix: Counter, code_hits: int,
             total_decisions: int) -> str:
    """Return one of: finished, stale, pre-apparatus, healthy, in-formation,
    inconclusive.

    Decision rules:
      - mixed (≥2 kinds × ≥2): healthy (this triage is for decision-only)
      - decision-only:
          - decision_era_frac < 0.3 AND last_ts < apparatus_mature: pre-apparatus
          - decision_era_frac ≥ 0.3 AND code_hits == 0: stale (had access to
            engagement-kinds, didn't use them, also no code presence)
          - decision_era_frac ≥ 0.3 AND code_hits > 0: stale-but-implemented
            (alive in code, but ongoing engagement absent — decision-thread
            decoupled)
          - decision_era_frac < 0.3 AND code_hits > 0: finished (alive in
            code, predates apparatus — correctly-frozen)
          - decision_era_frac < 0.3 AND code_hits == 0: dissolved-or-pre-apparatus-and-unimplemented
    """
    n_kinds_with_2plus = sum(1 for c in kind_mix.values() if c >= 2)
    if n_kinds_with_2plus >= 2:
        return "healthy"
    if total_decisions == 0:
        return "non-decision"  # other kinds dominate
    era = profile.get("decision_apparatus_era_fraction", 0.0)
    last_ts = profile.get("last_ts", 0)
    if era < 0.3 and last_ts < APPARATUS_MATURE_TS:
        return "finished" if code_hits > 0 else "dissolved-or-unimplemented"
    if era < 0.3 and code_hits > 0:
        return "finished"
    if era >= 0.3 and code_hits == 0:
        return "stale"
    if era >= 0.3 and code_hits > 0:
        return "stale-but-implemented"
    return "inconclusive"


def main():
    rows = load_manifest()
    print(f"# loaded {len(rows)} items from manifest")
    print(f"# apparatus maturity: {time.strftime('%Y-%m-%d', time.localtime(APPARATUS_MATURE_TS))}")

    # Use concern instruction (matches bridge.py findings)
    E_path = CACHE / "proj_e5_allkinds_concern.npz"
    E = np.load(E_path)["E"]
    D = cosine_dist(E)
    s, comps = find_richness_scale(D)
    non_trivial = [c for c in comps if len(c) >= 3]
    print(f"# concern instruction: σ={s:.4f}, {len(non_trivial)} non-trivial components")

    conn = sqlite3.connect(DB)

    # We need stable ids from manifest for fact lookup — manifest dropped 'id'
    # for collect-fold; fold-deduped kinds are looked up by topic/name above.
    # Add id back from a re-query for the items we care about:
    # (already passed via rows from load_manifest; load_all_kinds wrote 'id'
    #  for all rows except collect-fold. We need to be defensive.)

    print(f"\n# triage of all non-trivial clusters (concern instruction)")
    print(f"  legend: ★ = healthy (≥2 kinds ×≥2)  ◆ = finished  "
          f"⚠ = stale  ⊘ = stale-but-implemented  ◌ = pre-apparatus")
    print(f"          ✕ = dissolved-or-unimplemented  ? = inconclusive")

    classified = defaultdict(list)
    sorted_comps = sorted(non_trivial, key=len, reverse=True)
    for ci, comp in enumerate(sorted_comps, 1):
        kind_mix = Counter(rows[i]["kind"] for i in comp)
        prof = cluster_temporal_profile(comp, rows, conn)
        decision_topics = [rows[i]["topic"] for i in comp
                           if rows[i]["kind"] == "decision"]
        n_decisions = len(decision_topics)

        # Only do code-grep for clusters that might be (a/c) — small cost
        if n_decisions >= 2:
            code_hits_per = code_presence(decision_topics)
            n_with_code = sum(1 for v in code_hits_per.values() if v > 0)
            total_code_hits = sum(code_hits_per.values())
        else:
            code_hits_per = {}
            n_with_code = 0
            total_code_hits = 0

        verdict = classify(prof, kind_mix, total_code_hits, n_decisions)
        classified[verdict].append((ci, comp, prof, kind_mix, code_hits_per))

        # Render
        glyph = {
            "healthy": "★",
            "finished": "◆",
            "stale": "⚠",
            "stale-but-implemented": "⊘",
            "pre-apparatus": "◌",
            "dissolved-or-unimplemented": "✕",
            "inconclusive": "?",
            "non-decision": "·",
        }[verdict]
        kd_str = " ".join(f"{k}:{v}" for k, v in kind_mix.most_common())
        first = time.strftime("%Y-%m-%d", time.localtime(prof.get("first_ts", 0)))
        last = time.strftime("%Y-%m-%d", time.localtime(prof.get("last_ts", 0)))
        era = prof.get("apparatus_era_fraction", 0.0)
        d_era = prof.get("decision_apparatus_era_fraction", 0.0)
        engagement = ",".join(prof.get("engagement_kinds_present", [])) or "(none)"
        print(f"\n  {glyph} C{ci:<2} size={len(comp):<3} verdict={verdict:<25} "
              f"kinds=[{kd_str}]")
        print(f"        ts: {first} → {last}  era_frac={era:.2f}  "
              f"decision_era_frac={d_era:.2f}  engagement=[{engagement}]")
        if n_decisions >= 2:
            print(f"        code: {n_with_code}/{n_decisions} topics present "
                  f"({total_code_hits} total hits)")
        # show decisions sorted by code-presence
        if decision_topics:
            ranked = sorted(decision_topics,
                            key=lambda t: -code_hits_per.get(t, 0))[:5]
            for t in ranked:
                hits = code_hits_per.get(t, 0)
                marker = "✓" if hits > 0 else "✗"
                print(f"          {marker} {t} ({hits} hits)")
        # show non-decision members briefly
        non_dec = [(rows[i]["kind"], rows[i].get("topic", rows[i].get("key", "")),
                    rows[i].get("status", ""))
                   for i in comp if rows[i]["kind"] != "decision"]
        for kind, label, status in non_dec[:4]:
            stat = f" ({status})" if status else ""
            print(f"          [{kind:<11}] {label}{stat}")

    print(f"\n# classification summary")
    for verdict, items in sorted(classified.items(),
                                  key=lambda kv: -len(kv[1])):
        print(f"  {verdict:<28}  {len(items):>3} clusters")


if __name__ == "__main__":
    main()
