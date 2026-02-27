# Bend Capabilities Reference

Current state of the Bend language as of v0.2.38 (2025-02-23).
Based on source docs in `~/Code/bend/Bend/`.

## Numbers

All numbers are **24-bit**. No 32-bit or 64-bit types.

| Type | Range | Syntax | Notes |
|------|-------|--------|-------|
| `u24` | 0 to 16,777,215 | `42`, `0xFF`, `0b101` | Default for bare numbers |
| `i24` | -8,388,608 to 8,388,607 | `+7`, `-3` | **Must** have sign prefix |
| `f24` | ~7 decimal digits | `3.14`, `+1.0` | IEEE-754 float32 with truncated mantissa |

**Gotcha:** Mixing number types silently produces garbage. No runtime error.

Operations: `+ - * / % == != < > <= >= & | ^ >> <<` (bitwise only u24/i24).
Exponentiation `**` only for f24.

Casting: `u24/to_f24`, `f24/to_i24`, `i24/to_u24`, etc.

## Data Types

| Type | Description | Keys/Elements |
|------|-------------|---------------|
| `List` | Linked list (`Cons/Nil`) | Any, homogeneous recommended |
| `String` | Linked list of u24 chars | UTF-16 codepoints |
| `Map` | Binary tree map | **u24 keys only** |
| `Tree` | Binary tree with leaf values | Any |
| `Maybe` | `Some { value }` / `None` | |
| `Result` | `Ok { val }` / `Err { val }` | |
| `Nat` | Peano naturals (`Succ/Zero`) | |
| `DiffList` | O(1) append list | |

Custom types via `type` (ADT with variants) and `object` (single-constructor struct).

**Gotcha:** Lists and Strings are linked lists, not arrays. No indexing. O(n) access.

### Map operations

```
state = {}              # empty map
state[key] = value      # set (key must be u24)
val = state[key]        # get (unreachable if missing!)
state[key] @= fn        # map a function over value
(has, state) = Map/contains(state, key)  # returns (u24, Map)
```

### String operations

- `String/equals(s1, s2)` — equality check
- `String/split(s, delimiter)` — split by char into `List(String)`
- `String/encode_utf8(s)` / `String/decode_utf8(bytes)` — encoding
- `u24/to_string(n)` — number to string

### List operations

- `List/length(xs)` — returns `(u24, List)` tuple
- `List/reverse(xs)`, `List/flatten(xs)`, `List/concat(xs, ys)`
- `List/filter(xs, pred)`, `List/split_once(xs, cond)`
- List comprehensions: `[x + 1 for x in list if x > 2]`

## IO — More Capable Than Expected

IO uses a monadic `with IO:` block and requires **`bend run-c`** (not `run-rs`).

### Console

```python
def main() -> IO(u24):
  with IO:
    * <- IO/print("hello\n")           # write to stdout
    line <- IO/input()                  # read line from stdin
    return wrap(0)
```

### File IO

```python
IO/FS/open(path, mode)      # "r", "w", "a", "r+", "w+", "a+"
IO/FS/close(file)
IO/FS/read(file, num_bytes)  # returns List(u24) of bytes
IO/FS/read_line(fd)          # read one line
IO/FS/read_to_end(fd)        # read until EOF
IO/FS/read_file(path)        # read entire file
IO/FS/write(file, bytes)     # write bytes
IO/FS/write_file(path, bytes)
IO/FS/seek(file, offset, mode)
IO/FS/flush(file)
```

Standard file descriptors: `IO/FS/STDIN = 0`, `IO/FS/STDOUT = 1`, `IO/FS/STDERR = 2`.

### FFI (Dynamic Libraries)

```python
dl <- IO/DyLib/open("./libfoo.so", 0)
result <- IO/DyLib/call(dl, "function_name", args)
* <- IO/DyLib/close(dl)
```

C functions must have signature: `Port fn(Net* net, Book* book, Port arg)`.
Compile with `-shared -fPIC` and appropriate unresolved-symbols flags.

