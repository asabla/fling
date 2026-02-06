"""Tests for fling.core.scripting — response handler scripting engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fling.core.models import (
    ExecutionResult,
    HttpMethod,
    HttpRequestDefinition,
    ResponseHandler,
    ScriptResult,
    ScriptTestResult,
    SourceLocation,
)
from fling.core.scripting import (
    _ClientObject,
    _GlobalStore,
    _ResponseObject,
    execute_handler,
    transpile_js_to_python,
)

if TYPE_CHECKING:
    from pathlib import Path

_LOC = SourceLocation(file_path="test.http", start_line=1, end_line=1)


def _make_result(
    *,
    status_code: int = 200,
    body: str = "",
    headers: dict[str, list[str]] | None = None,
) -> ExecutionResult:
    """Create a minimal ExecutionResult for testing."""
    request = HttpRequestDefinition(
        method=HttpMethod.GET,
        url="https://example.com",
        location=_LOC,
    )
    return ExecutionResult(
        request=request,
        resolved_url="https://example.com",
        status_code=status_code,
        response_body=body,
        response_headers=headers or {},
    )


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestScriptTestResult:
    def test_passed_result(self) -> None:
        r = ScriptTestResult(name="test1", passed=True)
        assert r.name == "test1"
        assert r.passed is True
        assert r.error is None

    def test_failed_result(self) -> None:
        r = ScriptTestResult(name="test2", passed=False, error="boom")
        assert r.passed is False
        assert r.error == "boom"


class TestScriptResult:
    def test_empty_result(self) -> None:
        r = ScriptResult()
        assert r.tests == []
        assert r.global_vars == {}
        assert r.warnings == []
        assert r.error is None
        assert r.all_passed is True

    def test_all_passed(self) -> None:
        r = ScriptResult(
            tests=[
                ScriptTestResult(name="a", passed=True),
                ScriptTestResult(name="b", passed=True),
            ]
        )
        assert r.all_passed is True

    def test_some_failed(self) -> None:
        r = ScriptResult(
            tests=[
                ScriptTestResult(name="a", passed=True),
                ScriptTestResult(name="b", passed=False, error="nope"),
            ]
        )
        assert r.all_passed is False

    def test_with_global_vars(self) -> None:
        r = ScriptResult(global_vars={"token": "abc123"})
        assert r.global_vars["token"] == "abc123"


# ---------------------------------------------------------------------------
# ResponseObject tests
# ---------------------------------------------------------------------------


class TestResponseObject:
    def test_status(self) -> None:
        result = _make_result(status_code=201)
        resp = _ResponseObject(result)
        assert resp.status == 201

    def test_json_body(self) -> None:
        result = _make_result(body='{"token": "abc", "count": 42}')
        resp = _ResponseObject(result)
        assert resp.body == {"token": "abc", "count": 42}

    def test_non_json_body(self) -> None:
        result = _make_result(body="plain text")
        resp = _ResponseObject(result)
        assert resp.body == "plain text"

    def test_empty_body(self) -> None:
        result = _make_result(body="")
        resp = _ResponseObject(result)
        assert resp.body is None

    def test_headers(self) -> None:
        result = _make_result(headers={"Content-Type": ["application/json"], "X-Custom": ["val1"]})
        resp = _ResponseObject(result)
        assert resp.headers["Content-Type"] == "application/json"
        assert resp.headers["X-Custom"] == "val1"

    def test_content_type(self) -> None:
        result = _make_result(headers={"content-type": ["text/html"]})
        resp = _ResponseObject(result)
        assert resp.content_type == "text/html"

    def test_content_type_missing(self) -> None:
        result = _make_result()
        resp = _ResponseObject(result)
        assert resp.content_type == ""


# ---------------------------------------------------------------------------
# GlobalStore tests
# ---------------------------------------------------------------------------


class TestGlobalStore:
    def test_set_and_get(self) -> None:
        store = _GlobalStore()
        store.set("key", "value")
        assert store.get("key") == "value"

    def test_get_default(self) -> None:
        store = _GlobalStore()
        assert store.get("missing") is None
        assert store.get("missing", "fallback") == "fallback"

    def test_variables_property(self) -> None:
        store = _GlobalStore()
        store.set("a", 1)
        store.set("b", 2)
        assert store.variables == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# ClientObject tests
# ---------------------------------------------------------------------------


class TestClientObject:
    def test_passing_test(self) -> None:
        client = _ClientObject()
        client.test("passes", lambda: None)
        assert len(client.tests) == 1
        assert client.tests[0].passed is True
        assert client.tests[0].name == "passes"

    def test_failing_test(self) -> None:
        client = _ClientObject()

        def fail() -> None:
            raise AssertionError("bad")

        client.test("fails", fail)
        assert len(client.tests) == 1
        assert client.tests[0].passed is False
        assert "bad" in (client.tests[0].error or "")

    def test_no_callback(self) -> None:
        client = _ClientObject()
        client.test("empty")
        assert client.tests[0].passed is True

    def test_assert_passes(self) -> None:
        client = _ClientObject()
        client.assert_(True)  # Should not raise

    def test_assert_fails(self) -> None:
        client = _ClientObject()
        try:
            client.assert_(False, "custom msg")
        except AssertionError as e:
            assert "custom msg" in str(e)
        else:
            raise AssertionError("Expected AssertionError")

    def test_globals_alias(self) -> None:
        client = _ClientObject()
        client.globals.set("x", 42)
        assert client.global_store.get("x") == 42


# ---------------------------------------------------------------------------
# Transpiler tests
# ---------------------------------------------------------------------------


class TestTranspileJsToPython:
    def test_triple_equals(self) -> None:
        code, _warnings = transpile_js_to_python("response.status === 200")
        assert "==" in code
        assert "===" not in code

    def test_not_equals(self) -> None:
        code, _ = transpile_js_to_python("x !== y")
        assert "!=" in code
        assert "!==" not in code

    def test_var_declaration(self) -> None:
        code, _ = transpile_js_to_python("var data = response.body;")
        assert code.strip() == "data = response.body"
        assert "var " not in code

    def test_let_declaration(self) -> None:
        code, _ = transpile_js_to_python("let x = 5;")
        assert code.strip() == "x = 5"

    def test_const_declaration(self) -> None:
        code, _ = transpile_js_to_python("const val = 10;")
        assert code.strip() == "val = 10"

    def test_client_assert_renamed(self) -> None:
        code, _ = transpile_js_to_python("client.assert(true);")
        assert "client.assert_(" in code

    def test_client_global_renamed(self) -> None:
        code, _ = transpile_js_to_python('client.global.set("key", "val");')
        assert 'client.globals.set("key", "val")' in code

    def test_response_body_field_access(self) -> None:
        code, _ = transpile_js_to_python("response.body.token")
        assert 'response.body["token"]' in code

    def test_response_body_chained_access(self) -> None:
        code, _ = transpile_js_to_python("response.body.data.status")
        assert 'response.body["data"]["status"]' in code

    def test_response_body_no_field(self) -> None:
        code, _ = transpile_js_to_python("response.body")
        assert code.strip() == "response.body"

    def test_single_line_client_test(self) -> None:
        code, _ = transpile_js_to_python(
            'client.test("Status OK", function() { client.assert(response.status === 200); });'
        )
        assert 'client.test("Status OK"' in code
        assert "client.assert_(" in code
        assert "==" in code

    def test_multiline_client_test(self) -> None:
        js = """client.test("Has data", function() {
    client.assert(data !== null);
});"""
        code, _ = transpile_js_to_python(js)
        assert 'client.test("Has data"' in code
        assert "client.assert_(" in code
        assert "!=" in code

    def test_comment_transpilation(self) -> None:
        code, _ = transpile_js_to_python("// this is a comment")
        assert code.strip().startswith("#")

    def test_empty_lines_preserved(self) -> None:
        code, _ = transpile_js_to_python("x = 1\n\ny = 2")
        lines = code.splitlines()
        assert lines[1] == ""

    def test_unsupported_construct_warning(self) -> None:
        _, warnings = transpile_js_to_python("for (var i = 0; i < 10; i++) {}")
        assert len(warnings) > 0
        assert "Unsupported" in warnings[0]

    def test_semicolon_removal(self) -> None:
        code, _ = transpile_js_to_python("x = 5;")
        assert code.strip() == "x = 5"

    def test_client_global_set_with_body_access(self) -> None:
        code, _ = transpile_js_to_python('client.global.set("lastStatus", response.body.status);')
        assert 'client.globals.set("lastStatus", response.body["status"])' in code


# ---------------------------------------------------------------------------
# execute_handler tests
# ---------------------------------------------------------------------------


class TestExecuteHandler:
    def test_inline_simple_assertion_pass(self) -> None:
        handler = ResponseHandler(inline_script="client.assert(response.status === 200);")
        result = _make_result(status_code=200)
        sr = execute_handler(handler, result, "test.http")
        assert sr.error is None

    def test_inline_simple_assertion_fail(self) -> None:
        handler = ResponseHandler(
            inline_script='client.test("check", function() { client.assert(response.status === 200); });'
        )
        result = _make_result(status_code=500)
        sr = execute_handler(handler, result, "test.http")
        assert len(sr.tests) == 1
        assert sr.tests[0].passed is False

    def test_inline_test_pass(self) -> None:
        handler = ResponseHandler(
            inline_script='client.test("Status OK", function() { client.assert(response.status === 200); });'
        )
        result = _make_result(status_code=200)
        sr = execute_handler(handler, result, "test.http")
        assert len(sr.tests) == 1
        assert sr.tests[0].name == "Status OK"
        assert sr.tests[0].passed is True

    def test_inline_global_set(self) -> None:
        handler = ResponseHandler(inline_script='client.global.set("token", response.body.token);')
        result = _make_result(body='{"token": "abc123"}')
        sr = execute_handler(handler, result, "test.http")
        assert sr.global_vars["token"] == "abc123"

    def test_inline_multiline(self) -> None:
        handler = ResponseHandler(
            inline_script="""var data = response.body;
