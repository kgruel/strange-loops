# #terminal-crafters

*a channel about terminal things. est. 2011. originally for some ncurses project nobody remembers.*

---

**synthwave** — today at 4:58 PM
yo has anyone seen this? found a python TUI lib called painted while digging through some charm v2 comparisons

"a cell-buffer terminal UI framework"

```python
import asyncio
from painted import Surface, Block, Style, border

class HelloApp(Surface):
    def render(self):
        block = Block.text("Hello, painted!", Style(fg="green"))
        bordered = border(block, title="Demo")
        bordered.paint(self._buf)

asyncio.run(HelloApp().run())
```

one dep (wcwidth). the readme is sparse but the API table is interesting:

| Export | Purpose |
|--------|---------|
| `Cell` / `Style` | Atomic display unit (char + style) |
| `Buffer` / `BufferView` | 2D cell grid with region clipping |
| `Block` | Immutable rectangle of cells for composition |
| `Span` / `Line` | Styled text primitives |
| `join_horizontal`, `join_vertical`, `pad`, `border`, `truncate` | Composition functions |
| `Surface` | Async main loop with keyboard input and resize handling |
| `Layer` / `Lens` | Layered rendering and viewport |

reminds me of what charm just did with lip gloss v2 but in python

**noodle** — today at 5:01 PM
ooh interesting, let me look at that API table for a sec

so `Block` is immutable and you compose with free functions like `border()`, `join_horizontal()` etc? that's a pretty different mental model from Textual where you'd subclass `Widget` and override `render()` to return a `Rich.Text` or whatever

like in Textual you'd do something like:
```python
class Hello(Static):
    def render(self) -> RenderableType:
        return Text("Hello!", style="green")
```

and then compose by nesting widgets in the DOM tree. here it looks like you compose by... calling functions on Blocks? more like building up a value than building a widget tree

what's `Lens` though? that's not a term I've seen in TUI stuff before. is that like a Textual Screen or something?

**mrbits** — today at 5:03 PM
flat list for the buffer. `[EMPTY_CELL] * (width * height)`. row-major. that's the right call for cache locality. most python TUI libs i've seen use nested lists which is just asking for pointer chasing.

the diff is dead simple too — walk the flat array, compare cells, emit CellWrite for mismatches. no trees, no dirty rectangles, no invalidation nonsense. just compare two buffers. that's how you do it.

`frozen=True` on Cell and Style is interesting. means the buffer diff is literally `!=` on frozen dataclasses. no custom __eq__ needed.

one thing that caught my eye: `\x1b[?2026h` / `\x1b[?2026l` — they're doing synchronized output (mode 2026). that's a relatively recent DEC private mode. means frames don't tear. most python libs still don't bother with this.

the color depth downgrade chain is right too — hex rgb falls through to 256 falls through to basic 16. resolved at the Writer, not in the style definitions. views just say what they want, writer figures out what the terminal can handle.

only dep is wcwidth and they're actually using it correctly in the buffer — wide chars get a placeholder in the next cell, and the writer tracks covered positions. that's the part everyone gets wrong.

not sure about the Block immutability hack with `object.__setattr__` and `_frozen` — seems like a lot of ceremony when you could just use `__slots__` and not provide setters. but it works.

**ghost_pipe** — today at 5:04 PM
> views just say what they want, writer figures out what the terminal can handle

this is the part that matters to me. does that mean I can start with plain `print()` output and gradually move to styled Blocks without touching the rest of the codebase? or is it all-or-nothing once you import Surface?

**noodle** — today at 5:05 PM
okay mrbits just mass-dumped terminal knowledge on us as usual 😄

the synchronized output thing is interesting — I've definitely seen tearing in Textual apps when the terminal is slow, didn't even know mode 2026 was a thing. is that something terminals widely support now or is it like a kitty/wezterm only deal?

the "views express intent, Writer resolves capability" pattern is actually really clean though. in Textual/Rich you kind of have to think about color support when you're writing styles — like if you use `rgb(...)` in your CSS and someone's on a 256-color terminal, Rich handles the downgrade but it's more... implicit? here it sounds like it's an explicit architectural boundary

