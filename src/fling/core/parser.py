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
    ResponseHandler,
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

# Metadata comment patterns (# @key value)
_META_NAME_RE = re.compile(r"^@name\s+(.+)$")
_META_REF_RE = re.compile(r"^@ref\s+(.+)$")
_META_NO_REDIRECT_RE = re.compile(r"^@no-redirect\s*$")
_META_NO_COOKIE_JAR_RE = re.compile(r"^@no-cookie-jar\s*$")
_META_TIMEOUT_RE = re.compile(r"^@timeout\s+(\d+)\s*$")
_META_DISABLED_RE = re.compile(r"^@disabled\s*$")
_META_PROMPT_RE = re.compile(r"^@prompt\s+(\w+)\s*(.*)?$")
_META_NOTE_RE = re.compile(r"^@note\s+(.+)$")

# Body file reference: < ./file.json
_FILE_REF_RE = re.compile(r"^<\s+(.+)$")

# Response handler patterns
_RESPONSE_HANDLER_INLINE_START_RE = re.compile(r"^>\s*\{%\s*$")
_RESPONSE_HANDLER_INLINE_END_RE = re.compile(r"^%\}\s*$")
_RESPONSE_HANDLER_INLINE_ONELINE_RE = re.compile(r"^>\s*\{%\s*(.+?)\s*%\}\s*$")
_RESPONSE_HANDLER_FILE_RE = re.compile(r"^>\s+([^\s{].+)$")

# Pre-request script patterns
_PRE_REQUEST_INLINE_START_RE = re.compile(r"^<\s*\{%\s*$")
_PRE_REQUEST_INLINE_END_RE = re.compile(r"^%\}\s*$")
_PRE_REQUEST_INLINE_ONELINE_RE = re.compile(r"^<\s*\{%\s*(.+?)\s*%\}\s*$")

# Response save directive: >> file.json or >>! file.json
_RESPONSE_SAVE_RE = re.compile(r"^>>(!?)\s*(.+)$")

# HTTP methods set
_HTTP_METHODS = {m.value for m in HttpMethod}


