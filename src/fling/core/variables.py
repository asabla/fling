"""Variable resolution engine for fling.

Resolves {{variable}} templates in URLs, headers, and request bodies.
Handles file variables, environment variables, .env variables,
system/dynamic variables, and request chaining references.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import uuid
from datetime import UTC, datetime
from random import randint
from typing import TYPE_CHECKING, Any

from jsonpath_ng import parse as jsonpath_parse

from fling.core.environment import get_dotenv_variables, resolve_environment

if TYPE_CHECKING:
    from fling.core.models import EnvironmentFile, ExecutionResult, HttpFile

logger = logging.getLogger(__name__)

# Pattern to match {{variable}} templates, including nested whitespace
VARIABLE_PATTERN = re.compile(r"\{\{(.+?)\}\}")

# Pattern for system variables starting with $
SYSTEM_VAR_PATTERN = re.compile(r"^\$(\w+)(?:\s+(.*))?$")

# Pattern for $env.VAR syntax
ENV_DOT_PATTERN = re.compile(r"^\$env\.(.+)$")

# Pattern for chaining references: requestName.response.body.$.jsonpath
# or requestName.response.headers.HeaderName
CHAINING_PATTERN = re.compile(r"^(\w+)\.response\.(body\.\$\.(.+)|headers\.(.+))$")


class VariableResolver:
    """Resolves {{variable}} templates using a layered precedence chain.

    Resolution precedence (highest to lowest):
        1. Request-scoped variables (from chaining, added in Task 2.3)
        2. File variables (@var = value)
        3. Environment variables (from http-client.env.json)
        4. .env file variables
        5. System variables ($uuid, $timestamp, etc.)
    """

    def __init__(
        self,
        http_file: HttpFile | None = None,
        env_file: EnvironmentFile | None = None,
        env_name: str | None = None,
        *,
        extra_vars: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the resolver.

        Args:
            http_file: Parsed .http file with file-level variables.
            env_file: Loaded environment configuration.
            env_name: Active environment name.
            extra_vars: Additional variables (e.g., from request chaining).
        """
        # Layer 1: Request-scoped / extra variables (highest priority)
        self._extra_vars: dict[str, Any] = dict(extra_vars) if extra_vars else {}

        # Layer 2: File variables (@var = value)
        self._file_vars: dict[str, str] = {}
        if http_file:
            for var_def in http_file.variables:
                self._file_vars[var_def.name] = var_def.value

        # Layer 3: Environment variables
        self._env_vars: dict[str, Any] = {}
        if env_file and env_name:
            with contextlib.suppress(KeyError):
                self._env_vars = resolve_environment(env_file, env_name)

        # Layer 4: .env file variables
        self._dotenv_vars: dict[str, str] = {}
        if env_file:
            self._dotenv_vars = get_dotenv_variables(env_file)

        # Chaining: stored execution results keyed by request name
        self._chain_results: dict[str, ExecutionResult] = {}

    def resolve_string(self, text: str) -> str:
        """Resolve all {{variable}} templates in a string.

        Args:
            text: String potentially containing {{variable}} templates.

        Returns:
            String with all resolvable variables substituted.
            Unresolvable variables are left as-is.
        """

        def _replace(match: re.Match[str]) -> str:
            var_expr = match.group(1).strip()
            value = self._resolve_variable(var_expr)
            if value is None:
                return match.group(0)  # Leave unresolved
            return str(value)

        return VARIABLE_PATTERN.sub(_replace, text)

    def _resolve_variable(self, var_expr: str) -> Any | None:
        """Resolve a single variable expression.

        Args:
            var_expr: The variable expression (without {{ }}).

        Returns:
            The resolved value, or None if unresolvable.
        """
        # Check for $env.VAR syntax first
        env_dot_match = ENV_DOT_PATTERN.match(var_expr)
        if env_dot_match:
            var_name = env_dot_match.group(1)
            return self._resolve_env_access(var_name)

        # Check for system variable ($xxx ...)
        sys_match = SYSTEM_VAR_PATTERN.match(var_expr)
        if sys_match:
            func_name = sys_match.group(1)
            args_str = sys_match.group(2)
            return self._resolve_system_variable(func_name, args_str)

        # Check for chaining reference (requestName.response.body.$.jsonpath)
        chain_match = CHAINING_PATTERN.match(var_expr)
        if chain_match:
            return self._resolve_chaining_reference(chain_match)

        # Regular variable — walk the precedence chain
        return self._resolve_named_variable(var_expr)

    def _resolve_named_variable(self, name: str) -> Any | None:
        """Resolve a named variable through the precedence chain.

        Args:
            name: Variable name to resolve.

        Returns:
            The resolved value, or None if not found.
        """
        # 1. Request-scoped / extra variables
        if name in self._extra_vars:
            return self._extra_vars[name]

        # 2. File variables
        if name in self._file_vars:
            return self._file_vars[name]

        # 3. Environment variables
        if name in self._env_vars:
            return self._env_vars[name]

        # 4. .env file variables
        if name in self._dotenv_vars:
            return self._dotenv_vars[name]

        return None

    def _resolve_system_variable(self, func_name: str, args_str: str | None) -> Any | None:
        """Resolve a system variable ($uuid, $timestamp, etc.).

        Args:
            func_name: The system variable function name.
            args_str: Optional arguments string.

        Returns:
            The resolved value, or None if unknown.
        """
        match func_name:
            case "uuid" | "guid":
                return str(uuid.uuid4())

            case "timestamp":
                return str(int(datetime.now(tz=UTC).timestamp()))

            case "isoTimestamp":
                return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")

            case "datetime":
                return self._resolve_datetime(args_str)

            case "randomInt":
                return self._resolve_random_int(args_str)

            case "processEnv":
                if args_str:
                    var_name = args_str.strip()
                    return os.environ.get(var_name)
                return None

            case "dotenv":
                if args_str:
                    var_name = args_str.strip()
                    return self._dotenv_vars.get(var_name)
                return None

            case _:
                return None

    def _resolve_env_access(self, var_name: str) -> str | None:
        """Resolve $env.VAR — access OS environment variable.

        Args:
            var_name: Environment variable name.

        Returns:
            The environment variable value, or None if not set.
        """
        return os.environ.get(var_name)

    @staticmethod
    def _resolve_datetime(args_str: str | None) -> str | None:
        """Resolve $datetime with format argument.

        Supports:
            - iso8601 / rfc1123 / "custom format"

        Args:
            args_str: Format specifier string.

        Returns:
            Formatted datetime string, or None if no format given.
        """
        if not args_str:
            return None

        fmt = args_str.strip().strip('"').strip("'")
        now = datetime.now(tz=UTC)

        match fmt:
            case "iso8601":
                return now.isoformat().replace("+00:00", "Z")
            case "rfc1123":
                return now.strftime("%a, %d %b %Y %H:%M:%S GMT")
            case _:
                try:
                    return now.strftime(fmt)
                except ValueError:
                    return None

    @staticmethod
    def _resolve_random_int(args_str: str | None) -> str | None:
        """Resolve $randomInt with optional min/max arguments.

        Args:
            args_str: Space-separated min and max values.

        Returns:
            Random integer as string, or None on invalid input.
        """
        min_val = 0
        max_val = 1000

        if args_str:
            parts = args_str.strip().split()
            try:
                if len(parts) == 2:
                    min_val = int(parts[0])
                    max_val = int(parts[1])
                elif len(parts) == 1:
                    max_val = int(parts[0])
                else:
                    return None
            except ValueError:
                return None

        return str(randint(min_val, max_val))

    def _resolve_chaining_reference(self, chain_match: re.Match[str]) -> Any | None:
        """Resolve a request chaining reference.

        Supports:
            - {{requestName.response.body.$.jsonpath}} — extract from JSON body
            - {{requestName.response.headers.HeaderName}} — extract response header

        Args:
            chain_match: Regex match from CHAINING_PATTERN.

        Returns:
            The resolved value, or None if the referenced request hasn't
            been executed or the path doesn't resolve.
        """
        request_name = chain_match.group(1)
        body_jsonpath = chain_match.group(3)  # e.g. "token" from body.$.token
        header_name = chain_match.group(4)  # e.g. "X-Token" from headers.X-Token

        result = self._chain_results.get(request_name)
        if result is None:
            logger.warning("Chaining reference to '%s' but no result stored", request_name)
            return None

        if body_jsonpath:
            return self._extract_jsonpath(result.response_body, body_jsonpath)

        if header_name:
            # Headers are stored as dict[str, list[str]]; return first value
            values = result.response_headers.get(header_name)
            if not values:
                # Try case-insensitive lookup
                for key, vals in result.response_headers.items():
                    if key.lower() == header_name.lower():
                        return vals[0] if vals else None
                logger.warning(
                    "Header '%s' not found in response from '%s'",
                    header_name,
                    request_name,
                )
                return None
            return values[0]

        return None

    @staticmethod
    def _extract_jsonpath(body: str, path: str) -> Any | None:
        """Extract a value from a JSON body using JSONPath.

        Args:
            body: JSON response body as string.
            path: JSONPath expression (without the leading $.).

        Returns:
            The extracted value, or None if parsing/matching fails.
        """
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Failed to parse response body as JSON for chaining")
            return None

        try:
            expr = jsonpath_parse(f"$.{path}")
            matches = expr.find(data)
            if not matches:
                logger.warning("JSONPath '$.%s' matched nothing", path)
                return None
            # Return the single matched value (or first if multiple)
            value = matches[0].value
            # Convert non-string primitives to string for template substitution
            if isinstance(value, bool):
                return str(value).lower()
            if isinstance(value, (int, float)):
                return str(value)
            return value
        except Exception:
            logger.warning("JSONPath evaluation failed for '$.%s'", path, exc_info=True)
            return None

    def add_chain_result(self, name: str, result: ExecutionResult) -> None:
        """Store an execution result for request chaining.

        Args:
            name: The request name (from @name metadata).
            result: The execution result to store.
        """
        self._chain_results[name] = result

    def add_variables(self, variables: dict[str, Any]) -> None:
        """Add or update request-scoped variables.

        Used by the runner to inject chaining results.

        Args:
            variables: Variables to add to the request scope.
        """
        self._extra_vars.update(variables)
