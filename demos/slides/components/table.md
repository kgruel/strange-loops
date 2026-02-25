---
id: table
title: Table
group: components
order: 5
align: center
---

# Table

[spacer]

`TableState` + `table()`

[spacer]

[demo:table]

[spacer]

```python
columns = [Column(header=Line.plain("Name"), width=12)]
rows = [[Line.plain("Cell")], [Line.plain("Block")]]
state = TableState(cursor=Cursor(count=len(rows)))

tbl = table(state, columns, rows, visible_height=3)
```
