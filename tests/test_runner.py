"""Tests for the request orchestration runner and variable chaining."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock  # noqa: TC002

from fling.core.models import (
    ExecutionResult,
    Header,
    HttpFile,
    HttpMethod,
    HttpRequestDefinition,
    RequestBody,
    RequestMetadata,
    SourceLocation,
    VariableDefinition,
)
from fling.core.parser import parse_http_file
from fling.core.runner import (
    CyclicDependencyError,
    HttpRunner,
    RunnerError,
    build_dependency_graph,
    topological_sort,
)
from fling.core.variables import VariableResolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOC = SourceLocation(file_path="test.http", start_line=1, end_line=1)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _make_request(
    name: str | None = None,
    method: HttpMethod = HttpMethod.GET,
    url: str = "https://api.example.com/test",
    *,
    refs: list[str] | None = None,
    headers: list[Header] | None = None,
    body: RequestBody | None = None,
    disabled: bool = False,
    response_save_path: str | None = None,
) -> HttpRequestDefinition:
    """Create a minimal HttpRequestDefinition for testing."""
    return HttpRequestDefinition(
        method=method,
        url=url,
        headers=headers or [],
        body=body,
        metadata=RequestMetadata(
            name=name,
            refs=refs or [],
            disabled=disabled,
        ),
        response_save_path=response_save_path,
        location=_LOC,
    )


def _make_http_file(
    requests: list[HttpRequestDefinition],
    variables: list[VariableDefinition] | None = None,
) -> HttpFile:
    """Create an HttpFile for testing."""
    return HttpFile(
        file_path="test.http",
        requests=requests,
        variables=variables or [],
    )


def _make_result(
    request: HttpRequestDefinition,
    status_code: int = 200,
    response_body: str = "",
    response_headers: dict[str, list[str]] | None = None,
) -> ExecutionResult:
    """Create an ExecutionResult for testing."""
    return ExecutionResult(
        request=request,
        resolved_url=request.url,
        status_code=status_code,
        response_body=response_body,
        response_headers=response_headers or {},
    )


# ---------------------------------------------------------------------------
# Dependency graph tests
# ---------------------------------------------------------------------------


class TestBuildDependencyGraph:
    """Tests for build_dependency_graph()."""

    def test_no_dependencies(self) -> None:
        """Requests with no @ref or chaining have empty dep sets."""
        req_a = _make_request(name="a")
        req_b = _make_request(name="b")
        http_file = _make_http_file([req_a, req_b])

        graph = build_dependency_graph(http_file)

        assert graph == {"a": set(), "b": set()}

    def test_explicit_ref_dependency(self) -> None:
        """@ref creates an explicit dependency."""
        req_login = _make_request(name="login")
        req_profile = _make_request(name="get-profile", refs=["login"])
        http_file = _make_http_file([req_login, req_profile])

        graph = build_dependency_graph(http_file)

        assert graph["login"] == set()
        assert graph["get-profile"] == {"login"}

    def test_implicit_chaining_dependency(self) -> None:
        """{{name.response...}} creates an implicit dependency."""
        req_login = _make_request(name="login")
        req_profile = _make_request(
            name="get-profile",
            url="https://api.example.com/profile",
            headers=[Header(name="Authorization", value="Bearer {{login.response.body.$.token}}")],
        )
        http_file = _make_http_file([req_login, req_profile])

        graph = build_dependency_graph(http_file)

        assert "login" in graph["get-profile"]

    def test_implicit_dep_in_body(self) -> None:
        """Chaining references in the body create dependencies."""
        req_login = _make_request(name="login")
        req_update = _make_request(
            name="update",
            body=RequestBody(content='{"email": "{{login.response.body.$.email}}"}'),
        )
        http_file = _make_http_file([req_login, req_update])

        graph = build_dependency_graph(http_file)

        assert "login" in graph["update"]

    def test_unnamed_requests_excluded(self) -> None:
        """Unnamed requests don't appear in the dependency graph."""
        req_named = _make_request(name="named")
        req_unnamed = _make_request()
        http_file = _make_http_file([req_named, req_unnamed])

        graph = build_dependency_graph(http_file)

        assert "named" in graph
        assert len(graph) == 1

    def test_unknown_ref_is_warned(self) -> None:
        """@ref pointing to non-existent request is ignored (but logged)."""
        req = _make_request(name="test", refs=["nonexistent"])
        http_file = _make_http_file([req])

        graph = build_dependency_graph(http_file)

        assert graph["test"] == set()

    def test_self_reference_removed(self) -> None:
        """A request referencing itself doesn't create a self-dep."""
        req = _make_request(
            name="self",
            headers=[Header(name="X-Prev", value="{{self.response.headers.X-Id}}")],
        )
        http_file = _make_http_file([req])

        graph = build_dependency_graph(http_file)

        assert graph["self"] == set()

    def test_multi_level_chain(self) -> None:
        """Three-level dependency chain: a -> b -> c."""
        req_a = _make_request(name="a")
        req_b = _make_request(name="b", refs=["a"])
        req_c = _make_request(name="c", refs=["b"])
        http_file = _make_http_file([req_a, req_b, req_c])

        graph = build_dependency_graph(http_file)

        assert graph == {"a": set(), "b": {"a"}, "c": {"b"}}


