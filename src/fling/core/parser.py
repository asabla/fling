"""Line-by-line state-machine parser for .http files."""

from __future__ import annotations

import re
from enum import Enum, auto
from pathlib import Path

from fling.core.models import (
    Header,
    HttpFile,
    HttpMethod,
    HttpRequestDefinition,
    ParseError,
    ParseResult,
    RequestBody,
    RequestMetadata,
    SourceLocation,
    VariableDefinition,
)

# Regex patterns
_REQUEST_LINE_RE = re.compile(
    r"^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS|TRACE|CONNECT)\s+"
    r"(.+?)(?:\s+(HTTP/[\d.]+))?\s*$"
)
_VARIABLE_RE = re.compile(r"^@(\w[\w\-]*)\s*=\s*(.+)$")
_HEADER_RE = re.compile(r"^([\w\-]+)\s*:\s*(.*)$")
_SEPARATOR_RE = re.compile(r"^###\s*(.*)$")
_COMMENT_RE = re.compile(r"^\s*(?:#(?!#)|//)\s*(.*)$")

# HTTP methods that can also appear without explicit method (default GET)
_HTTP_METHODS = {m.value for m in HttpMethod}


class _ParserState(Enum):
    IDLE = auto()
    META = auto()
    REQUEST_LINE = auto()
    HEADERS = auto()
    BODY = auto()
    RESPONSE_HANDLER = auto()


