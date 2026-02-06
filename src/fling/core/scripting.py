"""Response handler scripting engine for fling.

Executes response handler scripts attached to HTTP requests.
Supports JetBrains-style JavaScript handlers with best-effort
transpilation to Python, plus native Python scripts.

Provides client/response context objects:
  - response.body, response.status, response.headers
  - client.test(name, callback)
  - client.global.set(name, value)
  - client.assert(condition)
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fling.core.models import ScriptResult, ScriptTestResult

if TYPE_CHECKING:
    from fling.core.models import ExecutionResult, ResponseHandler

logger = logging.getLogger(__name__)


class _DotDict(dict[str, Any]):
    """Dict subclass that supports attribute access for dot-notation in transpiled JS.

    Allows patterns like ``data.status`` when ``data`` is a parsed JSON object.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            value = self[name]
        except KeyError:
            raise AttributeError(name) from None
        return _wrap_value(value)

    def __repr__(self) -> str:
        return f"_DotDict({dict.__repr__(self)})"


def _wrap_value(value: Any) -> Any:
    """Recursively wrap dicts/lists so dot-access works at every level."""
    if isinstance(value, dict) and not isinstance(value, _DotDict):
        return _DotDict(value)
    if isinstance(value, list):
        return [_wrap_value(v) for v in value]
    return value


class _ResponseObject:
    """Proxy object providing response.body, response.status, response.headers."""

    def __init__(self, result: ExecutionResult) -> None:
        self.status: int = result.status_code
        self.headers: dict[str, str] = {k: v[0] if v else "" for k, v in result.response_headers.items()}
        self._raw_body: str = result.response_body

        # Try to parse body as JSON; fall back to raw string
        try:
            parsed = json.loads(self._raw_body) if self._raw_body else None
            self.body: Any = _wrap_value(parsed)
        except (json.JSONDecodeError, TypeError):
            self.body = self._raw_body

    @property
    def content_type(self) -> str:
        """Return the Content-Type header value."""
        for k, v in self.headers.items():
            if k.lower() == "content-type":
                return v
        return ""


class _GlobalStore:
    """Proxy for client.global.set(name, value) / client.global.get(name)."""

    def __init__(self) -> None:
        self._vars: dict[str, Any] = {}

    def set(self, name: str, value: Any) -> None:
        """Set a global variable."""
        self._vars[name] = value

    def get(self, name: str, default: Any = None) -> Any:
        """Get a global variable."""
        return self._vars.get(name, default)

    @property
    def variables(self) -> dict[str, Any]:
        """Return all global variables."""
        return dict(self._vars)


class _ClientObject:
    """Proxy object providing client.test(), client.assert(), client.global."""

    def __init__(self) -> None:
        self.tests: list[ScriptTestResult] = []
        self.global_store = _GlobalStore()

    # Expose as "global" attribute (Python reserved word workaround)
    @property
    def globals(self) -> _GlobalStore:
        """Access the global variable store (alias for JS client.global)."""
        return self.global_store

    def test(self, name: str, callback: Any = None) -> None:
        """Register and run a test assertion.

        Args:
            name: Test name.
            callback: Callable that performs assertions. If None, test passes.
        """
        try:
            if callable(callback):
                callback()
            self.tests.append(ScriptTestResult(name=name, passed=True))
        except (AssertionError, Exception) as exc:
            self.tests.append(ScriptTestResult(name=name, passed=False, error=str(exc) or "Assertion failed"))

    def assert_(self, condition: bool, message: str = "") -> None:
        """Assert a condition (used inside client.test callbacks).

        Args:
            condition: The condition to assert.
            message: Optional error message.

        Raises:
            AssertionError: If condition is falsy.
        """
        if not condition:
            raise AssertionError(message or "Assertion failed")


# ---------------------------------------------------------------------------
# JS-to-Python transpiler
# ---------------------------------------------------------------------------


