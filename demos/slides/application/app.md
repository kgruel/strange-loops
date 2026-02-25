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

<!-- docgen:begin py:fidelis.app:Surface#signature -->
```python
class Surface:
```
<!-- docgen:end -->

<!-- docgen:begin py:fidelis.app:Surface.run#signature -->
```python
    async def run(self) -> None:
```
<!-- docgen:end -->
