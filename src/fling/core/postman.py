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


# ---------------------------------------------------------------------------
# Postman-to-.http translator
# ---------------------------------------------------------------------------


def _auth_to_header(auth: PostmanAuth) -> tuple[str, str] | None:
    """Convert a PostmanAuth into an Authorization header key-value pair.

    Returns None for noauth or unsupported auth types.
    """
    if auth.type == "bearer":
        token = auth.get_param("token") or ""
        return ("Authorization", f"Bearer {token}")
    if auth.type == "basic":
        import base64

        username = auth.get_param("username") or ""
        password = auth.get_param("password") or ""
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        return ("Authorization", f"Basic {encoded}")
    if auth.type == "apikey":
        key = auth.get_param("key") or "X-API-Key"
        value = auth.get_param("value") or ""
        location = auth.get_param("in") or "header"
        if location == "header":
            return (key, value)
        # Query param API keys are handled in the URL, not as a header
        return None
    if auth.type == "noauth":
        return None
    # Unsupported auth types — emit a comment-style hint
    return None


def _convert_body(body: PostmanBody) -> tuple[str, str | None]:
    """Convert a PostmanBody to a body string and optional Content-Type.

    Returns:
        (body_text, content_type_or_none)
    """
    if body.mode == "raw":
        ct = None
        if body.raw_language == "json":
            ct = "application/json"
        elif body.raw_language == "xml":
            ct = "application/xml"
        elif body.raw_language == "text":
            ct = "text/plain"
        return (body.raw, ct)

    if body.mode == "urlencoded":
        active = [item for item in body.urlencoded if not item.get("disabled", False)]
        pairs = [f"{item.get('key', '')}={item.get('value', '')}" for item in active]
        return ("&".join(pairs), "application/x-www-form-urlencoded")

    if body.mode == "formdata":
        # Multipart form data: list key=value pairs, note file refs
        lines: list[str] = []
        for item in body.formdata:
            if item.get("disabled", False):
                continue
            if item.get("type") == "file":
                lines.append(f"# @file {item.get('key', '')}: {item.get('src', '')}")
            else:
                lines.append(f"{item.get('key', '')}={item.get('value', '')}")
        return ("\n".join(lines), "multipart/form-data")

    if body.mode == "graphql":
        # Convert GraphQL to a JSON POST body
        gql_body = {"query": body.graphql.get("query", "")}
        variables_str = body.graphql.get("variables", "")
        if variables_str:
            try:
                gql_body["variables"] = json.loads(variables_str)
            except (json.JSONDecodeError, ValueError):
                gql_body["variables"] = variables_str  # type: ignore[assignment]
        return (json.dumps(gql_body, indent=2), "application/json")

    return ("", None)


def _events_to_comments(events: list[PostmanEvent]) -> list[str]:
    """Convert Postman events to comment lines for .http output."""
    lines: list[str] = []
    for event in events:
        if not event.script_exec:
            continue
        label = "Pre-request Script" if event.listen == "prerequest" else "Test Script"
        lines.append(f"# [{label}]")
        lines.append("# TODO: Convert to response handler")
        for script_line in event.script_exec:
            lines.append(f"#   {script_line}")
    return lines


def _convert_request(
    req: PostmanRequest,
    *,
    include_disabled_as_comments: bool = True,
) -> str:
    """Convert a single PostmanRequest to .http format.

    Returns the .http text block for this request (including ### separator).
    """
    lines: list[str] = []

    # Name
    name = req.name or "Unnamed Request"
    lines.append(f"### {name}")

    # Description as comments
    if req.description:
        for desc_line in req.description.splitlines():
            lines.append(f"# {desc_line}")

    # Disabled marker
    if req.disabled:
        lines.append("# @disabled")

    # Events (pre-request/test scripts)
    event_comments = _events_to_comments(req.events)
    if event_comments:
        lines.extend(event_comments)

    # URL — prefer raw, fall back to structured
    url = req.url.raw or req.url.to_url_string()
    method = req.method or "GET"
    lines.append(f"{method} {url}")

    # Auth header from effective auth
    auth_header = None
    if req.effective_auth:
        auth_header = _auth_to_header(req.effective_auth)
        if auth_header:
            lines.append(f"{auth_header[0]}: {auth_header[1]}")

    # Determine if we need an explicit Content-Type from the body
    body_text = ""
    body_ct: str | None = None
    if req.body:
        body_text, body_ct = _convert_body(req.body)

    # Headers
    has_ct = False
    for header in req.headers:
        if header.disabled:
            if include_disabled_as_comments:
                lines.append(f"# {header.key}: {header.value}")
            continue
        if header.key.lower() == "content-type":
            has_ct = True
        lines.append(f"{header.key}: {header.value}")

    # Add Content-Type if the body implies one and none was explicitly set
    if body_ct and not has_ct:
        lines.append(f"Content-Type: {body_ct}")

    # Body
    if body_text:
        lines.append("")
        lines.append(body_text)

    return "\n".join(lines)


