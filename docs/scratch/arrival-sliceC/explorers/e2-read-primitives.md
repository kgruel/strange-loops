QUESTION SET — current read-primitive surface of the arrival/jsonl store layer.

In libs/store/src/store/ (jsonl.py, arrival store module(s), and any read/iteration modules):
1. Enumerate every public read/iteration method on the JSONL store and the arrival store classes: name, file, line range, verbatim signature + docstring first line. Note (as a description, not a judgment) what order each yields records in, quoting the code or docstring line that states it.
2. Locate where `record.id` is generated/assigned — file:line, verbatim.
3. Locate where arrival sequence / arrival position / arrival head is currently computed or exposed — every site, file:line, verbatim.
4. Locate any existing function or method taking a (prefix, key) or (watermark, key) style pair for reads — anything close to an `ordered(prefix, key)` shape.
5. Enumerate call sites OUTSIDE libs/store (libs/engine, libs/sdk, apps/) that call the read/iteration methods from item 1 — file:line, verbatim call line.
