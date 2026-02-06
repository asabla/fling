"""Tests for the variable resolution engine."""

from __future__ import annotations

import os
import re
from unittest.mock import patch

from fling.core.models import (
    EnvironmentFile,
    HttpFile,
    SourceLocation,
    VariableDefinition,
)
from fling.core.variables import VariableResolver

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_http_file(variables: dict[str, str] | None = None) -> HttpFile:
    """Create a minimal HttpFile with file-level variables."""
    var_defs = []
    if variables:
        for name, value in variables.items():
            var_defs.append(
                VariableDefinition(
                    name=name,
                    value=value,
                    location=SourceLocation(file_path="test.http", start_line=1, end_line=1),
                )
            )
    return HttpFile(file_path="test.http", variables=var_defs)


def _make_env_file(
    environments: dict[str, dict[str, str]] | None = None,
) -> EnvironmentFile:
    """Create a minimal EnvironmentFile."""
    return EnvironmentFile(environments=environments or {})


# ---------------------------------------------------------------------------
# Basic resolution
# ---------------------------------------------------------------------------


class TestBasicResolution:
    """Tests for basic variable substitution."""

    def test_no_variables(self) -> None:
        resolver = VariableResolver()
        assert resolver.resolve_string("hello world") == "hello world"

    def test_empty_string(self) -> None:
        resolver = VariableResolver()
        assert resolver.resolve_string("") == ""

    def test_unresolvable_left_as_is(self) -> None:
        resolver = VariableResolver()
        assert resolver.resolve_string("{{unknown}}") == "{{unknown}}"

    def test_resolve_file_variable(self) -> None:
        http_file = _make_http_file({"host": "localhost"})
        resolver = VariableResolver(http_file=http_file)
        assert resolver.resolve_string("https://{{host}}/api") == "https://localhost/api"

    def test_resolve_multiple_variables(self) -> None:
        http_file = _make_http_file({"host": "localhost", "port": "8080"})
        resolver = VariableResolver(http_file=http_file)
        result = resolver.resolve_string("https://{{host}}:{{port}}/api")
        assert result == "https://localhost:8080/api"

    def test_resolve_with_whitespace_in_braces(self) -> None:
        http_file = _make_http_file({"host": "localhost"})
        resolver = VariableResolver(http_file=http_file)
        assert resolver.resolve_string("{{ host }}") == "localhost"

    def test_mixed_resolved_and_unresolved(self) -> None:
        http_file = _make_http_file({"host": "localhost"})
        resolver = VariableResolver(http_file=http_file)
        result = resolver.resolve_string("https://{{host}}:{{port}}")
        assert result == "https://localhost:{{port}}"


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


class TestPrecedence:
    """Tests for variable resolution precedence."""

    def test_extra_vars_over_file_vars(self) -> None:
        http_file = _make_http_file({"token": "file-token"})
        resolver = VariableResolver(
            http_file=http_file,
            extra_vars={"token": "extra-token"},
        )
        assert resolver.resolve_string("{{token}}") == "extra-token"

    def test_file_vars_over_env_vars(self) -> None:
        http_file = _make_http_file({"token": "file-token"})
        env_file = _make_env_file({"dev": {"token": "env-token"}})
        resolver = VariableResolver(
            http_file=http_file,
            env_file=env_file,
            env_name="dev",
        )
        assert resolver.resolve_string("{{token}}") == "file-token"

    def test_env_vars_over_dotenv_vars(self) -> None:
        env_file = _make_env_file(
            {
                "dev": {"token": "env-token"},
                "_dotenv": {"token": "dotenv-token"},
            }
        )
        resolver = VariableResolver(env_file=env_file, env_name="dev")
        assert resolver.resolve_string("{{token}}") == "env-token"

    def test_dotenv_vars_used_when_no_env(self) -> None:
        env_file = _make_env_file(
            {
                "dev": {"other": "val"},
                "_dotenv": {"token": "dotenv-token"},
            }
        )
        resolver = VariableResolver(env_file=env_file, env_name="dev")
        assert resolver.resolve_string("{{token}}") == "dotenv-token"

    def test_full_precedence_chain(self) -> None:
        """Extra > file > env > dotenv."""
        http_file = _make_http_file({"b": "file-b", "c": "file-c", "d": "file-d"})
        env_file = _make_env_file(
            {
                "dev": {"c": "env-c", "d": "env-d"},
                "_dotenv": {"d": "dotenv-d"},
            }
        )
        resolver = VariableResolver(
            http_file=http_file,
            env_file=env_file,
            env_name="dev",
            extra_vars={"a": "extra-a"},
        )
        assert resolver.resolve_string("{{a}}") == "extra-a"
        assert resolver.resolve_string("{{b}}") == "file-b"
        assert resolver.resolve_string("{{c}}") == "file-c"
        assert resolver.resolve_string("{{d}}") == "file-d"


# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------


class TestEnvironmentVariables:
    """Tests for environment variable resolution."""

    def test_env_var_resolved(self) -> None:
        env_file = _make_env_file({"prod": {"baseUrl": "https://api.example.com"}})
        resolver = VariableResolver(env_file=env_file, env_name="prod")
        assert resolver.resolve_string("{{baseUrl}}") == "https://api.example.com"

    def test_shared_env_vars(self) -> None:
        env_file = _make_env_file(
            {
                "_shared": {"apiVersion": "v2"},
                "dev": {"baseUrl": "https://dev.example.com"},
            }
        )
        resolver = VariableResolver(env_file=env_file, env_name="dev")
        assert resolver.resolve_string("{{apiVersion}}") == "v2"
        assert resolver.resolve_string("{{baseUrl}}") == "https://dev.example.com"

    def test_unknown_env_name_no_error(self) -> None:
        env_file = _make_env_file({"dev": {"token": "t"}})
        resolver = VariableResolver(env_file=env_file, env_name="nonexistent")
        assert resolver.resolve_string("{{token}}") == "{{token}}"

    def test_no_env_name_no_env_vars(self) -> None:
        env_file = _make_env_file({"dev": {"token": "t"}})
        resolver = VariableResolver(env_file=env_file)
        assert resolver.resolve_string("{{token}}") == "{{token}}"


# ---------------------------------------------------------------------------
# System variables — UUID
# ---------------------------------------------------------------------------


class TestSystemUUID:
    """Tests for $uuid and $guid system variables."""

    def test_uuid_format(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$uuid}}")
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            result,
        )

    def test_guid_alias(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$guid}}")
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            result,
        )

    def test_uuid_unique_per_call(self) -> None:
        resolver = VariableResolver()
        r1 = resolver.resolve_string("{{$uuid}}")
        r2 = resolver.resolve_string("{{$uuid}}")
        assert r1 != r2


# ---------------------------------------------------------------------------
# System variables — Timestamp
# ---------------------------------------------------------------------------


class TestSystemTimestamp:
    """Tests for $timestamp and $isoTimestamp."""

    def test_timestamp_is_numeric(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$timestamp}}")
        assert result.isdigit()

    def test_iso_timestamp_format(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$isoTimestamp}}")
        # Should end with Z and be a valid ISO format
        assert result.endswith("Z")
        assert "T" in result

    def test_datetime_iso8601(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$datetime iso8601}}")
        assert result.endswith("Z")
        assert "T" in result

    def test_datetime_rfc1123(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$datetime rfc1123}}")
        assert "GMT" in result

    def test_datetime_custom_format(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string('{{$datetime "%Y-%m-%d"}}')
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", result)

    def test_datetime_no_format_returns_original(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$datetime}}")
        assert result == "{{$datetime}}"


# ---------------------------------------------------------------------------
# System variables — Random
# ---------------------------------------------------------------------------


class TestSystemRandomInt:
    """Tests for $randomInt."""

    def test_random_int_default_range(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$randomInt}}")
        val = int(result)
        assert 0 <= val <= 1000

    def test_random_int_with_range(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$randomInt 1 10}}")
        val = int(result)
        assert 1 <= val <= 10

    def test_random_int_with_max_only(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$randomInt 50}}")
        val = int(result)
        assert 0 <= val <= 50

    def test_random_int_invalid_args(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$randomInt abc}}")
        assert result == "{{$randomInt abc}}"


# ---------------------------------------------------------------------------
# System variables — OS environment
# ---------------------------------------------------------------------------


