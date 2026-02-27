# Loops parallel-fold computation — Bend implementation.
#
# Same computation as parallel_fold.py, on interaction combinators.
#
# Proves commutative folds can be tree-reduced = automatic parallelism.
#
# Generate 1024 health status values using bend (tree-structured generation).
# Status: 1 if leaf index is even, 0 if odd.
# Sum them via tree fold — Bend parallelizes this automatically.
#
# Sequential left-fold would be: sum over a list, O(n) depth.
# Tree fold: O(log n) depth, each level can run in parallel.
#
# Output: 512 (half of 1024 values are 1)

# Generate a binary tree of depth d with status values at leaves.
# Leaf index i: status = 1 if even, 0 if odd.
def gen_facts(d, i):
  if d < 10:
    return ![gen_facts(d + 1, i * 2), gen_facts(d + 1, i * 2 + 1)]
  else:
    if i % 2 == 0:
      return !1
    else:
      return !0

# Tree fold: sum all leaves. O(log n) depth = parallel.
def tree_sum(tree):
  fold tree:
    case Tree/Node:
      return tree.left + tree.right
    case Tree/Leaf:
      return tree.value

def main():
  tree = gen_facts(0, 0)
  return tree_sum(tree)
