"""Tests for fling.core.models."""

from fling.core.models import (
    EnvironmentFile,
    ExecutionResult,
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


class TestHttpMethod:
    def test_enum_values(self) -> None:
        assert HttpMethod.GET == "GET"
        assert HttpMethod.POST == "POST"
        assert HttpMethod.DELETE == "DELETE"
        assert HttpMethod.PATCH == "PATCH"
        assert HttpMethod.PUT == "PUT"
        assert HttpMethod.HEAD == "HEAD"
        assert HttpMethod.OPTIONS == "OPTIONS"
        assert HttpMethod.TRACE == "TRACE"
        assert HttpMethod.CONNECT == "CONNECT"

    def test_from_string(self) -> None:
        assert HttpMethod("GET") == HttpMethod.GET
        assert HttpMethod("POST") == HttpMethod.POST


class TestSourceLocation:
    def test_creation(self) -> None:
        loc = SourceLocation(file_path="test.http", start_line=1, end_line=5)
        assert loc.file_path == "test.http"
        assert loc.start_line == 1
        assert loc.end_line == 5

    def test_serialization(self) -> None:
        loc = SourceLocation(file_path="test.http", start_line=1, end_line=5)
        data = loc.model_dump()
        assert data == {"file_path": "test.http", "start_line": 1, "end_line": 5}
        restored = SourceLocation.model_validate(data)
        assert restored == loc


class TestRequestMetadata:
    def test_defaults(self) -> None:
        meta = RequestMetadata()
        assert meta.name is None
        assert meta.refs == []
        assert meta.no_redirect is False
        assert meta.no_cookie_jar is False
        assert meta.timeout_ms is None
        assert meta.disabled is False
        assert meta.prompt_vars == {}
        assert meta.note is None

    def test_full_metadata(self) -> None:
        meta = RequestMetadata(
            name="login",
            refs=["setup"],
            no_redirect=True,
            no_cookie_jar=True,
            timeout_ms=5000,
            disabled=False,
            prompt_vars={"username": "Enter username"},
            note="This is the login request",
        )
        assert meta.name == "login"
        assert meta.refs == ["setup"]
        assert meta.no_redirect is True
        assert meta.timeout_ms == 5000
        assert meta.prompt_vars == {"username": "Enter username"}


class TestHeader:
    def test_creation(self) -> None:
        h = Header(name="Content-Type", value="application/json")
        assert h.name == "Content-Type"
        assert h.value == "application/json"

    def test_with_variable(self) -> None:
        h = Header(name="Authorization", value="Bearer {{token}}")
        assert "{{token}}" in h.value


class TestRequestBody:
    def test_defaults(self) -> None:
        body = RequestBody()
        assert body.content == ""
        assert body.file_ref is None
        assert body.is_graphql is False

    def test_with_content(self) -> None:
        body = RequestBody(content='{"key": "value"}')
        assert body.content == '{"key": "value"}'

    def test_with_file_ref(self) -> None:
        body = RequestBody(file_ref="./data.json")
        assert body.file_ref == "./data.json"

    def test_graphql(self) -> None:
        body = RequestBody(content="query { users { id } }", is_graphql=True)
        assert body.is_graphql is True


class TestResponseHandler:
    def test_inline_script(self) -> None:
        handler = ResponseHandler(inline_script="client.test('status', () => response.status == 200)")
        assert handler.inline_script is not None
        assert handler.file_ref is None

    def test_file_ref(self) -> None:
        handler = ResponseHandler(file_ref="./handler.js")
        assert handler.file_ref == "./handler.js"
        assert handler.inline_script is None


class TestHttpRequestDefinition:
    def test_minimal_request(self) -> None:
        req = HttpRequestDefinition(
            url="https://example.com/api",
            location=SourceLocation(file_path="test.http", start_line=1, end_line=1),
        )
        assert req.method == HttpMethod.GET
        assert req.url == "https://example.com/api"
        assert req.http_version is None
        assert req.headers == []
        assert req.body is None
        assert req.metadata.name is None
        assert req.response_handler is None
        assert req.response_save_path is None
        assert req.pre_request_script is None
        assert req.comments == []

    def test_full_request(self) -> None:
        req = HttpRequestDefinition(
            method=HttpMethod.POST,
            url="https://api.example.com/login",
            http_version="HTTP/1.1",
            headers=[
                Header(name="Content-Type", value="application/json"),
                Header(name="Authorization", value="Bearer {{token}}"),
            ],
            body=RequestBody(content='{"user": "admin"}'),
            metadata=RequestMetadata(name="login", timeout_ms=3000),
            response_handler=ResponseHandler(inline_script="assert response.status == 200"),
            response_save_path="response.json",
            pre_request_script="print('starting')",
            location=SourceLocation(file_path="test.http", start_line=1, end_line=10),
            comments=["# Login request"],
        )
        assert req.method == HttpMethod.POST
        assert len(req.headers) == 2
        assert req.body is not None
        assert req.body.content == '{"user": "admin"}'
        assert req.metadata.name == "login"
        assert req.response_save_path == "response.json"


class TestVariableDefinition:
    def test_creation(self) -> None:
        var = VariableDefinition(
            name="baseUrl",
            value="https://api.example.com",
            location=SourceLocation(file_path="test.http", start_line=1, end_line=1),
        )
        assert var.name == "baseUrl"
        assert var.value == "https://api.example.com"

    def test_variable_with_template(self) -> None:
        var = VariableDefinition(
            name="authUrl",
            value="{{baseUrl}}/auth",
            location=SourceLocation(file_path="test.http", start_line=2, end_line=2),
        )
        assert "{{baseUrl}}" in var.value


class TestHttpFile:
    def test_empty_file(self) -> None:
        hf = HttpFile(file_path="test.http")
        assert hf.file_path == "test.http"
        assert hf.variables == []
        assert hf.requests == []
        assert hf.named_requests == {}

    def test_named_requests_property(self) -> None:
        loc = SourceLocation(file_path="test.http", start_line=1, end_line=1)
        hf = HttpFile(
            file_path="test.http",
            requests=[
                HttpRequestDefinition(
                    url="https://example.com/login",
                    metadata=RequestMetadata(name="login"),
                    location=loc,
                ),
                HttpRequestDefinition(
                    url="https://example.com/users",
                    location=loc,
                ),
                HttpRequestDefinition(
                    url="https://example.com/profile",
                    metadata=RequestMetadata(name="profile"),
                    location=loc,
                ),
            ],
        )
        named = hf.named_requests
        assert len(named) == 2
        assert "login" in named
        assert "profile" in named
        assert named["login"].url == "https://example.com/login"

    def test_with_variables(self) -> None:
        loc = SourceLocation(file_path="test.http", start_line=1, end_line=1)
        hf = HttpFile(
            file_path="test.http",
            variables=[
                VariableDefinition(name="host", value="localhost", location=loc),
                VariableDefinition(name="port", value="8080", location=loc),
            ],
        )
        assert len(hf.variables) == 2


class TestEnvironmentFile:
    def test_creation(self) -> None:
        env = EnvironmentFile(
            environments={
                "development": {"host": "localhost", "port": "8080"},
                "production": {"host": "api.example.com", "port": "443"},
            }
        )
        assert len(env.environments) == 2
        assert env.environments["development"]["host"] == "localhost"

    def test_empty(self) -> None:
        env = EnvironmentFile()
        assert env.environments == {}


class TestExecutionResult:
    def test_successful_result(self) -> None:
        loc = SourceLocation(file_path="test.http", start_line=1, end_line=1)
        req = HttpRequestDefinition(url="https://example.com", location=loc)
        result = ExecutionResult(
            request=req,
            resolved_url="https://example.com",
            resolved_headers={"Content-Type": "application/json"},
            status_code=200,
            response_headers={"content-type": ["application/json"]},
            response_body='{"ok": true}',
            elapsed_ms=123.45,
        )
        assert result.status_code == 200
        assert result.error is None
        assert result.elapsed_ms == 123.45

    def test_error_result(self) -> None:
        loc = SourceLocation(file_path="test.http", start_line=1, end_line=1)
        req = HttpRequestDefinition(url="https://example.com", location=loc)
        result = ExecutionResult(
            request=req,
            resolved_url="https://example.com",
            error="Connection refused",
        )
        assert result.status_code == 0
        assert result.error == "Connection refused"


class TestParseError:
    def test_with_location(self) -> None:
        err = ParseError(
            message="Invalid request line",
            location=SourceLocation(file_path="test.http", start_line=5, end_line=5),
        )
        assert err.message == "Invalid request line"
        assert err.location is not None
        assert err.location.start_line == 5

    def test_without_location(self) -> None:
        err = ParseError(message="Unexpected EOF")
        assert err.location is None


class TestParseResult:
    def test_no_errors(self) -> None:
        result = ParseResult(http_file=HttpFile(file_path="test.http"))
        assert result.has_errors is False
        assert result.errors == []

    def test_with_errors(self) -> None:
        result = ParseResult(
            http_file=HttpFile(file_path="test.http"),
            errors=[ParseError(message="Bad syntax")],
        )
        assert result.has_errors is True
        assert len(result.errors) == 1

    def test_serialization_roundtrip(self) -> None:
        loc = SourceLocation(file_path="test.http", start_line=1, end_line=1)
        result = ParseResult(
            http_file=HttpFile(
                file_path="test.http",
                requests=[
                    HttpRequestDefinition(
                        method=HttpMethod.GET,
                        url="https://example.com",
                        location=loc,
                    )
                ],
            )
        )
        data = result.model_dump()
        restored = ParseResult.model_validate(data)
        assert restored.http_file.file_path == "test.http"
        assert len(restored.http_file.requests) == 1
        assert restored.http_file.requests[0].url == "https://example.com"