class TestSystemProcessEnv:
    """Tests for $processEnv and $env.VAR."""

    def test_process_env(self) -> None:
        with patch.dict(os.environ, {"MY_VAR": "my-value"}):
            resolver = VariableResolver()
            assert resolver.resolve_string("{{$processEnv MY_VAR}}") == "my-value"

    def test_process_env_missing(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$processEnv DEFINITELY_NOT_SET_12345}}")
        assert result == "{{$processEnv DEFINITELY_NOT_SET_12345}}"

    def test_env_dot_syntax(self) -> None:
        with patch.dict(os.environ, {"API_KEY": "secret-key"}):
            resolver = VariableResolver()
            assert resolver.resolve_string("{{$env.API_KEY}}") == "secret-key"

    def test_env_dot_missing(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$env.DEFINITELY_NOT_SET_12345}}")
        assert result == "{{$env.DEFINITELY_NOT_SET_12345}}"

    def test_process_env_no_arg(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$processEnv}}")
        assert result == "{{$processEnv}}"


# ---------------------------------------------------------------------------
# System variables — dotenv
# ---------------------------------------------------------------------------


class TestSystemDotenv:
    """Tests for $dotenv."""

    def test_dotenv_var(self) -> None:
        env_file = _make_env_file({"_dotenv": {"DB_HOST": "localhost"}})
        resolver = VariableResolver(env_file=env_file)
        assert resolver.resolve_string("{{$dotenv DB_HOST}}") == "localhost"

    def test_dotenv_var_missing(self) -> None:
        env_file = _make_env_file({"_dotenv": {"DB_HOST": "localhost"}})
        resolver = VariableResolver(env_file=env_file)
        result = resolver.resolve_string("{{$dotenv MISSING}}")
        assert result == "{{$dotenv MISSING}}"

    def test_dotenv_no_dotenv_loaded(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$dotenv SOMETHING}}")
        assert result == "{{$dotenv SOMETHING}}"

    def test_dotenv_no_arg(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$dotenv}}")
        assert result == "{{$dotenv}}"


# ---------------------------------------------------------------------------
# Unknown system variables
# ---------------------------------------------------------------------------


class TestUnknownSystemVar:
    """Tests for unknown system variable names."""

    def test_unknown_system_var(self) -> None:
        resolver = VariableResolver()
        result = resolver.resolve_string("{{$notAVariable}}")
        assert result == "{{$notAVariable}}"


# ---------------------------------------------------------------------------
# add_variables
# ---------------------------------------------------------------------------


class TestAddVariables:
    """Tests for add_variables method."""

    def test_add_variables(self) -> None:
        resolver = VariableResolver()
        resolver.add_variables({"token": "abc123"})
        assert resolver.resolve_string("{{token}}") == "abc123"

    def test_add_variables_overrides(self) -> None:
        http_file = _make_http_file({"token": "file-token"})
        resolver = VariableResolver(http_file=http_file)
        resolver.add_variables({"token": "override-token"})
        assert resolver.resolve_string("{{token}}") == "override-token"

    def test_add_variables_incremental(self) -> None:
        resolver = VariableResolver()
        resolver.add_variables({"a": "1"})
        resolver.add_variables({"b": "2"})
        assert resolver.resolve_string("{{a}}+{{b}}") == "1+2"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests."""

    def test_non_string_env_values(self) -> None:
        """Non-string env values are converted to string."""
        env_file = _make_env_file({"dev": {"count": 42, "active": True}})  # type: ignore[dict-item]
        resolver = VariableResolver(env_file=env_file, env_name="dev")
        assert resolver.resolve_string("{{count}}") == "42"
        assert resolver.resolve_string("{{active}}") == "True"

    def test_variable_in_url(self) -> None:
        http_file = _make_http_file({"baseUrl": "https://api.example.com"})
        resolver = VariableResolver(http_file=http_file)
        result = resolver.resolve_string("{{baseUrl}}/users/{{$uuid}}")
        assert result.startswith("https://api.example.com/users/")
        # UUID part should be valid
        uuid_part = result.split("/users/")[1]
        assert re.match(r"^[0-9a-f-]+$", uuid_part)

    def test_adjacent_variables(self) -> None:
        http_file = _make_http_file({"a": "hello", "b": "world"})
        resolver = VariableResolver(http_file=http_file)
        assert resolver.resolve_string("{{a}}{{b}}") == "helloworld"

    def test_nested_braces_not_supported(self) -> None:
        """Nested braces are not a supported pattern — left as-is."""
        resolver = VariableResolver(extra_vars={"inner": "resolved"})
        # The regex captures "{inner" as the var name, which doesn't resolve
        result = resolver.resolve_string("{{{inner}}}")
        assert result == "{{{inner}}}"
