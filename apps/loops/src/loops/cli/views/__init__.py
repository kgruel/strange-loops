"""cli.views — per-verb argparse + Operation construction.

Each view is a module with a ``run(argv, ctx) -> int`` entry point. The
view parses argv, builds an ``Operation`` IR, and returns
``dispatch(op, reporter=ctx.reporter)``.

Step 3 lands the first pilot (``emit``). Subsequent views land in
steps 4–5.
"""