the frozen dataclass thing makes sense to me for diffing. like if your cells are immutable values then `prev_cell != curr_cell` is all you need. no worrying about mutation between frames. Textual does reactive attributes + dirty flags which is way more machinery

I still don't understand what Lens is though. the table says "viewport" but mrbits you clearly read the source — is it like a camera into data? the name feels optics-y

**synthwave** — today at 5:06 PM
ok so i've been poking around the source more and the thing that's got me hyped is how much this mirrors what charm just did with lip gloss v2

like, lip gloss v2 dropped the whole "string builder" approach and went full cell buffer. you build a `Style`, you render to cells, you compose rectangles. painted has literally the same core:

```python
Cell(char="x", style=Style(fg="green", bold=True))
```

that's your atom. everything builds from there. Block is an immutable grid of cells -- and i mean *actually* immutable, they override `__setattr__` to reject mutations. in Go you'd just... not export the fields. python has to work harder for that lol

but here's where it gets interesting vs bubble tea. BT v2 still uses the Elm architecture -- Model, Update, View. painted does this layer stack thing instead:

```
Stay | Pop | Push | Quit
```

four actions. that's your whole control flow algebra. top layer handles input, all layers render bottom-to-top. it's closer to a modal stack than Elm's message passing. honestly feels more like how you'd model it in a game engine?

and then there's this Lens thing that has no bubble tea equivalent at all -- it's basically "render any data structure at different zoom levels." zoom 0 = type name, zoom 1 = summary, zoom 2 = full dump. like a cartographic zoom, not just "show less." qualitatively different views at each level

the composition API is the dead ringer for lip gloss v2 though:

```python
join_horizontal(block_a, block_b, gap=2)
border(block, chars=ROUNDED, title="Demo")
pad(block, left=1, right=1)
```

vs lip gloss:
```go
lipgloss.JoinHorizontal(lipgloss.Top, a, b)
lipgloss.NewStyle().Border(lipgloss.RoundedBorder())
```

same idea. rectangles in, rectangles out. pure composition.

one dep total (wcwidth). charm's got like 12 go modules now lol

**noodle** — today at 5:08 PM
oh that's a good question ghost_pipe. looking at the API table again there's a `print_block` in the Writer module — that feels like it might be the "just print styled stuff to stdout" entry point without needing the full Surface loop?

like in Rich you can just do `console.print("[bold green]hello[/]")` without ever touching Textual. wondering if painted has that same kind of layered adoption where Block + print_block is the "Rich" level and Surface is the "Textual" level

actually looking at the imports synthwave posted:
```python
from painted import Style, Cell, Span, Line, Block, print_block  # CLI core
from painted.tui import Surface, Layer, Focus, Search             # Interactive apps
```

so it literally separates CLI core from TUI. that's a different split than Textual/Rich where they're two separate packages entirely. here it's one library with the TUI stuff as a subpackage

that's... actually kind of nice? one `pip install` and you pick your depth

**mrbits** — today at 5:09 PM
noodle — Lens here is not a Screen. it's `(content, zoom, width) -> Block`. literally a function with metadata. zoom 0 gives you a one-liner, zoom 2 gives you full detail. there's a `shape_lens` that takes any python value and renders it at whatever zoom level you ask for.

so it's more like a cartographic zoom than a widget hierarchy. same data, different level of detail. the name comes from optics, not UI frameworks.

the key difference from textual you're noticing is real. there's no widget tree, no DOM, no layout engine. it's just functions that return Blocks, and you compose Blocks with other functions. `border(join_vertical(a, b))` — done. no subclassing. no lifecycle. the Block IS the layout.

that's a design bet. textual needs the DOM for CSS selectors and reactive properties. this doesn't have any of that. it's closer to how you'd think about it if you were writing directly to a cell buffer, except someone gave you composition primitives.

**ghost_pipe** — today at 5:10 PM
right, the import split is promising. but what I actually want to know is: can I take one existing `print()` call that outputs a status table, replace it with a Block, and `print_block()` it — and have nothing else change? same stdout, same pipes, same `| grep` downstream?

because if the answer is "yes but you need to set up a CliContext first" or "yes but it takes over stderr" then it's not actually incremental.

