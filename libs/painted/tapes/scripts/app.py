from painted import show, Block, Style, border, join_vertical, ROUNDED

data = {"service": "api-gateway", "version": "2.4.1", "replicas": 3}

header = Block.text(f" {data['service']} ", Style(bold=True, reverse=True))
body = join_vertical(
    Block.text(f"  version:  {data['version']} ", Style(fg="cyan")),
    Block.text(f"  replicas: {data['replicas']}/3  ", Style(fg="green")),
)
show(border(join_vertical(header, body), chars=ROUNDED))
