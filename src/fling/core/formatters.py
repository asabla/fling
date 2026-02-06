"""Output formatters for fling execution results.

Provides JSON, JUnit XML, and Markdown report formatting
for CI integration and human-readable output.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fling.core.models import ExecutionResult, HttpRequestDefinition


def _request_name(request: HttpRequestDefinition) -> str:
    """Return the display name for a request."""
    return request.metadata.name or f"{request.method.value} {request.url}"


def _is_failure(result: ExecutionResult) -> bool:
    """Check if a result represents a failure (error or failed tests)."""
    if result.error:
        return True
    return bool(result.script_result and not result.script_result.all_passed)


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------


def format_json(
    results: list[tuple[HttpRequestDefinition, ExecutionResult]],
    *,
    file_path: str = "",
) -> str:
    """Format results as a machine-readable JSON report.

    Args:
        results: List of (request, result) tuples.
        file_path: Source .http file path.

    Returns:
        JSON string.
    """
    total_passed = 0
    total_failed = 0
    total_errors = 0
    entries: list[dict[str, object]] = []

    for request, result in results:
        failed = _is_failure(result)

        entry: dict[str, object] = {
            "name": _request_name(request),
            "method": request.method.value,
            "url": result.resolved_url,
            "status_code": result.status_code,
            "elapsed_ms": result.elapsed_ms,
            "passed": not failed,
        }

        if result.error:
            entry["error"] = result.error
            total_errors += 1
        elif failed:
            total_failed += 1
        else:
            total_passed += 1

        if result.script_result and result.script_result.tests:
            entry["tests"] = [
                {
                    "name": t.name,
                    "passed": t.passed,
                    **({"error": t.error} if t.error else {}),
                }
                for t in result.script_result.tests
            ]

        entries.append(entry)

    report = {
        "file": file_path,
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "summary": {
            "total": len(results),
            "passed": total_passed,
            "failed": total_failed,
            "errors": total_errors,
        },
        "results": entries,
    }

    return json.dumps(report, indent=2)


# ---------------------------------------------------------------------------
# JUnit XML
# ---------------------------------------------------------------------------


def format_junit(
    results: list[tuple[HttpRequestDefinition, ExecutionResult]],
    *,
    file_path: str = "",
) -> str:
    """Format results as JUnit XML for CI systems.

    Args:
        results: List of (request, result) tuples.
        file_path: Source .http file path.

    Returns:
        JUnit XML string.
    """
    failures = sum(1 for _, r in results if _is_failure(r))
    errors = sum(1 for _, r in results if r.error)
    total_time = sum(r.elapsed_ms for _, r in results) / 1000.0

    testsuite = ET.Element("testsuite")
    testsuite.set("name", file_path or "fling")
    testsuite.set("tests", str(len(results)))
    testsuite.set("failures", str(failures))
    testsuite.set("errors", str(errors))
    testsuite.set("time", f"{total_time:.3f}")
    testsuite.set("timestamp", datetime.now(tz=UTC).isoformat())

    for request, result in results:
        name = _request_name(request)
        testcase = ET.SubElement(testsuite, "testcase")
        testcase.set("name", name)
        testcase.set("classname", file_path or "fling")
        testcase.set("time", f"{result.elapsed_ms / 1000.0:.3f}")

        if result.error:
            error_el = ET.SubElement(testcase, "error")
            error_el.set("message", result.error)
            error_el.set("type", "RequestError")
        elif result.script_result and not result.script_result.all_passed:
            failed_tests = [t for t in result.script_result.tests if not t.passed]
            messages = [f"{t.name}: {t.error or 'failed'}" for t in failed_tests]
            failure_el = ET.SubElement(testcase, "failure")
            failure_el.set("message", "; ".join(messages))
            failure_el.set("type", "TestFailure")
            failure_el.text = "\n".join(messages)

        # Add script test results as system-out
        if result.script_result and result.script_result.tests:
            sysout = ET.SubElement(testcase, "system-out")
            lines = []
            for t in result.script_result.tests:
                status = "PASS" if t.passed else "FAIL"
                lines.append(f"[{status}] {t.name}")
            sysout.text = "\n".join(lines)

    ET.indent(testsuite, space="  ")
    xml_str = ET.tostring(testsuite, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_str}\n'


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def format_markdown(
    results: list[tuple[HttpRequestDefinition, ExecutionResult]],
    *,
    file_path: str = "",
) -> str:
    """Format results as a human-readable Markdown report.

    Args:
        results: List of (request, result) tuples.
        file_path: Source .http file path.

    Returns:
        Markdown string.
    """
    lines: list[str] = []

    # Title
    title = f"Test Report: {file_path}" if file_path else "Test Report"
    lines.append(f"# {title}")
    lines.append("")

    # Summary
    total = len(results)
    passed = sum(1 for _, r in results if not _is_failure(r))
    failed = total - passed
    total_time = sum(r.elapsed_ms for _, r in results)

    lines.append(
        f"**Total**: {total} | **Passed**: {passed} | **Failed**: {failed} | **Time**: {_format_time(total_time)}"
    )
    lines.append("")

    # Results table
    lines.append("| Status | Request | Method | Status Code | Time |")
    lines.append("|--------|---------|--------|-------------|------|")

    for request, result in results:
        name = _request_name(request)
        status = "FAIL" if _is_failure(result) else "PASS"
        status_icon = "x" if _is_failure(result) else "v"
        code = str(result.status_code) if result.status_code else "-"
        time_str = _format_time(result.elapsed_ms)
        lines.append(f"| {status_icon} {status} | {name} | {request.method.value} | {code} | {time_str} |")

    lines.append("")

    # Detail section for failures
    failures = [(req, res) for req, res in results if _is_failure(res)]
    if failures:
        lines.append("## Failures")
        lines.append("")
        for request, result in failures:
            name = _request_name(request)
            lines.append(f"### {name}")
            lines.append("")
            if result.error:
                lines.append(f"**Error**: {result.error}")
            elif result.script_result:
                for t in result.script_result.tests:
                    if not t.passed:
                        lines.append(f"- **FAIL**: {t.name}" + (f" — {t.error}" if t.error else ""))
            lines.append("")

    return "\n".join(lines)


def _format_time(ms: float) -> str:
    """Format milliseconds for display."""
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"
