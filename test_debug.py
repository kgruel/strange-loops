"""Quick test: render the debug panel via the render layer."""

import time

from framework.store import EventStore
from framework.debug import DebugPane
from framework.instrument import metrics
from render.buffer import Buffer
from render.writer import Writer


def main():
    # Set up store + debug pane
    store = EventStore()
    debug = DebugPane(store, actions={"B": ("bulk spawn", lambda: None)})
    debug.toggle()  # make visible + enable metrics

    # Simulate some activity
    for i in range(50):
        store.add({"type": "process_started", "pid": i})
        metrics.count("events_added")

    # Fake render timings (varying to show sparkline shape)
    for ms in [4, 6, 8, 12, 15, 10, 7, 5, 9, 14, 18, 11, 6, 8]:
        with metrics.time("render"):
            time.sleep(ms / 1000)

    # Fake projection work
    for _ in range(30):
        with metrics.time("proj.status.advance"):
            time.sleep(0.0005)
        metrics.count("proj.status.events_folded")
    metrics.gauge("proj.status.lag", 3.0)

    # Fake frame/effect counters
    metrics.count("frames_rendered", 10)
    metrics.count("effect_fires", 35)

    # Render
    block = debug.render()

    # Paint to buffer and write to terminal
    buf = Buffer(block.width, block.height)
    block.paint(buf, 0, 0)

    # Diff against empty buffer = full draw
    prev = Buffer(block.width, block.height)
    writes = buf.diff(prev)

    writer = Writer()
    writer.enter_alt_screen()
    writer.write_frame(writes)
    input()  # Enter to quit
    writer.exit_alt_screen()


if __name__ == "__main__":
    main()
