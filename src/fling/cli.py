"""CLI entry point for fling.

Provides commands for running .http files, listing requests,
listing environments, and converting Postman collections.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import click
from rich.console import Console
from rich.markup import escape
from rich.syntax import Syntax
from rich.table import Table

from fling import __version__
from fling.core.environment import list_environments, load_environment
from fling.core.parser import parse_http_file
from fling.core.runner import HttpRunner, RunnerError

if TYPE_CHECKING:
    from fling.core.models import ExecutionResult, HttpFile, HttpRequestDefinition

console = Console()
error_console = Console(stderr=True)


def _status_style(code: int) -> str:
    """Return a Rich style string for an HTTP status code."""
    if code < 300:
        return "bold green"
    if code < 400:
        return "bold yellow"
    return "bold red"


def _format_elapsed(ms: float) -> str:
    """Format elapsed time for display."""
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.2f}s"


def _print_result(
    request: HttpRequestDefinition,
    result: ExecutionResult,
    *,
    output: str,
    verbose: bool,
) -> None:
    """Print an execution result to the console.

    Args:
        request: The original request definition.
        result: The execution result.
        output: Output format (exchange, headers, body, json).
        verbose: Whether to show extra detail.
    """
    name = request.metadata.name or request.url

    if result.error:
        error_console.print(f"[bold red]ERROR[/] {escape(name)}: {escape(result.error)}")
        return

    status_style = _status_style(result.status_code)

    if output == "exchange" or verbose:
        # Print request line
        console.print(f"[dim]{request.method.value}[/] {escape(result.resolved_url)}")

    # Status line
    console.print(
        f"[{status_style}]{result.status_code}[/] "
        f"[dim]{_format_elapsed(result.elapsed_ms)}[/]"
        + (f"  [dim]# {escape(name)}[/]" if request.metadata.name else ""),
    )

    if output in ("exchange", "headers"):
        # Print response headers
        for header_name, values in result.response_headers.items():
            for val in values:
                console.print(f"[cyan]{escape(header_name)}[/]: {escape(val)}")
        console.print()

    if output in ("exchange", "body", "json"):
        body = result.response_body
        if body:
            # Try to detect JSON for syntax highlighting
            content_types = result.response_headers.get("content-type", [])
            is_json = any("json" in ct for ct in content_types) or _looks_like_json(body)
            is_xml = any("xml" in ct or "html" in ct for ct in content_types)

            if is_json:
                _print_highlighted(body, "json")
            elif is_xml:
                _print_highlighted(body, "xml")
            else:
                console.print(body)


def _looks_like_json(text: str) -> bool:
    """Quick heuristic: does the text look like JSON?"""
    stripped = text.strip()
    return (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    )


def _print_highlighted(text: str, lexer: str) -> None:
    """Print syntax-highlighted text."""
    try:
        import json

        if lexer == "json":
            # Pretty-print JSON
            parsed = json.loads(text)
            text = json.dumps(parsed, indent=2)
    except (json.JSONDecodeError, ValueError):
        pass

    syntax = Syntax(text, lexer, theme="monokai", word_wrap=True)
    console.print(syntax)


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="fling")
@click.pass_context
def main(ctx: click.Context) -> None:
    """fling -- A Python .http file runner with CLI, TUI, and web interfaces."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--name", "-n", help="Run a specific named request.")
