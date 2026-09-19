# Audited legacy provenance verification

The user accepted preserved historical boundaries whose fact-window commitments
refer to the original archive, with a separately audited observer mapping. The
verifier must prove that relationship; it must not turn off historical checks.

## Meaning of a passing result

A passing provenance result means the independently pinned original archive and
preparation manifest describe the supplied prepared input exactly; the pinned
migration prefix preserves that input's facts and ticks in order; the original
historical chain passes; every transformed historical window difference is
explained by the authorized observer mapping; and later tick-chain checks pass.
It is reported as **preserved boundaries with audited transformation**. The old
window commitments are not described as unchanged commitments over the prepared
facts. The ordinary deep audit retains its existing result.

## Trust and scope

The original archive SHA-256, preparation-manifest SHA-256, and migration head S
(lineage, ordinal, record hash) are review inputs supplied independently of the
files being checked. A file's own claims are not sufficient trust anchors. For
the loops rehearsal these pins come from the previously reviewed snapshot,
preparation and verified migration evidence. Replacing all files and all trusted
pins together is outside the verifier's ability to detect; the cutover procedure
must retain the reviewed pins separately.

The first supported policy is `legacy-unattributed-v1`: flat legacy JSONL, no
migration drops, exact empty observers on unsigned facts only. IDs, payload text,
all other fact fields, order, and every tick field remain preserved. Rows that do
not change must remain byte-identical between original and prepared input. The
manifest must account for every changed row exactly once, with matching original
and prepared line hashes. Unsupported formats and policies refuse explicitly.

This is an offline, read-only sidecar. It does not open live runtime writers,
create credentials, rewrite ticks, refresh signatures, or change the standard
runtime audit. Its chain checks are structural/content checks, not an independent
authentication of all historical authors or signing keys. The preexisting signed
migration report remains separate evidence of migration at S.

## Required refusal cases

- Unpinned or mismatched original/manifest bytes, incomplete or duplicate audit
  entries, signed-row attribution changes, or any other transformed field.
- Dropped, added, reordered, or mutated source rows in the migration prefix;
  arbitrary extra user rows cannot be treated as protocol metadata.
- A broken original tick predecessor, cursor continuity, or window commitment.
- An unexplained historical window mismatch, changed tick evidence, or any later
  tick-chain mismatch. Verification must inspect the whole stream rather than
  treating the first ten diagnostic locations as the complete failure set.
- Missing or forward-referencing window cursors, invalid Arrival chain, wrong S,
  or input mutation during verification.

Only window-hash differences on preserved historical ticks may be explained by
the checked mapping. Predecessor and cursor continuity are not waived. Results
contain counts, hashes and coordinates rather than payloads or private keys.

## Exact verification claims

The receipt labels trust pins as caller-supplied and does not claim the tool can
prove their independent origin. It distinguishes structural tick-chain checking
from signature authentication: registry-forming Arrival signatures are checked,
but ordinary record-envelope and inner FACT/TICK signatures are not authenticated
by this verifier. The separate real-copy tick attestation remains evidence for
the new signed boundary tick.

Historical unchained ticks are counted explicitly. They are permitted only
before the chained era and only without predecessor or cursor claims. A return
to an unchained tick after chaining starts refuses; later post-migration ticks
must be chained. No unchained row can erase a previously established continuity
requirement.
