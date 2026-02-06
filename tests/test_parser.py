"""Tests for fling.core.parser — basic request parsing."""

from pathlib import Path

from fling.core.models import HttpMethod
from fling.core.parser import parse_http_file, parse_http_string

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestSimpleGet:
    """Test parsing a single GET request."""

    def test_parse_simple_fixture(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "simple.http")
        assert not result.has_errors
        assert len(result.http_file.requests) == 1

        req = result.http_file.requests[0]
        assert req.method == HttpMethod.GET
        assert req.url == "https://api.example.com/users"

    def test_parse_get_with_http_version(self) -> None:
        result = parse_http_string("GET https://example.com/api HTTP/1.1\n")
        assert not result.has_errors
        req = result.http_file.requests[0]
        assert req.method == HttpMethod.GET
        assert req.url == "https://example.com/api"
        assert req.http_version == "HTTP/1.1"

    def test_implicit_get(self) -> None:
        result = parse_http_string("https://example.com/api\n")
        assert not result.has_errors
        req = result.http_file.requests[0]
        assert req.method == HttpMethod.GET
        assert req.url == "https://example.com/api"

    def test_implicit_get_http(self) -> None:
        result = parse_http_string("http://localhost:3000/api\n")
        assert not result.has_errors
        req = result.http_file.requests[0]
        assert req.method == HttpMethod.GET
        assert req.url == "http://localhost:3000/api"


class TestMultipleRequests:
    """Test parsing multiple requests separated by ###."""

    def test_parse_multiple_fixture(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "multiple.http")
        assert not result.has_errors
        assert len(result.http_file.requests) == 3

    def test_first_request(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "multiple.http")
        req = result.http_file.requests[0]
        assert req.method == HttpMethod.GET
        assert req.url == "https://api.example.com/users"
        assert req.comments == ["Get all users"]

    def test_second_request(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "multiple.http")
        req = result.http_file.requests[1]
        assert req.method == HttpMethod.POST
        assert req.url == "https://api.example.com/users"
        assert len(req.headers) == 1
        assert req.headers[0].name == "Content-Type"
        assert req.headers[0].value == "application/json"
        assert req.body is not None
        assert '"name": "John Doe"' in req.body.content
        assert req.comments == ["Create a user"]

    def test_third_request(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "multiple.http")
        req = result.http_file.requests[2]
        assert req.method == HttpMethod.DELETE
        assert req.url == "https://api.example.com/users/1"
        assert req.comments == ["Delete a user"]


class TestHeadersAndBody:
    """Test parsing requests with headers and body."""

    def test_parse_headers_body_fixture(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "headers_body.http")
        assert not result.has_errors
        assert len(result.http_file.requests) == 1

    def test_request_details(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "headers_body.http")
        req = result.http_file.requests[0]
        assert req.method == HttpMethod.POST
        assert req.url == "https://api.example.com/login"
        assert req.http_version == "HTTP/1.1"

    def test_headers(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "headers_body.http")
        req = result.http_file.requests[0]
        assert len(req.headers) == 3
        header_names = [h.name for h in req.headers]
        assert "Content-Type" in header_names
        assert "Accept" in header_names
        assert "Authorization" in header_names

        auth_header = next(h for h in req.headers if h.name == "Authorization")
        assert auth_header.value == "Bearer {{token}}"

    def test_body(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "headers_body.http")
        req = result.http_file.requests[0]
        assert req.body is not None
        assert '"username": "admin"' in req.body.content
        assert '"password": "secret"' in req.body.content


class TestVariables:
    """Test parsing file-level variables."""

    def test_parse_variables_fixture(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "variables.http")
        assert not result.has_errors
        assert len(result.http_file.variables) == 3

    def test_variable_values(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "variables.http")
        vars_dict = {v.name: v.value for v in result.http_file.variables}
        assert vars_dict["host"] == "api.example.com"
        assert vars_dict["port"] == "8080"
        assert vars_dict["baseUrl"] == "https://{{host}}:{{port}}"

    def test_request_with_variable_url(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "variables.http")
        assert len(result.http_file.requests) == 1
        req = result.http_file.requests[0]
        assert req.url == "{{baseUrl}}/users"

    def test_variable_locations(self) -> None:
        result = parse_http_file(FIXTURES_DIR / "variables.http")
        for var in result.http_file.variables:
            assert var.location.start_line > 0


