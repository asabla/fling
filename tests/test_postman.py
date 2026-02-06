"""Tests for fling.core.postman — Postman v2.1 collection parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fling.core.postman import (
    PostmanAuth,
    PostmanAuthParam,
    PostmanBody,
    PostmanCollection,
    PostmanFolder,
    PostmanQueryParam,
    PostmanRequest,
    PostmanUrl,
    PostmanVariable,
    parse_postman_collection,
    resolve_auth_inheritance,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
COLLECTION_PATH = FIXTURES_DIR / "postman_collection.json"


# ---------------------------------------------------------------------------
# Model unit tests
# ---------------------------------------------------------------------------


class TestPostmanVariable:
    def test_defaults(self) -> None:
        v = PostmanVariable(key="host")
        assert v.key == "host"
        assert v.value == ""
        assert v.disabled is False

    def test_full(self) -> None:
        v = PostmanVariable(key="k", value="v", description="desc", disabled=True)
        assert v.value == "v"
        assert v.description == "desc"
        assert v.disabled is True


class TestPostmanAuth:
    def test_get_param_found(self) -> None:
        auth = PostmanAuth(
            type="bearer",
            params=[PostmanAuthParam(key="token", value="abc")],
        )
        assert auth.get_param("token") == "abc"

    def test_get_param_not_found(self) -> None:
        auth = PostmanAuth(type="bearer", params=[])
        assert auth.get_param("token") is None


class TestPostmanUrl:
    def test_raw_only(self) -> None:
        url = PostmanUrl(raw="https://example.com/path")
        assert url.to_url_string() == "https://example.com/path"

    def test_structured_basic(self) -> None:
        url = PostmanUrl(
            host=["api", "example", "com"],
            path=["v1", "users"],
        )
        assert url.to_url_string() == "https://api.example.com/v1/users"

    def test_structured_with_port(self) -> None:
        url = PostmanUrl(
            protocol="http",
            host=["localhost"],
            port="8080",
            path=["api", "health"],
        )
        assert url.to_url_string() == "http://localhost:8080/api/health"

    def test_structured_with_query(self) -> None:
        url = PostmanUrl(
            host=["api", "example", "com"],
            path=["users"],
            query=[
                PostmanQueryParam(key="page", value="1"),
                PostmanQueryParam(key="limit", value="10"),
            ],
        )
        assert url.to_url_string() == "https://api.example.com/users?page=1&limit=10"

    def test_disabled_query_params_excluded(self) -> None:
        url = PostmanUrl(
            host=["api", "example", "com"],
            path=["users"],
            query=[
                PostmanQueryParam(key="page", value="1"),
                PostmanQueryParam(key="debug", value="true", disabled=True),
            ],
        )
        result = url.to_url_string()
        assert "page=1" in result
        assert "debug" not in result

    def test_empty_host_falls_back_to_raw(self) -> None:
        url = PostmanUrl(raw="http://fallback.com")
        assert url.to_url_string() == "http://fallback.com"

    def test_no_path(self) -> None:
        url = PostmanUrl(host=["example", "com"])
        assert url.to_url_string() == "https://example.com"

    def test_default_protocol(self) -> None:
        url = PostmanUrl(host=["example", "com"], path=["api"])
        assert url.to_url_string().startswith("https://")


class TestPostmanBody:
    def test_raw_mode(self) -> None:
        body = PostmanBody(mode="raw", raw='{"key": "value"}', raw_language="json")
        assert body.mode == "raw"
        assert body.raw_language == "json"

    def test_graphql_mode(self) -> None:
        body = PostmanBody(
            mode="graphql",
            graphql={"query": "{ users { id } }", "variables": "{}"},
        )
        assert body.graphql["query"] == "{ users { id } }"


class TestPostmanEventScriptText:
    def test_script_text_joins_lines(self) -> None:
        from fling.core.postman import PostmanEvent

        event = PostmanEvent(
            listen="test",
            script_exec=["line1;", "line2;"],
        )
        assert event.script_text == "line1;\nline2;"

    def test_script_text_empty(self) -> None:
        from fling.core.postman import PostmanEvent

        event = PostmanEvent(listen="prerequest")
        assert event.script_text == ""


# ---------------------------------------------------------------------------
# Fixture-based parsing tests
# ---------------------------------------------------------------------------


class TestParsePostmanCollection:
    """Tests that parse the comprehensive fixture file."""

    @pytest.fixture
    def collection(self) -> PostmanCollection:
        return parse_postman_collection(COLLECTION_PATH)

    def test_info(self, collection: PostmanCollection) -> None:
        assert collection.info.name == "Fling Test API"
        assert "comprehensive test" in collection.info.description
        assert "schema.getpostman.com" in collection.info.schema_url

    def test_collection_auth(self, collection: PostmanCollection) -> None:
        assert collection.auth is not None
        assert collection.auth.type == "bearer"
        assert collection.auth.get_param("token") == "{{auth_token}}"

    def test_collection_variables(self, collection: PostmanCollection) -> None:
        assert len(collection.variables) == 4
        names = [v.key for v in collection.variables]
        assert "base_url" in names
        assert "auth_token" in names
        assert "api_version" in names

        base = next(v for v in collection.variables if v.key == "base_url")
        assert base.value == "https://api.example.com"

        disabled = next(v for v in collection.variables if v.key == "disabled_var")
        assert disabled.disabled is True

    def test_collection_events(self, collection: PostmanCollection) -> None:
        assert len(collection.events) == 2
        prereq = next(e for e in collection.events if e.listen == "prerequest")
        assert "Collection pre-request" in prereq.script_text

        test = next(e for e in collection.events if e.listen == "test")
        assert "Response time" in test.script_text

    def test_top_level_item_count(self, collection: PostmanCollection) -> None:
        # Simple GET, Auth folder, Users folder, GraphQL folder,
        # File Upload, Disabled Request, URL shorthand, API Key auth,
        # Port URL
        assert len(collection.items) == 9

    def test_simple_get_request(self, collection: PostmanCollection) -> None:
        req = collection.items[0]
        assert isinstance(req, PostmanRequest)
        assert req.name == "Simple GET"
        assert req.method == "GET"
        assert req.url.raw == "{{base_url}}/{{api_version}}/status"
        assert req.description == "A simple GET request with a string URL"

    def test_auth_folder(self, collection: PostmanCollection) -> None:
        auth_folder = collection.items[1]
        assert isinstance(auth_folder, PostmanFolder)
        assert auth_folder.name == "Auth"
        assert auth_folder.auth is not None
        assert auth_folder.auth.type == "noauth"
        assert len(auth_folder.items) == 2

    def test_login_request(self, collection: PostmanCollection) -> None:
        auth_folder = collection.items[1]
        assert isinstance(auth_folder, PostmanFolder)
        login = auth_folder.items[0]
        assert isinstance(login, PostmanRequest)
        assert login.name == "Login"
        assert login.method == "POST"
        assert login.description == "Login to get an auth token"

        # Headers
        assert len(login.headers) == 2
        ct = login.headers[0]
        assert ct.key == "Content-Type"
        assert ct.value == "application/json"
        debug = login.headers[1]
        assert debug.disabled is True

        # Body
        assert login.body is not None
        assert login.body.mode == "raw"
        assert '"username"' in login.body.raw
        assert login.body.raw_language == "json"

        # Events
        assert len(login.events) == 1
        assert login.events[0].listen == "test"
        assert "auth_token" in login.events[0].script_text

    def test_register_urlencoded(self, collection: PostmanCollection) -> None:
        auth_folder = collection.items[1]
        assert isinstance(auth_folder, PostmanFolder)
        register = auth_folder.items[1]
        assert isinstance(register, PostmanRequest)
        assert register.body is not None
        assert register.body.mode == "urlencoded"
        assert len(register.body.urlencoded) == 3

    def test_users_folder_with_basic_auth(self, collection: PostmanCollection) -> None:
        users_folder = collection.items[2]
        assert isinstance(users_folder, PostmanFolder)
        assert users_folder.name == "Users"
        assert users_folder.auth is not None
        assert users_folder.auth.type == "basic"
        assert users_folder.auth.get_param("username") == "admin"
        assert users_folder.auth.get_param("password") == "secret"

    def test_list_users_query_params(self, collection: PostmanCollection) -> None:
        users_folder = collection.items[2]
        assert isinstance(users_folder, PostmanFolder)
        list_users = users_folder.items[0]
        assert isinstance(list_users, PostmanRequest)
        assert list_users.name == "List Users"

        active_query = [q for q in list_users.url.query if not q.disabled]
        assert len(active_query) == 3
        keys = [q.key for q in active_query]
        assert "page" in keys
        assert "limit" in keys
        assert "sort" in keys

        disabled_query = [q for q in list_users.url.query if q.disabled]
        assert len(disabled_query) == 1
        assert disabled_query[0].key == "debug"

    def test_nested_folder(self, collection: PostmanCollection) -> None:
        users_folder = collection.items[2]
        assert isinstance(users_folder, PostmanFolder)
        admin_folder = users_folder.items[2]
        assert isinstance(admin_folder, PostmanFolder)
        assert admin_folder.name == "Admin"
        assert len(admin_folder.items) == 2

    def test_delete_user_with_apikey_auth(self, collection: PostmanCollection) -> None:
        users_folder = collection.items[2]
        assert isinstance(users_folder, PostmanFolder)
        admin_folder = users_folder.items[2]
        assert isinstance(admin_folder, PostmanFolder)
        delete_user = admin_folder.items[0]
        assert isinstance(delete_user, PostmanRequest)
        assert delete_user.name == "Delete User"
        assert delete_user.method == "DELETE"
        assert delete_user.auth is not None
        assert delete_user.auth.type == "apikey"
        assert delete_user.auth.get_param("key") == "X-Admin-Key"

    def test_graphql_request(self, collection: PostmanCollection) -> None:
        gql_folder = collection.items[3]
        assert isinstance(gql_folder, PostmanFolder)
        gql_req = gql_folder.items[0]
        assert isinstance(gql_req, PostmanRequest)
        assert gql_req.body is not None
        assert gql_req.body.mode == "graphql"
        assert "GetUser" in gql_req.body.graphql["query"]
        assert '"id"' in gql_req.body.graphql["variables"]

    def test_formdata_body(self, collection: PostmanCollection) -> None:
        upload = collection.items[4]
        assert isinstance(upload, PostmanRequest)
        assert upload.name == "File Upload"
        assert upload.body is not None
        assert upload.body.mode == "formdata"
        assert len(upload.body.formdata) == 2

    def test_disabled_request(self, collection: PostmanCollection) -> None:
        disabled = collection.items[5]
        assert isinstance(disabled, PostmanRequest)
        assert disabled.disabled is True
        assert disabled.name == "Disabled Request"

    def test_url_string_shorthand(self, collection: PostmanCollection) -> None:
        shorthand = collection.items[6]
        assert isinstance(shorthand, PostmanRequest)
        assert shorthand.name == "Request with URL string shorthand"
        assert shorthand.method == "GET"
        assert shorthand.url.raw == "{{base_url}}/quick"

    def test_port_url(self, collection: PostmanCollection) -> None:
        port_req = collection.items[8]
        assert isinstance(port_req, PostmanRequest)
        assert port_req.url.port == "8080"
        assert port_req.url.protocol == "http"
        url_str = port_req.url.to_url_string()
        assert url_str == "http://localhost:8080/api/health"


# ---------------------------------------------------------------------------
# Auth inheritance tests
# ---------------------------------------------------------------------------


class TestAuthInheritance:
    @pytest.fixture
    def collection(self) -> PostmanCollection:
        return parse_postman_collection(COLLECTION_PATH)

    def test_simple_get_inherits_collection_auth(self, collection: PostmanCollection) -> None:
        """Top-level request with no own auth inherits collection bearer auth."""
        req = collection.items[0]
        assert isinstance(req, PostmanRequest)
        assert req.effective_auth is not None
        assert req.effective_auth.type == "bearer"
        assert req.effective_auth.get_param("token") == "{{auth_token}}"

    def test_noauth_folder_blocks_inheritance(self, collection: PostmanCollection) -> None:
        """Requests in a noauth folder get no effective auth."""
        auth_folder = collection.items[1]
        assert isinstance(auth_folder, PostmanFolder)
        login = auth_folder.items[0]
        assert isinstance(login, PostmanRequest)
        # Auth folder has noauth, so no effective auth is inherited
        assert login.effective_auth is None

    def test_folder_auth_inherited_by_requests(self, collection: PostmanCollection) -> None:
        """Requests inherit their parent folder's auth."""
        users_folder = collection.items[2]
        assert isinstance(users_folder, PostmanFolder)
        list_users = users_folder.items[0]
        assert isinstance(list_users, PostmanRequest)
        assert list_users.effective_auth is not None
        assert list_users.effective_auth.type == "basic"

    def test_request_own_auth_overrides(self, collection: PostmanCollection) -> None:
        """Request with its own auth uses that, not the folder's."""
        users_folder = collection.items[2]
        assert isinstance(users_folder, PostmanFolder)
        admin_folder = users_folder.items[2]
        assert isinstance(admin_folder, PostmanFolder)
        delete_user = admin_folder.items[0]
        assert isinstance(delete_user, PostmanRequest)
        assert delete_user.effective_auth is not None
        assert delete_user.effective_auth.type == "apikey"

    def test_nested_folder_inherits_parent_auth(self, collection: PostmanCollection) -> None:
        """Request in nested folder (no own auth) inherits nearest folder auth."""
        users_folder = collection.items[2]
        assert isinstance(users_folder, PostmanFolder)
        admin_folder = users_folder.items[2]
        assert isinstance(admin_folder, PostmanFolder)
        create_user = admin_folder.items[1]
        assert isinstance(create_user, PostmanRequest)
        # Admin folder has no auth, so inherits from Users folder (basic)
        assert create_user.effective_auth is not None
        assert create_user.effective_auth.type == "basic"

    def test_graphql_folder_inherits_collection_auth(self, collection: PostmanCollection) -> None:
        """Folder with no own auth — requests inherit collection auth."""
        gql_folder = collection.items[3]
        assert isinstance(gql_folder, PostmanFolder)
        gql_req = gql_folder.items[0]
        assert isinstance(gql_req, PostmanRequest)
        assert gql_req.effective_auth is not None
        assert gql_req.effective_auth.type == "bearer"

    def test_api_key_request_own_auth(self, collection: PostmanCollection) -> None:
        """Top-level request with own apikey auth uses it."""
        req = collection.items[7]
        assert isinstance(req, PostmanRequest)
        assert req.effective_auth is not None
        assert req.effective_auth.type == "apikey"
        assert req.effective_auth.get_param("value") == "my-api-key-123"


