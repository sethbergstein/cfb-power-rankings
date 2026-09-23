#!/usr/bin/env python3
"""CLI entrypoint for Bergstein CFB Power Index."""

from typing import Optional, Tuple

import click

from bcpi.backtest import BacktestMetrics, run_backtest
from bcpi.checks import format_annotations
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
    click.echo(f"\nOverall ({overall.games} games)")
    click.echo(_format_metrics(overall))


def _format_metrics(metrics: BacktestMetrics) -> str:
    return (
        f"  matchup page: MAE={metrics.margin_mae:.2f} pts | RMSE={metrics.margin_rmse:.2f} | "
        f"log-loss={metrics.win_log_loss:.3f} | accuracy={metrics.win_accuracy:.1%}\n"
        f"  fitted:       MAE={metrics.fitted_mae:.2f} (weeks 2-4 {metrics.fitted_mae_early:.2f}, "
        f"5-8 {metrics.fitted_mae_mid:.2f}, 9+ {metrics.fitted_mae_late:.2f}) | "
        f"log-loss={metrics.fitted_log_loss:.3f} | accuracy={metrics.fitted_accuracy:.1%}\n"
        f"  implied matchup scale={metrics.implied_matchup_margin_scale:.2f} | "
        f"home field={metrics.fitted_hfa:.2f} | win-prob scale={metrics.fitted_win_prob_scale:.2f} | "
        f"solver-only MAE={metrics.solver_margin_mae:.2f} | score={metrics.score():.3f}"
    )


@cli.command("tune")
@click.option("--start", default=BACKTEST_START_SEASON, show_default=True, type=int)
@click.option("--end", default=BACKTEST_END_SEASON, show_default=True, type=int)
@click.option("--rounds", default=4, show_default=True, type=int, help="Coordinate-search rounds.")
@click.option(
    "--holdout",
    multiple=True,
    type=int,
    help="Season to leave out of the search and report separately (repeatable).",
)
@click.option("--no-save", is_flag=True, help="Report only; keep the current tuned params.")
def tune(start: int, end: int, rounds: int, holdout: Tuple[int, ...], no_save: bool) -> None:
    """Search model parameters via walk-forward backtest, starting from the active params."""
    click.echo(f"Tuning BCPI on seasons {start}-{end}...")

    def progress(round_index: int, name: str, metrics: BacktestMetrics) -> None:
        click.echo(f"  round {round_index} {name:<36} score={metrics.score():.4f}")

    result = run_tuning(
        start_season=start,
        end_season=end,
        rounds=rounds,
        holdout=holdout,
        save=not no_save,
        progress=progress,
    )

    click.echo(f"\n{result['evaluations']} backtest evaluations")
    click.echo("--- Baseline (active params) ---")
    click.echo(_format_metrics(result["baseline"]["metrics"]))
    click.echo("--- Tuned ---")
    click.echo(_format_metrics(result["tuned"]["metrics"]))
    if "holdout" in result:
        seasons = ", ".join(str(season) for season in result["holdout"]["seasons"])
        click.echo(f"--- Holdout seasons ({seasons}): baseline, then tuned ---")
        click.echo(_format_metrics(result["holdout"]["baseline"]))
        click.echo(_format_metrics(result["holdout"]["tuned"]))
    if not no_save:
        click.echo(f"\nSaved tuned params to {TUNED_PARAMS_PATH}")


@cli.command("check")
@click.option("--season", default=TARGET_SEASON, show_default=True, type=int)
@click.option("--week", default=None, type=int, help="As-of week (default: latest on disk).")
@click.option("--postseason", is_flag=True, help="Check the postseason snapshot.")
def check_rankings(season: int, week: Optional[int], postseason: bool) -> None:
    """Print health/invariant annotations for a snapshot; exit 1 on a health error."""
    import json
    from pathlib import Path

    from bcpi.config import OUTPUT_DIR
    from bcpi.rankings_io import find_rankings_path

    paths = []
    for kind in ("power", "poll"):
        csv_path = find_rankings_path(kind, season, postseason=postseason, week=week)
        if csv_path is None:
            continue
        sidecar = Path(str(csv_path).replace(".csv", "_checks.json"))
        if sidecar.exists():
            paths.append(sidecar)

    if not paths:
        # Fall back to every sidecar in output/ for this season.
        paths = sorted(OUTPUT_DIR.glob(f"bcpi_*_{season}*_checks.json"))
    if not paths:
        raise click.ClickException(f"No check files found for {season}. Run rank and poll first.")

    health_errors = 0
    for path in paths:
        payload = json.loads(path.read_text())
        results = payload.get("violations", [])
        from bcpi.checks import CheckResult

        parsed = [CheckResult(**row) for row in results]
        health_errors += payload.get("health_errors", 0)
        click.echo(f"{path.name}: {len(parsed)} violation(s)")
        for line in format_annotations(parsed):
            click.echo(line)
    if health_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    cli()