def convert_collection_to_http(
    collection: PostmanCollection,
) -> str:
    """Convert an entire PostmanCollection to a single .http file string.

    The output includes:
    - Collection name as a header comment
    - Collection variables as @variable = value
    - Collection-level events as comments
    - Folder boundaries as comment banners
    - All requests in .http format
    """
    lines: list[str] = []

    # Header
    lines.append(f"# {collection.info.name}")
    if collection.info.description:
        lines.append(f"# {collection.info.description}")
    lines.append("")

    # Variables
    active_vars = [v for v in collection.variables if not v.disabled]
    for var in active_vars:
        lines.append(f"@{var.key} = {var.value}")
    if active_vars:
        lines.append("")

    # Collection-level events
    event_comments = _events_to_comments(collection.events)
    if event_comments:
        lines.extend(event_comments)
        lines.append("")

    # Items
    _convert_items(collection.items, lines, depth=0)

    # Ensure trailing newline
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    return result


def _convert_items(
    items: list[PostmanRequest | PostmanFolder],
    lines: list[str],
    depth: int,
) -> None:
    """Recursively convert items (requests and folders) to .http lines."""
    for item in items:
        if isinstance(item, PostmanFolder):
            sep = "=" * (60 - depth * 2)
            indent = "  " * depth
            lines.append(f"# {indent}{sep}")
            lines.append(f"# {indent}Folder: {item.name}")
            if item.description:
                lines.append(f"# {indent}{item.description}")
            lines.append(f"# {indent}{sep}")
            lines.append("")

            # Folder-level variables
            folder_vars = [v for v in item.variables if not v.disabled]
            for var in folder_vars:
                lines.append(f"@{var.key} = {var.value}")
            if folder_vars:
                lines.append("")

            # Folder-level events
            event_comments = _events_to_comments(item.events)
            if event_comments:
                lines.extend(event_comments)
                lines.append("")

            _convert_items(item.items, lines, depth + 1)
        elif isinstance(item, PostmanRequest):
            lines.append(_convert_request(item))
            lines.append("")


def convert_collection_to_http_per_folder(
    collection: PostmanCollection,
) -> dict[str, str]:
    """Convert a PostmanCollection into multiple .http files, one per folder.

    Top-level requests go into a file named after the collection.
    Each folder produces a separate file named after the folder.

    Returns:
        Dict mapping filename (without .http extension) to .http content.
    """
    result: dict[str, str] = {}

    # Header + variables preamble (shared across all files)
    preamble_lines: list[str] = []
    preamble_lines.append(f"# {collection.info.name}")
    if collection.info.description:
        preamble_lines.append(f"# {collection.info.description}")
    preamble_lines.append("")

    active_vars = [v for v in collection.variables if not v.disabled]
    for var in active_vars:
        preamble_lines.append(f"@{var.key} = {var.value}")
    if active_vars:
        preamble_lines.append("")

    preamble = "\n".join(preamble_lines)

    # Top-level requests
    top_level_lines: list[str] = []
    for item in collection.items:
        if isinstance(item, PostmanRequest):
            top_level_lines.append(_convert_request(item))
            top_level_lines.append("")

    if top_level_lines:
        content = preamble + "\n".join(top_level_lines)
        if not content.endswith("\n"):
            content += "\n"
        result[_safe_filename(collection.info.name or "collection")] = content

    # Folders
    for item in collection.items:
        if isinstance(item, PostmanFolder):
            folder_lines: list[str] = []
            _collect_requests_from_folder(item, folder_lines)
            if folder_lines:
                content = preamble + "\n".join(folder_lines)
                if not content.endswith("\n"):
                    content += "\n"
                result[_safe_filename(item.name)] = content

    return result


def _collect_requests_from_folder(
    folder: PostmanFolder,
    lines: list[str],
) -> None:
    """Recursively collect all requests from a folder into lines."""
    for item in folder.items:
        if isinstance(item, PostmanRequest):
            lines.append(_convert_request(item))
            lines.append("")
        elif isinstance(item, PostmanFolder):
            # Add subfolder banner
            lines.append(f"# ===== {item.name} =====")
            lines.append("")
            _collect_requests_from_folder(item, lines)


def _safe_filename(name: str) -> str:
    """Convert a name to a safe filename (lowercase, hyphens, no special chars)."""
    import re

    safe = re.sub(r"[^\w\s-]", "", name.lower())
    safe = re.sub(r"[\s_]+", "-", safe)
    return safe.strip("-") or "collection"