**synthwave** — today at 5:11 PM
@noodle yeah exactly, it's value composition not tree composition. no widget inheritance, no DOM. you just call functions that take Blocks and return Blocks. it's the same shift lip gloss v2 made -- they killed the string builder API and went "everything is a rectangle, compose rectangles"

the mental model is more like... functional pipelines? you build a Block, pass it to `border()`, get a new Block back, pass that to `pad()`, get another Block back. nothing is mutated, nothing has parent/child relationships. it's just data flowing through functions

re: Lens -- it's not like a Screen at all. it's closer to... ok so imagine you have a dict like `{"users": 150, "status": "healthy", "uptime": "3d"}`. a Lens renders that at different zoom levels:

- zoom 0: `dict(3 items)` -- just the type
- zoom 1: keys listed out, values summarized
- zoom 2: full dump of everything

and the cool part is it's recursive. nested structures reduce zoom by 1 at each level, so at zoom 2 you see the outer dict fully but inner dicts get summarized. it's like... cartographic? each zoom level is qualitatively different, not just "more text"

bubble tea doesn't have anything like this. in BT you'd just write a View function that decides what to show. ratatui doesn't either -- you'd manually write different render paths. this thing auto-derives views from data shape, which is a pretty wild idea for a TUI framework

honestly the closest analog might be Rich's `pretty` printer but made zoom-aware and returning cell buffers instead of strings

**noodle** — today at 5:13 PM
okay the layer stack vs Elm architecture comparison is clicking for me now

so in Textual you have this whole message-passing system right — widgets post messages, handlers catch them, there's bubbling up the DOM tree, and you end up with these `on_button_pressed` handlers scattered around. it works but sometimes I lose track of where state actually lives

the `Stay | Pop | Push | Quit` thing is almost aggressively simple. like you either stay on this screen, go back, go forward, or exit. that's it. no message bus, no event bubbling, no handler registration

I think the Textual comparison would be like... if `Screen.push_screen()` and `Screen.pop_screen()` were the ONLY way to do control flow? and each screen gets a self-contained `handle()` function instead of distributed message handlers?

```python
# painted (from what I'm gathering)
def handle(key, layer_state, app_state):
    return (new_layer_state, new_app_state, Pop(result))

# vs textual
def on_button_pressed(self, event):
    self.app.pop_screen()  # but also self.query_one()
                           # and self.post_message()
                           # and reactive watchers...
```

the painted version is just... a function that returns a value. no side effects to track down. I can see why mrbits would like that

the Lens zoom thing is genuinely new to me though. synthwave you said "cartographic" — so zoom 0 isn't just "zoom 2 with stuff hidden"? it's a completely different rendering? that's wild. I don't think anything in the Textual/Rich world does that. closest thing might be Rich's `__rich_repr__` but that's just for the REPL

**mrbits** — today at 5:14 PM
ghost_pipe — no, it's not all-or-nothing. there are actually three tiers and they don't depend on each other.

1. `print_block(block)` — takes a Block, writes it to stdout with ANSI. no event loop, no alt screen, no Surface. just styled print. you could use this in a script that otherwise does `print()` everywhere.

2. `InPlaceRenderer` — context manager that redraws a Block in-place using cursor control. for progress bars and spinners without taking over the screen. still no Surface.

3. `Surface` — full alt screen, keyboard input, async render loop. this is the TUI mode.

the imports even make it explicit:
```python
from painted import Block, Style, print_block  # tier 1
from painted.inplace import InPlaceRenderer     # tier 2
from painted.tui import Surface, Layer           # tier 3
```

there's a `run_cli` harness that auto-detects which tier based on TTY and flags. pipe gets static, tty gets live, `-i` gets interactive. same render function works for all three because it just returns a Block.

**synthwave** — today at 5:15 PM
@mrbits ok this is why i love this channel. i glossed right over the buffer layout and you went straight for the memory model lol

the mode 2026 thing is a great catch. bubble tea v2 does synchronized output too but it took them until v2 to get it right -- they had tearing issues in v1 with fast updates. the fact that this lib ships with it from the start says someone did their homework