class _ParserState(Enum):
    IDLE = auto()
    META = auto()
    REQUEST_LINE = auto()
    HEADERS = auto()
    BODY = auto()
    RESPONSE_HANDLER = auto()
    PRE_REQUEST_SCRIPT = auto()


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
        self._current_response_handler: ResponseHandler | None = None
        self._current_response_handler_lines: list[str] = []
        self._current_response_save_path: str | None = None
        self._current_pre_request_script: str | None = None
        self._current_pre_request_lines: list[str] = []
        self._current_file_ref: str | None = None

    def parse(self, content: str) -> ParseResult:
        """Parse .http file content and return a ParseResult."""
        lines = content.splitlines()

        for i, line in enumerate(lines):
            self._line_num = i + 1
            try:
                self._process_line(line)
            except Exception as exc:
                self._errors.append(
                    ParseError(
                        message=str(exc),
                        location=SourceLocation(
                            file_path=self._file_path,
                            start_line=self._line_num,
                            end_line=self._line_num,
                        ),
                    )
                )

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
        elif self._state == _ParserState.PRE_REQUEST_SCRIPT:
            self._process_pre_request_script(line)

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
            comment_text = comment_match.group(1)
            self._handle_comment_or_meta(comment_text)
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
        if self._is_url_start(stripped):
            self._current_method = HttpMethod.GET
            self._current_url = stripped
            self._current_http_version = None
            if self._current_start_line == 0:
                self._current_start_line = self._line_num
            self._state = _ParserState.REQUEST_LINE
            return

    def _process_meta(self, line: str) -> None:
        """Process a line in META state (accumulating comments/metadata before a request)."""
        stripped = line.strip()

        # Empty line — reset to idle (comments were not before a request)
        if not stripped:
            self._current_comments = []
            self._current_metadata = RequestMetadata()
            self._current_start_line = 0
            self._state = _ParserState.IDLE
            return

        # More comments / metadata
        comment_match = _COMMENT_RE.match(line)
        if comment_match:
            comment_text = comment_match.group(1)
            self._handle_comment_or_meta(comment_text)
            return

        # Request line after comments/metadata
        req_match = _REQUEST_LINE_RE.match(stripped)
        if req_match:
            self._start_request(req_match)
            return

        # URL without method (implicit GET)
        if self._is_url_start(stripped):
            self._current_method = HttpMethod.GET
            self._current_url = stripped
            self._current_http_version = None
            self._state = _ParserState.REQUEST_LINE
            return

        # Variable definition (reset meta)
        var_match = _VARIABLE_RE.match(stripped)
        if var_match:
            self._current_comments = []
            self._current_metadata = RequestMetadata()
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

        # Separator
        sep_match = _SEPARATOR_RE.match(stripped)
        if sep_match:
            self._current_comments = []
            self._current_metadata = RequestMetadata()
            self._current_start_line = 0
            self._state = _ParserState.IDLE
            return

        # Unrecognized — treat as comment continuation
        self._current_comments.append(stripped)

    def _handle_comment_or_meta(self, text: str) -> None:
        """Parse a comment line's text for metadata directives or regular comments."""
        # Check for metadata directives
        m = _META_NAME_RE.match(text)
        if m:
            self._current_metadata.name = m.group(1).strip()
            return

        m = _META_REF_RE.match(text)
        if m:
            self._current_metadata.refs.append(m.group(1).strip())
            return

        m = _META_NO_REDIRECT_RE.match(text)
        if m:
            self._current_metadata.no_redirect = True
            return

        m = _META_NO_COOKIE_JAR_RE.match(text)
        if m:
            self._current_metadata.no_cookie_jar = True
            return

        m = _META_TIMEOUT_RE.match(text)
        if m:
            self._current_metadata.timeout_ms = int(m.group(1))
            return

        m = _META_DISABLED_RE.match(text)
        if m:
            self._current_metadata.disabled = True
            return

        m = _META_PROMPT_RE.match(text)
        if m:
            var_name = m.group(1)
            description = m.group(2).strip() if m.group(2) else var_name
            self._current_metadata.prompt_vars[var_name] = description
            return

        m = _META_NOTE_RE.match(text)
        if m:
            self._current_metadata.note = m.group(1).strip()
            return

        # Regular comment
        self._current_comments.append(text)

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

        # Pre-request script (one-line): < {% script %}
        pre_oneline = _PRE_REQUEST_INLINE_ONELINE_RE.match(stripped)
        if pre_oneline:
            self._current_pre_request_script = pre_oneline.group(1)
            return

        # Pre-request script (multi-line start): < {%
        pre_start = _PRE_REQUEST_INLINE_START_RE.match(stripped)
        if pre_start:
            self._current_pre_request_lines = []
            self._state = _ParserState.PRE_REQUEST_SCRIPT
            return

        # Response handler (one-line): > {% script %}
        handler_oneline = _RESPONSE_HANDLER_INLINE_ONELINE_RE.match(stripped)
        if handler_oneline:
            self._current_response_handler = ResponseHandler(inline_script=handler_oneline.group(1))
            return

        # Response handler (multi-line start): > {%
        handler_start = _RESPONSE_HANDLER_INLINE_START_RE.match(stripped)
        if handler_start:
            self._current_response_handler_lines = []
            self._state = _ParserState.RESPONSE_HANDLER
            return

        # Response handler (file reference): > ./handler.js
        handler_file = _RESPONSE_HANDLER_FILE_RE.match(stripped)
        if handler_file and not stripped.startswith(">>"):
            self._current_response_handler = ResponseHandler(file_ref=handler_file.group(1).strip())
            return

        # Response save directive: >> file.json or >>! file.json
        save_match = _RESPONSE_SAVE_RE.match(stripped)
        if save_match:
            self._current_response_save_path = save_match.group(2).strip()
            return

        # File body reference: < ./file.json (only if no body content yet)
        if not self._current_body_lines:
            file_ref_match = _FILE_REF_RE.match(stripped)
            if file_ref_match:
                self._current_file_ref = file_ref_match.group(1).strip()
                return

        # Accumulate body line
        self._current_body_lines.append(line)

    def _process_response_handler(self, line: str) -> None:
        """Process a line in RESPONSE_HANDLER state (multi-line script)."""
        stripped = line.strip()

        # Separator → finalize request
        sep_match = _SEPARATOR_RE.match(stripped)
        if sep_match:
            # Finalize handler with accumulated lines
            self._current_response_handler = ResponseHandler(
                inline_script="\n".join(self._current_response_handler_lines)
            )
            self._current_response_handler_lines = []
            self._finalize_request()
            return

        # End of script block: %}
        end_match = _RESPONSE_HANDLER_INLINE_END_RE.match(stripped)
        if end_match:
            self._current_response_handler = ResponseHandler(
                inline_script="\n".join(self._current_response_handler_lines)
            )
            self._current_response_handler_lines = []
            self._state = _ParserState.BODY
            return

        # Accumulate script line
        self._current_response_handler_lines.append(line)

    def _process_pre_request_script(self, line: str) -> None:
        """Process a line in PRE_REQUEST_SCRIPT state (multi-line script)."""
        stripped = line.strip()

        # Separator → finalize request
        sep_match = _SEPARATOR_RE.match(stripped)
        if sep_match:
            self._current_pre_request_script = "\n".join(self._current_pre_request_lines)
            self._current_pre_request_lines = []
            self._finalize_request()
            return

        # End of script block: %}
        end_match = _PRE_REQUEST_INLINE_END_RE.match(stripped)
        if end_match:
            self._current_pre_request_script = "\n".join(self._current_pre_request_lines)
            self._current_pre_request_lines = []
            self._state = _ParserState.BODY
            return

        # Accumulate script line
        self._current_pre_request_lines.append(line)

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
        is_graphql = self._detect_graphql()

        if self._current_file_ref:
            body = RequestBody(file_ref=self._current_file_ref, is_graphql=is_graphql)
        elif self._current_body_lines:
            # Strip trailing empty lines from body
            body_lines = self._current_body_lines
            while body_lines and not body_lines[-1].strip():
                body_lines = body_lines[:-1]
            if body_lines:
                body = RequestBody(content="\n".join(body_lines), is_graphql=is_graphql)

        request = HttpRequestDefinition(
            method=self._current_method,
            url=self._current_url,
            http_version=self._current_http_version,
            headers=self._current_headers,
            body=body,
            metadata=self._current_metadata,
            response_handler=self._current_response_handler,
            response_save_path=self._current_response_save_path,
            pre_request_script=self._current_pre_request_script,
            location=SourceLocation(
                file_path=self._file_path,
                start_line=self._current_start_line or 1,
                end_line=self._line_num,
            ),
            comments=self._current_comments,
        )
        self._requests.append(request)
        self._reset_current()

    def _detect_graphql(self) -> bool:
        """Check if the current request is a GraphQL request based on headers."""
        for h in self._current_headers:
            if h.name.upper() == "X-REQUEST-TYPE" and h.value.upper() == "GRAPHQL":
                return True
            if h.name.lower() == "content-type" and "graphql" in h.value.lower():
                return True
        return False

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
        self._current_response_handler = None
        self._current_response_handler_lines = []
        self._current_response_save_path = None
        self._current_pre_request_script = None
        self._current_pre_request_lines = []
        self._current_file_ref = None
        self._state = _ParserState.IDLE

    @staticmethod
    def _is_url_start(text: str) -> bool:
        """Check if text looks like the start of a URL."""
        return text.startswith(("http://", "https://", "{{"))