# ---------------------------------------------------------------------------
# Topological sort tests
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    """Tests for topological_sort()."""

    def test_no_deps(self) -> None:
        """Nodes with no dependencies are sorted alphabetically."""
        graph = {"c": set(), "a": set(), "b": set()}
        result = topological_sort(graph)
        assert result == ["a", "b", "c"]

    def test_linear_chain(self) -> None:
        """Linear dependency: a -> b -> c."""
        graph = {"a": set(), "b": {"a"}, "c": {"b"}}
        result = topological_sort(graph)
        assert result == ["a", "b", "c"]

    def test_diamond_dependency(self) -> None:
        """Diamond: a -> b, a -> c, b -> d, c -> d."""
        graph = {"a": set(), "b": {"a"}, "c": {"a"}, "d": {"b", "c"}}
        result = topological_sort(graph)

        # a must be first, d must be last, b and c in between
        assert result[0] == "a"
        assert result[-1] == "d"
        assert set(result[1:3]) == {"b", "c"}

    def test_cycle_detection(self) -> None:
        """Cyclic dependency raises CyclicDependencyError."""
        graph = {"a": {"b"}, "b": {"a"}}
        with pytest.raises(CyclicDependencyError, match="Cyclic dependency"):
            topological_sort(graph)

    def test_three_node_cycle(self) -> None:
        """Three-node cycle: a -> b -> c -> a."""
        graph = {"a": {"c"}, "b": {"a"}, "c": {"b"}}
        with pytest.raises(CyclicDependencyError):
            topological_sort(graph)

    def test_empty_graph(self) -> None:
        """Empty graph returns empty list."""
        assert topological_sort({}) == []

    def test_single_node(self) -> None:
        """Single node with no deps."""
        assert topological_sort({"a": set()}) == ["a"]


# ---------------------------------------------------------------------------
# Variable chaining tests
# ---------------------------------------------------------------------------


