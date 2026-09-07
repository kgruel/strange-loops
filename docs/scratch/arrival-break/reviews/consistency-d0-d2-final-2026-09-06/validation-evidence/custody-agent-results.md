# Final custody validation provenance

Terra reported these final current-source results in its completed agent turn:

- Focused provider/recovery: 26 passed.
- Full custody: 76 passed.

The tests used isolated state/config/Loops roots. There is no separately saved
raw log for these two final commands; this record preserves the agent result,
not reconstructed pytest output. The earlier full run logs and independent root
probes are retained separately.