@click.option("--all", "run_all", is_flag=True, help="Run all requests in order.")
@click.option("--env", "-e", help="Environment name to use.")
@click.option("--env-file", type=click.Path(exists=True), help="Path to env file directory.")
@click.option("--verbose", "-v", is_flag=True, help="Show extra detail.")
@click.option(
    "--output",
    "-o",
    type=click.Choice(["exchange", "headers", "body", "json"]),
    default="exchange",
    help="Output format.",
)
@click.option("--timeout", type=int, help="Request timeout in milliseconds.")
@click.option("--insecure", "-k", is_flag=True, help="Skip SSL verification.")
def run(
    file: str,
    name: str | None,
    run_all: bool,
    env: str | None,
    env_file: str | None,
    verbose: bool,
    output: str,
    timeout: int | None,
    insecure: bool,
) -> None:
    """Run HTTP requests from a .http file."""
    # Parse the file
    parse_result = parse_http_file(file)
    if parse_result.has_errors:
        for err in parse_result.errors:
            loc = f" at line {err.location.start_line}" if err.location else ""
            error_console.print(f"[bold red]Parse error[/]{loc}: {escape(err.message)}")
        sys.exit(1)

    http_file = parse_result.http_file

    if not http_file.requests:
        error_console.print("[yellow]No requests found in file.[/]")
        sys.exit(0)

    # Load environment
    env_dir = Path(env_file) if env_file else Path(file).parent
    env_config = load_environment(str(env_dir))

    # Handle prompt variables
    extra_vars: dict[str, str] = {}
    if name:
        named = http_file.named_requests
        if name in named:
            for var_name, description in named[name].metadata.prompt_vars.items():
                value = click.prompt(description or var_name)
                extra_vars[var_name] = value

    # Build runner
    runner_kwargs: dict[str, object] = {
        "env_file": env_config,
        "env_name": env,
        "extra_vars": extra_vars if extra_vars else None,
        "verify_ssl": not insecure,
    }
    if timeout is not None:
        runner_kwargs["default_timeout"] = timeout / 1000.0

    runner = HttpRunner(**runner_kwargs)  # type: ignore[arg-type]

    # Execute
    async def _run() -> int:
        error_count = 0
        if name:
            try:
                async for req, result in runner.run_single(http_file, name):
                    _print_result(req, result, output=output, verbose=verbose)
                    if result.error:
                        error_count += 1
            except RunnerError as exc:
                error_console.print(f"[bold red]Error[/]: {exc}")
                return 1
        elif run_all or len(http_file.requests) == 1:
            async for req, result in runner.run_all(http_file):
                _print_result(req, result, output=output, verbose=verbose)
                if result.error:
                    error_count += 1
        else:
            # Default: run first request only
            first = http_file.requests[0]
            async for req, result in runner.run_all(_make_single_file(http_file, first)):
                _print_result(req, result, output=output, verbose=verbose)
                if result.error:
                    error_count += 1
        return error_count

    errors = asyncio.run(_run())
    if errors:
        sys.exit(1)


def _make_single_file(
    http_file: HttpFile,
    request: HttpRequestDefinition,
) -> HttpFile:
    """Create an HttpFile containing only the given request.

    Preserves file-level variables from the original file.
    """
    from fling.core.models import HttpFile as HttpFileModel

    return HttpFileModel(
        file_path=http_file.file_path,
        variables=http_file.variables,
        requests=[request],
    )


@main.command("list")
@click.argument("file", type=click.Path(exists=True))
def list_requests(file: str) -> None:
    """List all requests in a .http file."""
    parse_result = parse_http_file(file)
    if parse_result.has_errors:
        for err in parse_result.errors:
            loc = f" at line {err.location.start_line}" if err.location else ""
            error_console.print(f"[bold red]Parse error[/]{loc}: {escape(err.message)}")
        sys.exit(1)

    http_file = parse_result.http_file

    if not http_file.requests:
        console.print("[yellow]No requests found.[/]")
        return

    table = Table(title=f"Requests in {file}")
    table.add_column("#", style="dim", width=4)
    table.add_column("Name", style="cyan")
    table.add_column("Method", style="bold")
    table.add_column("URL")
    table.add_column("Flags", style="dim")

    for i, req in enumerate(http_file.requests, 1):
        flags = []
        if req.metadata.disabled:
            flags.append("disabled")
        if req.metadata.no_redirect:
            flags.append("no-redirect")
        if req.metadata.refs:
            flags.append(f"refs: {', '.join(req.metadata.refs)}")

        table.add_row(
            str(i),
            req.metadata.name or "[dim]-[/]",
            req.method.value,
            req.url,
            ", ".join(flags) if flags else "",
        )

    console.print(table)


