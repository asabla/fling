"""Formatter for .http files.

Normalizes whitespace, aligns headers, ensures consistent ``###``
separators, and sorts file-level variables to the top of the file.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from fling.core.parser import parse_http_file, parse_http_string

if TYPE_CHECKING:
    from pathlib import Path

    from fling.core.models import (
        HttpFile,
        HttpRequestDefinition,
    )

# Header alignment regex — detect "Name: Value" lines
_HEADER_RE = re.compile(r"^([\w\-]+)\s*:\s*(.*)$")


def format_http_file(file_path: str | Path) -> str:
    """Format an ``.http`` file on disk and return the formatted content.

    Args:
        file_path: Path to the ``.http`` file.

    Returns:
        The formatted file content as a string.
    """
    result = parse_http_file(file_path)
    return format_http_model(result.http_file)


def format_http_string(content: str, file_path: str = "<string>") -> str:
    """Format ``.http`` content from a string.

    Args:
        content: Raw ``.http`` file content.
        file_path: Virtual file path for error messages.

    Returns:
        The formatted content as a string.
    """
    result = parse_http_string(content, file_path)
    return format_http_model(result.http_file)


def format_http_model(http_file: HttpFile) -> str:
    """Produce canonical formatted output from a parsed ``HttpFile`` model.

    Formatting rules:
    - File-level variables (``@name = value``) are placed first, one per line.
    - Requests are separated by ``###`` on its own line with a blank line
      before and after.
    - Metadata comments (``# @name``, ``# @ref``, etc.) appear immediately
      before the request line.
    - Headers are vertically aligned on the ``:`` character.
    - A single blank line separates headers from body.
    - Trailing whitespace is stripped from all lines.
    - File ends with a single trailing newline.
    """
    parts: list[str] = []

    # --- Variables first ---
    if http_file.variables:
        for var in http_file.variables:
            parts.append(f"@{var.name} = {var.value}")
        parts.append("")  # blank line after variables

    # --- Requests ---
    for idx, req in enumerate(http_file.requests):
        if idx > 0 or http_file.variables:
            parts.append("###")
            parts.append("")

        _emit_request(parts, req)

    # Ensure trailing newline
    text = "\n".join(parts)
    if not text.endswith("\n"):
        text += "\n"
    return text


def _emit_request(parts: list[str], req: HttpRequestDefinition) -> None:
    """Emit a single request into *parts*."""
    # --- Metadata comments ---
    if req.metadata.name:
        parts.append(f"# @name {req.metadata.name}")
    for ref in req.metadata.refs:
        parts.append(f"# @ref {ref}")
    if req.metadata.no_redirect:
        parts.append("# @no-redirect")
    if req.metadata.no_cookie_jar:
        parts.append("# @no-cookie-jar")
    if req.metadata.timeout_ms is not None:
        parts.append(f"# @timeout {req.metadata.timeout_ms}")
    if req.metadata.disabled:
        parts.append("# @disabled")
    for var_name, description in req.metadata.prompt_vars.items():
        parts.append(f"# @prompt {var_name} {description}")
    if req.metadata.note:
        parts.append(f"# @note {req.metadata.note}")

    # Regular comments (non-metadata)
    for comment in req.comments:
        # Skip metadata comments that we already emitted above
        stripped = comment.strip()
        if stripped.startswith("@"):
            continue
        parts.append(f"# {comment}")

    # --- Request line ---
    request_line = f"{req.method.value} {req.url}"
    if req.http_version:
        request_line += f" {req.http_version}"
    parts.append(request_line)

    # --- Headers (aligned) ---
    if req.headers:
        aligned = _align_headers(req.headers)
        parts.extend(aligned)

    # --- Body ---
    if req.body:
        parts.append("")  # blank line before body
        if req.body.file_ref:
            parts.append(f"< {req.body.file_ref}")
        elif req.body.content:
            parts.extend(req.body.content.splitlines())

    # --- Pre-request script ---
    if req.pre_request_script:
        parts.append("")
        script_lines = req.pre_request_script.splitlines()
        if len(script_lines) == 1:
            parts.append(f"< {{% {script_lines[0]} %}}")
        else:
            parts.append("< {%")
            parts.extend(script_lines)
            parts.append("%}")

    # --- Response handler ---
    if req.response_handler:
        parts.append("")
        if req.response_handler.file_ref:
            parts.append(f"> {req.response_handler.file_ref}")
        elif req.response_handler.inline_script:
            script_lines = req.response_handler.inline_script.splitlines()
            if len(script_lines) == 1:
                parts.append(f"> {{% {script_lines[0]} %}}")
            else:
                parts.append("> {%")
                parts.extend(script_lines)
                parts.append("%}")

    # --- Response save ---
    if req.response_save_path:
        parts.append("")
        parts.append(f">> {req.response_save_path}")


def _align_headers(headers: list[object]) -> list[str]:
    """Align header lines so ``:`` characters are vertically aligned.

    Args:
        headers: List of ``Header`` objects with ``.name`` and ``.value``.

    Returns:
        List of formatted header strings.
    """
    # Find the longest header name
    max_name_len = max(len(h.name) for h in headers)  # type: ignore[union-attr]

    lines: list[str] = []
    for h in headers:
        name: str = h.name  # type: ignore[union-attr]
        value: str = h.value  # type: ignore[union-attr]
        padded_name = name.ljust(max_name_len)
        lines.append(f"{padded_name}: {value}")
    return lines
