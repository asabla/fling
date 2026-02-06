"""Tests for output formatters."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

from fling.core.formatters import format_json, format_junit, format_markdown
from fling.core.models import (
    ExecutionResult,
    HttpMethod,
    HttpRequestDefinition,
    RequestMetadata,
    ScriptResult,
    ScriptTestResult,
    SourceLocation,
)

_LOC = SourceLocation(file_path="test.http", start_line=1, end_line=1)


def _make_request(
    name: str | None = None,
    method: HttpMethod = HttpMethod.GET,
    url: str = "https://api.example.com/test",
) -> HttpRequestDefinition:
    return HttpRequestDefinition(
        method=method,
        url=url,
        metadata=RequestMetadata(name=name),
        location=_LOC,
    )


def _make_result(
    request: HttpRequestDefinition,
    status_code: int = 200,
    elapsed_ms: float = 100.0,
    error: str | None = None,
    script_result: ScriptResult | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        request=request,
        resolved_url=request.url,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        error=error,
        response_body='{"ok": true}',
        script_result=script_result,
    )


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------


class TestFormatJson:
    """Tests for JSON report output."""

    def test_basic_success(self) -> None:
        req = _make_request(name="get-users")
        result = _make_result(req)
        output = format_json([(req, result)], file_path="test.http")
        data = json.loads(output)

        assert data["file"] == "test.http"
        assert data["summary"]["total"] == 1
        assert data["summary"]["passed"] == 1
        assert data["summary"]["failed"] == 0
        assert data["summary"]["errors"] == 0
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "get-users"
        assert data["results"][0]["passed"] is True
        assert data["results"][0]["status_code"] == 200

    def test_error_result(self) -> None:
        req = _make_request(name="fail-req")
        result = _make_result(req, status_code=0, error="Connection refused")
        output = format_json([(req, result)], file_path="test.http")
        data = json.loads(output)

        assert data["summary"]["errors"] == 1
        assert data["summary"]["passed"] == 0
        assert data["results"][0]["passed"] is False
        assert data["results"][0]["error"] == "Connection refused"

    def test_failed_tests(self) -> None:
        req = _make_request(name="test-req")
        script = ScriptResult(
            tests=[
                ScriptTestResult(name="status is 200", passed=True),
                ScriptTestResult(name="body has token", passed=False, error="missing field"),
            ]
        )
        result = _make_result(req, script_result=script)
        output = format_json([(req, result)])
        data = json.loads(output)

        assert data["summary"]["failed"] == 1
        assert data["summary"]["passed"] == 0
        assert len(data["results"][0]["tests"]) == 2
        assert data["results"][0]["tests"][1]["passed"] is False

    def test_multiple_results(self) -> None:
        req1 = _make_request(name="first")
        req2 = _make_request(name="second")
        r1 = _make_result(req1)
        r2 = _make_result(req2, error="timeout")
        output = format_json([(req1, r1), (req2, r2)])
        data = json.loads(output)

        assert data["summary"]["total"] == 2
        assert data["summary"]["passed"] == 1
        assert data["summary"]["errors"] == 1

    def test_unnamed_request_uses_method_and_url(self) -> None:
        req = _make_request()  # No name
        result = _make_result(req)
        output = format_json([(req, result)])
        data = json.loads(output)

        assert data["results"][0]["name"] == "GET https://api.example.com/test"

    def test_timestamp_present(self) -> None:
        req = _make_request()
        result = _make_result(req)
        output = format_json([(req, result)])
        data = json.loads(output)

        assert "timestamp" in data


# ---------------------------------------------------------------------------
# JUnit XML
# ---------------------------------------------------------------------------


class TestFormatJunit:
    """Tests for JUnit XML output."""

    def test_basic_success(self) -> None:
        req = _make_request(name="get-users")
        result = _make_result(req)
        output = format_junit([(req, result)], file_path="test.http")

        assert output.startswith('<?xml version="1.0"')
        root = ET.fromstring(output)
        assert root.tag == "testsuite"
        assert root.get("tests") == "1"
        assert root.get("failures") == "0"
        assert root.get("errors") == "0"

        testcases = root.findall("testcase")
        assert len(testcases) == 1
        assert testcases[0].get("name") == "get-users"

    def test_error_result(self) -> None:
        req = _make_request(name="fail-req")
        result = _make_result(req, status_code=0, error="Connection refused")
        output = format_junit([(req, result)])

        root = ET.fromstring(output)
        assert root.get("errors") == "1"
        error_el = root.find(".//error")
        assert error_el is not None
        assert error_el.get("message") == "Connection refused"

    def test_failed_tests(self) -> None:
        req = _make_request(name="test-req")
        script = ScriptResult(
            tests=[
                ScriptTestResult(name="status is 200", passed=True),
                ScriptTestResult(name="body check", passed=False, error="mismatch"),
            ]
        )
        result = _make_result(req, script_result=script)
        output = format_junit([(req, result)])

        root = ET.fromstring(output)
        assert root.get("failures") == "1"
        failure_el = root.find(".//failure")
        assert failure_el is not None
        assert "body check" in (failure_el.get("message") or "")

    def test_system_out_for_tests(self) -> None:
        req = _make_request(name="test-req")
        script = ScriptResult(tests=[ScriptTestResult(name="check ok", passed=True)])
        result = _make_result(req, script_result=script)
        output = format_junit([(req, result)])

        root = ET.fromstring(output)
        sysout = root.find(".//system-out")
        assert sysout is not None
        assert "[PASS] check ok" in (sysout.text or "")

    def test_multiple_results(self) -> None:
        req1 = _make_request(name="first")
        req2 = _make_request(name="second")
        r1 = _make_result(req1)
        r2 = _make_result(req2, error="timeout")
        output = format_junit([(req1, r1), (req2, r2)])

        root = ET.fromstring(output)
        assert root.get("tests") == "2"
        testcases = root.findall("testcase")
        assert len(testcases) == 2

    def test_time_attribute(self) -> None:
        req = _make_request(name="timed")
        result = _make_result(req, elapsed_ms=1500.0)
        output = format_junit([(req, result)])

        root = ET.fromstring(output)
        tc = root.find("testcase")
        assert tc is not None
        assert tc.get("time") == "1.500"


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


class TestFormatMarkdown:
    """Tests for Markdown report output."""

    def test_basic_success(self) -> None:
        req = _make_request(name="get-users")
        result = _make_result(req)
        output = format_markdown([(req, result)], file_path="test.http")

        assert "# Test Report: test.http" in output
        assert "**Passed**: 1" in output
        assert "**Failed**: 0" in output
        assert "get-users" in output
        assert "v PASS" in output

    def test_failure_section(self) -> None:
        req = _make_request(name="bad-req")
        result = _make_result(req, error="timeout")
        output = format_markdown([(req, result)])

        assert "**Failed**: 1" in output
        assert "x FAIL" in output
        assert "## Failures" in output
        assert "### bad-req" in output
        assert "timeout" in output

    def test_failed_tests_in_failure_section(self) -> None:
        req = _make_request(name="test-req")
        script = ScriptResult(
            tests=[
                ScriptTestResult(name="check a", passed=True),
                ScriptTestResult(name="check b", passed=False, error="wrong value"),
            ]
        )
        result = _make_result(req, script_result=script)
        output = format_markdown([(req, result)])

        assert "## Failures" in output
        assert "**FAIL**: check b" in output
        assert "wrong value" in output

    def test_no_failures_section_when_all_pass(self) -> None:
        req = _make_request(name="ok")
        result = _make_result(req)
        output = format_markdown([(req, result)])

        assert "## Failures" not in output

    def test_table_header_present(self) -> None:
        req = _make_request(name="ok")
        result = _make_result(req)
        output = format_markdown([(req, result)])

        assert "| Status | Request | Method | Status Code | Time |" in output

    def test_no_file_path(self) -> None:
        req = _make_request()
        result = _make_result(req)
        output = format_markdown([(req, result)])

        assert "# Test Report" in output
        # Should not have "Test Report: " with trailing colon and nothing
        assert "Test Report:" not in output