and yeah the "views express intent, writer resolves capability" thing is exactly what charm landed on with ultraviolet (their new color lib). in BT v1 you'd pick your colors and if the terminal couldn't handle truecolor... too bad. ultraviolet does the degradation at render time. painted has the same pattern but it's just baked into the Writer -- no separate color library needed

re: the `object.__setattr__` thing -- i actually kind of respect the stubbornness? in rust you'd just not derive `Clone` or make fields private. in go you don't export. python doesn't give you those tools so they went nuclear. `frozen=True` on the dataclasses handles Cell and Style, but Block isn't a dataclass -- it's a class with `__slots__` that manually freezes itself. belt AND suspenders

the wide char handling is the thing that really got me though. ratatui had bugs with CJK characters for like two years because people kept getting the placeholder cell wrong. if painted has that right from day one in python that's genuinely impressive

**ghost_pipe** — today at 5:16 PM
the three tiers thing is what I needed to hear. especially tier 1 just being `print_block()` to stdout.

**noodle** — today at 5:17 PM
okay `(content, zoom, width) -> Block` makes it click. it's literally just a render function with a zoom parameter. no magic, no base class, just "give me data and a detail level and I'll give you a rectangle"

so if I'm understanding right, the whole rendering model is:

1. you have data (python values, whatever)
2. you pick a zoom level (how much detail)
3. a Lens turns that into a Block (immutable rectangle)
4. you compose Blocks with `border()`, `join_vertical()`, etc
5. Block gets painted to a Buffer
6. Buffer diffs against previous frame
7. Writer emits only the changed cells as ANSI

and there's just... no tree? no reconciliation step? no "which widget is dirty"?

I think what's tripping me up is that in Textual, the widget tree IS the abstraction for composition. you nest widgets, the framework walks the tree, does layout, renders. here the composition IS the function calls. `border(join_vertical(a, b))` is both the composition AND the layout in one expression

like I get why that's elegant but I'm genuinely curious — how do you handle something like a scrollable list where you need to track selection state and respond to keyboard input? in Textual that's a `ListView` widget with reactive properties and message handlers. here is it just... a function that takes state and returns a Block?

**mrbits** — today at 5:18 PM
mode 2026 — it's in kitty, wezterm, foot, ghostty, contour, alacritty (recent). iTerm2 has its own thing but supports it now too. the xterm-family holdouts are the ones who don't. for any terminal released in the last couple years it's basically standard. the way this code does it is correct — just wrap the frame output in begin/end markers. terminals that don't understand it ignore the private mode sequence. zero cost to emit, graceful fallback.

on Lens — yeah it's optics-inspired. but concretely: `shape_lens` takes a python dict and at zoom 0 you get `dict(5 keys)`. zoom 1 you get the keys listed. zoom 2 you get the full key-value expansion. same data, three representations. the function signature is `(content, zoom, width) -> Block`.

the word "viewport" in that table is misleading. a lens doesn't scroll. it changes *what level of detail* you see, not *where* you're looking. cartographic zoom, not google maps pan.

**ghost_pipe** — today at 5:19 PM
that's what I needed. one follow-up: when I pipe `print_block` output through `| grep`, do I get plain text or ANSI escape garbage? Rich auto-strips when it detects a non-TTY. if painted doesn't, tier 1 breaks my existing pipelines.

**noodle** — today at 5:20 PM
that's the right question to ask. "incremental" means nothing if there's hidden setup

I don't actually know the answer — ghost_pipe are you asking if `print_block` literally just writes ANSI to stdout and returns? because that's what it'd need to be for true drop-in. no context manager, no terminal mode changes, no global state

like in Rich you can do:
```python
from rich import print
print("[green]hello[/green]")
```
and it genuinely replaces `print()`. pipes work, grep works, redirect works. Rich sniffs the TTY and strips ANSI automatically when piping

if `print_block` does the same thing — detect TTY, emit ANSI or plain text accordingly, write to stdout, done — then yeah, that's real incremental adoption. but if it needs a Writer instance or terminal setup... that's a different story

someone who read the source want to confirm? mrbits?

**synthwave** — today at 5:21 PM
@ghost_pipe no this is actually the part i think is most interesting about the whole design. it's explicitly NOT all-or-nothing

there's like... a gradient of commitment:

