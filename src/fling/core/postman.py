"""Postman v2.1 collection parser for fling.

Parses Postman collection JSON (v2.1 schema) into intermediate Pydantic
models and provides auth inheritance resolution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Intermediate Pydantic models for Postman v2.1 schema
# ---------------------------------------------------------------------------


class PostmanVariable(BaseModel):
    """A Postman variable (collection-level or folder-level)."""

    key: str
    value: str = ""
    description: str = ""
    disabled: bool = False


class PostmanAuthParam(BaseModel):
    """A single key-value parameter within an auth block."""

    key: str
    value: str = ""
    type: str = "string"


class PostmanAuth(BaseModel):
    """Postman auth configuration (bearer, basic, apikey, etc.)."""

    type: str  # "bearer", "basic", "apikey", "oauth2", "noauth", etc.
    params: list[PostmanAuthParam] = Field(default_factory=list)

    def get_param(self, key: str) -> str | None:
        """Get a parameter value by key."""
        for p in self.params:
            if p.key == key:
                return p.value
        return None


class PostmanHeader(BaseModel):
    """A Postman request header."""

    key: str
    value: str = ""
    description: str = ""
    disabled: bool = False


class PostmanQueryParam(BaseModel):
    """A Postman URL query parameter."""

    key: str
    value: str = ""
    description: str = ""
    disabled: bool = False


class PostmanUrl(BaseModel):
    """Structured Postman URL representation."""

    raw: str = ""
    protocol: str = ""
    host: list[str] = Field(default_factory=list)
    port: str = ""
    path: list[str] = Field(default_factory=list)
    query: list[PostmanQueryParam] = Field(default_factory=list)

    def to_url_string(self) -> str:
        """Reconstruct a URL string from structured components.

        Falls back to the raw string if structured components are missing.
        """
        if not self.host:
            return self.raw

        protocol = self.protocol or "https"
        host = ".".join(self.host)
        port = f":{self.port}" if self.port else ""
        path = "/" + "/".join(self.path) if self.path else ""

        active_query = [q for q in self.query if not q.disabled]
        query_str = ""
        if active_query:
            pairs = [f"{q.key}={q.value}" for q in active_query]
            query_str = "?" + "&".join(pairs)

        return f"{protocol}://{host}{port}{path}{query_str}"


class PostmanBody(BaseModel):
    """Postman request body."""

    mode: str = ""  # "raw", "urlencoded", "formdata", "graphql", "file"
    raw: str = ""
    raw_language: str = ""  # "json", "xml", "text", etc.
    urlencoded: list[dict[str, Any]] = Field(default_factory=list)
    formdata: list[dict[str, Any]] = Field(default_factory=list)
    graphql: dict[str, str] = Field(default_factory=dict)


class PostmanEvent(BaseModel):
    """A Postman event (pre-request or test script)."""

    listen: str  # "prerequest" or "test"
    script_type: str = "text/javascript"
    script_exec: list[str] = Field(default_factory=list)

    @property
    def script_text(self) -> str:
        """Return the script as a single string."""
        return "\n".join(self.script_exec)


class PostmanRequest(BaseModel):
    """A parsed Postman request item (leaf node)."""

    name: str = ""
    method: str = "GET"
    url: PostmanUrl = Field(default_factory=PostmanUrl)
    headers: list[PostmanHeader] = Field(default_factory=list)
    body: PostmanBody | None = None
    auth: PostmanAuth | None = None
    events: list[PostmanEvent] = Field(default_factory=list)
    description: str = ""
    disabled: bool = False

    # Resolved at auth-inheritance time
    effective_auth: PostmanAuth | None = None


class PostmanFolder(BaseModel):
    """A Postman folder (item group) that may contain requests or subfolders."""

    name: str = ""
    description: str = ""
    auth: PostmanAuth | None = None
    events: list[PostmanEvent] = Field(default_factory=list)
    variables: list[PostmanVariable] = Field(default_factory=list)
    items: list[PostmanRequest | PostmanFolder] = Field(default_factory=list)


class PostmanInfo(BaseModel):
    """Metadata from the Postman collection info block."""

    name: str = ""
    description: str = ""
    schema_url: str = ""


class PostmanCollection(BaseModel):
    """Top-level Postman collection (v2.1)."""

    info: PostmanInfo = Field(default_factory=PostmanInfo)
    auth: PostmanAuth | None = None
    variables: list[PostmanVariable] = Field(default_factory=list)
    events: list[PostmanEvent] = Field(default_factory=list)
    items: list[PostmanRequest | PostmanFolder] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_auth(data: dict[str, Any] | None) -> PostmanAuth | None:
    """Parse a Postman auth object into PostmanAuth."""
    if not data:
        return None

    auth_type = data.get("type", "noauth")
    if auth_type == "noauth":
        return PostmanAuth(type="noauth")

    params: list[PostmanAuthParam] = []
    # Auth params are stored under a key matching the type name
    auth_params_raw = data.get(auth_type, [])
    if isinstance(auth_params_raw, list):
        for p in auth_params_raw:
            if isinstance(p, dict):
                params.append(
                    PostmanAuthParam(
                        key=p.get("key", ""),
                        value=str(p.get("value", "")),
                        type=p.get("type", "string"),
                    )
                )

    return PostmanAuth(type=auth_type, params=params)


def _parse_variable(data: dict[str, Any]) -> PostmanVariable:
    """Parse a single Postman variable dict."""
    return PostmanVariable(
        key=data.get("key", ""),
        value=str(data.get("value", "")),
        description=data.get("description", "") or "",
        disabled=data.get("disabled", False),
    )


def _parse_variables(data_list: list[dict[str, Any]] | None) -> list[PostmanVariable]:
    """Parse a list of Postman variable dicts."""
    if not data_list:
        return []
    return [_parse_variable(v) for v in data_list if isinstance(v, dict)]


def _parse_header(data: dict[str, Any]) -> PostmanHeader:
    """Parse a single Postman header dict."""
    return PostmanHeader(
        key=data.get("key", ""),
        value=str(data.get("value", "")),
        description=data.get("description", "") or "",
        disabled=data.get("disabled", False),
    )


def _parse_url(data: str | dict[str, Any]) -> PostmanUrl:
    """Parse a Postman URL (can be a string or structured object)."""
    if isinstance(data, str):
        return PostmanUrl(raw=data)

    query = []
    for q in data.get("query", []) or []:
        if isinstance(q, dict):
            query.append(
                PostmanQueryParam(
                    key=q.get("key", ""),
                    value=str(q.get("value", "")),
                    description=q.get("description", "") or "",
                    disabled=q.get("disabled", False),
                )
            )

    host = data.get("host", []) or []
    if isinstance(host, str):
        host = [host]

    path = data.get("path", []) or []
    if isinstance(path, str):
        path = [path]

    return PostmanUrl(
        raw=data.get("raw", ""),
        protocol=data.get("protocol", "") or "",
        host=host,
        port=str(data.get("port", "") or ""),
        path=path,
        query=query,
    )


def _parse_body(data: dict[str, Any] | None) -> PostmanBody | None:
    """Parse a Postman request body."""
    if not data:
        return None

    mode = data.get("mode", "")
    raw = ""
    raw_language = ""
    urlencoded: list[dict[str, Any]] = []
    formdata: list[dict[str, Any]] = []
    graphql: dict[str, str] = {}

    if mode == "raw":
        raw = data.get("raw", "")
        options = data.get("options", {}) or {}
        raw_opts = options.get("raw", {}) or {}
        raw_language = raw_opts.get("language", "") or ""
    elif mode == "urlencoded":
        urlencoded = data.get("urlencoded", []) or []
    elif mode == "formdata":
        formdata = data.get("formdata", []) or []
    elif mode == "graphql":
        graphql = data.get("graphql", {}) or {}

    return PostmanBody(
        mode=mode,
        raw=raw,
        raw_language=raw_language,
        urlencoded=urlencoded,
        formdata=formdata,
        graphql=graphql,
    )


def _parse_events(data_list: list[dict[str, Any]] | None) -> list[PostmanEvent]:
    """Parse Postman event arrays (pre-request / test scripts)."""
    if not data_list:
        return []

    events: list[PostmanEvent] = []
    for ev in data_list:
        if not isinstance(ev, dict):
            continue
        script = ev.get("script", {}) or {}
        events.append(
            PostmanEvent(
                listen=ev.get("listen", ""),
                script_type=script.get("type", "text/javascript"),
                script_exec=script.get("exec", []) or [],
            )
        )
    return events


def _parse_item(data: dict[str, Any]) -> PostmanRequest | PostmanFolder:
    """Parse a single Postman item (request or folder).

    An item is a folder if it has a nested 'item' array. Otherwise it's a
    request (has a 'request' key).
    """
    # Folder: has nested items
    if "item" in data and "request" not in data:
        return PostmanFolder(
            name=data.get("name", ""),
            description=_extract_description(data.get("description")),
            auth=_parse_auth(data.get("auth")),
            events=_parse_events(data.get("event")),
            variables=_parse_variables(data.get("variable")),
            items=[_parse_item(child) for child in data.get("item", [])],
        )

    # Request item
    req_data = data.get("request", {})
    if isinstance(req_data, str):
        # Shorthand: just a URL string
        return PostmanRequest(
            name=data.get("name", ""),
            method="GET",
            url=PostmanUrl(raw=req_data),
            disabled=data.get("disabled", False),
        )

    headers = [_parse_header(h) for h in req_data.get("header", []) or []]

    return PostmanRequest(
        name=data.get("name", ""),
        method=req_data.get("method", "GET"),
        url=_parse_url(req_data.get("url", "")),
        headers=headers,
        body=_parse_body(req_data.get("body")),
        auth=_parse_auth(req_data.get("auth")),
        events=_parse_events(data.get("event")),
        description=_extract_description(req_data.get("description")),
        disabled=data.get("disabled", False),
    )


def _extract_description(desc: str | dict[str, Any] | None) -> str:
    """Extract description text (can be a string or an object with 'content')."""
    if desc is None:
        return ""
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        return desc.get("content", "")
    return ""


# ---------------------------------------------------------------------------
# Auth inheritance
# ---------------------------------------------------------------------------


def resolve_auth_inheritance(collection: PostmanCollection) -> None:
    """Resolve effective auth for every request by walking the auth chain.

    For each request, the effective auth is determined by:
    1. Request's own auth (if set and not "noauth")
    2. Nearest folder's auth (walking up)
    3. Collection's auth

    This mutates the collection in-place, setting `effective_auth` on each
    PostmanRequest.
    """
    _resolve_auth_recursive(collection.items, [collection.auth])


def _resolve_auth_recursive(
    items: list[PostmanRequest | PostmanFolder],
    auth_chain: list[PostmanAuth | None],
) -> None:
    """Recursively resolve auth for items, building up the auth chain."""
    for item in items:
        if isinstance(item, PostmanFolder):
            _resolve_auth_recursive(item.items, [*auth_chain, item.auth])
        elif isinstance(item, PostmanRequest):
            # Walk chain from most specific (request) to least (collection)
            if item.auth and item.auth.type != "noauth":
                item.effective_auth = item.auth
            else:
                # Walk the chain in reverse (innermost folder first).
                # If we encounter an explicit "noauth", stop — it blocks
                # further inheritance from outer scopes.
                for auth in reversed(auth_chain):
                    if auth is not None:
                        if auth.type == "noauth":
                            # Explicit "no auth" — stop the chain
                            break
                        item.effective_auth = auth
                        break


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_postman_collection(path: str | Path) -> PostmanCollection:
    """Parse a Postman v2.1 collection JSON file.

    Args:
        path: Path to the Postman collection JSON file.

    Returns:
        Parsed PostmanCollection with auth inheritance resolved.

    Raises:
        FileNotFoundError: If the file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
        ValueError: If the file is not a valid Postman v2.1 collection.
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        msg = f"Expected a JSON object, got {type(data).__name__}"
        raise ValueError(msg)

    # Validate it looks like a Postman collection
    info_data = data.get("info", {})
    schema_url = info_data.get("schema", "")
    if "schema.getpostman.com" not in schema_url and "item" not in data:
        msg = "File does not appear to be a Postman v2.1 collection"
        raise ValueError(msg)

    info = PostmanInfo(
        name=info_data.get("name", ""),
        description=_extract_description(info_data.get("description")),
        schema_url=schema_url,
    )

    collection = PostmanCollection(
        info=info,
        auth=_parse_auth(data.get("auth")),
        variables=_parse_variables(data.get("variable")),
        events=_parse_events(data.get("event")),
        items=[_parse_item(item) for item in data.get("item", [])],
    )

    # Resolve auth inheritance
    resolve_auth_inheritance(collection)

    return collection
