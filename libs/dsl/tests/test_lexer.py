"""Tests for DSL lexer."""

import pytest

from dsl import LexError, TokenType, tokenize


class TestTokenize:
    """Basic tokenization tests."""

    def test_empty(self):
        tokens = tokenize("")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF

    def test_comment_only(self):
        tokens = tokenize("# just a comment")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF

    def test_key_value(self):
        tokens = tokenize("source: echo hello")
        types = [t.type for t in tokens]
        assert TokenType.IDENTIFIER in types
        assert TokenType.COLON in types

    def test_string_quoted(self):
        tokens = tokenize('strip "%"')
        # Find the string token
        strings = [t for t in tokens if t.type == TokenType.STRING]
        assert len(strings) == 1
        assert strings[0].value == "%"

    def test_string_preserves_quote_char(self):
        """STRING tokens track their original quote character."""
        # Double quotes
        tokens = tokenize('echo "hello"')
        strings = [t for t in tokens if t.type == TokenType.STRING]
        assert len(strings) == 1
        assert strings[0].value == "hello"
        assert strings[0].quote_char == '"'

        # Single quotes
        tokens = tokenize("echo 'world'")
        strings = [t for t in tokens if t.type == TokenType.STRING]
        assert len(strings) == 1
        assert strings[0].value == "world"
        assert strings[0].quote_char == "'"

    def test_duration(self):
        tokens = tokenize("every: 5s")
        durations = [t for t in tokens if t.type == TokenType.DURATION]
        assert len(durations) == 1
        assert durations[0].value == "5s"

    def test_duration_compound(self):
        tokens = tokenize("timeout: 1h30m")
        durations = [t for t in tokens if t.type == TokenType.DURATION]
        assert len(durations) == 1
        assert durations[0].value == "1h30m"

    def test_number(self):
        tokens = tokenize("pick 0, 4, 8")
        numbers = [t for t in tokens if t.type == TokenType.NUMBER]
        assert len(numbers) == 3
        assert [n.value for n in numbers] == ["0", "4", "8"]

    def test_arrow(self):
        tokens = tokenize("pick 0 -> name")
        arrows = [t for t in tokens if t.type == TokenType.ARROW]
        assert len(arrows) == 1

    def test_pipe(self):
        tokens = tokenize("strip | int")
        pipes = [t for t in tokens if t.type == TokenType.PIPE]
        assert len(pipes) == 1

    def test_glob(self):
        tokens = tokenize("discover: ./**/*.loop")
        globs = [t for t in tokens if t.type == TokenType.GLOB]
        assert len(globs) == 1
        assert globs[0].value == "./**/*.loop"

    def test_brackets(self):
        """Test bracket tokens for list syntax."""
        tokens = tokenize("on: [minute, hour]")
        lbrackets = [t for t in tokens if t.type == TokenType.LBRACKET]
        rbrackets = [t for t in tokens if t.type == TokenType.RBRACKET]
        assert len(lbrackets) == 1
        assert len(rbrackets) == 1

    def test_at_symbol_in_identifier(self):
        """Test @ symbol is allowed in identifiers (e.g., SSH user@host)."""
        tokens = tokenize("source: ssh deploy@192.168.1.30 cmd")
        identifiers = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        values = [t.value for t in identifiers]
        assert "deploy@192.168.1.30" in values

    def test_at_symbol_with_port(self):
        """Test @ with colon for port numbers."""
        tokens = tokenize("source: curl user@host:8080")
        identifiers = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        # user@host gets tokenized, then : becomes COLON, then 8080 is NUMBER
        values = [t.value for t in identifiers]
        assert "user@host" in values

    def test_at_symbol_multiple(self):
        """Test multiple @ symbols in one identifier."""
        tokens = tokenize("source: echo a@b@c")
        identifiers = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        values = [t.value for t in identifiers]
        assert "a@b@c" in values

    def test_at_symbol_email(self):
        """Test email-like patterns."""
        tokens = tokenize("source: echo user@domain.com")
        identifiers = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        values = [t.value for t in identifiers]
        assert "user@domain.com" in values


class TestIndentation:
    """Indentation handling tests."""

    def test_indent_dedent(self):
        text = """\
parse:
  skip ^Foo
  split
"""
        tokens = tokenize(text)
        types = [t.type for t in tokens]
        assert TokenType.INDENT in types
        assert TokenType.DEDENT in types

    def test_nested_indent(self):
        text = """\
loops:
  disk:
    fold:
      count: +1
"""
        tokens = tokenize(text)
        types = [t.type for t in tokens]
        # Should have multiple indents
        assert types.count(TokenType.INDENT) >= 2


class TestKeywords:
    """Keyword recognition tests."""

    def test_parse_keywords(self):
        text = "skip split pick"
        tokens = tokenize(text)
        types = [t.type for t in tokens if t.type != TokenType.NEWLINE and t.type != TokenType.EOF]
        assert TokenType.SKIP in types
        assert TokenType.SPLIT in types
        assert TokenType.PICK in types

    def test_fold_keywords(self):
        text = "by latest collect max min"
        tokens = tokenize(text)
        types = [t.type for t in tokens if t.type != TokenType.NEWLINE and t.type != TokenType.EOF]
        assert TokenType.BY in types
        assert TokenType.LATEST in types
        assert TokenType.COLLECT in types
        assert TokenType.MAX in types
        assert TokenType.MIN in types

    def test_transform_keywords(self):
        text = "strip lstrip rstrip replace int float bool str"
        tokens = tokenize(text)
        types = [t.type for t in tokens if t.type != TokenType.NEWLINE and t.type != TokenType.EOF]
        assert TokenType.STRIP in types
        assert TokenType.LSTRIP in types
        assert TokenType.RSTRIP in types
        assert TokenType.REPLACE in types
        assert TokenType.INT in types
        assert TokenType.FLOAT in types
        assert TokenType.BOOL in types
        assert TokenType.STR in types


class TestErrors:
    """Error handling tests."""

    def test_unterminated_string(self):
        with pytest.raises(LexError, match="Unterminated string"):
            tokenize('"hello')

    def test_inconsistent_indent(self):
        # Dedenting to 1 space when we came from 0 -> 2 is inconsistent
        text = """\
parse:
  skip foo
 split
"""
        with pytest.raises(LexError, match="Inconsistent indentation"):
            tokenize(text)
