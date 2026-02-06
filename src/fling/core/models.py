"""Pydantic v2 data models for fling."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class HttpMethod(StrEnum):
    """HTTP methods supported by .http files."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"
    TRACE = "TRACE"
    CONNECT = "CONNECT"


class SourceLocation(BaseModel):
    """Location of a parsed element within an .http file."""

    file_path: str
    start_line: int
    end_line: int


class RequestMetadata(BaseModel):
    """Metadata extracted from comments preceding a request."""

    name: str | None = None
    refs: list[str] = Field(default_factory=list)
    no_redirect: bool = False
    no_cookie_jar: bool = False
    timeout_ms: int | None = None
    disabled: bool = False
    prompt_vars: dict[str, str] = Field(default_factory=dict)
    note: str | None = None


class Header(BaseModel):
    """An HTTP header with a name and value (may contain {{variables}})."""

    name: str
    value: str


class RequestBody(BaseModel):
    """The body of an HTTP request."""

    content: str = ""
    file_ref: str | None = None
    is_graphql: bool = False


class ResponseHandler(BaseModel):
    """A response handler script attached to a request."""

    inline_script: str | None = None
    file_ref: str | None = None


class HttpRequestDefinition(BaseModel):
    """A single HTTP request parsed from an .http file."""

    method: HttpMethod = HttpMethod.GET
    url: str
    http_version: str | None = None
    headers: list[Header] = Field(default_factory=list)
    body: RequestBody | None = None
    metadata: RequestMetadata = Field(default_factory=RequestMetadata)
    response_handler: ResponseHandler | None = None
    response_save_path: str | None = None
    pre_request_script: str | None = None
    location: SourceLocation
    comments: list[str] = Field(default_factory=list)


class VariableDefinition(BaseModel):
    """A file-level variable definition (@variable = value)."""

    name: str
    value: str
    location: SourceLocation


class HttpFile(BaseModel):
    """The complete parsed representation of an .http file."""

    file_path: str
    variables: list[VariableDefinition] = Field(default_factory=list)
    requests: list[HttpRequestDefinition] = Field(default_factory=list)

    @property
    def named_requests(self) -> dict[str, HttpRequestDefinition]:
        """Return a dict mapping request names to their definitions."""
        return {r.metadata.name: r for r in self.requests if r.metadata.name}


class EnvironmentFile(BaseModel):
    """Loaded environment configuration from http-client.env.json."""

    environments: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """The result of executing a single HTTP request."""

    request: HttpRequestDefinition
    resolved_url: str
    resolved_headers: dict[str, str] = Field(default_factory=dict)
    resolved_body: str | None = None
    status_code: int = 0
    response_headers: dict[str, list[str]] = Field(default_factory=dict)
    response_body: str = ""
    elapsed_ms: float = 0.0
    error: str | None = None


class ParseError(BaseModel):
    """An error encountered during parsing."""

    message: str
    location: SourceLocation | None = None


class ParseResult(BaseModel):
    """The result of parsing an .http file, including any errors."""

    http_file: HttpFile
    errors: list[ParseError] = Field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Return True if any parse errors occurred."""
        return len(self.errors) > 0