**level 0** — just print styled text, no Surface, no alt screen, nothing:
```python
from painted import Block, Style, print_block

block = Block.text("deploy OK", Style(fg="green", bold=True))
print_block(block)  # just prints to stdout with ANSI codes
```
that's it. you import two types and a function. your script still works with pipes because `print_block` has a `use_ansi=False` flag

**level 1** — in-place animation, still no alt screen:
```python
from painted.inplace import InPlaceRenderer

with InPlaceRenderer() as r:
    r.render(some_block)  # overwrites previous output
```
cursor control to update in place. like a progress bar. no alt screen, no keyboard capture

**level 2** — full TUI with Surface, alt screen, the works

and the CLI harness auto-detects which level you need:
- piped to file? STATIC mode, plain text
- TTY? LIVE mode, in-place updates
- user passed `-i`? INTERACTIVE, full alt screen

charm doesn't have this at all. in Go you're either in bubble tea or you're not. there's no "just print a styled block to stdout." you'd use lip gloss for styling but then switching to bubble tea is a whole different paradigm. here it's the same Block type all the way through

that's the thing that makes this feel like a CLI framework that happens to support TUI, not a TUI framework you hack into CLI use

**noodle** — today at 5:23 PM
okay wait. the same render function works for all three tiers?

so you write ONE function that returns a Block, and then:
- `print_block` prints it and scrolls
- `InPlaceRenderer` redraws it in place
- `Surface` composites it in a full TUI

and the function itself doesn't know or care which one is calling it?

that's... not how Textual/Rich works at all. in the Rich/Textual world, your Rich renderables and your Textual widgets are completely different types. if I build a nice Rich table for CLI output, I can't just drop it into a Textual app — I have to wrap it in a `Static` widget or rewrite it. and going the other direction is worse, Textual widgets are meaningless outside the framework

so painted basically said "Block is the universal unit" and everything just consumes Blocks. that's why the one-package-not-two thing works — it's not that CLI and TUI are bundled together, it's that they literally share the same rendering primitive

ghost_pipe I think that answers your question? `print_block(your_block)` is genuinely just a replacement for `print()` with styling. and then if you later want animation or interactivity, you already have the Block — just hand it to a different runner

**mrbits** — today at 5:24 PM
ghost_pipe — yes, it's actually drop-in. i just read `print_block`:

```python
print_block(block)                    # styled to stdout
print_block(block, use_ansi=False)    # plain chars to stdout
```

no context object, no setup, no stderr touching. it writes line-by-line to the stream you give it (default stdout), flushes, done. `use_ansi=False` emits just the characters — no escape codes, pipes and grep work fine.

the plain path is literally:
```python
for row in block:
    for cell in row:
        stream.write(cell.char)
    stream.write("\n")
```

that's it. it's `print()` with rectangles.

**ghost_pipe** — today at 5:25 PM
> a CLI framework that happens to support TUI, not a TUI framework you hack into CLI use

that's the sentence. every other python option in this space starts from TUI and works backward. if this actually delivers on "same Block, all three modes" without ceremony, it solves a problem I've been stuck on for two years.

**mrbits** — today at 5:26 PM
synthwave — the game engine comparison is closer than Elm, yeah. the layer stack is literally a modal stack. in Elm everything is one big `update(msg, model)` and you route messages yourself. here, Push a confirmation dialog, it captures all input, it Pops with a result. the parent layer never knew it existed.

that's actually simpler for the common case. most TUI apps are "main screen + modal dialogs + maybe a command palette." the layer stack models that directly. Elm makes you model it with message routing, which is more general but more ceremony.

where Elm wins is when you need sibling communication — two panels that both react to the same event. layers are strictly stacked, no horizontal message passing. if you need that, you'd put it in the app state that both layers share.

the charm comparison is fair on composition. both converged on "immutable rectangle + free functions." but charm split it into separate Go modules (lipgloss, bubbletea, ultraviolet) that version independently. this is one package. tradeoff is obvious — one thing to install, but also one thing that has to stay coherent.