def transpile_js_to_python(js_code: str) -> tuple[str, list[str]]:
    """Best-effort transpilation of JetBrains-style JS to Python.

    Handles common patterns found in .http response handler scripts:
      - client.test("name", function() { ... })
      - client.assert(condition)
      - client.global.set("key", value)
      - response.body.field -> response.body["field"]
      - var x = ...; -> x = ...
      - === / !== -> == / !=
      - function() { ... } -> lambda: ...
      - null -> None, true -> True, false -> False

    Args:
        js_code: JavaScript code from > {% ... %} block.

    Returns:
        Tuple of (transpiled Python code, list of warnings).
    """
    warnings: list[str] = []
    lines = js_code.strip().splitlines()
    py_lines: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            py_lines.append("")
            i += 1
            continue

        # Skip pure comment lines
        if stripped.startswith("//"):
            py_lines.append(re.sub(r"^(\s*)//", r"\1#", line))
            i += 1
            continue

        # Single-line client.test with inline function body
        # Must check BEFORE multi-line to avoid false match
        single_test = re.match(
            r'client\.test\(\s*["\'](.+?)["\']\s*,\s*function\s*\(\s*\)\s*\{'
            r"\s*(.+?)\s*\}\s*\)\s*;?\s*$",
            stripped,
        )
        if single_test:
            indent = _get_indent(line)
            test_name = single_test.group(1)
            body = _transpile_statement(single_test.group(2), warnings).strip()
            if body:
                py_lines.append(f'{indent}client.test("{test_name}", lambda: ({body}))')
            else:
                py_lines.append(f'{indent}client.test("{test_name}")')
            i += 1
            continue

        # Multi-line client.test — opening line ends with { but no closing }
        test_match = re.match(
            r'client\.test\(\s*["\'](.+?)["\']\s*,\s*function\s*\(\s*\)\s*\{\s*$',
            stripped,
        )
        if test_match:
            indent = _get_indent(line)
            test_name = test_match.group(1)
            # Collect body lines until we find the closing });
            body_lines: list[str] = []
            i += 1
            while i < len(lines):
                inner = lines[i]
                inner_stripped = inner.strip()
                if inner_stripped.startswith("});") or inner_stripped == "}":
                    break
                body_lines.append(inner)
                i += 1
            i += 1  # skip closing line

            # Transpile body
            if body_lines:
                transpiled_body = []
                for bl in body_lines:
                    transpiled_body.append(_transpile_statement(bl, warnings))
                # Emit as client.test with lambda
                body_code = "; ".join(b.strip() for b in transpiled_body if b.strip())
                if body_code:
                    py_lines.append(f'{indent}client.test("{test_name}", lambda: ({body_code}))')
                else:
                    py_lines.append(f'{indent}client.test("{test_name}")')
            else:
                py_lines.append(f'{indent}client.test("{test_name}")')
            continue

        # Regular statement
        py_lines.append(_transpile_statement(line, warnings))
        i += 1

    return "\n".join(py_lines), warnings


def _get_indent(line: str) -> str:
    """Extract the leading whitespace from a line."""
    return line[: len(line) - len(line.lstrip())]


def _transpile_statement(line: str, warnings: list[str]) -> str:
    """Transpile a single JS statement to Python.

    Args:
        line: A single line of JS code.
        warnings: List to append warnings to.

    Returns:
        Transpiled Python line.
    """
    indent = _get_indent(line)
    stmt = line.strip().rstrip(";")

    if not stmt:
        return ""

    # var/let/const declarations
    stmt = re.sub(r"^(var|let|const)\s+", "", stmt)

    # === / !==
    stmt = stmt.replace("!==", "!=")
    stmt = stmt.replace("===", "==")

    # JS literals -> Python literals
    # Use word-boundary replacements to avoid mangling strings
    stmt = re.sub(r"\bnull\b", "None", stmt)
    stmt = re.sub(r"\bundefined\b", "None", stmt)
    # Only replace bare true/false, not inside strings
    stmt = re.sub(r"\btrue\b", "True", stmt)
    stmt = re.sub(r"\bfalse\b", "False", stmt)

    # client.assert(...) -> client.assert_(...)
    stmt = re.sub(r"client\.assert\(", "client.assert_(", stmt)

    # client.global.set(...) stays the same (Python _GlobalStore has .set())
    # client.global -> client.globals (Python reserved word)
    stmt = re.sub(r"client\.global\b", "client.globals", stmt)

    # response.body.field (not response.body["..."] already) -> response.body["field"]
    # Handle chained access like response.body.data.status
    stmt = _transpile_response_body_access(stmt)

    # Detect unsupported constructs
    if re.search(r"\b(for|while|switch|try|catch|throw|new|typeof|instanceof)\b", stmt):
        warnings.append(f"Unsupported JS construct: {stmt.strip()}")

    return indent + stmt