## Control Flow

- `if/elif/else` — condition must be u24 (0 = false, nonzero = true)
- `match` — pattern match on ADT variants
- `switch` — pattern match on u24 numbers (cases 0, 1, ..., _)
- `fold` — recursive match that auto-recurses on `~` fields
- `bend` — recursive loop that generates structures via `fork`
- `with` — monadic blocks (used for IO, Result, custom monads)

## Functions

- Top-level `def` with optional type annotations
- Lambdas: `lambda x: body` or `λx: body`
- Higher-order functions, closures (local `def` captures variables)
- Partial application
- No early return — all branches must end with `return`

## Parallelism

Automatic. Independent expressions parallelize without annotations.

| Runner | Command | Threads | IO Support | Speed |
|--------|---------|---------|------------|-------|
| Reference | `bend run-rs` | 1 | **No** | Slowest |
| C interpreter | `bend run-c` / `bend run` | Multi (pthreads) | **Yes** | Fast |
| C compiler | `bend gen-c` + gcc | Multi (pthreads) | Yes | Faster |
| CUDA | `bend run-cu` | GPU (16k+) | Yes | Fastest |

**Key insight:** `run-rs` cannot do IO. Must use `run-c` or compiled.

Tree-shaped computations parallelize best. Sequential folds (left-fold over list)
don't parallelize. Fold over balanced binary tree does.

## Math Builtins

All operate on f24: `Math/log`, `Math/sqrt`, `Math/sin`, `Math/cos`, `Math/tan`,
`Math/atan`, `Math/atan2`, `Math/asin`, `Math/acos`, `Math/ceil`, `Math/floor`,
`Math/round`, `Math/radians`, `Math/PI`, `Math/E`.

No built-in `max`, `min`, `abs`.

## CLI Arguments

Programs can receive arguments: `bend run-c prog.bend arg1 arg2`.
Arguments are applied to `main` as lambda arguments. Any expression is valid.

## Import System

```python
from path import name
from path import (name1, name2)
from path import *
import path as alias
```

Paths starting with `./` or `../` are relative to file. Others relative to main file.

## What Bend Cannot Do

- **No 32/64-bit numbers.** u24 max is ~16M. Percentages and small counts are fine.
- **No JSON parsing.** Would need manual implementation from string operations.
- **No regex.** String processing is char-by-char on linked lists.
- **No mutable state.** Everything is immutable. "Mutation" = rebinding.
- **No arrays/vectors.** All sequences are linked lists (O(n) access).
- **No standard max/min/abs.** Must implement manually.
- **No try/catch.** Use `Result` type instead.
- **No type safety by default.** Type system is optional; mistakes produce garbage silently.
- **No string interpolation or formatting.** Concatenation only.

## What Bend Can Do (That We Didn't Use Yet)

- **Read from stdin** via `IO/input()` or `IO/FS/read_line(IO/FS/STDIN)`
- **Read files** via `IO/FS/read_file(path)` — could read witness output from a file
- **Call C libraries** via FFI — could write a C adapter for any I/O
- **Split strings** via `String/split(s, delimiter)` — could parse simple formats
- **CLI arguments** — could pass data to Bend programs as arguments

## Implications for Loops

### The disk_monitor compute.bend could read from stdin

Using `IO/input()` in a `with IO:` block, the Bend program could read JSONL
facts line by line. Combined with `String/split` and manual parsing, it could
consume witness.sh output directly: `bash witness.sh | bend run-c compute.bend`.

The main challenge is parsing: JSONL → structured facts requires extracting
numbers from strings, which Bend has no built-in support for. We'd need to
implement `string_to_u24` and a simple field parser.

### The 24-bit limit is fine for our use case

Percentages (0-100), mount IDs (1-5), and small counts all fit in u24.
Would break for timestamps, large byte counts, or anything > 16M.

### IO requires run-c, not run-rs

All our existing experiments used `run-rs`. IO experiments must switch to `run-c`.
This also means IO programs get multi-threaded execution automatically.