**synthwave** — today at 5:27 PM
@noodle mode 2026 support — it's broader than you'd think at this point. kitty, wezterm, foot, contour, ghostty all support it. iTerm2 added it a while back. the main holdout is Terminal.app (apple's default) and some of the older linux console emulators. but basically if you're using a terminal made in the last 3-4 years, you probably have it

the way most libs handle it is just... try to enable it and don't worry if the terminal ignores the escape sequence. it's a no-op on terminals that don't understand it. so there's no feature detection needed, you just wrap your frame output in the begin/end markers

re: the explicit capability boundary — yeah this is something charm figured out the hard way. in BT v1 / lip gloss v1, color was kind of everywhere. then they extracted ultraviolet as a separate module specifically to be the "resolve colors at the boundary" layer. painted just... started with that architecture. the Writer is the boundary. views never think about terminal capabilities. it's a cleaner separation than what Rich does where the Console object sort of handles both rendering AND capability detection at the same time

**synthwave** — today at 5:29 PM
@mrbits "the Block IS the layout" -- yeah that's the one-liner for this whole architecture

this is exactly the same bet ratatui made in rust btw. no widget tree, no retained state in the framework, just `fn render(&self, area: Rect, buf: &mut Buffer)`. you build up your UI as function calls every frame. they call it "immediate mode" but it's really "value mode" -- your render function returns a description of what the screen should look like, the framework diffs and flushes

bubble tea sits in a weird middle ground. it's technically retained (your Model persists) but the View is a pure function from Model to string. so your state is retained but your rendering is immediate. painted does the same thing with the Layer stack -- the Layer holds state, but render is a pure function from state to painted buffer

the interesting question is does the no-DOM bet scale? textual went DOM specifically because they wanted CSS-like layout, scrollable containers, focus traversal, etc. ratatui punts on all of that -- you do layout math yourself. painted has... some of it? Focus is in there, Search is in there, Viewport is in there. but they're all frozen state types with free functions, not a DOM tree

feels like they're betting on "you can get surprisingly far with pure functions and explicit state" which... having used ratatui for a year, yeah, you actually can. the complexity ceiling is lower than a DOM but you hit that ceiling way later than you'd expect

**noodle** — today at 5:30 PM
the wide char thing is real pain btw. I built an internal tool that had to display Japanese hostnames in a table and Rich handled it fine but when I tried to do manual column alignment with plain strings everything was off by one because `len("日")` is 1 but it takes 2 columns. that's literally what wcwidth solves right?

so painted just... uses wcwidth everywhere from the start? like Span knows its display width, Block knows its cell width, the buffer knows a wide char occupies two cells? that consistency would've saved me a weekend

also synthwave the "belt AND suspenders" for immutability is interesting because it tells you something about the design priorities. they REALLY don't want you mutating state between frames. like that's not a suggestion, it's enforced at every level. frozen dataclasses for the small types, manual `__setattr__` rejection for Block

in Textual the mutability is the feature — you mutate reactive properties and the framework reacts. here immutability is the feature — you build new values every frame and the framework diffs. two totally opposite bets on the same problem

**synthwave** — today at 5:31 PM
@noodle yeah you nailed it. and this is where painted diverges from the charm model in a way that i think actually matters

charm went the opposite direction — they split everything into separate Go modules. bubbletea, lipgloss, ultraviolet, bubbles, huh, glamour... you `go get` each one separately. it's the Go ecosystem ethos: small composable packages

painted said "nah, one library, subpackages for depth." and honestly? for python that's the right call. `pip install painted` and you have everything from `print_block` to full TUI. you just import deeper as you need more

the thing that makes it work is the Block type being the universal currency. in charm-land, lipgloss returns strings, bubbletea's View returns a string, and that string is your rendered output. they converged on cell buffers in v2 but you still wire things up differently between the libs

here Block is the same type whether you're doing:
```python
print_block(block)              # CLI script
renderer.render(block)          # live animation
block.paint(surface._buf)       # full TUI
```

same type, three different delivery mechanisms. that's a genuinely different architecture than "Rich for printing, Textual for TUI, hope they play nice together"

**ghost_pipe** — today at 5:32 PM
> a CLI framework that happens to support TUI, not a TUI framework you hack into CLI use

that's the sentence. every other python option in this space starts from TUI and works backward. if this actually delivers on "same Block, all three modes" without ceremony, it solves a problem I've been stuck on for two years.

