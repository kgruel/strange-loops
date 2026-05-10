"""Triage frozen clusters — gate 6 verdict-distribution verification.

Loads from fixtures/ for embedding/manifest. Live sqlite DB is needed for
fact-history (apparatus_era_fraction). Override via env STRUCTURE_REVEAL_DB
for verification against fixture-era state.
"""
from __future__ import annotations
import os
import sqlite3
import sys
import time
from pathlib import Path
from collections import Counter, defaultdict

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT))

from core import Corpus, E5InstructEmbedder, Kernel, Query, Readout, run  # noqa: E402
from core.corpus import load_manifest                                     # noqa: E402
from core.query import RunContext                                         # noqa: E402

INSTRUCTIONS = {
    "concern": "Group these items by the design concern or area of work "
               "each item participates in.",
}

FIXTURES = ROOT / "fixtures"
MANIFEST = FIXTURES / "project_all_kinds_manifest.json"
EMBED_CONCERN = FIXTURES / "proj_e5_allkinds_concern.npz"

APPARATUS_MATURE_TS = 1777176000.0  # 2026-04-25


def _resolve_db():
    override = os.environ.get("STRUCTURE_REVEAL_DB")
    if override:
        return Path(override)
    return REPO / ".loops" / "data" / "project.db"


def main():
    rows = load_manifest(MANIFEST)
    E_concern = np.load(EMBED_CONCERN)["E"]
    print(f"# loaded {len(rows)} items from manifest")
    print(f"# apparatus maturity: {time.strftime('%Y-%m-%d', time.localtime(APPARATUS_MATURE_TS))}")

    db_path = _resolve_db()
    print(f"# fact-history DB: {db_path}", file=sys.stderr)
    conn = sqlite3.connect(str(db_path)) if db_path.exists() else None

    q = Query(
        corpus=Corpus(vertex="project",
                      kinds=("decision", "thread", "task", "plan",
                             "observation", "hypothesis", "cite", "handoff"),
                      min_chars=50),
        embedder=E5InstructEmbedder(instruction=INSTRUCTIONS["concern"]),
        kernel=Kernel(),
        readouts=(Readout(name="triage", params={}),),
    )
    ctx = RunContext(sqlite_conn=conn, repo_path=REPO)
    qr = run(q, rows=rows, E=E_concern, ctx=ctx)

    s = qr.sigma
    non_trivial = [c for c in qr.components if len(c) >= 3]
    print(f"# concern instruction: σ={s:.4f}, {len(non_trivial)} non-trivial components")
    print(f"\n# triage of all non-trivial clusters (concern instruction)")
    print(f"  legend: ★ = healthy (≥2 kinds ×≥2)  ◆ = finished  "
          f"⚠ = stale  ⊘ = stale-but-implemented  ◌ = pre-apparatus")
    print(f"          ✕ = dissolved-or-unimplemented  ? = inconclusive")

    glyph = {
        "healthy": "★", "finished": "◆", "stale": "⚠",
        "stale-but-implemented": "⊘", "pre-apparatus": "◌",
        "dissolved-or-unimplemented": "✕", "inconclusive": "?",
        "non-decision": "·",
    }

    out = qr.readout_outputs["triage"]
    for cluster in out["clusters"]:
        prof = cluster["profile"]
        kd_str = " ".join(f"{k}:{v}" for k, v in cluster["kinds"].items())
        first = time.strftime("%Y-%m-%d", time.localtime(prof.get("first_ts", 0)))
        last = time.strftime("%Y-%m-%d", time.localtime(prof.get("last_ts", 0)))
        era = prof.get("apparatus_era_fraction", 0.0)
        d_era = prof.get("decision_apparatus_era_fraction", 0.0)
        engagement = ",".join(prof.get("engagement_kinds_present", [])) or "(none)"
        g = glyph[cluster["verdict"]]
        print(f"\n  {g} {cluster['id']:<3} size={cluster['size']:<3} "
              f"verdict={cluster['verdict']:<25} kinds=[{kd_str}]")
        print(f"        ts: {first} → {last}  era_frac={era:.2f}  "
              f"decision_era_frac={d_era:.2f}  engagement=[{engagement}]")

    print(f"\n# classification summary")
    summary_sorted = sorted(out["summary"].items(), key=lambda kv: -kv[1])
    for verdict, count in summary_sorted:
        print(f"  {verdict:<28}  {count:>3} clusters")


if __name__ == "__main__":
    main()
