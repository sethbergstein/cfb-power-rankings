#!/usr/bin/env python3
"""CLI entrypoint for Bergstein CFB Power Index."""

from typing import Optional

import click

from bcpi.backtest import run_backtest
from bcpi.constants import BACKTEST_END_SEASON, BACKTEST_START_SEASON, TARGET_SEASON
from bcpi.params import ModelParams, TUNED_PARAMS_PATH, get_active_params
from bcpi.matchup import format_matchup, predict_matchup
from bcpi.pipeline import run_poll_rankings, run_rankings
from bcpi.tune import run_tuning


@click.group()
def cli() -> None:
    """Bergstein CFB Power Index tools."""


@cli.command("rank")
@click.option("--season", default=TARGET_SEASON, show_default=True, type=int)
@click.option("--week", default=None, type=int, help="As-of week (default: latest completed).")
@click.option("--refresh", is_flag=True, help="Bypass local API cache.")
@click.option("--use-defaults", is_flag=True, help="Ignore tuned params file.")
@click.option("--postseason", is_flag=True, help="Include bowl/CFP games in ratings.")
def rank(season: int, week: Optional[int], refresh: bool, use_defaults: bool, postseason: bool) -> None:
    """Generate BCPI power rankings."""
    params = ModelParams() if use_defaults else get_active_params()
    path = run_rankings(
        season=season,
        week=week,
        refresh_data=refresh,
        params=params,
        include_postseason=postseason,
    )
    click.echo(f"BCPI rankings written to {path}")


@cli.command("poll")
@click.option("--season", default=TARGET_SEASON, show_default=True, type=int)
@click.option("--week", default=None, type=int, help="As-of week (default: latest completed).")
@click.option("--refresh", is_flag=True, help="Bypass local API cache.")
@click.option("--use-defaults", is_flag=True, help="Ignore tuned power params file.")
@click.option("--postseason", is_flag=True, help="Include bowl/CFP games in rankings.")
def poll(season: int, week: Optional[int], refresh: bool, use_defaults: bool, postseason: bool) -> None:
    """Generate Bergstein poll-style (resume) rankings."""
    params = ModelParams() if use_defaults else get_active_params()
    path = run_poll_rankings(
        season=season,
        week=week,
        refresh_data=refresh,
        params=params,
        include_postseason=postseason,
    )
    click.echo(f"Poll rankings written to {path}")


@cli.command("matchup")
@click.argument("team_a")
@click.argument("team_b")
@click.option(
    "--site",
    default="neutral",
    show_default=True,
    type=click.Choice(["neutral", "home_a", "home_b"], case_sensitive=False),
    help="home_a = first team home; home_b = second team home.",
)
@click.option("--season", default=TARGET_SEASON, show_default=True, type=int)
@click.option("--week", default=None, type=int, help="Ratings as-of week (default: latest).")
@click.option("--refresh", is_flag=True, help="Bypass local API cache.")
@click.option("--use-defaults", is_flag=True, help="Ignore tuned power params file.")
@click.option("--postseason", is_flag=True, help="Use ratings including bowl/CFP games.")
def matchup(
    team_a: str,
    team_b: str,
    site: str,
    season: int,
    week: Optional[int],
    refresh: bool,
    use_defaults: bool,
    postseason: bool,
) -> None:
    """Predict a matchup using BCPI power ratings (margin + win probability)."""
    params = ModelParams() if use_defaults else get_active_params()
    try:
        prediction = predict_matchup(
            team_a=team_a,
            team_b=team_b,
            site=site,
            season=season,
            week=week,
            refresh_data=refresh,
            params=params,
            include_postseason=postseason,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(format_matchup(prediction))


@cli.command("backfill-snapshots")
@click.option("--start", default=BACKTEST_START_SEASON, show_default=True, type=int)
@click.option("--end", default=BACKTEST_END_SEASON, show_default=True, type=int)
@click.option("--refresh", is_flag=True, help="Bypass local API cache.")
@click.option("--use-defaults", is_flag=True, help="Ignore tuned params file.")
def backfill_snapshots(start: int, end: int, refresh: bool, use_defaults: bool) -> None:
    """Generate postseason power + poll CSVs for a season range (static site catalog)."""
    params = ModelParams() if use_defaults else get_active_params()
    for season in range(start, end + 1):
        click.echo(f"Building {season} postseason rankings…")
        run_rankings(
            season=season,
            refresh_data=refresh,
            params=params,
            include_postseason=True,
        )
        run_poll_rankings(
            season=season,
            refresh_data=refresh,
            params=params,
            include_postseason=True,
        )
    click.echo(f"Backfill complete for {start}–{end}.")


@cli.command("export-site")
@click.option("--season", default=None, type=int, help="Season to publish (default: inferred).")
@click.option("--refresh", is_flag=True, help="Refresh CFBD cache when building rankings.")
def export_site(season: Optional[int], refresh: bool) -> None:
    """Build static site in docs/ for GitHub Pages."""
    from bcpi.static_export import export_site_tree

    path = export_site_tree(refresh=refresh, season=season)
    click.echo(f"Static site written to {path}")
    click.echo("Enable GitHub Pages: Settings → Pages → Deploy from branch → main → /docs")


@cli.command("serve")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True, type=int)
def serve(host: str, port: int) -> None:
    """Run local web UI for matchup predictions."""
    try:
        from web.serve import main as serve_main
    except ImportError as exc:
        raise click.ClickException(
            "Flask is required. Run: pip install -r requirements.txt"
        ) from exc
    serve_main(host=host, port=port)


