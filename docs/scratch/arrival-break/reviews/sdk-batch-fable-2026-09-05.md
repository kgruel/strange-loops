# Fable 5.1 adversarial review — SDK batch emission

Date: 2026-09-05  
Status: queued; invocation prohibited before the reported 21:20 CDT quota reset

The complete static review packet is
`/tmp/loops-arrival-review/sdk-batch-prompt.txt` (302,980 bytes, SHA-256
`64d2da0b22c5133c2a60d2e8bee1f7c10628b34fbcfcd667a5444ee1b17772de`). It
contains the complete current SDK emission/result/error/export sources, full
SDK acceptance tests including untracked Arrival tests, the narrow engine
signing repair diff and its complete test files, relevant design text, the
stage report, and the previously accepted engine batch report.

The queued command is recorded in
`/tmp/loops-arrival-review/sdk-batch-review-command.txt`. It requests verified
`claude-fable-5-1[1m]` in safe mode with no tools or session persistence and
caps the answer at eight findings and 1,500 words. Its JSON result path is
`/tmp/loops-arrival-review/sdk-batch-result.json`.

No review invocation was made at 18:26 CDT because the Claude session limit
reported by root does not reset until 21:20 CDT. Verdict, exact `modelUsage`,
finding dispositions, and final focused rechecks remain pending.