class HttpFileParser:
    """Parses .http file content into an HttpFile AST."""

    def __init__(self, file_path: str = "<string>") -> None:
        self._file_path = file_path
        self._state = _ParserState.IDLE
        self._line_num = 0

        # Accumulated results
        self._variables: list[VariableDefinition] = []
        self._requests: list[HttpRequestDefinition] = []
        self._errors: list[ParseError] = []

        # Current request being built
        self._current_method: HttpMethod = HttpMethod.GET
        self._current_url: str = ""
        self._current_http_version: str | None = None
        self._current_headers: list[Header] = []
        self._current_body_lines: list[str] = []
        self._current_metadata: RequestMetadata = RequestMetadata()
        self._current_comments: list[str] = []
        self._current_start_line: int = 0

    def parse(self, content: str) -> ParseResult:
        """Parse .http file content and return a ParseResult."""
        lines = content.splitlines()

        for i, line in enumerate(lines):
            self._line_num = i + 1
            self._process_line(line)

        # Finalize any in-progress request
        self._finalize_request()

        http_file = HttpFile(
            file_path=self._file_path,
            variables=self._variables,
            requests=self._requests,
        )
        return ParseResult(http_file=http_file, errors=self._errors)

    def _process_line(self, line: str) -> None:
        """Process a single line based on the current parser state."""
        if self._state == _ParserState.IDLE:
            self._process_idle(line)
        elif self._state == _ParserState.META:
            self._process_meta(line)
        elif self._state == _ParserState.REQUEST_LINE:
            self._process_request_line(line)
        elif self._state == _ParserState.HEADERS:
            self._process_headers(line)
        elif self._state == _ParserState.BODY:
            self._process_body(line)
        elif self._state == _ParserState.RESPONSE_HANDLER:
            self._process_response_handler(line)

    def _process_idle(self, line: str) -> None:
        """Process a line in IDLE state."""
        stripped = line.strip()

        # Empty line in IDLE state — skip
        if not stripped:
            return

        # Separator
        sep_match = _SEPARATOR_RE.match(stripped)
        if sep_match:
            return

        # File-level variable
        var_match = _VARIABLE_RE.match(stripped)
        if var_match:
            self._variables.append(
                VariableDefinition(
                    name=var_match.group(1),
                    value=var_match.group(2).strip(),
                    location=SourceLocation(
                        file_path=self._file_path,
                        start_line=self._line_num,
                        end_line=self._line_num,
                    ),
                )
            )
            return

        # Comment (may be metadata)
        comment_match = _COMMENT_RE.match(line)
        if comment_match:
            self._current_comments.append(comment_match.group(1))
            self._state = _ParserState.META
            if self._current_start_line == 0:
                self._current_start_line = self._line_num
            return

        # Request line
        req_match = _REQUEST_LINE_RE.match(stripped)
        if req_match:
            self._start_request(req_match)
            return

        # URL without method (implicit GET)
        if stripped.startswith("http://") or stripped.startswith("https://") or stripped.startswith("{{"):
            self._current_method = HttpMethod.GET
            self._current_url = stripped
            self._current_http_version = None
            if self._current_start_line == 0:
                self._current_start_line = self._line_num
            self._state = _ParserState.REQUEST_LINE
            return

    def _process_meta(self, line: str) -> None:
        """Process a line in META state (accumulating comments before a request)."""
        stripped = line.strip()

        # Empty line — reset to idle (comments were not before a request)
        if not stripped:
            self._current_comments = []
            self._current_start_line = 0
            self._state = _ParserState.IDLE
            return

        # More comments
        comment_match = _COMMENT_RE.match(line)
        if comment_match:
            self._current_comments.append(comment_match.group(1))
            return

        # Request line after comments
        req_match = _REQUEST_LINE_RE.match(stripped)
        if req_match:
            self._start_request(req_match)
            return

        # URL without method (implicit GET)
        if stripped.startswith("http://") or stripped.startswith("https://") or stripped.startswith("{{"):
            self._current_method = HttpMethod.GET
            self._current_url = stripped
            self._current_http_version = None
            self._state = _ParserState.REQUEST_LINE
            return

        # Variable definition (reset meta)
        var_match = _VARIABLE_RE.match(stripped)
        if var_match:
            self._current_comments = []
            self._current_start_line = 0
            self._variables.append(
                VariableDefinition(
                    name=var_match.group(1),
                    value=var_match.group(2).strip(),
                    location=SourceLocation(
                        file_path=self._file_path,
                        start_line=self._line_num,
                        end_line=self._line_num,
                    ),
                )
            )
            self._state = _ParserState.IDLE
            return

        # Unrecognized — treat as comment continuation
        self._current_comments.append(stripped)

    def _process_request_line(self, line: str) -> None:
        """Process a line after seeing the request line (expect headers or blank)."""
        stripped = line.strip()

        # Blank line → transition to body
        if not stripped:
            self._state = _ParserState.BODY
            return

        # Header
        header_match = _HEADER_RE.match(stripped)
        if header_match:
            self._current_headers.append(Header(name=header_match.group(1), value=header_match.group(2).strip()))
            self._state = _ParserState.HEADERS
            return

        # Separator → finalize request (no body)
        sep_match = _SEPARATOR_RE.match(stripped)
        if sep_match:
            self._finalize_request()
            return

        # Query parameter continuation (?key=val or &key=val)
        if stripped.startswith("?") or stripped.startswith("&"):
            self._current_url += stripped
            return

    def _process_headers(self, line: str) -> None:
        """Process a line in HEADERS state."""
        stripped = line.strip()

        # Blank line → transition to body
        if not stripped:
            self._state = _ParserState.BODY
            return

        # Another header
        header_match = _HEADER_RE.match(stripped)
        if header_match:
            self._current_headers.append(Header(name=header_match.group(1), value=header_match.group(2).strip()))
            return

        # Separator → finalize request (no body)
        sep_match = _SEPARATOR_RE.match(stripped)
        if sep_match:
            self._finalize_request()
            return

        # Query parameter continuation
        if stripped.startswith("?") or stripped.startswith("&"):
            self._current_url += stripped
            return

    def _process_body(self, line: str) -> None:
        """Process a line in BODY state."""
        stripped = line.strip()

        # Separator → finalize request
        sep_match = _SEPARATOR_RE.match(stripped)
        if sep_match:
            self._finalize_request()
            return

        # Response handler start
        if stripped.startswith("> {%") or (stripped.startswith("> ") and not stripped.startswith(">> ")):
            self._state = _ParserState.RESPONSE_HANDLER
            return

        # Response save directive
        if stripped.startswith(">>"):
            return

        # Accumulate body line
        self._current_body_lines.append(line)

    def _process_response_handler(self, line: str) -> None:
        """Process a line in RESPONSE_HANDLER state."""
        stripped = line.strip()

        # Separator → finalize request
        sep_match = _SEPARATOR_RE.match(stripped)
        if sep_match:
            self._finalize_request()
            return

    def _start_request(self, match: re.Match[str]) -> None:
        """Initialize a new request from a matched request line."""
        method_str = match.group(1)
        self._current_method = HttpMethod(method_str)
        self._current_url = match.group(2).strip()
        self._current_http_version = match.group(3)
        if self._current_start_line == 0:
            self._current_start_line = self._line_num
        self._state = _ParserState.REQUEST_LINE

    def _finalize_request(self) -> None:
        """Emit the current request (if any) and reset state."""
        if not self._current_url:
            # No request in progress
            self._reset_current()
            return

        # Build body
        body: RequestBody | None = None
        if self._current_body_lines:
            # Strip trailing empty lines from body
            body_lines = self._current_body_lines
            while body_lines and not body_lines[-1].strip():
                body_lines = body_lines[:-1]
            if body_lines:
                body = RequestBody(content="\n".join(body_lines))

        request = HttpRequestDefinition(
            method=self._current_method,
            url=self._current_url,
            http_version=self._current_http_version,
            headers=self._current_headers,
            body=body,
            metadata=self._current_metadata,
            location=SourceLocation(
                file_path=self._file_path,
                start_line=self._current_start_line or 1,
                end_line=self._line_num,
            ),
            comments=self._current_comments,
        )
        self._requests.append(request)
        self._reset_current()

    def _reset_current(self) -> None:
        """Reset all current-request state."""
        self._current_method = HttpMethod.GET
        self._current_url = ""
        self._current_http_version = None
        self._current_headers = []
        self._current_body_lines = []
        self._current_metadata = RequestMetadata()
        self._current_comments = []
        self._current_start_line = 0
        self._state = _ParserState.IDLE


def parse_http_file(file_path: str | Path) -> ParseResult:
    """Parse an .http file from disk."""
    path = Path(file_path)
    content = path.read_text(encoding="utf-8")
    parser = HttpFileParser(file_path=str(path))
    return parser.parse(content)


def parse_http_string(content: str, file_path: str = "<string>") -> ParseResult:
    """Parse .http content from a string."""
    parser = HttpFileParser(file_path=file_path)
    return parser.parse(content)