class TestVariableChaining:
    """Tests for chaining reference resolution in VariableResolver."""

    def test_resolve_body_jsonpath(self) -> None:
        """Resolve {{name.response.body.$.token}} from stored result."""
        resolver = VariableResolver()
        req = _make_request(name="login")
        result = _make_result(req, response_body='{"token": "abc123", "expires": 3600}')
        resolver.add_chain_result("login", result)

        resolved = resolver.resolve_string("Bearer {{login.response.body.$.token}}")
        assert resolved == "Bearer abc123"

    def test_resolve_body_nested_jsonpath(self) -> None:
        """Resolve nested JSONPath like $.data.user.id."""
        resolver = VariableResolver()
        req = _make_request(name="login")
        result = _make_result(req, response_body='{"data": {"user": {"id": 42}}}')
        resolver.add_chain_result("login", result)

        resolved = resolver.resolve_string("{{login.response.body.$.data.user.id}}")
        assert resolved == "42"

    def test_resolve_header_reference(self) -> None:
        """Resolve {{name.response.headers.X-Token}} from stored result."""
        resolver = VariableResolver()
        req = _make_request(name="login")
        result = _make_result(
            req,
            response_headers={"X-Token": ["secret-header-value"]},
        )
        resolver.add_chain_result("login", result)

        resolved = resolver.resolve_string("{{login.response.headers.X-Token}}")
        assert resolved == "secret-header-value"

    def test_resolve_header_case_insensitive(self) -> None:
        """Header lookup is case-insensitive."""
        resolver = VariableResolver()
        req = _make_request(name="login")
        result = _make_result(
            req,
            response_headers={"content-type": ["application/json"]},
        )
        resolver.add_chain_result("login", result)

        resolved = resolver.resolve_string("{{login.response.headers.Content-Type}}")
        assert resolved == "application/json"

    def test_missing_chain_result(self) -> None:
        """Unresolved chaining reference is left as-is."""
        resolver = VariableResolver()
        resolved = resolver.resolve_string("{{missing.response.body.$.token}}")
        assert resolved == "{{missing.response.body.$.token}}"

    def test_invalid_json_body(self) -> None:
        """Non-JSON body leaves the reference unresolved."""
        resolver = VariableResolver()
        req = _make_request(name="login")
        result = _make_result(req, response_body="not json")
        resolver.add_chain_result("login", result)

        resolved = resolver.resolve_string("{{login.response.body.$.token}}")
        assert resolved == "{{login.response.body.$.token}}"

    def test_jsonpath_no_match(self) -> None:
        """JSONPath that doesn't match leaves reference unresolved."""
        resolver = VariableResolver()
        req = _make_request(name="login")
        result = _make_result(req, response_body='{"other": "value"}')
        resolver.add_chain_result("login", result)

        resolved = resolver.resolve_string("{{login.response.body.$.token}}")
        assert resolved == "{{login.response.body.$.token}}"

    def test_missing_header(self) -> None:
        """Missing header leaves reference unresolved."""
        resolver = VariableResolver()
        req = _make_request(name="login")
        result = _make_result(req, response_headers={})
        resolver.add_chain_result("login", result)

        resolved = resolver.resolve_string("{{login.response.headers.X-Missing}}")
        assert resolved == "{{login.response.headers.X-Missing}}"

    def test_numeric_jsonpath_value(self) -> None:
        """Numeric values are converted to strings."""
        resolver = VariableResolver()
        req = _make_request(name="data")
        result = _make_result(req, response_body='{"count": 42}')
        resolver.add_chain_result("data", result)

        resolved = resolver.resolve_string("{{data.response.body.$.count}}")
        assert resolved == "42"

    def test_boolean_jsonpath_value(self) -> None:
        """Boolean values are converted to lowercase strings."""
        resolver = VariableResolver()
        req = _make_request(name="data")
        result = _make_result(req, response_body='{"active": true}')
        resolver.add_chain_result("data", result)

        resolved = resolver.resolve_string("{{data.response.body.$.active}}")
        assert resolved == "true"

    def test_multiple_chaining_refs_in_one_string(self) -> None:
        """Multiple chaining references in one string are all resolved."""
        resolver = VariableResolver()
        req = _make_request(name="login")
        result = _make_result(
            req,
            response_body='{"token": "abc", "user": "admin"}',
            response_headers={"X-Id": ["req-123"]},
        )
        resolver.add_chain_result("login", result)

        resolved = resolver.resolve_string("token={{login.response.body.$.token}}&id={{login.response.headers.X-Id}}")
        assert resolved == "token=abc&id=req-123"


# ---------------------------------------------------------------------------
# HttpRunner integration tests
# ---------------------------------------------------------------------------