@main.command()
@click.option("--env-file", type=click.Path(exists=True), help="Path to env file directory.")
def envs(env_file: str | None) -> None:
    """List available environments."""
    search_dir = env_file or "."
    env_config = load_environment(search_dir)

    if not env_config:
        console.print("[yellow]No environment files found.[/]")
        return

    environments = list_environments(env_config)

    if not environments:
        console.print("[yellow]No environments defined.[/]")
        return

    table = Table(title="Available Environments")
    table.add_column("Name", style="cyan bold")
    table.add_column("Variables", style="dim")

    for env_name in sorted(environments):
        env_vars = env_config.environments.get(env_name, {})
        var_count = len(env_vars)
        var_names = ", ".join(sorted(env_vars.keys())[:5])
        if var_count > 5:
            var_names += f" (+{var_count - 5} more)"
        table.add_row(env_name, var_names or "[dim]empty[/]")

    console.print(table)


@main.command()
@click.argument("postman_file", type=click.Path(exists=True))
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    help="Output directory for .http files (default: current directory).",
)
@click.option(
    "--split-folders",
    is_flag=True,
    help="Create one .http file per top-level folder.",
)
def convert(postman_file: str, output: str | None, split_folders: bool) -> None:
    """Convert a Postman collection to .http file(s)."""
    import json
    import re

    from fling.core.postman import (
        convert_collection_to_http,
        convert_collection_to_http_per_folder,
        parse_postman_collection,
    )

    try:
        collection = parse_postman_collection(postman_file)
    except (ValueError, json.JSONDecodeError) as exc:
        error_console.print(f"[bold red]Error[/]: {exc}")
        sys.exit(1)

    output_dir = Path(output) if output else Path(".")
    output_dir.mkdir(parents=True, exist_ok=True)

    if split_folders:
        files = convert_collection_to_http_per_folder(collection)
        if not files:
            error_console.print("[yellow]No requests found in collection.[/]")
            sys.exit(0)

        for name, content in files.items():
            file_path = output_dir / f"{name}.http"
            file_path.write_text(content, encoding="utf-8")
            console.print(f"[green]Created[/] {file_path}")

        console.print(f"\n[bold]Converted {len(files)} file(s)[/]")
    else:
        content = convert_collection_to_http(collection)
        # Use collection name as filename
        safe_name = collection.info.name.lower().replace(" ", "-") or "collection"
        safe_name = re.sub(r"[^\w-]", "", safe_name)
        file_path = output_dir / f"{safe_name}.http"
        file_path.write_text(content, encoding="utf-8")
        console.print(f"[green]Created[/] {file_path}")
        console.print(f"\n[bold]Converted collection '{collection.info.name}'[/]")


@main.command()
@click.argument("file", required=False, type=click.Path(exists=True))
@click.option("--env", "-e", help="Environment name to use.")
def tui(file: str | None, env: str | None) -> None:
    """Launch the interactive TUI for a .http file."""
    from fling.tui.app import FlingApp

    app = FlingApp(file_path=file, env_name=env)
    app.run()


@main.command()
@click.argument("file", required=False, type=click.Path(exists=True))
@click.option("--port", "-p", default=8000, help="Port to serve on.")
@click.option("--host", default="0.0.0.0", help="Host to bind to.")
@click.option("--env", "-e", help="Environment name to use.")
def serve(file: str | None, port: int, host: str, env: str | None) -> None:
    """Launch the web interface for a .http file."""
    import uvicorn

    from fling.web.app import create_app

    app = create_app(file_path=file, env_name=env)
    uvicorn.run(app, host=host, port=port)
