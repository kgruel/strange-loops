"""Generate autoresearch journey visualization from autoresearch.jsonl."""

import json
from pathlib import Path

# ---------------------------------------------------------------------------
# Parse the JSONL
# ---------------------------------------------------------------------------
records = []
configs = []
with open("autoresearch.jsonl") as f:
    for line in f:
        obj = json.loads(line.strip())
        if obj.get("type") == "config":
            configs.append(obj)
        elif obj.get("run") is not None:
            obj["_config"] = configs[-1]["name"] if configs else "unknown"
            records.append(obj)

for i, r in enumerate(records):
    r["seq"] = i + 1

# ---------------------------------------------------------------------------
# Collapse the 3 engine configs into a single "engine" phase
# Use 4 clean phases: atoms | engine | lang | loops
# ---------------------------------------------------------------------------
PHASE_MAP = {
    "atoms test coverage efficiency (stairstep)":          "atoms",
    "engine test coverage efficiency (stairstep)":         "engine",
    "engine coverage efficiency (warmup+min3)":            "engine",
    "engine coverage efficiency (warmup+min3, pytest timing)": "engine",
    "lang test coverage efficiency (stairstep)":           "lang",
    "loops app coverage efficiency":                       "loops",
}
for r in records:
    r["phase"] = PHASE_MAP.get(r["_config"], r["_config"])

# Detect phase boundaries (only when phase actually changes)
phase_spans = []
cur_phase, span_start = None, 1
for r in records:
    if r["phase"] != cur_phase:
        if cur_phase is not None:
            phase_spans.append((cur_phase, span_start, r["seq"] - 1))
        cur_phase = r["phase"]
        span_start = r["seq"]
phase_spans.append((cur_phase, span_start, records[-1]["seq"]))

# ---------------------------------------------------------------------------
# Build series (kept-only for trend lines, all for scatter)
# ---------------------------------------------------------------------------
kept    = [r for r in records if r["status"] == "keep"]
k_seqs  = [r["seq"] for r in kept]
k_cov   = [r["metrics"].get("coverage_pct", 0) for r in kept]
k_eff   = [r["metric"] for r in kept]

# ---------------------------------------------------------------------------
# Canvas & coordinate helpers
# ---------------------------------------------------------------------------
W, H        = 1200, 720
PAD_L       = 75
PAD_R       = 72   # room for right-axis label
PAD_T       = 58
PAD_B       = 68
PW          = W - PAD_L - PAD_R
PH          = H - PAD_T - PAD_B

N           = len(records)
x_min, x_max = 1, N

COV_MIN, COV_MAX = 50, 102   # a little above 100 so final dot isn't clipped
EFF_MIN, EFF_MAX = 0, 24

def px(seq):
    return PAD_L + (seq - x_min) / (x_max - x_min) * PW

def py_cov(v):
    v = max(COV_MIN, min(COV_MAX, v))
    return PAD_T + PH - (v - COV_MIN) / (COV_MAX - COV_MIN) * PH

def py_eff(v):
    v = max(EFF_MIN, min(EFF_MAX, v))
    return PAD_T + PH - (v - EFF_MIN) / (EFF_MAX - EFF_MIN) * PH

# ---------------------------------------------------------------------------
# Phase palette
# ---------------------------------------------------------------------------
PHASE_STYLE = {
    "atoms":  {"bg": "#e6f7ef", "label_col": "#2d7a4f"},
    "engine": {"bg": "#e8edf8", "label_col": "#3b5bab"},
    "lang":   {"bg": "#fdf4e3", "label_col": "#9a6200"},
    "loops":  {"bg": "#f3eefb", "label_col": "#6d28d9"},
}

# ---------------------------------------------------------------------------
# Compose SVG
# ---------------------------------------------------------------------------
svg = []

def add(*args):
    svg.extend(args)

add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
    f'style="font-family: ui-monospace, \'Menlo\', monospace; background: #f8f9fa;">')

# ── Title ──────────────────────────────────────────────────────────────────
add(f'<text x="{W//2}" y="36" text-anchor="middle" font-size="16" '
    f'font-weight="bold" fill="#1a1a2e" letter-spacing="0.3">'
    f'autoresearch journey — {N} experiments across {len(phase_spans)} libraries</text>')

# ── Phase background bands (drawn before grid so grid sits on top) ─────────
for phase, s0, s1 in phase_spans:
    st = PHASE_STYLE[phase]
    bx = px(s0)
    bw = px(s1 + 0.5) - bx
    add(f'<rect x="{bx:.1f}" y="{PAD_T}" width="{bw:.1f}" height="{PH}" '
        f'fill="{st["bg"]}" opacity="0.85"/>')