def _transpile_response_body_access(stmt: str) -> str:
    """Convert response.body.x.y to response.body["x"]["y"].

    Handles patterns like:
      response.body.token -> response.body["token"]
      response.body.data.status -> response.body["data"]["status"]

    Does NOT touch:
      response.body (no further access)
      response.body["key"] (already subscript)

    Args:
        stmt: Statement to transform.

    Returns:
        Transformed statement.
    """

    def _replace_body_access(match: re.Match[str]) -> str:
        full = match.group(0)
        # Extract the dot-chain after response.body
        after_body = full[len("response.body") :]
        if not after_body or after_body[0] != ".":
            return full
        # Split the chain: .token.data -> ["token"]["data"]
        parts = after_body.split(".")
        # parts[0] is "" (before first dot)
        subscripts = "".join(f'["{p}"]' for p in parts[1:] if p)
        return f"response.body{subscripts}"

    # Match response.body followed by one or more .identifier chains
    return re.sub(r"response\.body(?:\.\w+)+", _replace_body_access, stmt)


# ---------------------------------------------------------------------------
# Script execution
# ---------------------------------------------------------------------------


def execute_handler(
    handler: ResponseHandler,
    result: ExecutionResult,
    source_file: str,
) -> ScriptResult:
    """Execute a response handler script against an execution result.

    Supports inline scripts (from > {% ... %}) and file references (> ./file.js).
    JavaScript handlers are transpiled to Python before execution.

    Args:
        handler: The response handler definition.
        result: The HTTP execution result.
        source_file: Path to the .http file (for resolving file refs).

    Returns:
        ScriptResult with test results, global variables, and warnings.
    """
    script_code: str | None = None
    warnings: list[str] = []

    if handler.inline_script:
        script_code = handler.inline_script
    elif handler.file_ref:
        script_code = _load_handler_file(handler.file_ref, source_file)
        if script_code is None:
            return ScriptResult(
                error=f"Handler file not found: {handler.file_ref}",
            )
    else:
        return ScriptResult()

    # Transpile JS to Python
    transpiled, transpile_warnings = transpile_js_to_python(script_code)
    warnings.extend(transpile_warnings)

    # Execute
    response = _ResponseObject(result)
    client = _ClientObject()

    try:
        # Build execution namespace
        namespace: dict[str, Any] = {
            "response": response,
            "client": client,
            "json": json,
        }

        exec(transpiled, namespace)

    except Exception as exc:
        logger.warning("Script execution error: %s", exc)
        return ScriptResult(
            tests=client.tests,
            global_vars=client.global_store.variables,
            warnings=warnings,
            error=f"Script execution error: {exc}",
        )

    return ScriptResult(
        tests=client.tests,
        global_vars=client.global_store.variables,
        warnings=warnings,
    )


def _load_handler_file(file_ref: str, source_file: str) -> str | None:
    """Load a handler script from a file reference.

    Args:
        file_ref: Relative path to the handler file.
        source_file: Path to the .http file (for relative resolution).

    Returns:
        File contents as string, or None if not found.
    """
    base_dir = Path(source_file).parent
    handler_path = base_dir / file_ref

    try:
        return handler_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("Handler file not found: %s", handler_path)
        return None
    except OSError as exc:
        logger.warning("Error reading handler file %s: %s", handler_path, exc)
        return None
