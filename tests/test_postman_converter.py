"""Tests for the Postman-to-.http converter and CLI convert command."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from fling.cli import main
from fling.core.postman import (
    PostmanAuth,
    PostmanAuthParam,
    PostmanBody,
    PostmanCollection,
    PostmanEvent,
    PostmanFolder,
    PostmanHeader,
    PostmanInfo,
    PostmanRequest,
    PostmanUrl,
    PostmanVariable,
    convert_collection_to_http,
    convert_collection_to_http_per_folder,
    parse_postman_collection,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
COLLECTION_PATH = FIXTURES_DIR / "postman_collection.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_collection(
    *,
    name: str = "Test",
    items: list[PostmanRequest | PostmanFolder] | None = None,
    variables: list[PostmanVariable] | None = None,
    auth: PostmanAuth | None = None,
    events: list[PostmanEvent] | None = None,
) -> PostmanCollection:
    """Create a simple PostmanCollection for testing."""
    return PostmanCollection(
        info=PostmanInfo(name=name, description="Test collection"),
        items=items or [],
        variables=variables or [],
        auth=auth,
        events=events or [],
    )


def _make_request(
    *,
    name: str = "Test Request",
    method: str = "GET",
    url: str = "https://example.com/api",
    headers: list[PostmanHeader] | None = None,
    body: PostmanBody | None = None,
    effective_auth: PostmanAuth | None = None,
    events: list[PostmanEvent] | None = None,
    disabled: bool = False,
    description: str = "",
) -> PostmanRequest:
    """Create a simple PostmanRequest for testing."""
    return PostmanRequest(
        name=name,
        method=method,
        url=PostmanUrl(raw=url),
        headers=headers or [],
        body=body,
        effective_auth=effective_auth,
        events=events or [],
        disabled=disabled,
        description=description,
    )


# ---------------------------------------------------------------------------
# Convert single requests
# ---------------------------------------------------------------------------


class TestConvertRequest:
    def test_simple_get(self) -> None:
        coll = _make_collection(items=[_make_request()])
        output = convert_collection_to_http(coll)
        assert "### Test Request" in output
        assert "GET https://example.com/api" in output

    def test_post_with_json_body(self) -> None:
        body = PostmanBody(mode="raw", raw='{"key": "value"}', raw_language="json")
        req = _make_request(method="POST", body=body)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        assert "POST https://example.com/api" in output
        assert "Content-Type: application/json" in output
        assert '{"key": "value"}' in output

    def test_explicit_content_type_not_duplicated(self) -> None:
        body = PostmanBody(mode="raw", raw='{"key": "value"}', raw_language="json")
        headers = [PostmanHeader(key="Content-Type", value="application/json")]
        req = _make_request(method="POST", headers=headers, body=body)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        # Should only appear once
        assert output.count("Content-Type: application/json") == 1

    def test_urlencoded_body(self) -> None:
        body = PostmanBody(
            mode="urlencoded",
            urlencoded=[
                {"key": "username", "value": "admin"},
                {"key": "password", "value": "secret"},
                {"key": "role", "value": "hidden", "disabled": True},
            ],
        )
        req = _make_request(method="POST", body=body)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        assert "Content-Type: application/x-www-form-urlencoded" in output
        assert "username=admin&password=secret" in output
        assert "hidden" not in output  # disabled item excluded

    def test_formdata_body(self) -> None:
        body = PostmanBody(
            mode="formdata",
            formdata=[
                {"key": "description", "value": "My file", "type": "text"},
                {"key": "file", "type": "file", "src": "/path/to/file.txt"},
            ],
        )
        req = _make_request(method="POST", body=body)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        assert "Content-Type: multipart/form-data" in output
        assert "description=My file" in output
        assert "# @file file: /path/to/file.txt" in output

    def test_graphql_body(self) -> None:
        body = PostmanBody(
            mode="graphql",
            graphql={
                "query": "{ users { id name } }",
                "variables": '{"limit": 10}',
            },
        )
        req = _make_request(method="POST", body=body)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        assert "Content-Type: application/json" in output
        assert "users" in output
        assert '"limit"' in output

    def test_bearer_auth_header(self) -> None:
        auth = PostmanAuth(
            type="bearer",
            params=[PostmanAuthParam(key="token", value="my-token")],
        )
        req = _make_request(effective_auth=auth)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        assert "Authorization: Bearer my-token" in output

    def test_basic_auth_header(self) -> None:
        import base64

        auth = PostmanAuth(
            type="basic",
            params=[
                PostmanAuthParam(key="username", value="user"),
                PostmanAuthParam(key="password", value="pass"),
            ],
        )
        req = _make_request(effective_auth=auth)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        encoded = base64.b64encode(b"user:pass").decode()
        assert f"Authorization: Basic {encoded}" in output

    def test_apikey_auth_header(self) -> None:
        auth = PostmanAuth(
            type="apikey",
            params=[
                PostmanAuthParam(key="key", value="X-API-Key"),
                PostmanAuthParam(key="value", value="secret-123"),
                PostmanAuthParam(key="in", value="header"),
            ],
        )
        req = _make_request(effective_auth=auth)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        assert "X-API-Key: secret-123" in output

    def test_disabled_headers_as_comments(self) -> None:
        headers = [
            PostmanHeader(key="Accept", value="application/json"),
            PostmanHeader(key="X-Debug", value="true", disabled=True),
        ]
        req = _make_request(headers=headers)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        assert "Accept: application/json" in output
        assert "# X-Debug: true" in output

    def test_disabled_request(self) -> None:
        req = _make_request(disabled=True)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        assert "# @disabled" in output

    def test_request_description(self) -> None:
        req = _make_request(description="Fetches the user list")
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        assert "# Fetches the user list" in output

    def test_events_as_comments(self) -> None:
        events = [
            PostmanEvent(
                listen="prerequest",
                script_exec=["console.log('before');"],
            ),
            PostmanEvent(
                listen="test",
                script_exec=["pm.test('ok', function() {});"],
            ),
        ]
        req = _make_request(events=events)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        assert "# [Pre-request Script]" in output
        assert "# [Test Script]" in output
        assert "# TODO: Convert to response handler" in output
        assert "#   console.log('before');" in output


# ---------------------------------------------------------------------------
# Convert full collections
# ---------------------------------------------------------------------------


class TestConvertCollection:
    def test_collection_header(self) -> None:
        coll = _make_collection(name="My API")
        output = convert_collection_to_http(coll)
        assert "# My API" in output
        assert "# Test collection" in output

    def test_collection_variables(self) -> None:
        vars_ = [
            PostmanVariable(key="base_url", value="https://api.example.com"),
            PostmanVariable(key="token", value="abc123"),
            PostmanVariable(key="unused", value="x", disabled=True),
        ]
        coll = _make_collection(variables=vars_)
        output = convert_collection_to_http(coll)
        assert "@base_url = https://api.example.com" in output
        assert "@token = abc123" in output
        assert "unused" not in output  # disabled var excluded

    def test_collection_events(self) -> None:
        events = [
            PostmanEvent(
                listen="prerequest",
                script_exec=["console.log('global');"],
            ),
        ]
        coll = _make_collection(events=events)
        output = convert_collection_to_http(coll)
        assert "# [Pre-request Script]" in output

    def test_folder_structure(self) -> None:
        folder = PostmanFolder(
            name="User Endpoints",
            description="All user-related APIs",
            items=[
                _make_request(name="List Users"),
                _make_request(name="Get User"),
            ],
        )
        coll = _make_collection(items=[folder])
        output = convert_collection_to_http(coll)
        assert "Folder: User Endpoints" in output
        assert "All user-related APIs" in output
        assert "### List Users" in output
        assert "### Get User" in output

    def test_nested_folders(self) -> None:
        inner = PostmanFolder(
            name="Admin",
            items=[_make_request(name="Delete User")],
        )
        outer = PostmanFolder(
            name="Users",
            items=[_make_request(name="List Users"), inner],
        )
        coll = _make_collection(items=[outer])
        output = convert_collection_to_http(coll)
        assert "Folder: Users" in output
        assert "Folder: Admin" in output
        assert "### List Users" in output
        assert "### Delete User" in output

    def test_trailing_newline(self) -> None:
        coll = _make_collection(items=[_make_request()])
        output = convert_collection_to_http(coll)
        assert output.endswith("\n")

    def test_full_fixture_conversion(self) -> None:
        """Convert the full fixture and verify key sections exist."""
        coll = parse_postman_collection(COLLECTION_PATH)
        output = convert_collection_to_http(coll)

        # Collection header
        assert "# Fling Test API" in output

        # Variables
        assert "@base_url = https://api.example.com" in output
        assert "@auth_token = default-token-123" in output
        assert "@api_version = v2" in output
        # Disabled var should be excluded
        assert "disabled_var" not in output

        # Folders
        assert "Folder: Auth" in output
        assert "Folder: Users" in output
        assert "Folder: GraphQL" in output
        assert "Folder: Admin" in output

        # Requests
        assert "### Simple GET" in output
        assert "### Login" in output
        assert "### Register" in output
        assert "### List Users" in output
        assert "### Delete User" in output
        assert "### Get User Query" in output
        assert "### Disabled Request" in output
        assert "# @disabled" in output

        # Auth headers
        assert "Authorization: Bearer" in output
        assert "Authorization: Basic" in output

        # Body content
        assert '"username"' in output

    def test_xml_body_language(self) -> None:
        body = PostmanBody(mode="raw", raw="<root/>", raw_language="xml")
        req = _make_request(method="POST", body=body)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        assert "Content-Type: application/xml" in output

    def test_text_body_language(self) -> None:
        body = PostmanBody(mode="raw", raw="hello", raw_language="text")
        req = _make_request(method="POST", body=body)
        coll = _make_collection(items=[req])
        output = convert_collection_to_http(coll)
        assert "Content-Type: text/plain" in output


# ---------------------------------------------------------------------------
# Split-folders conversion
# ---------------------------------------------------------------------------


class TestConvertPerFolder:
    def test_split_basic(self) -> None:
        folder = PostmanFolder(
            name="User APIs",
            items=[_make_request(name="Get Users")],
        )
        top_req = _make_request(name="Health Check")
        coll = _make_collection(name="My API", items=[top_req, folder])
        files = convert_collection_to_http_per_folder(coll)

        assert len(files) == 2
        assert "my-api" in files
        assert "user-apis" in files
        assert "### Health Check" in files["my-api"]
        assert "### Get Users" in files["user-apis"]

    def test_split_no_top_level_requests(self) -> None:
        folder = PostmanFolder(
            name="APIs",
            items=[_make_request(name="Req1")],
        )
        coll = _make_collection(items=[folder])
        files = convert_collection_to_http_per_folder(coll)
        assert len(files) == 1
        assert "apis" in files

    def test_split_includes_variables(self) -> None:
        vars_ = [PostmanVariable(key="base_url", value="https://api.com")]
        folder = PostmanFolder(
            name="Endpoints",
            items=[_make_request(name="Test")],
        )
        coll = _make_collection(variables=vars_, items=[folder])
        files = convert_collection_to_http_per_folder(coll)
        for content in files.values():
            assert "@base_url = https://api.com" in content

    def test_split_nested_subfolder_banner(self) -> None:
        inner = PostmanFolder(
            name="Admin",
            items=[_make_request(name="Delete")],
        )
        outer = PostmanFolder(
            name="Users",
            items=[_make_request(name="List"), inner],
        )
        coll = _make_collection(items=[outer])
        files = convert_collection_to_http_per_folder(coll)
        content = files["users"]
        assert "### List" in content
        assert "===== Admin =====" in content
        assert "### Delete" in content

    def test_split_safe_filename(self) -> None:
        folder = PostmanFolder(
            name="Special!@#$% Chars (test)",
            items=[_make_request(name="Req")],
        )
        coll = _make_collection(items=[folder])
        files = convert_collection_to_http_per_folder(coll)
        # All filenames should be safe
        for fname in files:
            assert " " not in fname
            assert all(c.isalnum() or c == "-" for c in fname)


# ---------------------------------------------------------------------------
# CLI convert command
# ---------------------------------------------------------------------------


class TestConvertCLI:
    @pytest.fixture
    def runner(self) -> CliRunner:
        return CliRunner()

    def test_convert_single_file(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            main,
            ["convert", str(COLLECTION_PATH), "--output", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "Created" in result.output

        http_files = list(tmp_path.glob("*.http"))
        assert len(http_files) == 1
        content = http_files[0].read_text(encoding="utf-8")
        assert "### Simple GET" in content
        assert "### Login" in content

    def test_convert_split_folders(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(
            main,
            [
                "convert",
                str(COLLECTION_PATH),
                "--output",
                str(tmp_path),
                "--split-folders",
            ],
        )
        assert result.exit_code == 0
        assert "Converted" in result.output

        http_files = list(tmp_path.glob("*.http"))
        # Should have multiple files (top-level requests + auth + users + graphql)
        assert len(http_files) >= 2

    def test_convert_invalid_file(self, runner: CliRunner, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json", encoding="utf-8")
        result = runner.invoke(main, ["convert", str(bad_file)])
        assert result.exit_code != 0

    def test_convert_nonexistent_file(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["convert", "/nonexistent/file.json"])
        assert result.exit_code != 0

    def test_convert_creates_output_dir(self, runner: CliRunner, tmp_path: Path) -> None:
        new_dir = tmp_path / "subdir" / "output"
        result = runner.invoke(
            main,
            ["convert", str(COLLECTION_PATH), "--output", str(new_dir)],
        )
        assert result.exit_code == 0
        assert new_dir.exists()
        assert len(list(new_dir.glob("*.http"))) == 1


# ---------------------------------------------------------------------------
# Round-trip: Postman -> .http -> parse back
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_converted_file_is_parseable(self, tmp_path: Path) -> None:
        """Convert the fixture to .http and verify it can be parsed back."""
        from fling.core.parser import parse_http_file

        coll = parse_postman_collection(COLLECTION_PATH)
        content = convert_collection_to_http(coll)

        http_path = tmp_path / "converted.http"
        http_path.write_text(content, encoding="utf-8")

        result = parse_http_file(str(http_path))
        # Should parse without errors
        assert not result.has_errors
        # Should have requests
        assert len(result.http_file.requests) > 0

    def test_converted_request_count(self, tmp_path: Path) -> None:
        """Verify the number of requests matches expectation."""
        from fling.core.parser import parse_http_file

        coll = parse_postman_collection(COLLECTION_PATH)
        content = convert_collection_to_http(coll)

        http_path = tmp_path / "converted.http"
        http_path.write_text(content, encoding="utf-8")

        result = parse_http_file(str(http_path))

        # Count non-folder requests in the Postman collection
        def count_requests(
            items: list[PostmanRequest | PostmanFolder],
        ) -> int:
            total = 0
            for item in items:
                if isinstance(item, PostmanRequest):
                    total += 1
                elif isinstance(item, PostmanFolder):
                    total += count_requests(item.items)
            return total

        expected = count_requests(coll.items)
        assert len(result.http_file.requests) == expected

    def test_converted_preserves_variables(self, tmp_path: Path) -> None:
        """Verify converted file preserves collection variables."""
        from fling.core.parser import parse_http_file

        coll = parse_postman_collection(COLLECTION_PATH)
        content = convert_collection_to_http(coll)

        http_path = tmp_path / "converted.http"
        http_path.write_text(content, encoding="utf-8")

        result = parse_http_file(str(http_path))
        var_names = {v.name for v in result.http_file.variables}
        assert "base_url" in var_names
        assert "auth_token" in var_names
        assert "api_version" in var_names