# Phase labels — centred horizontally, sitting just ABOVE the plot frame
for phase, s0, s1 in phase_spans:
    st   = PHASE_STYLE[phase]
    mid  = (px(s0) + px(s1 + 0.5)) / 2
    # small phases get a rotated label if too narrow
    span_w = px(s1 + 0.5) - px(s0)
    if span_w < 40:
        add(f'<text x="{mid:.1f}" y="{PAD_T - 6}" text-anchor="middle" '
            f'font-size="10" fill="{st["label_col"]}" font-style="italic" '
            f'transform="rotate(-30 {mid:.1f} {PAD_T - 6})">{phase}</text>')
    else:
        add(f'<text x="{mid:.1f}" y="{PAD_T - 8}" text-anchor="middle" '
            f'font-size="12" fill="{st["label_col"]}" font-weight="600" '
            f'font-style="italic">{phase}</text>')

# Phase boundary vertical lines (between phases only)
prev_phase = None
for phase, s0, s1 in phase_spans:
    if prev_phase is not None:
        bx = px(s0)
        add(f'<line x1="{bx:.1f}" y1="{PAD_T}" x2="{bx:.1f}" y2="{PAD_T+PH}" '
            f'stroke="#999" stroke-width="1.2" stroke-dasharray="5,3"/>')
    prev_phase = phase

# ── Grid lines ─────────────────────────────────────────────────────────────
# Coverage (left axis)
for v in range(50, 105, 10):
    y = py_cov(v)
    add(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{PAD_L+PW}" y2="{y:.1f}" '
        f'stroke="#d0d0d0" stroke-width="1" stroke-dasharray="4,3"/>')
    add(f'<text x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end" '
        f'font-size="11" fill="#555">{v}%</text>')

# Efficiency (right axis) — light ticks, labelled on right
for v in [0, 5, 10, 15, 20]:
    y = py_eff(v)
    add(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{PAD_L+PW}" y2="{y:.1f}" '
        f'stroke="#e0d8f0" stroke-width="0.8" stroke-dasharray="2,5"/>')
    add(f'<text x="{PAD_L+PW + 8}" y="{y + 4:.1f}" '
        f'font-size="11" fill="#9b6fd0">{v}</text>')

# Axis frame
add(f'<rect x="{PAD_L}" y="{PAD_T}" width="{PW}" height="{PH}" '
    f'fill="none" stroke="#aaa" stroke-width="1.5"/>')

# ── Coverage filled area ────────────────────────────────────────────────────
bot_y = py_cov(COV_MIN)
poly_top = [(px(s), py_cov(c)) for s, c in zip(k_seqs, k_cov)]
poly_bot = [(px(s), bot_y)     for s     in k_seqs]
poly_pts  = poly_top + list(reversed(poly_bot))
poly_str  = " ".join(f"{x:.1f},{y:.1f}" for x, y in poly_pts)
add(f'<polygon points="{poly_str}" fill="#22c55e" opacity="0.12"/>')

# Coverage line
cov_path = " ".join(
    f"{'M' if i == 0 else 'L'}{px(s):.1f},{py_cov(c):.1f}"
    for i, (s, c) in enumerate(zip(k_seqs, k_cov))
)
add(f'<path d="{cov_path}" fill="none" stroke="#16a34a" stroke-width="2.5" '
    f'stroke-linejoin="round"/>')

# ── Efficiency line (kept only) ────────────────────────────────────────────
eff_path = " ".join(
    f"{'M' if i == 0 else 'L'}{px(s):.1f},{py_eff(e):.1f}"
    for i, (s, e) in enumerate(zip(k_seqs, k_eff))
)
add(f'<path d="{eff_path}" fill="none" stroke="#9b6fd0" stroke-width="1.5" '
    f'stroke-dasharray="6,3" opacity="0.75"/>')

# ── Scatter dots — all experiments ────────────────────────────────────────
STATUS_DOT = {
    "keep":          ("#16a34a", 4.0, 0.85),
    "discard":       ("#f97316", 3.5, 0.75),
    "crash":         ("#ef4444", 5.0, 1.00),
    "checks_failed": ("#eab308", 4.0, 0.85),
}
for r in records:
    sx = px(r["seq"])
    sy = py_cov(r["metrics"].get("coverage_pct", 0))
    col, rad, opa = STATUS_DOT.get(r["status"], ("#888", 3, 0.5))
    add(f'<circle cx="{sx:.1f}" cy="{sy:.1f}" r="{rad}" '
        f'fill="{col}" opacity="{opa}"/>')

