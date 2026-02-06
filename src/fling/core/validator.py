"""Validator for .http files.

Detects issues such as duplicate request names, circular ``@ref``
dependencies, undefined variable references, and missing ``Content-Type``
headers on requests that carry a body.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from fling.core.models import SourceLocation  # noqa: TC001 - needed at runtime by Pydantic
from fling.core.parser import parse_http_file, parse_http_string
from fling.core.variables import (
    CHAINING_PATTERN,
    ENV_DOT_PATTERN,
    SYSTEM_VAR_PATTERN,
    VARIABLE_PATTERN,
)

if TYPE_CHECKING:
    from pathlib import Path

    from fling.core.models import (
        HttpFile,
        HttpRequestDefinition,
        ParseResult,
    )


class Severity(StrEnum):
    """Severity level for a validation issue."""

    ERROR = "error"
    WARNING = "warning"


class ValidationIssue(BaseModel):
    """A single validation issue found in an .http file."""

    severity: Severity
    message: str
    location: SourceLocation | None = None

    def format(self) -> str:
        """Format the issue for human-readable output.

        Returns:
            A string like ``file.http:5: error: duplicate request name 'login'``.
        """
        loc_str = ""
        if self.location:
            loc_str = f"{self.location.file_path}:{self.location.start_line}: "
        return f"{loc_str}{self.severity.value}: {self.message}"


class ValidationResult(BaseModel):
    """Aggregated result of validating an .http file."""

    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Return True if any issues have error severity."""
        return any(i.severity == Severity.ERROR for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        """Return True if any issues have warning severity."""
        return any(i.severity == Severity.WARNING for i in self.issues)

    @property
    def error_count(self) -> int:
        """Count of error-level issues."""
        return sum(1 for i in self.issues if i.severity == Severity.ERROR)

    @property
    def warning_count(self) -> int:
        """Count of warning-level issues."""
        return sum(1 for i in self.issues if i.severity == Severity.WARNING)


def validate_http_file(file_path: str | Path) -> ValidationResult:
    """Validate an ``.http`` file on disk.

    Args:
        file_path: Path to the ``.http`` file.

    Returns:
        A :class:`ValidationResult` with all detected issues.
    """
    parse_result = parse_http_file(file_path)
    return _validate(parse_result)


def validate_http_string(content: str, file_path: str = "<string>") -> ValidationResult:
    """Validate ``.http`` content from a string.

    Args:
        content: Raw ``.http`` file content.
        file_path: Virtual file path for error messages.

    Returns:
        A :class:`ValidationResult` with all detected issues.
    """
    parse_result = parse_http_string(content, file_path)
    return _validate(parse_result)


# ---------------------------------------------------------------------------
# Internal validation pipeline
# ---------------------------------------------------------------------------


def _validate(parse_result: ParseResult) -> ValidationResult:
    """Run all validation checks against a parsed file."""
    issues: list[ValidationIssue] = []

    # 1. Report parse errors
    issues.extend(_check_parse_errors(parse_result))

    http_file = parse_result.http_file

    # 2. Duplicate request names
    issues.extend(_check_duplicate_names(http_file))

    # 3. Circular @ref dependencies
    issues.extend(_check_circular_refs(http_file))

    # 4. Undefined variable references
    issues.extend(_check_undefined_variables(http_file))

    # 5. Missing Content-Type for bodies
    issues.extend(_check_missing_content_type(http_file))

    return ValidationResult(issues=issues)


def _check_parse_errors(parse_result: ParseResult) -> list[ValidationIssue]:
    """Convert parse errors into validation issues."""
    return [
        ValidationIssue(
            severity=Severity.ERROR,
            message=f"parse error: {err.message}",
            location=err.location,
        )
        for err in parse_result.errors
    ]


def _check_duplicate_names(http_file: HttpFile) -> list[ValidationIssue]:
    """Detect requests that share the same ``@name``."""
    issues: list[ValidationIssue] = []
    seen: dict[str, SourceLocation] = {}

    for req in http_file.requests:
        name = req.metadata.name
        if not name:
            continue
        if name in seen:
            issues.append(
                ValidationIssue(
                    severity=Severity.ERROR,
                    message=f"duplicate request name '{name}'",
                    location=req.location,
                ),
            )
        else:
            seen[name] = req.location

    return issues


def _check_circular_refs(http_file: HttpFile) -> list[ValidationIssue]:
    """Detect circular ``@ref`` dependency chains.

    Builds a directed graph of request-name → refs and performs DFS
    cycle detection.
    """
    issues: list[ValidationIssue] = []

    # Build adjacency list: name -> list of ref targets
    graph: dict[str, list[str]] = {}
    location_by_name: dict[str, SourceLocation] = {}

    for req in http_file.requests:
        name = req.metadata.name
        if not name:
            continue
        graph[name] = list(req.metadata.refs)
        location_by_name[name] = req.location

    # DFS cycle detection
    _white, _gray, _black = 0, 1, 2
    color: dict[str, int] = {n: _white for n in graph}
    path: list[str] = []
    reported_cycles: set[frozenset[str]] = set()

    def _dfs(node: str) -> None:
        color[node] = _gray
        path.append(node)

        for neighbor in graph.get(node, []):
            if neighbor not in color:
                # Reference to undefined name — skip (different check)
                continue
            if color[neighbor] == _gray:
                # Found a cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:]
                cycle_key = frozenset(cycle)
                if cycle_key not in reported_cycles:
                    reported_cycles.add(cycle_key)
                    cycle_desc = " -> ".join([*cycle, neighbor])
                    issues.append(
                        ValidationIssue(
                            severity=Severity.ERROR,
                            message=f"circular @ref dependency: {cycle_desc}",
                            location=location_by_name.get(node),
                        ),
                    )
            elif color[neighbor] == _white:
                _dfs(neighbor)

        path.pop()
        color[node] = _black

    for node in graph:
        if color[node] == _white:
            _dfs(node)

    return issues


def _check_undefined_variables(http_file: HttpFile) -> list[ValidationIssue]:
    """Flag ``{{var}}`` references that cannot be resolved statically.

    We can only check against file-level variables. References to
    environment variables, system variables (``$uuid``, etc.),
    ``$env.X``, ``$processEnv``, ``$dotenv``, and chaining
    patterns (``name.response.…``) are considered potentially
    resolvable at runtime and are **not** flagged.
    """
    issues: list[ValidationIssue] = []

    # Collect known file-level variable names
    file_var_names = {v.name for v in http_file.variables}

    # Collect known request names (for chaining)
    request_names = {r.metadata.name for r in http_file.requests if r.metadata.name}

    for req in http_file.requests:
        refs = _extract_variable_refs(req)
        for var_expr, location in refs:
            if _is_known_variable(var_expr, file_var_names, request_names):
                continue
            issues.append(
                ValidationIssue(
                    severity=Severity.WARNING,
                    message=f"possibly undefined variable '{var_expr}'",
                    location=location,
                ),
            )

    return issues


def _extract_variable_refs(
    req: HttpRequestDefinition,
) -> list[tuple[str, SourceLocation]]:
    """Extract all ``{{...}}`` variable expressions from a request.

    Returns a list of ``(variable_expression, location)`` tuples.
    """
    results: list[tuple[str, SourceLocation]] = []
    loc = req.location

    # URL
    for m in VARIABLE_PATTERN.finditer(req.url):
        results.append((m.group(1).strip(), loc))

    # Headers
    for h in req.headers:
        for m in VARIABLE_PATTERN.finditer(h.value):
            results.append((m.group(1).strip(), loc))
        for m in VARIABLE_PATTERN.finditer(h.name):
            results.append((m.group(1).strip(), loc))

    # Body
    if req.body and req.body.content:
        for m in VARIABLE_PATTERN.finditer(req.body.content):
            results.append((m.group(1).strip(), loc))

    return results


def _is_known_variable(
    var_expr: str,
    file_var_names: set[str],
    request_names: set[str],
) -> bool:
    """Determine whether a variable expression is known/resolvable.

    Returns True if the expression matches any of:
    - A file-level variable name
    - A system variable pattern (``$uuid``, ``$timestamp``, etc.)
    - An ``$env.X`` pattern
    - A chaining pattern (``requestName.response.…``)
    """
    # File variable
    if var_expr in file_var_names:
        return True

    # System variable ($uuid, $timestamp, $randomInt, $processEnv, $dotenv, etc.)
    if SYSTEM_VAR_PATTERN.match(var_expr):
        return True

    # $env.VAR
    if ENV_DOT_PATTERN.match(var_expr):
        return True

    # Chaining reference (requestName.response.body.$.jsonpath or .headers.X)
    if CHAINING_PATTERN.match(var_expr):
        return True

    # Also accept plain request-name based variable patterns that don't
    # match the full chaining regex but start with a known request name
    # followed by ".response" — a lenient check.
    return any(var_expr.startswith(f"{rn}.response") for rn in request_names)


def _check_missing_content_type(http_file: HttpFile) -> list[ValidationIssue]:
    """Flag requests that have a body but no ``Content-Type`` header."""
    issues: list[ValidationIssue] = []

    for req in http_file.requests:
        if not req.body:
            continue
        # A body exists — check headers
        has_content_type = any(h.name.lower() == "content-type" for h in req.headers)
        if not has_content_type:
            issues.append(
                ValidationIssue(
                    severity=Severity.WARNING,
                    message="request has a body but no Content-Type header",
                    location=req.location,
                ),
            )

    return issues
