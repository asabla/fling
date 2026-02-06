"""CLI entry point for fling."""

import click

from fling import __version__


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="fling")
@click.pass_context
def main(ctx: click.Context) -> None:
    """fling — A Python .http file runner with CLI, TUI, and web interfaces."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
