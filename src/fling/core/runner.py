"""Request orchestration runner for fling.

Parses an .http file, builds a dependency graph from @ref metadata
and {{requestName.response...}} chaining references, performs
topological sort, and executes requests in dependency order.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fling.core.executor import HttpExecutor
from fling.core.variables import VariableResolver

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fling.core.models import ExecutionResult, HttpFile, HttpRequestDefinition

logger = logging.getLogger(__name__)

# Pattern to detect implicit chaining references in raw template strings
# e.g. {{login.response.body.$.token}} -> extracts "login"
_IMPLICIT_REF_PATTERN = re.compile(r"\{\{\s*(\w+)\.response\.(body\.\$\..+|headers\..+)\s*\}\}")


class RunnerError(Exception):
    """Raised when the runner encounters an unrecoverable error."""


class CyclicDependencyError(RunnerError):
    """Raised when a dependency cycle is detected."""


def _extract_implicit_deps(request: HttpRequestDefinition) -> set[str]:
    """Extract implicit dependency names from chaining references in a request.

    Scans URL, headers, and body for {{name.response...}} patterns.

    Args:
        request: The request definition to scan.

    Returns:
        Set of request names that this request implicitly depends on.
    """
    deps: set[str] = set()
    texts_to_scan: list[str] = [request.url]

    for header in request.headers:
        texts_to_scan.append(header.value)

    if request.body and request.body.content:
        texts_to_scan.append(request.body.content)

    for text in texts_to_scan:
        for match in _IMPLICIT_REF_PATTERN.finditer(text):
            deps.add(match.group(1))

    return deps


def build_dependency_graph(
    http_file: HttpFile,
) -> dict[str, set[str]]:
    """Build a dependency graph for all named requests.

    Dependencies come from two sources:
    1. Explicit: @ref metadata tags
    2. Implicit: {{requestName.response...}} chaining references

    Args:
        http_file: Parsed .http file.

    Returns:
        Dict mapping request name -> set of dependency request names.
        Unnamed requests are excluded.
    """
    named = http_file.named_requests
    graph: dict[str, set[str]] = {}

    for name, request in named.items():
        deps: set[str] = set()

        # Explicit @ref dependencies
        for ref in request.metadata.refs:
            if ref in named:
                deps.add(ref)
            else:
                logger.warning(
                    "Request '%s' references unknown request '%s' via @ref",
                    name,
                    ref,
                )

        # Implicit chaining dependencies
        implicit = _extract_implicit_deps(request)
        for dep_name in implicit:
            if dep_name in named:
                deps.add(dep_name)

        # Remove self-references
        deps.discard(name)
        graph[name] = deps

    return graph


def topological_sort(graph: dict[str, set[str]]) -> list[str]:
    """Topological sort using Kahn's algorithm.

    Args:
        graph: Dependency graph (name -> set of dependency names).

    Returns:
        List of names in execution order (dependencies first).

    Raises:
        CyclicDependencyError: If a cycle is detected.
    """
    # Build reverse graph: for each node, which nodes depend on it
    reverse: dict[str, set[str]] = {name: set() for name in graph}
    for name, deps in graph.items():
        for dep in deps:
            if dep in reverse:
                reverse[dep].add(name)

    # in_degree[x] = number of dependencies x has (must run before x)
    in_degree = {name: len(deps) for name, deps in graph.items()}

    # Start with nodes that have no dependencies
    queue = sorted(name for name, deg in in_degree.items() if deg == 0)
    result: list[str] = []

    while queue:
        node = queue.pop(0)
        result.append(node)

        # For each node that depends on `node`, decrement its in-degree
        for dependent in sorted(reverse.get(node, set())):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(graph):
        remaining = set(graph) - set(result)
        raise CyclicDependencyError(f"Cyclic dependency detected among: {', '.join(sorted(remaining))}")

    return result


class HttpRunner:
    """Orchestrates parsing, variable resolution, and HTTP execution.

    Manages the full lifecycle: parse -> build dependency graph ->
    topological sort -> resolve variables -> execute -> store results.
    """

    def __init__(
        self,
        *,
        env_file: Any | None = None,
        env_name: str | None = None,
        extra_vars: dict[str, Any] | None = None,
        verify_ssl: bool = True,
        default_timeout: float = 30.0,
        executor: HttpExecutor | None = None,
    ) -> None:
        """Initialize the runner.

        Args:
            env_file: Loaded environment file.
            env_name: Active environment name.
            extra_vars: Additional variables to inject.
            verify_ssl: Whether to verify SSL certificates.
            default_timeout: Default request timeout in seconds.
            executor: Optional pre-configured executor (for testing).
        """
        self._env_file = env_file
        self._env_name = env_name
        self._extra_vars = extra_vars or {}
        self._verify_ssl = verify_ssl
        self._default_timeout = default_timeout
        self._executor = executor or HttpExecutor(
            verify_ssl=verify_ssl,
            default_timeout=default_timeout,
        )
        self._results: dict[str, ExecutionResult] = {}

    async def run_all(
        self,
        http_file: HttpFile,
    ) -> AsyncGenerator[tuple[HttpRequestDefinition, ExecutionResult], None]:
        """Run all requests in dependency order.

        Disabled requests (@disabled) are skipped. Unnamed requests
        are executed after all named requests in file order.

        Args:
            http_file: Parsed .http file.

        Yields:
            Tuples of (request_definition, execution_result).
        """
        resolver = self._create_resolver(http_file)

        # Build dependency graph and get execution order for named requests
        named = http_file.named_requests
        graph = build_dependency_graph(http_file)
        order = topological_sort(graph)

        # Execute named requests in dependency order
        executed_names: set[str] = set()
        for name in order:
            request = named[name]
            if request.metadata.disabled:
                logger.info("Skipping disabled request: %s", name)
                continue

            result = await self._execute_request(request, resolver)
            resolver.add_chain_result(name, result)
            self._results[name] = result
            executed_names.add(name)
            yield request, result

        # Execute unnamed requests in file order
        for request in http_file.requests:
            if request.metadata.name:
                continue  # Already handled
            if request.metadata.disabled:
                continue

            result = await self._execute_request(request, resolver)
            yield request, result

    async def run_single(
        self,
        http_file: HttpFile,
        name: str,
    ) -> AsyncGenerator[tuple[HttpRequestDefinition, ExecutionResult], None]:
        """Run a single named request and its dependencies.

        Args:
            http_file: Parsed .http file.
            name: Name of the request to run.

        Yields:
            Tuples of (request_definition, execution_result) for
            each dependency and the target request.

        Raises:
            RunnerError: If the named request is not found.
        """
        named = http_file.named_requests
        if name not in named:
            raise RunnerError(f"Request '{name}' not found in {http_file.file_path}")

        resolver = self._create_resolver(http_file)
        graph = build_dependency_graph(http_file)

        # Get full dependency chain via topological sort, then filter
        full_order = topological_sort(graph)
        deps = self._collect_transitive_deps(name, graph)
        deps.add(name)

        # Execute only the needed requests in topo order
        for req_name in full_order:
            if req_name not in deps:
                continue

            request = named[req_name]
            if request.metadata.disabled:
                logger.info("Skipping disabled request: %s", req_name)
                continue

            result = await self._execute_request(request, resolver)
            resolver.add_chain_result(req_name, result)
            self._results[req_name] = result
            yield request, result

    def _collect_transitive_deps(self, name: str, graph: dict[str, set[str]]) -> set[str]:
        """Collect all transitive dependencies for a request.

        Args:
            name: Request name.
            graph: Dependency graph.

        Returns:
            Set of all transitive dependency names.
        """
        visited: set[str] = set()
        stack = list(graph.get(name, set()))

        while stack:
            dep = stack.pop()
            if dep in visited:
                continue
            visited.add(dep)
            stack.extend(graph.get(dep, set()))

        return visited

    async def _execute_request(
        self,
        request: HttpRequestDefinition,
        resolver: VariableResolver,
    ) -> ExecutionResult:
        """Resolve variables and execute a single request.

        Also handles response saving (>> and >>!) directives.

        Args:
            request: The request definition.
            resolver: The variable resolver with current state.

        Returns:
            The execution result.
        """
        # Resolve URL
        resolved_url = resolver.resolve_string(request.url)

        # Resolve headers
        resolved_headers: dict[str, str] = {}
        for header in request.headers:
            resolved_headers[header.name] = resolver.resolve_string(header.value)

        # Resolve body
        resolved_body: str | None = None
        if request.body:
            if request.body.file_ref:
                resolved_body = self._load_file_body(request.body.file_ref, request.location.file_path)
            elif request.body.content:
                resolved_body = resolver.resolve_string(request.body.content)

        result = await self._executor.execute(
            request=request,
            resolved_url=resolved_url,
            resolved_headers=resolved_headers,
            resolved_body=resolved_body,
        )

        # Handle response save directives
        if request.response_save_path and not result.error:
            self._save_response(
                request.response_save_path,
                result.response_body,
                request.location.file_path,
            )

        return result

    def _create_resolver(self, http_file: HttpFile) -> VariableResolver:
        """Create a VariableResolver for the given http_file.

        Args:
            http_file: Parsed .http file.

        Returns:
            Configured VariableResolver instance.
        """
        return VariableResolver(
            http_file=http_file,
            env_file=self._env_file,
            env_name=self._env_name,
            extra_vars=self._extra_vars,
        )

    @staticmethod
    def _load_file_body(file_ref: str, source_file: str) -> str | None:
        """Load body content from a file reference.

        Args:
            file_ref: Relative path to the body file.
            source_file: Path to the .http file (for relative resolution).

        Returns:
            File contents as string, or None if file not found.
        """
        base_dir = Path(source_file).parent
        body_path = base_dir / file_ref

        try:
            return body_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("Body file not found: %s", body_path)
            return None
        except OSError as exc:
            logger.warning("Error reading body file %s: %s", body_path, exc)
            return None

    @staticmethod
    def _save_response(save_path: str, body: str, source_file: str) -> None:
        """Save response body to a file.

        Handles both >> (no overwrite) and >>! (force overwrite).

        Args:
            save_path: The save path (may start with ! for overwrite).
            body: Response body to save.
            source_file: Path to the .http file (for relative resolution).
        """
        force = save_path.startswith("!")
        actual_path = save_path.lstrip("!").strip()
        base_dir = Path(source_file).parent
        full_path = base_dir / actual_path

        if full_path.exists() and not force:
            logger.warning(
                "Response file already exists (use >>! to overwrite): %s",
                full_path,
            )
            return

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(body, encoding="utf-8")
            logger.info("Response saved to %s", full_path)
        except OSError as exc:
            logger.warning("Failed to save response to %s: %s", full_path, exc)

    def get_result(self, name: str) -> ExecutionResult | None:
        """Get a stored execution result by request name.

        Args:
            name: Request name.

        Returns:
            The execution result, or None if not executed.
        """
        return self._results.get(name)

    @property
    def results(self) -> dict[str, ExecutionResult]:
        """Return all stored execution results."""
        return dict(self._results)