def parse_http_file(file_path: str | Path) -> ParseResult:
    """Parse an .http file from disk.

    Handles file I/O errors gracefully, returning a ParseResult
    with an error rather than raising an exception.
    """
    path = Path(file_path)
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ParseResult(
            http_file=HttpFile(file_path=str(path), variables=[], requests=[]),
            errors=[ParseError(message=f"File not found: {path}", location=None)],
        )
    except PermissionError:
        return ParseResult(
            http_file=HttpFile(file_path=str(path), variables=[], requests=[]),
            errors=[ParseError(message=f"Permission denied: {path}", location=None)],
        )
    except UnicodeDecodeError as exc:
        return ParseResult(
            http_file=HttpFile(file_path=str(path), variables=[], requests=[]),
            errors=[ParseError(message=f"Encoding error in {path}: {exc}", location=None)],
        )
    except OSError as exc:
        return ParseResult(
            http_file=HttpFile(file_path=str(path), variables=[], requests=[]),
            errors=[ParseError(message=f"Cannot read {path}: {exc}", location=None)],
        )
    parser = HttpFileParser(file_path=str(path))
    return parser.parse(content)


def parse_http_string(content: str, file_path: str = "<string>") -> ParseResult:
    """Parse .http content from a string."""
    parser = HttpFileParser(file_path=file_path)
    return parser.parse(content)
