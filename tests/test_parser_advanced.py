"""Tests for fling.core.parser — advanced features."""

from pathlib import Path

from fling.core.models import HttpMethod
from fling.core.parser import parse_http_file, parse_http_string

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestMetadataComments:
    """Test parsing of metadata comments (@name, @ref, etc.)."""

    def test_name_metadata(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        req = result.http_file.requests[0]
        assert req.metadata.name == "login"

    def test_note_metadata(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        req = result.http_file.requests[0]
        assert req.metadata.note == "Authentication request"

    def test_timeout_metadata(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        req = result.http_file.requests[0]
        assert req.metadata.timeout_ms == 5000

    def test_ref_metadata(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        req = result.http_file.requests[1]  # getUsers
        assert req.metadata.name == "getUsers"
        assert "login" in req.metadata.refs

    def test_no_redirect_metadata(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        req = result.http_file.requests[1]  # getUsers
        assert req.metadata.no_redirect is True

    def test_no_cookie_jar_metadata(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        req = result.http_file.requests[2]  # createUser
        assert req.metadata.no_cookie_jar is True

    def test_disabled_metadata(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        req = result.http_file.requests[2]  # createUser
        assert req.metadata.disabled is True

    def test_prompt_metadata(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        req = result.http_file.requests[3]  # searchUsers
        assert req.metadata.name == "searchUsers"
        assert "query" in req.metadata.prompt_vars
        assert "limit" in req.metadata.prompt_vars
        assert req.metadata.prompt_vars["query"] == "Enter search query"
        assert req.metadata.prompt_vars["limit"] == "Enter result limit"

    def test_inline_metadata(self) -> None:
        content = "# @name test\n# @timeout 1000\n# @no-redirect\nGET https://example.com\n"
        result = parse_http_string(content)
        req = result.http_file.requests[0]
        assert req.metadata.name == "test"
        assert req.metadata.timeout_ms == 1000
        assert req.metadata.no_redirect is True


class TestMultilineUrls:
    """Test multiline URL with query parameters."""

    def test_query_params_in_advanced(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        req = result.http_file.requests[3]  # searchUsers
        assert "?q={{query}}" in req.url
        assert "&limit={{limit}}" in req.url

    def test_multiline_url_from_string(self) -> None:
        content = """GET https://example.com/api
    ?page=1
    &size=20
    &sort=name
"""
        result = parse_http_string(content)
        req = result.http_file.requests[0]
        assert "?page=1" in req.url
        assert "&size=20" in req.url
        assert "&sort=name" in req.url


class TestFileBodyReference:
    """Test file body reference (< ./file.json)."""

    def test_file_ref_parsing(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        req = result.http_file.requests[2]  # createUser
        assert req.body is not None
        assert req.body.file_ref == "./fixtures/new_user.json"

    def test_file_ref_from_string(self) -> None:
        content = "POST https://example.com\nContent-Type: application/json\n\n< ./data.json\n"
        result = parse_http_string(content)
        req = result.http_file.requests[0]
        assert req.body is not None
        assert req.body.file_ref == "./data.json"

    def test_file_refs_fixture(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "file_refs.http")
        assert len(result.http_file.requests) == 3
        # First has file ref
        assert result.http_file.requests[0].body is not None
        assert result.http_file.requests[0].body.file_ref == "./data/payload.json"
        # Second has inline body
        assert result.http_file.requests[1].body is not None
        assert result.http_file.requests[1].body.content == '{"key": "value"}'
        assert result.http_file.requests[1].body.file_ref is None


class TestResponseHandlers:
    """Test response handler parsing."""

    def test_multiline_handler(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        req = result.http_file.requests[0]  # login
        assert req.response_handler is not None
        assert req.response_handler.inline_script is not None
        assert "client.global.set" in req.response_handler.inline_script
        assert "client.test" in req.response_handler.inline_script

    def test_oneline_handler(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "response_handlers.http")
        req = result.http_file.requests[0]  # preRequestExample
        assert req.response_handler is not None
        assert req.response_handler.inline_script is not None
        assert "client.test" in req.response_handler.inline_script

    def test_multiline_handler_fixture(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "response_handlers.http")
        req = result.http_file.requests[1]  # multilineHandler
        assert req.response_handler is not None
        script = req.response_handler.inline_script
        assert script is not None
        assert "var data = response.body" in script
        assert "client.global.set" in script

    def test_file_handler(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "response_handlers.http")
        req = result.http_file.requests[2]  # fileHandler
        assert req.response_handler is not None
        assert req.response_handler.file_ref == "./handlers/check_response.js"
        assert req.response_handler.inline_script is None


class TestResponseSave:
    """Test response save directives (>> and >>!)."""

    def test_response_save_path(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        req = result.http_file.requests[1]  # getUsers
        assert req.response_save_path == "users_response.json"

    def test_response_save_in_file_refs(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "file_refs.http")
        # Second request has >> output.json
        assert result.http_file.requests[1].response_save_path == "output.json"
        # Third has >>! output_force.json
        assert result.http_file.requests[2].response_save_path == "output_force.json"

    def test_response_save_from_string(self) -> None:
        content = "GET https://example.com\n\n>> response.json\n"
        result = parse_http_string(content)
        req = result.http_file.requests[0]
        assert req.response_save_path == "response.json"


class TestGraphQLDetection:
    """Test GraphQL request detection."""

    def test_graphql_via_header(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "graphql.http")
        req = result.http_file.requests[0]
        assert req.body is not None
        assert req.body.is_graphql is True

    def test_graphql_via_content_type(self) -> None:
        content = "POST https://example.com/graphql\nContent-Type: application/graphql\n\n{ users { id } }\n"
        result = parse_http_string(content)
        req = result.http_file.requests[0]
        assert req.body is not None
        assert req.body.is_graphql is True

    def test_non_graphql_request(self) -> None:
        content = 'POST https://example.com/api\nContent-Type: application/json\n\n{"key": "value"}\n'
        result = parse_http_string(content)
        req = result.http_file.requests[0]
        assert req.body is not None
        assert req.body.is_graphql is False


class TestPreRequestScripts:
    """Test pre-request script parsing."""

    def test_oneline_pre_request(self) -> None:
        content = """POST https://example.com
Content-Type: application/json

< {% console.log("pre-request") %}

{"key": "value"}
"""
        result = parse_http_string(content)
        req = result.http_file.requests[0]
        assert req.pre_request_script is not None
        assert 'console.log("pre-request")' in req.pre_request_script

    def test_multiline_pre_request(self) -> None:
        content = """POST https://example.com
Content-Type: application/json

< {%
var timestamp = Date.now();
request.variables.set("ts", timestamp);
%}

{"key": "value"}
"""
        result = parse_http_string(content)
        req = result.http_file.requests[0]
        assert req.pre_request_script is not None
        assert "var timestamp" in req.pre_request_script
        assert "request.variables.set" in req.pre_request_script


class TestErrorRecovery:
    """Test that the parser continues after errors."""

    def test_parse_continues_after_weird_syntax(self) -> None:
        """Parser should handle files with unusual content gracefully."""
        content = """GET https://example.com/1

###

GET https://example.com/2
"""
        result = parse_http_string(content)
        # Both requests should parse
        assert len(result.http_file.requests) == 2

    def test_empty_request_skipped(self) -> None:
        """Empty separators should not create empty requests."""
        content = "###\n###\nGET https://example.com\n###\n###\n"
        result = parse_http_string(content)
        assert len(result.http_file.requests) == 1

    def test_named_requests_dict(self) -> None:
        """Test that named_requests works with metadata-parsed names."""
        result = parse_http_file(FIXTURES_DIR / "advanced.http")
        named = result.http_file.named_requests
        assert "login" in named
        assert "getUsers" in named
        assert "createUser" in named
        assert "searchUsers" in named


class TestExistingTestsStillPass:
    """Ensure the refactored parser still handles all basic cases."""

    def test_simple_fixture(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "simple.http")
        assert not result.has_errors
        assert len(result.http_file.requests) == 1
        assert result.http_file.requests[0].method == HttpMethod.GET

    def test_multiple_fixture(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "multiple.http")
        assert len(result.http_file.requests) == 3

    def test_headers_body_fixture(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "headers_body.http")
        req = result.http_file.requests[0]
        assert req.method == HttpMethod.POST
        assert len(req.headers) == 3
        assert req.body is not None

    def test_variables_fixture(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "variables.http")
        assert len(result.http_file.variables) == 3
        assert len(result.http_file.requests) == 1
