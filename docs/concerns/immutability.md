## Level 0: **Conventional immutability** (frozen dataclass, but payloads are mutable)

### What it is

* `@dataclass(frozen=True)` prevents rebinding `event.data = …`
* but `event.data["x"] = …` still works if it’s a dict

### What you gain

* **Ergonomics**: easiest to use, fewest constraints
* **Performance**: no deep copying/freezing costs
* **Frictionless interop**: everyone already has dicts

### What you lose

* **Truthfulness**: you can’t honestly claim “immutable”
* **Safety**: subtle bugs where a renderer or middleware mutates payloads
* **Test stability**: previously-emitted events can be altered accidentally
* **Replay/audit integrity**: transcripts are not tamper-resistant by default

### When it’s okay

* early prototypes
* single-owner codebase
* minimal plumbing (few middlewares)

This is the “Pythonic” default, but it’s also where contracts tend to decay.

---

## Level 1: **Shallow immutability + discipline** (immutable at top-level + optional copy-on-emit)

### What it is

* still accept dict-like payloads
* but you enforce one or more guardrails:

  * copy payload on construction (`dict(data)`), or
  * freeze only the top-level mapping (e.g., `MappingProxyType`)
  * document “payloads must be treated as immutable”
  * optionally deep-copy in the emitter when recording

### What you gain

* **Better safety** with minimal pain
* **More honest story**: “effectively immutable once emitted”
* **Cheap**: shallow copy is fast
* **Works with JSON serialization** more predictably

### What you lose

* **Not perfect**: nested structures can still mutate unless deep-frozen
* **Some overhead**: shallow copy on every event
* **Some confusion**: devs may assume deep immutability when it isn’t

### When it’s the sweet spot

* a Python ecosystem library aiming for adoption
* Black-like “we’ll be strict, but not painful”
* when you want a strong contract but not heavy machinery

If you do one thing, do this.

---

## Level 2: **Deep immutability enforced** (persistent/immutable structures)

### What it is

Payloads are stored in truly immutable containers:

* persistent maps/lists (immutables.Map, pyrsistent, etc.)
* deep-frozen tuples / frozendict recursively
* a “freeze()” function that converts recursively

Now `data`/`meta` cannot be mutated at any depth.

### What you gain

* **Strongest guarantee**: events are *tamper-proof by construction*
* **Predictable behavior**: safe to share across threads, middlewares
* **Replay integrity**: stored transcripts are reliable
* **Renderer safety**: no accidental mutation
* **“Black-style” vibe**: discipline is baked in

### What you lose

* **Friction**: users have to learn/accept immutable containers
* **Interop cost**: converting in/out of plain dicts
* **Overhead**: freezing and conversion costs (often acceptable, but real)
* **Dependency pressure**: you either ship your own immutables or take a dep

### When it’s worth it

* you expect plugins and third-party extensions early
* you want a “contract you can trust” story strongly
* you want transcripts to be intrinsically safe

This is the “correctest,” but it can slow adoption.

---

# What immutability buys you in *this* specific design

Your contract layer is trying to be:

* authoritative (Result)
* auditable (events)
* renderer-agnostic
* composable
* stable

Immutability directly supports:

### 1) **Transcript integrity**

If you store `Event`s, you want to know they won’t change after emission.

### 2) **Middleware safety**

As soon as you add:

* event filtering
* enrichment
* renderer adapters
  it becomes easy for one layer to mutate shared dicts and surprise everyone.

### 3) **Testing + determinism**

You want to snapshot a transcript and assert on it. Mutation makes tests flaky.

### 4) **Concurrency safety**

Not your main focus, but if you later stream events from async tasks, mutable shared payloads are painful.

---

# What immutability costs you

### 1) Ergonomic friction

People love `dict` and will keep using it.

### 2) Performance overhead

Deep freeze on every event could be noticeable in extremely chatty commands (though you can throttle events anyway).

### 3) “Python expectations”

Python users often accept “don’t mutate that” rather than enforced immutability. Too strict too early can reduce adoption.

---

# The real decision: what promise do you want to make?

You can choose your immutability level based on the promise you want to put in the README:

### Promise A (lightweight)

> “Events and Results are frozen dataclasses; treat payloads as immutable.”

→ Level 0/1

### Promise B (stronger)

> “Once emitted, Events/Results are immutable values suitable for storage and replay.”

→ Level 1 (with copy-on-emit + mapping proxy) or Level 2

### Promise C (strongest)

> “Payloads are deeply immutable by construction.”

→ Level 2

# A useful framing

Think of it like `logging.LogRecord`:

* not truly immutable
* but treated as immutable after creation
* mutation is considered a bug