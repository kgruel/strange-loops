"""Six perspectives on: should write receipts include current state?
Crossed design: substance ∈ {YES, NO} × style ∈ {terse, casual, formal}.
Each style bucket has exactly one YES and one NO.
"""

PERSPECTIVES = [
    # A: YES, terse-formal
    ("A", "YES", "terse",
     "The receipt should carry the current value. Callers querying state "
     "after write expect coherence; forcing a second read introduces a "
     "race. Including current state honors the principle of least surprise."),

    # B: YES, bulleted-casual
    ("B", "YES", "casual",
     "yeah I'd just put the value in the response\n"
     "- saves a roundtrip\n"
     "- avoids the race window\n"
     "- callers were going to read it anyway\n"
     "- the cost is basically nothing"),

    # C: NO, terse-formal
    ("C", "NO", "terse",
     "Writes return write receipts. State queries return state. Conflating "
     "them produces a value that is already stale when it reaches the "
     "caller — a lie wearing the costume of consistency."),

    # D: NO, bulleted-casual
    ("D", "NO", "casual",
     "nah keep them separate\n"
     "- the write already happened, that's what the receipt confirms\n"
     "- 'current state' is already racy with the next writer\n"
     "- baking it in just makes the lie official\n"
     "- if you need consensus add a CAS primitive"),

    # E: YES, bulleted-formal
    ("E", "YES", "formal",
     "Including the post-write value in the response is consistent with "
     "HTTP semantics:\n"
     "- PUT typically returns the resource representation\n"
     "- avoids a follow-up GET round trip\n"
     "- the value at write-time is the most authoritative timestamp the "
     "server can provide\n"
     "- omitting it forces every caller to retry-read defensively"),

    # F: NO, bulleted-formal
    ("F", "NO", "formal",
     "Returning current state from a write conflates two operations with "
     "distinct semantics:\n"
     "- the receipt's authority terminates at the write moment\n"
     "- 'current state' implies a fresh read, racy by definition\n"
     "- coupling them obscures which guarantee the caller relies on\n"
     "- separation supports CAS, leases, and other consensus primitives "
     "cleanly"),
]
