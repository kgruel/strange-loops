# One-shot version: reads URLs from stdin, hashes them (u24), deduplicates by
# hash using Map membership, returns total unique count.
#
# Input format:
# - URL lines, UTF-8 bytes
# - comment/boundary lines start with '#', ignored
#
# NOTE: We intentionally use `IO/FS/read_to_end(IO/FS/STDIN)` rather than
# `IO/FS/read_line`, because `read_line` relies on `seek` and fails on pipes.

def insert_hash(items: Map(u24), total: u24, h: u24) -> (Map(u24), u24):
  (has, items2) = Map/contains(items, h)
  if has == 1:
    return (items2, total)
  else:
    items3 = Map/set(items2, h, 1)
    return (items3, total + 1)

def consume_bytes(bytes: List(u24)) -> u24:
  items = Map/empty()
  (items, total) = consume_bytes.go(bytes, items, 0, 0, 0, 0)
  return total

def consume_bytes.go(
  bytes: List(u24),
  items: Map(u24),
  total: u24,
  line_hash: u24,
  line_len: u24,
  line_is_comment: u24
) -> (Map(u24), u24):
  match bytes:
    case List/Nil:
      if line_len > 0:
        if line_is_comment == 0:
          return insert_hash(items, total, line_hash)
        else:
          return (items, total)
      else:
        return (items, total)
    case List/Cons:
      b = bytes.head
      if b == '\n':
        if line_len > 0:
          if line_is_comment == 0:
            (items2, total2) = insert_hash(items, total, line_hash)
            return consume_bytes.go(bytes.tail, items2, total2, 0, 0, 0)
          else:
            return consume_bytes.go(bytes.tail, items, total, 0, 0, 0)
        else:
          return consume_bytes.go(bytes.tail, items, total, 0, 0, 0)
      else:
        if b == '\r':
          return consume_bytes.go(bytes.tail, items, total, line_hash, line_len, line_is_comment)
        else:
          if line_len == 0:
            if b == '#':
              line_is_comment = 1
            else:
              line_is_comment = line_is_comment
          else:
            line_is_comment = line_is_comment

          if line_is_comment == 0:
            line_hash = (line_hash * 31) + b
          else:
            line_hash = line_hash

          line_len += 1
          return consume_bytes.go(bytes.tail, items, total, line_hash, line_len, line_is_comment)

def main() -> IO(u24):
  with IO:
    res <- IO/FS/read_to_end(IO/FS/STDIN)
    match res:
      case Result/Err:
        return wrap(0)
      case Result/Ok:
        bytes = res.val
        total = consume_bytes(bytes)
        return wrap(total)