# ---------------------------------------------------------------------------
# Edge cases and error handling
# ---------------------------------------------------------------------------


class TestParseEdgeCases:
    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            parse_postman_collection("/nonexistent/file.json")

    def test_invalid_json(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json at all", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            parse_postman_collection(bad_file)

    def test_not_a_postman_collection(self, tmp_path: Path) -> None:
        wrong_file = tmp_path / "wrong.json"
        wrong_file.write_text('{"foo": "bar"}', encoding="utf-8")
        with pytest.raises(ValueError, match="does not appear to be"):
            parse_postman_collection(wrong_file)

    def test_not_a_json_object(self, tmp_path: Path) -> None:
        arr_file = tmp_path / "arr.json"
        arr_file.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ValueError, match="Expected a JSON object"):
            parse_postman_collection(arr_file)

    def test_empty_collection(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.json"
        empty.write_text(
            json.dumps(
                {
                    "info": {
                        "name": "Empty",
                        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                    },
                    "item": [],
                }
            ),
            encoding="utf-8",
        )
        coll = parse_postman_collection(empty)
        assert coll.info.name == "Empty"
        assert len(coll.items) == 0
        assert len(coll.variables) == 0

    def test_minimal_request(self, tmp_path: Path) -> None:
        """Collection with a bare minimum request."""
        minimal = tmp_path / "minimal.json"
        minimal.write_text(
            json.dumps(
                {
                    "info": {
                        "name": "Minimal",
                        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                    },
                    "item": [
                        {
                            "name": "Simple",
                            "request": {"method": "GET", "url": "http://test.com"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        coll = parse_postman_collection(minimal)
        assert len(coll.items) == 1
        req = coll.items[0]
        assert isinstance(req, PostmanRequest)
        assert req.method == "GET"
        assert req.url.raw == "http://test.com"

    def test_description_as_object(self, tmp_path: Path) -> None:
        """Description can be a string or an object with 'content'."""
        coll_file = tmp_path / "desc.json"
        coll_file.write_text(
            json.dumps(
                {
                    "info": {
                        "name": "Desc Test",
                        "description": {
                            "content": "Object-style description",
                            "type": "text/markdown",
                        },
                        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                    },
                    "item": [],
                }
            ),
            encoding="utf-8",
        )
        coll = parse_postman_collection(coll_file)
        assert coll.info.description == "Object-style description"

    def test_null_body(self, tmp_path: Path) -> None:
        """Request with null body field."""
        coll_file = tmp_path / "null_body.json"
        coll_file.write_text(
            json.dumps(
                {
                    "info": {
                        "name": "Null Body",
                        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                    },
                    "item": [
                        {
                            "name": "No Body",
                            "request": {
                                "method": "GET",
                                "url": "http://test.com",
                                "body": None,
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        coll = parse_postman_collection(coll_file)
        req = coll.items[0]
        assert isinstance(req, PostmanRequest)
        assert req.body is None

    def test_null_headers(self, tmp_path: Path) -> None:
        """Request with null header field."""
        coll_file = tmp_path / "null_headers.json"
        coll_file.write_text(
            json.dumps(
                {
                    "info": {
                        "name": "Null Headers",
                        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
                    },
                    "item": [
                        {
                            "name": "No Headers",
                            "request": {
                                "method": "GET",
                                "url": "http://test.com",
                                "header": None,
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        coll = parse_postman_collection(coll_file)
        req = coll.items[0]
        assert isinstance(req, PostmanRequest)
        assert req.headers == []


class TestResolveAuthInheritanceManual:
    """Test auth inheritance resolution with manually built collections."""

    def test_no_auth_anywhere(self) -> None:
        req = PostmanRequest(name="r1")
        coll = PostmanCollection(items=[req])
        resolve_auth_inheritance(coll)
        assert req.effective_auth is None

    def test_collection_auth_only(self) -> None:
        req = PostmanRequest(name="r1")
        coll = PostmanCollection(
            auth=PostmanAuth(type="bearer", params=[PostmanAuthParam(key="token", value="t")]),
            items=[req],
        )
        resolve_auth_inheritance(coll)
        assert req.effective_auth is not None
        assert req.effective_auth.type == "bearer"

    def test_deeply_nested_inherits_nearest(self) -> None:
        """Three levels: collection -> folder1 -> folder2 -> request.
        folder1 has basic auth, folder2 has no auth.
        Request should inherit folder1's basic auth.
        """
        req = PostmanRequest(name="deep")
        inner_folder = PostmanFolder(name="inner", items=[req])
        outer_folder = PostmanFolder(
            name="outer",
            auth=PostmanAuth(
                type="basic",
                params=[
                    PostmanAuthParam(key="username", value="u"),
                    PostmanAuthParam(key="password", value="p"),
                ],
            ),
            items=[inner_folder],
        )
        coll = PostmanCollection(
            auth=PostmanAuth(type="bearer", params=[PostmanAuthParam(key="token", value="t")]),
            items=[outer_folder],
        )
        resolve_auth_inheritance(coll)
        assert req.effective_auth is not None
        assert req.effective_auth.type == "basic"

    def test_request_noauth_does_not_override(self) -> None:
        """If a request has auth type 'noauth', it still inherits from parent."""
        req = PostmanRequest(
            name="r1",
            auth=PostmanAuth(type="noauth"),
        )
        coll = PostmanCollection(
            auth=PostmanAuth(type="bearer", params=[PostmanAuthParam(key="token", value="t")]),
            items=[req],
        )
        resolve_auth_inheritance(coll)
        assert req.effective_auth is not None
        assert req.effective_auth.type == "bearer"


class TestParsePostmanCollectionUrl:
    """Test URL reconstruction from the parsed fixture."""

    @pytest.fixture
    def collection(self) -> PostmanCollection:
        return parse_postman_collection(COLLECTION_PATH)

    def test_structured_url_with_port(self, collection: PostmanCollection) -> None:
        port_req = collection.items[8]
        assert isinstance(port_req, PostmanRequest)
        assert port_req.url.to_url_string() == "http://localhost:8080/api/health"

    def test_structured_url_with_query(self, collection: PostmanCollection) -> None:
        users_folder = collection.items[2]
        assert isinstance(users_folder, PostmanFolder)
        list_users = users_folder.items[0]
        assert isinstance(list_users, PostmanRequest)
        url = list_users.url.to_url_string()
        assert "page=1" in url
        assert "limit=10" in url
        assert "sort=name" in url
        assert "debug" not in url  # disabled param excluded

    def test_structured_url_multiple_host_parts(self, collection: PostmanCollection) -> None:
        users_folder = collection.items[2]
        assert isinstance(users_folder, PostmanFolder)
        admin_folder = users_folder.items[2]
        assert isinstance(admin_folder, PostmanFolder)
        create_user = admin_folder.items[1]
        assert isinstance(create_user, PostmanRequest)
        url = create_user.url.to_url_string()
        assert "api.example.com" in url