class TestHttpRunner:
    """Integration tests for HttpRunner."""

    @pytest.mark.asyncio
    async def test_run_all_simple(self, httpx_mock: HTTPXMock) -> None:
        """Run all requests from a simple file with no dependencies."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)

        req = _make_request(name="simple", url="https://api.example.com/test")
        http_file = _make_http_file([req])

        runner = HttpRunner()
        results = []
        async for request, result in runner.run_all(http_file):
            results.append((request, result))

        assert len(results) == 1
        assert results[0][1].status_code == 200

    @pytest.mark.asyncio
    async def test_run_all_skips_disabled(self, httpx_mock: HTTPXMock) -> None:
        """Disabled requests are skipped."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)

        req_a = _make_request(name="a", url="https://api.example.com/a")
        req_b = _make_request(name="b", url="https://api.example.com/b", disabled=True)
        http_file = _make_http_file([req_a, req_b])

        runner = HttpRunner()
        results = []
        async for request, result in runner.run_all(http_file):
            results.append((request, result))

        assert len(results) == 1
        assert results[0][0].metadata.name == "a"

    @pytest.mark.asyncio
    async def test_run_all_dependency_order(self, httpx_mock: HTTPXMock) -> None:
        """Requests execute in dependency order."""
        httpx_mock.add_response(json={"token": "t1"}, status_code=200)
        httpx_mock.add_response(json={"profile": "data"}, status_code=200)

        req_login = _make_request(name="login", url="https://api.example.com/login")
        req_profile = _make_request(
            name="profile",
            url="https://api.example.com/profile",
            refs=["login"],
        )
        # Put profile first in the list — should still execute login first
        http_file = _make_http_file([req_profile, req_login])

        runner = HttpRunner()
        order = []
        async for request, _result in runner.run_all(http_file):
            order.append(request.metadata.name)

        assert order == ["login", "profile"]

    @pytest.mark.asyncio
    async def test_run_all_chaining_resolves(self, httpx_mock: HTTPXMock) -> None:
        """Chaining variables are resolved from previous request results."""
        # Login returns a token
        httpx_mock.add_response(
            json={"token": "my-secret-token"},
            status_code=200,
        )
        # Profile request succeeds
        httpx_mock.add_response(json={"name": "Admin"}, status_code=200)

        req_login = _make_request(
            name="login",
            method=HttpMethod.POST,
            url="https://api.example.com/login",
        )
        req_profile = _make_request(
            name="profile",
            url="https://api.example.com/profile",
            refs=["login"],
            headers=[
                Header(
                    name="Authorization",
                    value="Bearer {{login.response.body.$.token}}",
                )
            ],
        )
        http_file = _make_http_file([req_login, req_profile])

        runner = HttpRunner()
        results = []
        async for _request, result in runner.run_all(http_file):
            results.append(result)

        # Profile should have been called with the resolved header
        assert results[1].resolved_headers["Authorization"] == "Bearer my-secret-token"

    @pytest.mark.asyncio
    async def test_run_all_unnamed_after_named(self, httpx_mock: HTTPXMock) -> None:
        """Unnamed requests run after all named requests."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)
        httpx_mock.add_response(json={"ok": True}, status_code=200)

        req_named = _make_request(name="named", url="https://api.example.com/named")
        req_unnamed = _make_request(url="https://api.example.com/unnamed")
        # Put unnamed first — should still execute after named
        http_file = _make_http_file([req_unnamed, req_named])

        runner = HttpRunner()
        order = []
        async for request, _result in runner.run_all(http_file):
            order.append(request.metadata.name)

        assert order == ["named", None]

    @pytest.mark.asyncio
    async def test_run_single(self, httpx_mock: HTTPXMock) -> None:
        """Run a single named request."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)

        req_a = _make_request(name="a", url="https://api.example.com/a")
        req_b = _make_request(name="b", url="https://api.example.com/b")
        http_file = _make_http_file([req_a, req_b])

        runner = HttpRunner()
        results = []
        async for request, _result in runner.run_single(http_file, "a"):
            results.append(request.metadata.name)

        assert results == ["a"]

    @pytest.mark.asyncio
    async def test_run_single_with_deps(self, httpx_mock: HTTPXMock) -> None:
        """run_single executes dependencies first."""
        httpx_mock.add_response(json={"token": "t"}, status_code=200)
        httpx_mock.add_response(json={"data": "ok"}, status_code=200)

        req_a = _make_request(name="a", url="https://api.example.com/a")
        req_b = _make_request(name="b", url="https://api.example.com/b", refs=["a"])
        req_c = _make_request(name="c", url="https://api.example.com/c")
        http_file = _make_http_file([req_a, req_b, req_c])

        runner = HttpRunner()
        order = []
        async for request, _result in runner.run_single(http_file, "b"):
            order.append(request.metadata.name)

        # Should execute a then b, skip c
        assert order == ["a", "b"]

    @pytest.mark.asyncio
    async def test_run_single_not_found(self) -> None:
        """run_single raises RunnerError for unknown request."""
        http_file = _make_http_file([])
        runner = HttpRunner()

        with pytest.raises(RunnerError, match="not found"):
            async for _ in runner.run_single(http_file, "missing"):
                pass

    @pytest.mark.asyncio
    async def test_results_stored(self, httpx_mock: HTTPXMock) -> None:
        """Results are stored and accessible via runner.results."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)

        req = _make_request(name="test", url="https://api.example.com/test")
        http_file = _make_http_file([req])

        runner = HttpRunner()
        async for _ in runner.run_all(http_file):
            pass

        assert "test" in runner.results
        assert runner.get_result("test") is not None
        assert runner.get_result("test").status_code == 200

    @pytest.mark.asyncio
    async def test_get_result_missing(self) -> None:
        """get_result returns None for unexecuted request."""
        runner = HttpRunner()
        assert runner.get_result("nonexistent") is None

    @pytest.mark.asyncio
    async def test_variable_resolution_in_url(self, httpx_mock: HTTPXMock) -> None:
        """File-level variables are resolved in URLs."""
        httpx_mock.add_response(json={"ok": True}, status_code=200)

        req = _make_request(name="test", url="https://{{host}}/api")
        var = VariableDefinition(
            name="host",
            value="api.example.com",
            location=_LOC,
        )
        http_file = _make_http_file([req], variables=[var])

        runner = HttpRunner()
        async for _request, result in runner.run_all(http_file):
            assert result.resolved_url == "https://api.example.com/api"


# ---------------------------------------------------------------------------
# Parser integration with chaining fixture
# ---------------------------------------------------------------------------


class TestChainingFixture:
    """Tests using the chaining.http fixture file."""

    def test_parse_chaining_fixture(self) -> None:
        """chaining.http parses correctly."""
        result = parse_http_file(str(FIXTURES_DIR / "chaining.http"))
        assert not result.has_errors
        assert len(result.http_file.requests) == 5

        named = result.http_file.named_requests
        assert "login" in named
        assert "get-profile" in named
        assert "update-profile" in named
        assert "disabled-request" in named

    def test_chaining_fixture_dependency_graph(self) -> None:
        """Dependency graph is built correctly from the fixture."""
        result = parse_http_file(str(FIXTURES_DIR / "chaining.http"))
        graph = build_dependency_graph(result.http_file)

        assert graph["login"] == set()
        assert "login" in graph["get-profile"]
        assert "login" in graph["update-profile"]
        assert "get-profile" in graph["update-profile"]

    def test_chaining_fixture_topo_sort(self) -> None:
        """Topological sort produces valid execution order."""
        result = parse_http_file(str(FIXTURES_DIR / "chaining.http"))
        graph = build_dependency_graph(result.http_file)
        order = topological_sort(graph)

        # login must come before get-profile and update-profile
        assert order.index("login") < order.index("get-profile")
        assert order.index("login") < order.index("update-profile")
        # get-profile must come before update-profile
        assert order.index("get-profile") < order.index("update-profile")

    @pytest.mark.asyncio
    async def test_chaining_fixture_full_run(self, httpx_mock: HTTPXMock) -> None:
        """Full run of chaining.http with mocked responses."""
        # Login response
        httpx_mock.add_response(
            json={"token": "jwt-token-123"},
            status_code=200,
            headers={"X-Request-Id": "req-001"},
        )
        # Get profile response
        httpx_mock.add_response(
            json={"email": "admin@example.com", "name": "Admin"},
            status_code=200,
        )
        # Update profile response
        httpx_mock.add_response(
            json={"updated": True},
            status_code=200,
        )
        # Unnamed request response
        httpx_mock.add_response(
            json={"unnamed": True},
            status_code=200,
        )

        result = parse_http_file(str(FIXTURES_DIR / "chaining.http"))
        runner = HttpRunner()

        executed = []
        async for request, exec_result in runner.run_all(result.http_file):
            executed.append((request.metadata.name, exec_result))

        # disabled-request should be skipped
        names = [name for name, _ in executed]
        assert "disabled-request" not in names

        # Should have 4 results: login, get-profile, update-profile, unnamed
        assert len(executed) == 4
        assert names[0] == "login"
        assert names[1] == "get-profile"
        assert names[2] == "update-profile"
        assert names[3] is None  # unnamed

        # Verify chaining worked: get-profile got the token
        profile_result = executed[1][1]
        assert profile_result.resolved_headers["Authorization"] == "Bearer jwt-token-123"

        # Verify update-profile got both token and X-Request-Id header
        update_result = executed[2][1]
        assert update_result.resolved_headers["Authorization"] == "Bearer jwt-token-123"
        assert update_result.resolved_headers["X-Request-Id"] == "req-001"


# ---------------------------------------------------------------------------
# Response save tests
# ---------------------------------------------------------------------------


class TestResponseSave:
    """Tests for response save directives (>> and >>!)."""

    @pytest.mark.asyncio
    async def test_save_response_new_file(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        """>> saves the response body to a file."""
        httpx_mock.add_response(text='{"saved": true}', status_code=200)

        source_file = str(tmp_path / "test.http")
        req = _make_request(
            name="save-test",
            url="https://api.example.com/test",
            response_save_path="output.json",
        )
        req = req.model_copy(update={"location": SourceLocation(file_path=source_file, start_line=1, end_line=1)})
        http_file = _make_http_file([req])

        runner = HttpRunner()
        async for _ in runner.run_all(http_file):
            pass

        saved_file = tmp_path / "output.json"
        assert saved_file.exists()
        assert json.loads(saved_file.read_text()) == {"saved": True}

    @pytest.mark.asyncio
    async def test_save_response_no_overwrite(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        """>> without ! does not overwrite existing files."""
        httpx_mock.add_response(text="new content", status_code=200)

        existing = tmp_path / "output.json"
        existing.write_text("original content")

        source_file = str(tmp_path / "test.http")
        req = _make_request(
            name="save-test",
            url="https://api.example.com/test",
            response_save_path="output.json",
        )
        req = req.model_copy(update={"location": SourceLocation(file_path=source_file, start_line=1, end_line=1)})
        http_file = _make_http_file([req])

        runner = HttpRunner()
        async for _ in runner.run_all(http_file):
            pass

        # Original content should be preserved
        assert existing.read_text() == "original content"

    @pytest.mark.asyncio
    async def test_save_response_force_overwrite(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        """>>! (force) overwrites existing files."""
        httpx_mock.add_response(text="new content", status_code=200)

        existing = tmp_path / "output.json"
        existing.write_text("original content")

        source_file = str(tmp_path / "test.http")
        req = _make_request(
            name="save-test",
            url="https://api.example.com/test",
            response_save_path="!output.json",
        )
        req = req.model_copy(update={"location": SourceLocation(file_path=source_file, start_line=1, end_line=1)})
        http_file = _make_http_file([req])

        runner = HttpRunner()
        async for _ in runner.run_all(http_file):
            pass

        assert existing.read_text() == "new content"
