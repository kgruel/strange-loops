# C7 target-resolution notes

The descriptor resolver had one shape policy embedded in its common parsing
path: any explicit Arrival descriptor whose local locator also declared
`combine` or `discover` was refused. That is correct for single-store reads,
writes, sources, transfer, verification, and the public
`resolve_arrival_target` result, but it also prevented declaration inspection
from opening the root store to inspect its bounded effective declaration.

The narrow parsed-root seam is
`_arrival_definition(target, *, allow_aggregate=False)`. It returns one valid
parsed local AST together with its descriptor, or `descriptor=None` when no
backend is explicit (including storeless and legacy stored roots). Declaration
inspection separately requires `ast.store is None` for local-frozen evidence
and uses this retained definition for both
classification and local evidence, avoiding a second parse that could observe
a different file. The existing `_arrival_descriptor` delegates to this seam,
filters out roots without a descriptor, and preserves its default aggregate refusal for
all existing callers. Inspection explicitly passes `allow_aggregate=True`.
Neither helper discovers or opens members. Inspection supplies no aggregate
head or member basis, only the captured root basis and unexpanded effective
topology.
The public `resolve_arrival_target` remains single-store.

Descriptor resolution and role enforcement remain unchanged in substance:
the store location is passed through opaquely by `descriptor_for`, and an
explicit role is required. Role validation now precedes the local aggregate
shape policy, so an aggregate descriptor missing its role reports the more
fundamental SDK configuration error instead of the later member-basis refusal.
Malformed roles remain parser failures and therefore follow the existing
malformed-target fallback behavior.

The caller audit covered SDK read, emit, source, declaration edit, kind,
verification, export, and restore paths. None opts in implicitly. This slice
does not make aggregate entity resolution, aggregate writes, aggregate
transfer, or aggregate verification supported, and it does not decide whether
local or effective aggregate topology controls inspection output.