# Efficiency dots (kept only, smaller, purple)
for s, e in zip(k_seqs, k_eff):
    add(f'<circle cx="{px(s):.1f}" cy="{py_eff(e):.1f}" r="2.2" '
        f'fill="#9b6fd0" opacity="0.45"/>')

# ── Baseline drop annotation ───────────────────────────────────────────────
r_base = next(r for r in records if r["phase"] == "loops" and r.get("run") == 1)
bx2 = px(r_base["seq"])
by2 = py_cov(r_base["metrics"]["coverage_pct"])
# Small callout bubble below the drop point
add(f'<line x1="{bx2:.1f}" y1="{by2 + 6:.1f}" x2="{bx2:.1f}" y2="{by2 + 34:.1f}" '
    f'stroke="#6d28d9" stroke-width="1" stroke-dasharray="2,2"/>')
add(f'<rect x="{bx2 - 26:.1f}" y="{by2 + 35:.1f}" width="58" height="30" '
    f'rx="4" fill="#f3eefb" stroke="#9b6fd0" stroke-width="0.8"/>')
add(f'<text x="{bx2:.1f}" y="{by2 + 49:.1f}" text-anchor="middle" '
    f'font-size="10" fill="#6d28d9" font-weight="bold">baseline</text>')
add(f'<text x="{bx2:.1f}" y="{by2 + 61:.1f}" text-anchor="middle" '
    f'font-size="10" fill="#6d28d9">56.8%</text>')

# ── TUI jump annotation (experiment 154 area) ──────────────────────────────
r154 = next((r for r in records if r.get("run") == 154 and "TUI" in r.get("description", "")), None)
if r154:
    ax = px(r154["seq"])
    ay = py_cov(r154["metrics"]["coverage_pct"])
    # Draw a bracket-style annotation above the jump
    add(f'<line x1="{ax:.1f}" y1="{ay - 6:.1f}" x2="{ax:.1f}" y2="{PAD_T + 10:.1f}" '
        f'stroke="#475569" stroke-width="1" stroke-dasharray="3,2"/>')
    add(f'<rect x="{ax - 42:.1f}" y="{PAD_T + 2:.1f}" width="90" height="26" '
        f'rx="4" fill="white" stroke="#94a3b8" stroke-width="0.8" opacity="0.92"/>')
    add(f'<text x="{ax + 3:.1f}" y="{PAD_T + 13:.1f}" text-anchor="middle" '
        f'font-size="10" fill="#334155" font-weight="bold">+631 covered</text>')
    add(f'<text x="{ax + 3:.1f}" y="{PAD_T + 24:.1f}" text-anchor="middle" '
        f'font-size="10" fill="#475569">TUI test harness</text>')

# ── Final result marker ────────────────────────────────────────────────────
r_final = records[-1]
fx = px(r_final["seq"])
fy = py_cov(r_final["metrics"]["coverage_pct"])
add(f'<circle cx="{fx:.1f}" cy="{fy:.1f}" r="8" fill="none" stroke="#16a34a" stroke-width="2.5"/>')
add(f'<circle cx="{fx:.1f}" cy="{fy:.1f}" r="4" fill="#16a34a"/>')
add(f'<text x="{fx - 9:.1f}" y="{fy - 14:.1f}" text-anchor="end" '
    f'font-size="11.5" fill="#16a34a" font-weight="bold">{r_final["metrics"]["coverage_pct"]}%</text>')

# ── X axis ─────────────────────────────────────────────────────────────────
for t in [1] + list(range(25, N, 25)) + ([N] if N % 25 != 0 else []):
    tx = px(t)
    add(f'<line x1="{tx:.1f}" y1="{PAD_T+PH}" x2="{tx:.1f}" y2="{PAD_T+PH+5}" '
        f'stroke="#888" stroke-width="1"/>')
    add(f'<text x="{tx:.1f}" y="{PAD_T+PH+18}" text-anchor="middle" '
        f'font-size="11" fill="#555">{t}</text>')
add(f'<text x="{PAD_L + PW//2}" y="{H - 10}" text-anchor="middle" '
    f'font-size="12" fill="#444">experiment #</text>')