@cli.command("backtest")
@click.option("--start", default=BACKTEST_START_SEASON, show_default=True, type=int)
@click.option("--end", default=BACKTEST_END_SEASON, show_default=True, type=int)
@click.option("--use-defaults", is_flag=True, help="Use default weights instead of tuned.")
def backtest(start: int, end: int, use_defaults: bool) -> None:
    """Walk-forward backtest (margin MAE + win log-loss)."""
    params = ModelParams() if use_defaults else get_active_params()
    summary, overall = run_backtest(start_season=start, end_season=end, params=params)

    if summary.empty:
        click.echo("No backtest results.")
        return

    click.echo(summary.to_string(index=False))
    click.echo(
        f"\nOverall ({overall.games} games): "
        f"MAE={overall.margin_mae:.2f} pts | "
        f"RMSE={overall.margin_rmse:.2f} | "
        f"log-loss={overall.win_log_loss:.3f} | "
        f"accuracy={overall.win_accuracy:.1%} | "
        f"solver MAE={overall.solver_margin_mae:.2f}"
    )


@cli.command("tune")
@click.option("--start", default=BACKTEST_START_SEASON, show_default=True, type=int)
@click.option("--end", default=BACKTEST_END_SEASON, show_default=True, type=int)
@click.option("--samples", default=80, show_default=True, type=int, help="Random search samples.")
@click.option("--refine", default=50, show_default=True, type=int, help="Local refine steps.")
def tune(start: int, end: int, samples: int, refine: int) -> None:
    """Search for better weights via walk-forward backtest (2018-2025)."""
    click.echo(f"Tuning BCPI on seasons {start}-{end}...")
    click.echo("Loading season data (cached API responses when available)...")

    result = run_tuning(
        start_season=start,
        end_season=end,
        random_samples=samples,
        refine_iterations=refine,
    )

    baseline = result["baseline"]["metrics"]
    tuned = result["tuned"]["metrics"]
    improvement = result["improvement"]

    click.echo("\n--- Baseline (default weights) ---")
    click.echo(
        f"MAE={baseline.margin_mae:.2f} | log-loss={baseline.win_log_loss:.3f} | "
        f"score={baseline.score():.3f}"
    )
    click.echo("\n--- Tuned ---")
    click.echo(
        f"MAE={tuned.margin_mae:.2f} | log-loss={tuned.win_log_loss:.3f} | "
        f"score={tuned.score():.3f}"
    )
    click.echo("\n--- Improvement ---")
    click.echo(
        f"MAE {improvement['margin_mae']:+.2f} pts | "
        f"log-loss {improvement['win_log_loss']:+.3f} | "
        f"score {improvement['score']:+.3f}"
    )
    click.echo(f"\nSaved tuned params to {TUNED_PARAMS_PATH}")


if __name__ == "__main__":
    cli()