client.test("Has data", function() {
    client.assert(data !== null);
});
client.global.set("lastStatus", data.status);"""
        )
        result = _make_result(body='{"status": "ok", "count": 5}')
        sr = execute_handler(handler, result, "test.http")
        assert len(sr.tests) == 1
        assert sr.tests[0].passed is True
        assert sr.global_vars["lastStatus"] == "ok"

    def test_inline_response_headers(self) -> None:
        handler = ResponseHandler(inline_script='client.global.set("ct", response.headers["Content-Type"]);')
        result = _make_result(headers={"Content-Type": ["application/json"]})
        sr = execute_handler(handler, result, "test.http")
        assert sr.global_vars["ct"] == "application/json"

    def test_file_ref_not_found(self) -> None:
        handler = ResponseHandler(file_ref="./nonexistent.js")
        result = _make_result()
        sr = execute_handler(handler, result, "test.http")
        assert sr.error is not None
        assert "not found" in sr.error

    def test_file_ref_loads_and_executes(self, tmp_path: Path) -> None:
        # Create a handler file
        handler_dir = tmp_path / "handlers"
        handler_dir.mkdir()
        handler_file = handler_dir / "check.js"
        handler_file.write_text('client.test("file test", function() { client.assert(response.status === 200); });')

        # Create a fake .http file path in tmp_path
        http_file = tmp_path / "test.http"
        http_file.write_text("")

        handler = ResponseHandler(file_ref="./handlers/check.js")
        result = _make_result(status_code=200)
        sr = execute_handler(handler, result, str(http_file))
        assert len(sr.tests) == 1
        assert sr.tests[0].name == "file test"
        assert sr.tests[0].passed is True

    def test_empty_handler(self) -> None:
        handler = ResponseHandler()
        result = _make_result()
        sr = execute_handler(handler, result, "test.http")
        assert sr.tests == []
        assert sr.global_vars == {}

    def test_script_execution_error(self) -> None:
        handler = ResponseHandler(inline_script="undefined_variable_xyz")
        result = _make_result()
        sr = execute_handler(handler, result, "test.http")
        assert sr.error is not None
        assert "Script execution error" in sr.error

    def test_multiple_tests(self) -> None:
        handler = ResponseHandler(
            inline_script="""client.test("test1", function() { client.assert(response.status === 200); });