# ── Axis labels ────────────────────────────────────────────────────────────
# Left (coverage)
cx = 16
cy = PAD_T + PH // 2
add(f'<text x="{cx}" y="{cy}" text-anchor="middle" font-size="12" fill="#16a34a" '
    f'font-weight="600" transform="rotate(-90 {cx} {cy})">coverage %</text>')

# Right (efficiency) — sits just outside the right edge of the plot
rx = W - 16
ry = PAD_T + PH // 2
add(f'<text x="{rx}" y="{ry}" text-anchor="middle" font-size="12" fill="#9b6fd0" '
    f'font-weight="600" transform="rotate(90 {rx} {ry})">efficiency  (lower = better)</text>')

# ── Stats box — top-left of the loops zone, away from coverage line ────────
# Place it in the middle of the loops phase, vertically near the bottom
loops_start = next(s0 for (ph, s0, s1) in phase_spans if ph == "loops")
sx0 = px(loops_start) + 20
sy0 = py_cov(60) - 10   # at 60% coverage level, well below the loops coverage line

first_cov = k_cov[0] if k_cov else 0
last_cov = k_cov[-1] if k_cov else 0
first_miss = records[0]["metrics"].get("miss", 0)
last_miss = records[-1]["metrics"].get("miss", 0)
first_eff = k_eff[0] if k_eff else 0
last_eff = k_eff[-1] if k_eff else 0
eff_delta = round(100 * (last_eff - first_eff) / first_eff) if first_eff else 0
stats = [
    ("start",         f"{first_cov}%  /  {first_miss:,} miss"),
    ("finish",        f"{last_cov}%  /  {last_miss:,} miss"),
    ("efficiency",    f"{first_eff:.2f} → {last_eff:.2f}  ({eff_delta:+d}%)"),
    ("experiments",   f"{N} total  /  {len(kept)} kept"),
]
box_w, box_h = 238, len(stats) * 20 + 16
add(f'<rect x="{sx0 - 10:.1f}" y="{sy0 - 16:.1f}" width="{box_w}" height="{box_h}" '
    f'rx="5" fill="white" opacity="0.90" stroke="#c4b5fd" stroke-width="1.2"/>')
for i, (k, v) in enumerate(stats):
    y = sy0 + i * 20
    add(f'<text x="{sx0:.1f}" y="{y:.1f}" font-size="11" fill="#333">'
        f'<tspan font-weight="bold" fill="#6d28d9">{k}</tspan>  {v}</text>')

# ── Legend — top-right, clear of phase labels ──────────────────────────────
lx = PAD_L + PW - 230
ly = PAD_T + 48   # below the TUI annotation area

legend_items = [
    ("line",   "#16a34a", "2.5", "none",  "coverage %  (kept)"),
    ("line",   "#9b6fd0", "1.5", "6,3",   "efficiency  (kept)"),
    ("dot",    "#16a34a", "4.0", None,    "kept"),
    ("dot",    "#f97316", "3.5", None,    "discarded / noise"),
    ("dot",    "#eab308", "4.0", None,    "checks failed"),
]

box_lw = 222
box_lh = len(legend_items) * 19 + 14
add(f'<rect x="{lx - 10:.1f}" y="{ly - 14:.1f}" width="{box_lw}" height="{box_lh}" '
    f'rx="5" fill="white" opacity="0.92" stroke="#ddd" stroke-width="1"/>')

for i, (kind, col, sw, dash, label) in enumerate(legend_items):
    iy = ly + i * 19
    if kind == "line":
        d = f'stroke-dasharray="{dash}"' if dash and dash != "none" else ""
        add(f'<line x1="{lx:.1f}" y1="{iy - 4:.1f}" x2="{lx + 24:.1f}" y2="{iy - 4:.1f}" '
            f'stroke="{col}" stroke-width="{sw}" {d}/>')
    else:
        add(f'<circle cx="{lx + 12:.1f}" cy="{iy - 4:.1f}" r="{sw}" fill="{col}" opacity="0.85"/>')
    add(f'<text x="{lx + 31:.1f}" y="{iy:.1f}" font-size="11" fill="#333">{label}</text>')

add('</svg>')

# Write output
out = Path("autoresearch_journey.svg")
out.write_text("\n".join(svg))
print(f"Written {out}  ({len('\n'.join(svg)):,} bytes)")
print(f"Experiments: {len(records)}  kept={sum(1 for r in records if r['status']=='keep')}")
for ph, s0, s1 in phase_spans:
    print(f"  {ph:8s}  seq {s0:3d}–{s1:3d}  ({s1-s0+1} experiments)")
