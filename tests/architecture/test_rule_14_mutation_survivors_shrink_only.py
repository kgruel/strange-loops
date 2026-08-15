"""Rule 14: mutation-testing survivors are shrink-only."""

from __future__ import annotations

import re

from ._helpers import REPO_ROOT

# Ceiling per MUTATION-<module>.md report (libs/<lib>/tests/). Every survivor
# above zero is individually classified equivalent/timeout in the report; a
# number may shrink here (better tests kill more) but never grow. Adding a new
# mutmut target means adding its report and its ceiling entry together.
_MUTATION_SURVIVOR_CEILINGS = {
    "libs/engine/tests/MUTATION-admission.md": 0,
    "libs/engine/tests/MUTATION-witness.md": 110,
    "libs/lang/tests/MUTATION-vertex_mutation.md": 130,
}

_SURVIVORS_LINE = re.compile(r"^SURVIVORS: (\d+) \(all equivalent/finding\)$")


def test_mutation_survivor_ratchet():
    """Every mutation report exists, ends with the SURVIVORS line, and its
    count has not grown past the recorded ceiling.

    The MUTATION-*.md files are the durable record of each mutmut run; this
    turns their final line from a review artifact into a floor.
    """
    violations = []
    for rel, ceiling in _MUTATION_SURVIVOR_CEILINGS.items():
        path = REPO_ROOT / rel
        if not path.is_file():
            violations.append(f"  {rel}: report missing")
            continue
        last = path.read_text().strip().splitlines()[-1]
        m = _SURVIVORS_LINE.match(last)
        if m is None:
            violations.append(f"  {rel}: final line {last!r} is not a SURVIVORS line")
        elif int(m.group(1)) > ceiling:
            violations.append(f"  {rel}: {m.group(1)} survivors > ceiling {ceiling}")
    assert not violations, (
        "mutation survivors must never grow (shrink the tests' kill set only "
        "by killing more mutants; update the ceiling downward when they do):\n"
        + "\n".join(violations)
    )
