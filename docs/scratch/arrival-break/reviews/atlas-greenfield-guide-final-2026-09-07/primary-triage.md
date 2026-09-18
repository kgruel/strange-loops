# Primary triage — revise execution instructions

Fable verdict REVISE, two purported prose blockers. Original frozen packet and
findings retained unchanged.

1. Accepted as a usability correction: the native replay executed a script,
   while the guide invited a persistent interactive Bash session. Guide now
   explicitly instructs saving the six blocks into one script and running it
   with bash. Strict shell options stay in that script; command bodies unchanged.
2. The asserted missing declaration fields are a false positive. The actual
   declaration.json has both top-level head and phase, in addition to status
   and commit. The reviewer inferred absence because a checker did not assert
   those fields. A whitelisted actual result-shape extract is provided with
   the correction packet. We still accept the suggested simpler reader focus:
   status and commit.before/after. No runtime or result-shape correction occurred.

Optional improvements adopted: explicit per-item signed/witnessed/stored batch
wording and uv sync's ignored lockfile effect. Python>=3.11 is the package
metadata floor, not a claim that this replay ran every interpreter version;
this native replay used Python3.13.11. Initialization recovery facts come from
the existing CLI reference/implemented tests, not this happy-path walkthrough.

Primary closure pending the focused correction review. The guide remains a
successful native script replay; no source/CLI changes or new store run required
for prose-only changes. The current six blocks remain byte-identical to guide.sh.
