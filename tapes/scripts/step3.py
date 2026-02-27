from painted import show, Block, Style, border, join_vertical, ROUNDED

header = Block.text(" api-gateway v2.4.1 ", Style(bold=True, reverse=True))
status = join_vertical(
    Block.text("  replicas: 3/3 ready  ", Style(fg="green")),
    Block.text("  /health:     200 12ms", Style(fg="green")),
    Block.text("  /api/v1:     200 45ms", Style(fg="cyan")),
)
show(border(join_vertical(header, status), chars=ROUNDED))
