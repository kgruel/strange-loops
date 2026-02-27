"""
Loops parallel-fold computation — Python reference implementation.

Proves that commutative folds can be tree-reduced for automatic parallelism.

Generate 1024 health facts (status alternating 0/1 across containers 1-3).
Fold them two ways:
  1. Sequential left-fold: sum all status values one by one
  2. Tree-structured fold: divide and conquer, same result

Both produce the same result because addition is commutative+associative.
The tree version is what Bend can parallelize across cores.

Container IDs: 1=web, 2=api, 3=db (cycling)
Status:        alternating pattern

Output: the fold result (both methods must agree)
"""

# --- Generate 1024 facts as (container, status) pairs ---
# We just need the status values for summing. Keep it simple.

N = 1024
statuses = []
for i in range(N):
    # Container cycles 1,2,3,1,2,3,...
    container = (i % 3) + 1
    # Status alternates: 1 if even index, 0 if odd
    status = 1 if i % 2 == 0 else 0
    statuses.append(status)

# --- Sequential left-fold: sum ---

seq_result = 0
for s in statuses:
    seq_result += s

# --- Tree-structured fold: divide and conquer ---

def tree_sum(arr, lo, hi):
    if hi - lo == 1:
        return arr[lo]
    mid = (lo + hi) // 2
    left = tree_sum(arr, lo, mid)
    right = tree_sum(arr, mid, hi)
    return left + right

tree_result = tree_sum(statuses, 0, len(statuses))

# Both must agree
assert seq_result == tree_result, f"Mismatch: {seq_result} != {tree_result}"

# 512 even indices out of 1024 -> sum = 512
print(seq_result)
