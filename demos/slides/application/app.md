---
id: app
title: Surface
group: application
order: 1
align: center
---

# Surface

[spacer]

[zoom:0]

the application loop - `keyboard`, `resize`, `diff rendering`

[spacer]

```python
class MyApp(Surface):
    def render(self):
        # paint into self._buf

    def on_key(self, key: str):
        if key == "q":
            self.quit()
```

[spacer]

→ right for `components` (interactive widgets)

[zoom:1]

from `fidelis/app.py`

[spacer]

```python
class Surface:
    """Async main loop with diff-based rendering."""

    async def run(self):
        self._writer.enter_alt_screen()
        try:
            while not self._quit:
                # Handle input
                for key in self._keyboard.read():
                    self.on_key(key)
                # Update state
                self.update()
                # Render if dirty
                if self._dirty:
                    self.render()
                    self._flush()
                await asyncio.sleep(1 / self._fps_cap)
        finally:
            self._writer.exit_alt_screen()
```
