"""Profile benchmark - correct calling convention for committed HEAD."""
import time, gc, sys
sys.path.insert(0, "benchmarks")
from benchmark_replay_fidelity import (
    _preparse_kdl_configs, _direct_configs, _prebuild_all,
    _fast_copy, run_verification,
)

all_configs = _preparse_kdl_configs() + _direct_configs()
fast_1, fast_n, multi, tc, tf, zc = _prebuild_all(all_configs)
args = (fast_1, fast_n, multi, tc, tf, zc, _fast_copy)

print(f"fast_1: {len(fast_1)}, fast_n: {len(fast_n)}, multi: {len(multi)}, zero: {zc}")
print(f"total_configs: {tc}, total_facts: {tf}")

# Warmup
run_verification(*args)

# Time each tier separately (1000 iters)
N = 2000

gc.disable()

t0 = time.perf_counter()
for _ in range(N):
    for payload, apply_fn, reset_fn in fast_1:
        state = reset_fn()
        apply_fn(state, payload)
t1 = time.perf_counter()
print(f"\nTier 1 (fast_1): {(t1-t0)/N*1e6:.0f}us per iter ({len(fast_1)} configs)")

t0 = time.perf_counter()
for _ in range(N):
    for payloads, apply_fn, reset_fn in fast_n:
        state = reset_fn()
        for p in payloads:
            apply_fn(state, p)
t1 = time.perf_counter()
print(f"Tier 2 (fast_n): {(t1-t0)/N*1e6:.0f}us per iter ({len(fast_n)} configs)")

t0 = time.perf_counter()
for _ in range(N):
    for flat, facts, all_known, expected in multi:
        states = {kind: rst() for kind, (_, rst) in flat.items()}
        if all_known:
            for kind, payload in facts:
                flat[kind][0](states[kind], payload)
        if states != expected:
            pass
t1 = time.perf_counter()
print(f"Tier 3 (multi):  {(t1-t0)/N*1e6:.0f}us per iter ({len(multi)} configs)")

# Full benchmark - best of many
times = []
for _ in range(N):
    t0 = time.perf_counter()
    run_verification(*args)
    t = time.perf_counter() - t0
    times.append(t)

gc.enable()

times.sort()
best = times[0]
p5 = times[len(times)//20]
p10 = times[len(times)//10]
median = times[len(times)//2]
print(f"\nFull best:   {best*1e6:.0f}us = {tc/best:.0f}/sec")
print(f"Full p5:     {p5*1e6:.0f}us = {tc/p5:.0f}/sec")
print(f"Full p10:    {p10*1e6:.0f}us = {tc/p10:.0f}/sec")
print(f"Full median: {median*1e6:.0f}us = {tc/median:.0f}/sec")
