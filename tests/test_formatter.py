"""Tests for the .http file formatter."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from click.testing import CliRunner

from fling.cli import main
from fling.core.formatter import format_http_string

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# format_http_string
# ---------------------------------------------------------------------------


class TestFormatBasic:
    """Basic formatting tests."""

    def test_simple_get(self) -> None:
        content = "GET https://example.com/users\n"
        result = format_http_string(content)
        assert result == "GET https://example.com/users\n"

    def test_trailing_whitespace_stripped(self) -> None:
        content = "GET https://example.com/users   \n"
        result = format_http_string(content)
        assert "   \n" not in result
        assert result.endswith("\n")

    def test_ensures_trailing_newline(self) -> None:
        content = "GET https://example.com/users"
        result = format_http_string(content)
        assert result.endswith("\n")

    def test_preserves_http_version(self) -> None:
        content = "GET https://example.com/users HTTP/1.1\n"
        result = format_http_string(content)
        assert "HTTP/1.1" in result


class TestFormatVariables:
    """Variable formatting tests."""

    def test_variables_sorted_to_top(self) -> None:
        content = dedent("""\
            @host = example.com
            @path = users

            ###

            GET https://{{host}}/{{path}}
        """)
        result = format_http_string(content)
        lines = result.strip().splitlines()
        # Variables should come first
        assert lines[0].startswith("@host")
        assert lines[1].startswith("@path")

    def test_blank_line_after_variables(self) -> None:
        content = dedent("""\
            @baseUrl = https://example.com

            ###

            GET {{baseUrl}}/users
        """)
        result = format_http_string(content)
        lines = result.splitlines()
        # After variables there should be a blank line
        assert lines[0].startswith("@baseUrl")
        assert lines[1] == ""


class TestFormatHeaders:
    """Header alignment tests."""

    def test_headers_aligned(self) -> None:
        content = dedent("""\
            GET https://example.com/users
            Content-Type: application/json
            Authorization: Bearer token123
            X-Custom: value
        """)
        result = format_http_string(content)
        lines = result.strip().splitlines()
        # Skip request line
        header_lines = [line for line in lines[1:] if ":" in line]
        # All colons should be at the same position
        colon_positions = [line.index(":") for line in header_lines]
        assert len(set(colon_positions)) == 1, f"Colons not aligned: {colon_positions}"

    def test_single_header_no_extra_padding(self) -> None:
        content = dedent("""\
            GET https://example.com/users
            Accept: application/json
        """)
        result = format_http_string(content)
        assert "Accept: application/json" in result


class TestFormatSeparators:
    """Request separator formatting tests."""

    def test_separator_between_requests(self) -> None:
        content = dedent("""\
            GET https://example.com/a
            ###
            GET https://example.com/b
        """)
        result = format_http_string(content)
        assert "\n###\n" in result

    def test_blank_lines_around_separator(self) -> None:
        content = dedent("""\
            GET https://example.com/a
            ###
            GET https://example.com/b
        """)
        result = format_http_string(content)
        # Should have blank line before ### and after ###
        lines = result.splitlines()
        sep_idx = lines.index("###")
        # Line before separator should be the last line of the request (or blank)
        # Line after separator should be blank
        assert lines[sep_idx + 1] == ""


class TestFormatMetadata:
    """Metadata comment formatting tests."""

    def test_metadata_canonical_order(self) -> None:
        content = dedent("""\
            # @disabled
            # @name myRequest
            # @timeout 5000
            # @no-redirect
            GET https://example.com/users
        """)
        result = format_http_string(content)
        lines = result.strip().splitlines()
        # @name should come first, then @no-redirect, then @timeout, then @disabled
        meta_lines = [line for line in lines if line.startswith("# @")]
        assert "# @name myRequest" in meta_lines[0]
        assert any("@no-redirect" in line for line in meta_lines)
        assert any("@timeout 5000" in line for line in meta_lines)
        assert any("@disabled" in line for line in meta_lines)

    def test_refs_emitted(self) -> None:
        content = dedent("""\
            # @name getUsers
            # @ref login
            GET https://example.com/users
            Authorization: Bearer {{login.response.body.$.token}}
        """)
        result = format_http_string(content)
        assert "# @ref login" in result


class TestFormatBody:
    """Body formatting tests."""

    def test_blank_line_before_body(self) -> None:
        content = dedent("""\
            POST https://example.com/users
            Content-Type: application/json

            {"name": "John"}
        """)
        result = format_http_string(content)
        lines = result.splitlines()
        # Find body content
        body_idx = next(i for i, line in enumerate(lines) if line.startswith("{"))
        # Line before body should be blank
        assert lines[body_idx - 1] == ""

    def test_file_ref_body(self) -> None:
        content = dedent("""\
            POST https://example.com/users
            Content-Type: application/json

            < ./payload.json
        """)
        result = format_http_string(content)
        assert "< ./payload.json" in result


class TestFormatResponseHandler:
    """Response handler formatting tests."""

    def test_inline_response_handler(self) -> None:
        content = dedent("""\
            GET https://example.com/users

            > {%
            client.test("ok", function() {
                client.assert(response.status === 200);
            });
            %}
        """)
        result = format_http_string(content)
        assert "> {%" in result
        assert "%}" in result


class TestFormatIdempotent:
    """Idempotency tests — format(format(x)) == format(x)."""

    def test_idempotent_simple(self) -> None:
        content = "GET https://example.com/users\n"
        first = format_http_string(content)
        second = format_http_string(first)
        assert first == second

    def test_idempotent_complex(self) -> None:
        content = dedent("""\
            @host = example.com

            ###

            # @name login
            POST https://{{host}}/auth
            Content-Type: application/json

            {"user": "admin"}

            ###

            # @name getUsers
            # @ref login
            GET https://{{host}}/users
            Authorization: Bearer {{login.response.body.$.token}}
        """)
        first = format_http_string(content)
        second = format_http_string(first)
        assert first == second

    def test_idempotent_fixture_simple(self) -> None:
        formatted = format_http_string((FIXTURES_DIR / "simple.http").read_text(encoding="utf-8"))
        again = format_http_string(formatted)
        assert formatted == again

    def test_idempotent_fixture_multiple(self) -> None:
        formatted = format_http_string((FIXTURES_DIR / "multiple.http").read_text(encoding="utf-8"))
        again = format_http_string(formatted)
        assert formatted == again

    def test_idempotent_fixture_advanced(self) -> None:
        formatted = format_http_string((FIXTURES_DIR / "advanced.http").read_text(encoding="utf-8"))
        again = format_http_string(formatted)
        assert formatted == again

    def test_idempotent_fixture_chaining(self) -> None:
        formatted = format_http_string((FIXTURES_DIR / "chaining.http").read_text(encoding="utf-8"))
        again = format_http_string(formatted)
        assert formatted == again


# ---------------------------------------------------------------------------
# CLI: fling fmt
# ---------------------------------------------------------------------------


class TestFmtCommand:
    """Tests for the 'fling fmt' CLI command."""

    def test_fmt_check_no_changes(self, tmp_path: Path) -> None:
        """File already canonical → exit 0."""
        content = "GET https://example.com/users\n"
        f = tmp_path / "test.http"
        f.write_text(content)
        # Format once to make canonical
        from fling.core.formatter import format_http_file

        canonical = format_http_file(f)
        f.write_text(canonical)

        runner = CliRunner()
        result = runner.invoke(main, ["fmt", "--check", str(f)])
        assert result.exit_code == 0

    def test_fmt_check_would_change(self, tmp_path: Path) -> None:
        """File not canonical → exit 1 with --check."""
        content = "GET   https://example.com/users  \nContent-Type:   application/json\nAccept:application/xml\n"
        f = tmp_path / "test.http"
        f.write_text(content)

        runner = CliRunner()
        result = runner.invoke(main, ["fmt", "--check", str(f)])
        assert result.exit_code == 1

    def test_fmt_inplace(self, tmp_path: Path) -> None:
        """In-place formatting rewrites the file."""
        content = "GET   https://example.com/users  \nContent-Type:   application/json\nAccept:application/xml\n"
        f = tmp_path / "test.http"
        f.write_text(content)

        runner = CliRunner()
        result = runner.invoke(main, ["fmt", str(f)])
        assert result.exit_code == 0
        assert "Formatted" in result.output

        new_content = f.read_text()
        assert new_content != content
        # Should be idempotent now
        result2 = runner.invoke(main, ["fmt", "--check", str(f)])
        assert result2.exit_code == 0

    def test_fmt_diff(self, tmp_path: Path) -> None:
        """--diff shows a unified diff."""
        content = "GET   https://example.com/users  \nContent-Type:   application/json\nAccept:application/xml\n"
        f = tmp_path / "test.http"
        f.write_text(content)

        runner = CliRunner()
        result = runner.invoke(main, ["fmt", "--diff", str(f)])
        assert result.exit_code == 0
        assert "---" in result.output or "+++" in result.output

    def test_fmt_directory(self, tmp_path: Path) -> None:
        """Formatting a directory recurses into .http files."""
        (tmp_path / "a.http").write_text("GET  https://example.com/a  \n")
        (tmp_path / "b.http").write_text("GET  https://example.com/b  \n")

        runner = CliRunner()
        result = runner.invoke(main, ["fmt", str(tmp_path)])
        assert result.exit_code == 0
        assert "Formatted" in result.output

    def test_fmt_already_formatted(self, tmp_path: Path) -> None:
        """No-op when already formatted."""
        content = "GET https://example.com/users\n"
        f = tmp_path / "test.http"
        f.write_text(content)

        runner = CliRunner()
        result = runner.invoke(main, ["fmt", str(f)])
        assert result.exit_code == 0
        assert "already formatted" in result.output.lower()