class TestComments:
    """Test comment handling."""

    def test_hash_comments(self) -> None:
        result = parse_http_string("# This is a comment\nGET https://example.com\n")
        assert not result.has_errors
        req = result.http_file.requests[0]
        assert "This is a comment" in req.comments

    def test_double_slash_comments(self) -> None:
        result = parse_http_string("// This is a comment\nGET https://example.com\n")
        assert not result.has_errors
        req = result.http_file.requests[0]
        assert "This is a comment" in req.comments

    def test_comments_not_treated_as_separator(self) -> None:
        content = "# comment\nGET https://example.com/1\n### separator\nGET https://example.com/2\n"
        result = parse_http_string(content)
        assert len(result.http_file.requests) == 2


class TestEdgeCases:
    """Test various edge cases."""

    def test_empty_content(self) -> None:
        result = parse_http_string("")
        assert not result.has_errors
        assert len(result.http_file.requests) == 0

    def test_only_comments(self) -> None:
        result = parse_http_string("# Just a comment\n// Another comment\n")
        assert len(result.http_file.requests) == 0

    def test_only_separators(self) -> None:
        result = parse_http_string("###\n###\n")
        assert len(result.http_file.requests) == 0

    def test_all_http_methods(self) -> None:
        for method in ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "CONNECT"]:
            result = parse_http_string(f"{method} https://example.com\n")
            assert len(result.http_file.requests) == 1
            assert result.http_file.requests[0].method == HttpMethod(method)

    def test_request_without_trailing_newline(self) -> None:
        result = parse_http_string("GET https://example.com")
        assert len(result.http_file.requests) == 1

    def test_body_with_trailing_empty_lines(self) -> None:
        content = 'POST https://example.com\n\n{"key": "value"}\n\n\n'
        result = parse_http_string(content)
        req = result.http_file.requests[0]
        assert req.body is not None
        assert req.body.content == '{"key": "value"}'

    def test_multiple_headers_same_name(self) -> None:
        content = "GET https://example.com\nAccept: text/html\nAccept: application/json\n"
        result = parse_http_string(content)
        req = result.http_file.requests[0]
        accept_headers = [h for h in req.headers if h.name == "Accept"]
        assert len(accept_headers) == 2

    def test_source_locations(self) -> None:
        content = "# comment\nGET https://example.com\n\n###\n\nPOST https://example.com\n"
        result = parse_http_string(content)
        assert len(result.http_file.requests) == 2
        # First request starts at the comment
        assert result.http_file.requests[0].location.start_line == 1
        # Second request starts at its line
        assert result.http_file.requests[1].location.start_line == 6

    def test_multiline_body(self) -> None:
        content = """POST https://example.com
Content-Type: application/json

{
    "name": "test",
    "items": [1, 2, 3],
    "nested": {
        "key": "value"
    }
}
"""
        result = parse_http_string(content)
        req = result.http_file.requests[0]
        assert req.body is not None
        assert '"name": "test"' in req.body.content
        assert '"nested"' in req.body.content

    def test_variable_in_url_template(self) -> None:
        """Variables in URLs should be preserved as raw templates."""
        result = parse_http_string("GET {{baseUrl}}/users\n")
        req = result.http_file.requests[0]
        assert req.url == "{{baseUrl}}/users"

    def test_file_path_preserved(self) -> None:
        result = parse_http_string("GET https://example.com\n", file_path="my_api.http")
        assert result.http_file.file_path == "my_api.http"

    def test_query_params_continuation(self) -> None:
        content = """GET https://example.com/search
    ?q=test
    &page=1
    &limit=10
"""
        result = parse_http_string(content)
        req = result.http_file.requests[0]
        assert "?q=test" in req.url
        assert "&page=1" in req.url
        assert "&limit=10" in req.url
