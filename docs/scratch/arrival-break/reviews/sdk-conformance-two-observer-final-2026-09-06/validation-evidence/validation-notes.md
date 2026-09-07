# Native validation

All test processes used disposable task-local XDG_STATE_HOME, XDG_CONFIG_HOME
and LOOPS_HOME, including process-level isolation for the inherited SDK suite.
The new test also carries its own autouse isolation fixture.

Commands reported by the validation agent:

```sh
uv run --no-sync --package sdk pytest libs/sdk/tests -q
uv run --no-sync pytest tests/architecture -q
uv run --no-sync --package sdk ruff check libs/sdk/tests/test_arrival_mapped_workload.py
git diff --check
```

Fable's frozen packet contains the first full runs: SDK 579 /20.88s and
architecture 101 /5.49s. Supplemental final runs confirmed SDK 579 /17.53s
and architecture 101 /6.02s; final Ruff passed. The supplemental logs and
source hashes were archived after review launch, so they are not claimed as
input to the reviewer. Final workload hash matches the review packet.
No production file changed in this slice. Raw fixture directories, private
keys and stores are deliberately excluded from committed review artifacts.
