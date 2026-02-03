"""Parser for .loop and .vertex DSL files.

Transforms token stream into AST.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .ast import (
    Boundary,
    BoundaryAfter,
    BoundaryEvery,
    BoundaryWhen,
    Coerce,
    Duration,
    FoldAvg,
    FoldBy,
    FoldCollect,
    FoldCount,
    FoldDecl,
    FoldLatest,
    FoldMax,
    FoldMin,
    FoldOp,
    FoldSum,
    FoldWindow,
    LoopDef,
    LoopFile,
    LStrip,
    ParseStep,
    Pick,
    Replace,
    RStrip,
    Select,
    Skip,
    SourceEntry,
    SourceParams,
    Split,
    Strip,
    TemplateSource,
    Transform,
    TransformOp,
    Trigger,
    VertexFile,
)
from .errors import Location, ParseError
from .lexer import Token, TokenType, tokenize

if TYPE_CHECKING:
    from typing import Literal


class Parser:
    """Parser for DSL files."""

    def __init__(self, tokens: list[Token], path: Path | None = None):
        self.tokens = tokens
        self.path = path
        self.pos = 0

    def peek(self, n: int = 0) -> Token:
        """Peek at token at current position + n."""
        pos = self.pos + n
        if pos >= len(self.tokens):
            return self.tokens[-1]  # EOF
        return self.tokens[pos]

    def advance(self) -> Token:
        """Advance and return current token."""
        token = self.peek()
        self.pos += 1
        return token

    def at(self, *types: TokenType) -> bool:
        """Check if current token is one of the given types."""
        return self.peek().type in types

    def expect(self, token_type: TokenType, context: str = "") -> Token:
        """Expect and consume a token of the given type."""
        token = self.peek()
        if token.type != token_type:
            msg = f"Expected {token_type.name}"
            if context:
                msg += f" {context}"
            msg += f", got {token.type.name}"
            raise ParseError(msg, token.location)
        return self.advance()

    def skip_newlines(self) -> None:
        """Skip any newline tokens."""
        while self.at(TokenType.NEWLINE):
            self.advance()

    def parse_key_value(self) -> tuple[str, Token, list[Token]]:
        """Parse a key: value line. Returns (key, first_value_token, rest_tokens)."""
        key_token = self.expect(TokenType.IDENTIFIER, "for key")
        self.expect(TokenType.COLON)

        # Collect all tokens until newline
        value_tokens = []
        while not self.at(TokenType.NEWLINE, TokenType.EOF, TokenType.INDENT, TokenType.DEDENT):
            value_tokens.append(self.advance())

        if not value_tokens:
            raise ParseError(f"Expected value for {key_token.value}", key_token.location)

        return key_token.value, value_tokens[0], value_tokens[1:]

    def parse_duration(self, token: Token) -> Duration:
        """Parse a duration token."""
        if token.type == TokenType.DURATION:
            return Duration.parse(token.value)
        raise ParseError(f"Expected duration, got {token.type.name}", token.location)

    def parse_string(self, token: Token) -> str:
        """Parse a string value (quoted or bare identifier)."""
        if token.type == TokenType.STRING:
            return token.value
        if token.type == TokenType.IDENTIFIER:
            return token.value
        raise ParseError(f"Expected string, got {token.type.name}", token.location)

    def parse_trigger(self) -> Trigger:
        """Parse a trigger value: single kind or [kind1, kind2, ...] list."""
        if self.at(TokenType.LBRACKET):
            # List of kinds: [minute, hour]
            self.advance()  # consume [
            kinds = []
            while not self.at(TokenType.RBRACKET, TokenType.NEWLINE, TokenType.EOF):
                kind_token = self.expect(TokenType.IDENTIFIER, "for trigger kind")
                kinds.append(kind_token.value)
                if self.at(TokenType.COMMA):
                    self.advance()
                elif not self.at(TokenType.RBRACKET):
                    break
            self.expect(TokenType.RBRACKET, "to close trigger list")
            if not kinds:
                raise ParseError("Empty trigger list", self.peek().location)
            return Trigger.multi(kinds)
        else:
            # Single kind: minute
            kind_token = self.expect(TokenType.IDENTIFIER, "for trigger kind")
            return Trigger.single(kind_token.value)

    # -------------------------------------------------------------------------
    # Parse section parsing (.loop files)
    # -------------------------------------------------------------------------

    def parse_transform_op(self) -> TransformOp:
        """Parse a single transform operation."""
        token = self.peek()

        if token.type == TokenType.STRIP:
            self.advance()
            chars_token = self.advance()
            return Strip(self.parse_string(chars_token))

        if token.type == TokenType.LSTRIP:
            self.advance()
            chars_token = self.advance()
            return LStrip(self.parse_string(chars_token))

        if token.type == TokenType.RSTRIP:
            self.advance()
            chars_token = self.advance()
            return RStrip(self.parse_string(chars_token))

        if token.type == TokenType.REPLACE:
            self.advance()
            old_token = self.advance()
            new_token = self.advance()
            return Replace(self.parse_string(old_token), self.parse_string(new_token))

        if token.type == TokenType.INT:
            self.advance()
            return Coerce("int")

        if token.type == TokenType.FLOAT:
            self.advance()
            return Coerce("float")

        if token.type == TokenType.BOOL:
            self.advance()
            return Coerce("bool")

        if token.type == TokenType.STR:
            self.advance()
            return Coerce("str")

        raise ParseError(f"Unknown transform operation: {token.value}", token.location)

    def parse_transform_chain(self) -> tuple[TransformOp, ...]:
        """Parse a chain of transform ops separated by |."""
        ops = [self.parse_transform_op()]
        while self.at(TokenType.PIPE):
            self.advance()
            ops.append(self.parse_transform_op())
        return tuple(ops)

    def parse_parse_step(self) -> ParseStep:
        """Parse a single parse step."""
        token = self.peek()

        # skip <pattern>
        if token.type == TokenType.SKIP:
            self.advance()
            pattern_token = self.advance()
            return Skip(pattern_token.value)

        # split [delimiter]
        if token.type == TokenType.SPLIT:
            self.advance()
            delimiter = None
            if self.at(TokenType.STRING, TokenType.IDENTIFIER):
                delimiter = self.parse_string(self.advance())
            return Split(delimiter)

        # pick 0, 4, 8 [-> name1, name2, name3]
        if token.type == TokenType.PICK:
            self.advance()
            indices = []
            # Parse indices
            while self.at(TokenType.NUMBER):
                indices.append(int(self.advance().value))
                if self.at(TokenType.COMMA):
                    self.advance()
                elif self.at(TokenType.ARROW):
                    break
                else:
                    break

            names = None
            if self.at(TokenType.ARROW):
                self.advance()
                names = []
                while self.at(TokenType.IDENTIFIER):
                    names.append(self.advance().value)
                    if self.at(TokenType.COMMA):
                        self.advance()
                    else:
                        break
                if len(names) != len(indices):
                    raise ParseError(
                        f"pick: {len(indices)} indices but {len(names)} names",
                        token.location,
                    )

            return Pick(tuple(indices), tuple(names) if names else None)

        # select Field1, Field2, Field3 (for ndjson format)
        if token.type == TokenType.SELECT:
            self.advance()
            fields = []
            while self.at(TokenType.IDENTIFIER, TokenType.STRING):
                fields.append(self.parse_string(self.advance()))
                if self.at(TokenType.COMMA):
                    self.advance()
                else:
                    break
            if not fields:
                raise ParseError("select requires at least one field name", token.location)
            return Select(tuple(fields))

        # field: transform chain
        if token.type == TokenType.IDENTIFIER:
            field = self.advance().value
            if self.at(TokenType.COLON):
                self.advance()
                ops = self.parse_transform_chain()
                return Transform(field, ops)
            raise ParseError(f"Expected ':' after field name in transform", token.location)

        raise ParseError(f"Unknown parse step: {token.value}", token.location)

    def parse_parse_block(self) -> tuple[ParseStep, ...]:
        """Parse a parse: block."""
        steps = []
        self.expect(TokenType.INDENT)
        while not self.at(TokenType.DEDENT, TokenType.EOF):
            self.skip_newlines()
            if self.at(TokenType.DEDENT, TokenType.EOF):
                break
            steps.append(self.parse_parse_step())
            self.skip_newlines()
        if self.at(TokenType.DEDENT):
            self.advance()
        return tuple(steps)

    # -------------------------------------------------------------------------
    # Fold section parsing (.vertex files)
    # -------------------------------------------------------------------------

    def parse_fold_op(self, target: str) -> FoldOp:
        """Parse a fold operation."""
        token = self.peek()

        # by <field>
        if token.type == TokenType.BY:
            self.advance()
            field_token = self.expect(TokenType.IDENTIFIER, "for 'by' field")
            return FoldBy(field_token.value)

        # +1
        if token.type == TokenType.PLUS:
            self.advance()
            if self.at(TokenType.NUMBER):
                num = self.advance()
                if num.value == "1":
                    return FoldCount()
                # + field (sum)
                raise ParseError("Use '+ <field>' for sum, '+1' for count", token.location)
            # + <field>
            if self.at(TokenType.IDENTIFIER):
                field = self.advance().value
                return FoldSum(field)
            raise ParseError("Expected field name or '1' after '+'", token.location)

        # latest
        if token.type == TokenType.LATEST:
            self.advance()
            return FoldLatest()

        # collect <n>
        if token.type == TokenType.COLLECT:
            self.advance()
            n_token = self.expect(TokenType.NUMBER, "for collect count")
            return FoldCollect(int(n_token.value))

        # max <field>
        if token.type == TokenType.MAX:
            self.advance()
            field_token = self.expect(TokenType.IDENTIFIER, "for max field")
            return FoldMax(field_token.value)

        # min <field>
        if token.type == TokenType.MIN:
            self.advance()
            field_token = self.expect(TokenType.IDENTIFIER, "for min field")
            return FoldMin(field_token.value)

        # avg <field>
        if token.type == TokenType.AVG:
            self.advance()
            field_token = self.expect(TokenType.IDENTIFIER, "for avg field")
            return FoldAvg(field_token.value)

        # window <size> <field>
        if token.type == TokenType.WINDOW:
            self.advance()
            size_token = self.expect(TokenType.NUMBER, "for window size")
            field_token = self.expect(TokenType.IDENTIFIER, "for window field")
            return FoldWindow(field_token.value, int(size_token.value))

        raise ParseError(f"Unknown fold operation: {token.value}", token.location)

    def parse_fold_block(self) -> tuple[FoldDecl, ...]:
        """Parse a fold: block."""
        decls = []
        self.expect(TokenType.INDENT)
        while not self.at(TokenType.DEDENT, TokenType.EOF):
            self.skip_newlines()
            if self.at(TokenType.DEDENT, TokenType.EOF):
                break

            # target: op
            target_token = self.expect(TokenType.IDENTIFIER, "for fold target")
            self.expect(TokenType.COLON)
            op = self.parse_fold_op(target_token.value)
            decls.append(FoldDecl(target_token.value, op))
            self.skip_newlines()

        if self.at(TokenType.DEDENT):
            self.advance()
        return tuple(decls)

    # -------------------------------------------------------------------------
    # Boundary parsing
    # -------------------------------------------------------------------------

    def parse_boundary(self) -> Boundary:
        """Parse a boundary declaration."""
        # when <kind>
        if self.at(TokenType.WHEN):
            self.advance()
            kind_token = self.expect(TokenType.IDENTIFIER, "for boundary kind")
            return BoundaryWhen(kind_token.value)

        # after <N> or every <N> (as identifiers to avoid conflict with top-level keys)
        if self.at(TokenType.IDENTIFIER):
            keyword = self.peek().value
            if keyword == "after":
                self.advance()
                count_token = self.expect(TokenType.NUMBER, "for count")
                return BoundaryAfter(int(count_token.value))
            elif keyword == "every":
                self.advance()
                count_token = self.expect(TokenType.NUMBER, "for count")
                return BoundaryEvery(int(count_token.value))

        raise ParseError(
            "Expected 'when <kind>', 'after <N>', or 'every <N>' for boundary",
            self.peek().location,
        )

    # -------------------------------------------------------------------------
    # Loop definition parsing (.vertex files)
    # -------------------------------------------------------------------------

    def parse_loop_def(self) -> LoopDef:
        """Parse a loop definition within loops: block."""
        folds: tuple[FoldDecl, ...] = ()
        boundary: Boundary | None = None

        self.expect(TokenType.INDENT)
        while not self.at(TokenType.DEDENT, TokenType.EOF):
            self.skip_newlines()
            if self.at(TokenType.DEDENT, TokenType.EOF):
                break

            key_token = self.expect(TokenType.IDENTIFIER)
            self.expect(TokenType.COLON)

            if key_token.value == "fold":
                self.skip_newlines()
                folds = self.parse_fold_block()
            elif key_token.value == "boundary":
                boundary = self.parse_boundary()
                self.skip_newlines()
            else:
                raise ParseError(f"Unknown loop field: {key_token.value}", key_token.location)

        if self.at(TokenType.DEDENT):
            self.advance()

        return LoopDef(folds=folds, boundary=boundary)

    def parse_loops_block(self) -> dict[str, LoopDef]:
        """Parse the loops: block."""
        loops = {}
        self.expect(TokenType.INDENT)
        while not self.at(TokenType.DEDENT, TokenType.EOF):
            self.skip_newlines()
            if self.at(TokenType.DEDENT, TokenType.EOF):
                break

            # loop_name:
            name_token = self.expect(TokenType.IDENTIFIER, "for loop name")
            self.expect(TokenType.COLON)
            self.skip_newlines()
            loops[name_token.value] = self.parse_loop_def()

        if self.at(TokenType.DEDENT):
            self.advance()
        return loops

    # -------------------------------------------------------------------------
    # Routes parsing (.vertex files)
    # -------------------------------------------------------------------------

    def parse_routes_block(self) -> dict[str, str]:
        """Parse the routes: block."""
        routes = {}
        self.expect(TokenType.INDENT)
        while not self.at(TokenType.DEDENT, TokenType.EOF):
            self.skip_newlines()
            if self.at(TokenType.DEDENT, TokenType.EOF):
                break

            # kind: loop_name
            kind_token = self.expect(TokenType.IDENTIFIER, "for route kind")
            self.expect(TokenType.COLON)
            loop_token = self.expect(TokenType.IDENTIFIER, "for route target")
            routes[kind_token.value] = loop_token.value
            self.skip_newlines()

        if self.at(TokenType.DEDENT):
            self.advance()
        return routes

    # -------------------------------------------------------------------------
    # Path list parsing (.vertex files)
    # -------------------------------------------------------------------------

    def parse_path_list(self) -> tuple[Path, ...]:
        """Parse a list of paths (used for vertices:).

        Handles paths like:
          - ./foo.vertex           (single token)
          - timers/*.loop          (identifier + glob)
          - ./sub/dir/*.vertex     (glob with leading ./)
        """
        paths = []
        self.expect(TokenType.INDENT)
        while not self.at(TokenType.DEDENT, TokenType.EOF):
            self.skip_newlines()
            if self.at(TokenType.DEDENT, TokenType.EOF):
                break

            # - path
            self.expect(TokenType.DASH)

            # Collect consecutive path-like tokens until newline/dedent
            path_parts = []
            while self.at(TokenType.GLOB, TokenType.IDENTIFIER, TokenType.STRING):
                path_parts.append(self.advance().value)

            if not path_parts:
                raise ParseError(f"Expected path, got {self.peek().type.name}", self.peek().location)

            # Join parts into full path
            paths.append(Path("".join(path_parts)))
            self.skip_newlines()

        if self.at(TokenType.DEDENT):
            self.advance()
        return tuple(paths)

    # -------------------------------------------------------------------------
    # Sources list parsing (.vertex files) - handles both paths and templates
    # -------------------------------------------------------------------------

    def parse_sources_block(self) -> tuple[SourceEntry, ...]:
        """Parse a sources: block with paths and/or template sources.

        Handles:
          - ./foo.loop                          (simple path)
          - template: stacks/status.loop        (template source)
              with:
                - kind: infra
                  host: 192.168.1.30
              loop:
                fold:
                  containers: collect 50
                boundary: when ${kind}.complete
        """
        sources: list[SourceEntry] = []
        self.expect(TokenType.INDENT)
        while not self.at(TokenType.DEDENT, TokenType.EOF):
            self.skip_newlines()
            if self.at(TokenType.DEDENT, TokenType.EOF):
                break

            # - path or - template:
            self.expect(TokenType.DASH)

            if self.at(TokenType.TEMPLATE):
                # Template source
                self.advance()  # consume 'template'
                self.expect(TokenType.COLON)

                # Collect path tokens
                path_parts = []
                while self.at(TokenType.GLOB, TokenType.IDENTIFIER, TokenType.STRING):
                    path_parts.append(self.advance().value)
                if not path_parts:
                    raise ParseError("Expected template path", self.peek().location)
                template_path = Path("".join(path_parts))

                self.skip_newlines()

                # Parse with: and optional loop: blocks
                params: list[SourceParams] = []
                loop_def: LoopDef | None = None

                if self.at(TokenType.INDENT):
                    self.advance()  # consume INDENT
                    while not self.at(TokenType.DEDENT, TokenType.EOF):
                        self.skip_newlines()
                        if self.at(TokenType.DEDENT, TokenType.EOF):
                            break

                        # Handle 'with' and 'loop' keywords (they're lexed as keywords, not identifiers)
                        if self.at(TokenType.WITH):
                            self.advance()  # consume 'with'
                            self.expect(TokenType.COLON)
                            self.skip_newlines()
                            params = self.parse_with_block()
                        elif self.at(TokenType.LOOP):
                            self.advance()  # consume 'loop'
                            self.expect(TokenType.COLON)
                            self.skip_newlines()
                            loop_def = self.parse_loop_def()
                        else:
                            raise ParseError(
                                f"Unknown template block (expected 'with' or 'loop'), got {self.peek().type.name}",
                                self.peek().location,
                            )

                    if self.at(TokenType.DEDENT):
                        self.advance()

                if not params:
                    raise ParseError("Template source requires 'with:' block", self.peek().location)

                sources.append(
                    TemplateSource(
                        template=template_path,
                        params=tuple(params),
                        loop=loop_def,
                    )
                )
            else:
                # Simple path
                path_parts = []
                while self.at(TokenType.GLOB, TokenType.IDENTIFIER, TokenType.STRING):
                    path_parts.append(self.advance().value)

                if not path_parts:
                    raise ParseError(f"Expected path, got {self.peek().type.name}", self.peek().location)

                sources.append(Path("".join(path_parts)))
                self.skip_newlines()

        if self.at(TokenType.DEDENT):
            self.advance()
        return tuple(sources)

    def parse_param_value(self) -> str:
        """Parse a parameter value (can be string, identifier, number, or IP-like)."""
        # Collect all tokens until newline, treating them as a single value
        # This handles IP addresses like 192.168.1.30 which are lexed as multiple tokens
        parts = []
        while not self.at(TokenType.NEWLINE, TokenType.EOF, TokenType.DEDENT):
            token = self.advance()
            if token.type == TokenType.STRING:
                parts.append(token.value)
            elif token.type == TokenType.IDENTIFIER:
                parts.append(token.value)
            elif token.type == TokenType.NUMBER:
                parts.append(token.value)
            elif token.type == TokenType.GLOB:
                parts.append(token.value)
            else:
                # Put the unexpected token back and stop
                self.pos -= 1
                break
        return "".join(parts)

    def parse_with_block(self) -> list[SourceParams]:
        """Parse a with: block containing parameter rows.

        with:
          - kind: infra
            host: 192.168.1.30
          - kind: media
            host: 192.168.1.40
        """
        params: list[SourceParams] = []
        self.expect(TokenType.INDENT)
        while not self.at(TokenType.DEDENT, TokenType.EOF):
            self.skip_newlines()
            if self.at(TokenType.DEDENT, TokenType.EOF):
                break

            # - key: value pairs
            self.expect(TokenType.DASH)

            # First key: value on same line as dash
            row: dict[str, str] = {}
            key_token = self.expect(TokenType.IDENTIFIER, "for parameter key")
            self.expect(TokenType.COLON)
            row[key_token.value] = self.parse_param_value()
            self.skip_newlines()

            # Additional key: value pairs at same indentation (within this item)
            if self.at(TokenType.INDENT):
                self.advance()
                while not self.at(TokenType.DEDENT, TokenType.EOF):
                    self.skip_newlines()
                    if self.at(TokenType.DEDENT, TokenType.EOF):
                        break

                    key_token = self.expect(TokenType.IDENTIFIER, "for parameter key")
                    self.expect(TokenType.COLON)
                    row[key_token.value] = self.parse_param_value()
                    self.skip_newlines()

                if self.at(TokenType.DEDENT):
                    self.advance()

            params.append(SourceParams(values=row))

        if self.at(TokenType.DEDENT):
            self.advance()
        return params

    # -------------------------------------------------------------------------
    # Top-level file parsing
    # -------------------------------------------------------------------------

    def parse_loop_file(self) -> LoopFile:
        """Parse a .loop file."""
        source: str | None = None
        kind: str | None = None
        observer: str | None = None
        every: Duration | None = None
        on: Trigger | None = None
        format_: Literal["lines", "json", "ndjson", "blob"] = "lines"
        timeout = Duration(60000)
        env: dict[str, str] | None = None
        parse_steps: tuple[ParseStep, ...] = ()

        while not self.at(TokenType.EOF):
            self.skip_newlines()
            if self.at(TokenType.EOF):
                break

            key_token = self.expect(TokenType.IDENTIFIER, "for config key")
            self.expect(TokenType.COLON)

            key = key_token.value
            if key == "source":
                # Collect rest of line as command, preserving punctuation spacing
                parts = []
                prev_was_punct = False
                while not self.at(TokenType.NEWLINE, TokenType.EOF):
                    token = self.advance()
                    is_punct = token.type in (TokenType.COMMA, TokenType.PIPE)
                    # No space before/after punctuation
                    if parts and not prev_was_punct and not is_punct:
                        parts.append(" ")
                    # Re-wrap STRING tokens in their original quotes
                    if token.type == TokenType.STRING and token.quote_char:
                        parts.append(f"{token.quote_char}{token.value}{token.quote_char}")
                    else:
                        parts.append(token.value)
                    prev_was_punct = is_punct
                source = "".join(parts)
            elif key == "kind":
                source_token = self.advance()
                kind = self.parse_string(source_token)
            elif key == "observer":
                obs_token = self.advance()
                observer = self.parse_string(obs_token)
            elif key == "every":
                every = self.parse_duration(self.advance())
            elif key == "on":
                on = self.parse_trigger()
            elif key == "format":
                fmt_token = self.advance()
                fmt_value = self.parse_string(fmt_token)
                if fmt_value not in ("lines", "json", "ndjson", "blob"):
                    raise ParseError(
                        f"format must be 'lines', 'json', 'ndjson', or 'blob', got {fmt_value!r}",
                        fmt_token.location,
                    )
                format_ = fmt_value  # type: ignore
            elif key == "timeout":
                timeout = self.parse_duration(self.advance())
            elif key == "parse":
                self.skip_newlines()
                parse_steps = self.parse_parse_block()
            elif key == "env":
                # TODO: parse env dict
                raise ParseError("env not yet implemented", key_token.location)
            else:
                raise ParseError(f"Unknown config key: {key}", key_token.location)

            self.skip_newlines()

        # Validate required fields
        if kind is None:
            raise ParseError("Missing required field: kind", Location(self.path, 1))
        if observer is None:
            raise ParseError("Missing required field: observer", Location(self.path, 1))
        # source is required unless every: is present (pure timer loop)
        if source is None and every is None:
            raise ParseError(
                "Missing required field: source (or use every: for pure timer loop)",
                Location(self.path, 1),
            )

        return LoopFile(
            kind=kind,
            observer=observer,
            source=source,
            every=every,
            on=on,
            format=format_,
            timeout=timeout,
            env=env,
            parse=parse_steps,
            path=self.path,
        )

    def parse_vertex_file(self) -> VertexFile:
        """Parse a .vertex file."""
        name: str | None = None
        store: Path | None = None
        discover: str | None = None
        sources: tuple[SourceEntry, ...] | None = None
        vertices: tuple[Path, ...] | None = None
        loops: dict[str, LoopDef] = {}
        routes: dict[str, str] | None = None
        emit: str | None = None

        while not self.at(TokenType.EOF):
            self.skip_newlines()
            if self.at(TokenType.EOF):
                break

            key_token = self.expect(TokenType.IDENTIFIER, "for config key")
            self.expect(TokenType.COLON)

            key = key_token.value
            if key == "name":
                name_token = self.advance()
                name = self.parse_string(name_token)
            elif key == "store":
                path_token = self.advance()
                store = Path(path_token.value)
            elif key == "discover":
                glob_token = self.advance()
                discover = glob_token.value
            elif key == "sources":
                self.skip_newlines()
                sources = self.parse_sources_block()
            elif key == "vertices":
                self.skip_newlines()
                vertices = self.parse_path_list()
            elif key == "loops":
                self.skip_newlines()
                loops = self.parse_loops_block()
            elif key == "routes":
                self.skip_newlines()
                routes = self.parse_routes_block()
            elif key == "emit":
                emit_token = self.advance()
                emit = self.parse_string(emit_token)
            else:
                raise ParseError(f"Unknown config key: {key}", key_token.location)

            self.skip_newlines()

        # Validate required fields
        if name is None:
            raise ParseError("Missing required field: name", Location(self.path, 1))

        # loops: is required unless template sources with loop: blocks provide specs
        has_template_loop_specs = sources and any(
            isinstance(s, TemplateSource) and s.loop is not None for s in sources
        )
        if not loops and not has_template_loop_specs:
            raise ParseError("Missing required field: loops", Location(self.path, 1))

        return VertexFile(
            name=name,
            loops=loops,
            store=store,
            discover=discover,
            sources=sources,
            vertices=vertices,
            routes=routes,
            emit=emit,
            path=self.path,
        )


def parse_loop(text: str, path: Path | None = None) -> LoopFile:
    """Parse a .loop file from text."""
    tokens = tokenize(text, path)
    parser = Parser(tokens, path)
    return parser.parse_loop_file()


def parse_vertex(text: str, path: Path | None = None) -> VertexFile:
    """Parse a .vertex file from text."""
    tokens = tokenize(text, path)
    parser = Parser(tokens, path)
    return parser.parse_vertex_file()


def parse_loop_file(path: Path) -> LoopFile:
    """Parse a .loop file from path."""
    text = path.read_text()
    return parse_loop(text, path)


def parse_vertex_file(path: Path) -> VertexFile:
    """Parse a .vertex file from path."""
    text = path.read_text()
    return parse_vertex(text, path)
