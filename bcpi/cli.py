#!/usr/bin/env python3
"""CLI entrypoint for Bergstein CFB Power Index."""

from typing import Optional

import click

from bcpi.constants import TARGET_SEASON
from bcpi.pipeline import run_rankings
from bcpi.backtest import run_backtest


@click.group()
def cli() -> None:
    """Bergstein CFB Power Index tools."""


@cli.command("rank")
@click.option("--season", default=TARGET_SEASON, show_default=True, type=int)
@click.option("--week", default=None, type=int, help="As-of week (default: latest completed).")
@click.option("--refresh", is_flag=True, help="Bypass local API cache.")
def rank(season: int, week: Optional[int], refresh: bool) -> None:
    """Generate BCPI power rankings."""
    path = run_rankings(season=season, week=week, refresh_data=refresh)
    click.echo(f"BCPI rankings written to {path}")


@cli.command("backtest")
@click.option("--start", default=2018, show_default=True, type=int)
@click.option("--end", default=2025, show_default=True, type=int)
def backtest(start: int, end: int) -> None:
    """Run simple margin MAE backtest across seasons."""
    frame = run_backtest(start_season=start, end_season=end)
    if frame.empty:
        click.echo("No backtest results.")
        return
    click.echo(frame.to_string(index=False))
    click.echo(f"\nOverall MAE: {frame['margin_mae'].mean():.2f} points")


if __name__ == "__main__":
    cli()