client.test("test2", function() { client.assert(response.status === 200); });"""
        )
        result = _make_result(status_code=200)
        sr = execute_handler(handler, result, "test.http")
        assert len(sr.tests) == 2
        assert all(t.passed for t in sr.tests)

    def test_mixed_pass_and_fail(self) -> None:
        handler = ResponseHandler(
            inline_script="""client.test("pass", function() { client.assert(response.status === 200); });
client.test("fail", function() { client.assert(response.status === 404); });"""
        )
        result = _make_result(status_code=200)
        sr = execute_handler(handler, result, "test.http")
        assert len(sr.tests) == 2
        assert sr.tests[0].passed is True
        assert sr.tests[1].passed is False

    def test_body_json_path_access(self) -> None:
        handler = ResponseHandler(inline_script='client.global.set("name", response.body.user.name);')
        result = _make_result(body='{"user": {"name": "Alice"}}')
        sr = execute_handler(handler, result, "test.http")
        assert sr.global_vars["name"] == "Alice"

    def test_response_status_in_global(self) -> None:
        handler = ResponseHandler(inline_script='client.global.set("code", response.status);')
        result = _make_result(status_code=201)
        sr = execute_handler(handler, result, "test.http")
        assert sr.global_vars["code"] == 201


# ---------------------------------------------------------------------------
# Integration with ExecutionResult model
# ---------------------------------------------------------------------------


class TestExecutionResultScriptField:
    def test_default_none(self) -> None:
        result = _make_result()
        assert result.script_result is None

    def test_with_script_result(self) -> None:
        result = _make_result()
        result.script_result = ScriptResult(
            tests=[ScriptTestResult(name="t1", passed=True)],
            global_vars={"x": 1},
        )
        assert result.script_result is not None
        assert result.script_result.all_passed is True
        assert result.script_result.global_vars["x"] == 1

    def test_serialization_roundtrip(self) -> None:
        result = _make_result()
        result.script_result = ScriptResult(
            tests=[ScriptTestResult(name="t1", passed=True)],
            global_vars={"key": "val"},
            warnings=["some warning"],
        )
        data = result.model_dump()
        restored = ExecutionResult.model_validate(data)
        assert restored.script_result is not None
        assert restored.script_result.tests[0].name == "t1"
        assert restored.script_result.global_vars["key"] == "val"
        assert restored.script_result.warnings == ["some warning"]
