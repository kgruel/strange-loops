# Persistent version: implements the vertex `store "./data/feeds.db"` clause
# by reading/writing a simple state file.
#
# Key idea / expected wall:
# - Bend's built-in `Map(T)` has no supported iteration over keys/entries, so it
#   cannot be serialized directly.
# - Workaround: persist a parallel `List(u24)` of keys (hashes) and rebuild the
#   `Map(u24)` on startup.
#
# State file format (`./data/feeds.db`):
# - ASCII text, one base-10 u24 hash per line.
#
# Input format (stdin):
# - URL lines (UTF-8)
# - comment/boundary lines start with '#', ignored

STATE_PATH : String = "./data/feeds.db"

type State:
  State { items: Map(u24), keys: List(u24), total: u24, new: u24 }

def is_digit(c: u24) -> u24:
  if c < '0':
    return 0
  else:
    if c <= '9':
      return 1
    else:
      return 0

def parse_state_bytes(bytes: List(u24)) -> List(u24):
  return parse_state_bytes.go(bytes, 0, 0, [])

def parse_state_bytes.go(
  bytes: List(u24),
  acc: u24,
  in_num: u24,
  out: List(u24)
) -> List(u24):
  match bytes:
    case List/Nil:
      if in_num == 1:
        return List/reverse(List/Cons(acc, out))
      else:
        return List/reverse(out)
    case List/Cons:
      b = bytes.head
      if b == '\n':
        if in_num == 1:
          out = List/Cons(acc, out)
          return parse_state_bytes.go(bytes.tail, 0, 0, out)
        else:
          return parse_state_bytes.go(bytes.tail, 0, 0, out)
      else:
        if b == '\r':
          return parse_state_bytes.go(bytes.tail, acc, in_num, out)
        else:
          if is_digit(b):
            acc = (acc * 10) + (b - '0')
            return parse_state_bytes.go(bytes.tail, acc, 1, out)
          else:
            return parse_state_bytes.go(bytes.tail, acc, in_num, out)

def build_state(keys: List(u24)) -> State:
  return build_state.go(keys, Map/empty(), [], 0)

def build_state.go(
  keys: List(u24),
  items: Map(u24),
  out_keys: List(u24),
  total: u24
) -> State:
  match keys:
    case List/Nil:
      return State/State(items, List/reverse(out_keys), total, 0)
    case List/Cons:
      key = keys.head
      (has, items2) = Map/contains(items, key)
      if has == 1:
        return build_state.go(keys.tail, items2, out_keys, total)
      else:
        items3 = Map/set(items2, key, 1)
        return build_state.go(keys.tail, items3, List/Cons(key, out_keys), total + 1)

def load_state(path: String) -> IO(State):
  with IO:
    res <- IO/FS/read_file(path)
    match res:
      case Result/Err:
        return wrap(State/State(Map/empty(), [], 0, 0))
      case Result/Ok:
        bytes = res.val
        keys = parse_state_bytes(bytes)
        state = build_state(keys)
        return wrap(state)

def insert_hash(state: State, h: u24) -> State:
  match state:
    case State/State:
      (has, items2) = Map/contains(state.items, h)
      if has == 1:
        return State/State(items2, state.keys, state.total, state.new)
      else:
        items3 = Map/set(items2, h, 1)
        keys2 = List/Cons(h, state.keys)
        return State/State(items3, keys2, state.total + 1, state.new + 1)

def consume_input_bytes(bytes: List(u24), state: State) -> State:
  return consume_input_bytes.go(bytes, state, 0, 0, 0)

def consume_input_bytes.go(
  bytes: List(u24),
  state: State,
  line_hash: u24,
  line_len: u24,
  line_is_comment: u24
) -> State:
  match bytes:
    case List/Nil:
      if line_len > 0:
        if line_is_comment == 0:
          return insert_hash(state, line_hash)
        else:
          return state
      else:
        return state
    case List/Cons:
      b = bytes.head
      if b == '\n':
        if line_len > 0:
          if line_is_comment == 0:
            state = insert_hash(state, line_hash)
            return consume_input_bytes.go(bytes.tail, state, 0, 0, 0)
          else:
            return consume_input_bytes.go(bytes.tail, state, 0, 0, 0)
        else:
          return consume_input_bytes.go(bytes.tail, state, 0, 0, 0)
      else:
        if b == '\r':
          return consume_input_bytes.go(bytes.tail, state, line_hash, line_len, line_is_comment)
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
          return consume_input_bytes.go(bytes.tail, state, line_hash, line_len, line_is_comment)

def encode_state(keys: List(u24)) -> List(u24):
  # List of lines (bytes) flattened at the end.
  fold keys with chunks=[]:
    case List/Nil:
      return List/flatten(List/reverse(chunks))
    case List/Cons:
      digits = u24/to_string(keys.head)
      line = List/concat(String/encode_ascii(digits), ['\n'])
      return keys.tail(List/Cons(line, chunks))

def save_state(path: String, keys: List(u24)) -> IO(u24):
  with IO:
    bytes = encode_state(keys)
    res <- IO/FS/write_file(path, bytes)
    match res:
      case Result/Ok:
        return wrap(1)
      case Result/Err:
        return wrap(0)

def main() -> IO((u24, u24)):
  with IO:
    state <- load_state(STATE_PATH)
    res <- IO/FS/read_to_end(IO/FS/STDIN)
    match res:
      case Result/Err:
        state2 = state
        match state2:
          case State/State:
            _ <- save_state(STATE_PATH, state2.keys)
            return wrap((state2.new, state2.total))
      case Result/Ok:
        bytes = res.val
        state2 = consume_input_bytes(bytes, state)
        match state2:
          case State/State:
            _ <- save_state(STATE_PATH, state2.keys)
            return wrap((state2.new, state2.total))
