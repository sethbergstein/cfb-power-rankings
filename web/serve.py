"""Local web UI — Press Box Ledger."""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from bcpi.cfbd import CFBDClient
from bcpi.constants import TARGET_SEASON
from bcpi.matchup import predict_matchup, resolve_team_name
from bcpi.params import get_active_params
from bcpi.rankings_io import load_rankings_df
from bcpi.team_profiles import get_team_profiles
from bcpi.teams import get_fbs_teams

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"


def _enrich_rankings(
    kind: str,
    df,
    season: int,
    postseason: bool,
) -> list:
    rows = df.sort_values("rank").to_dict(orient="records")
    other_kind = "poll" if kind == "power" else "power"
    try:
        other_df, _, _ = load_rankings_df(
            other_kind, season, postseason=postseason, refresh=False
        )
        other_by = other_df.set_index("school")
        for row in rows:
            school = row["school"]
            if school not in other_by.index:
                continue
            other = other_by.loc[school]
            if kind == "power":
                row["wins"] = int(other.get("wins", 0))
                row["losses"] = int(other.get("losses", 0))
                row["poll_rank"] = int(other["rank"])
                row["poll_score"] = float(other["poll_score"])
            else:
                row["power_rank"] = int(other["rank"])
                row["power_score"] = float(other["power_score"])
    except Exception:
        pass
    return rows


def create_app() -> Flask:
    app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")

    def _season() -> int:
        return request.args.get("season", TARGET_SEASON, type=int)

    def _postseason() -> bool:
        return request.args.get("postseason", "0") in ("1", "true", "yes")

    @app.get("/")
    def index() -> object:
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/power")
    @app.get("/power.html")
    def power_page() -> object:
        return send_from_directory(WEB_DIR, "power.html")

    @app.get("/poll")
    @app.get("/poll.html")
    def poll_page() -> object:
        return send_from_directory(WEB_DIR, "poll.html")

    @app.get("/api/teams")
    def api_teams() -> object:
        season = _season()
        client = CFBDClient(use_cache=True)
        try:
            teams = get_fbs_teams(client, season)
            profiles = get_team_profiles(client, season)
            payload = []
            for team in teams:
                profile = profiles.get(team.school, {})
                payload.append(
                    {
                        "school": team.school,
                        "abbreviation": team.abbreviation,
                        "conference": profile.get("conference") or team.conference,
                        "color": profile.get("color"),
                        "alternate_color": profile.get("alternate_color"),
                        "logo": profile.get("logo"),
                        "logo_dark": profile.get("logo_dark"),
                        "venue_name": profile.get("venue_name"),
                        "venue_city": profile.get("venue_city"),
                        "venue_state": profile.get("venue_state"),
                        "venue_location": profile.get("venue_location"),
                        "venue_capacity": profile.get("venue_capacity"),
                    }
                )
            return jsonify(payload)
        finally:
            client.close()

    @app.get("/api/rankings/<kind>")
    def api_rankings(kind: str) -> object:
        if kind not in ("power", "poll"):
            return jsonify({"error": "kind must be power or poll"}), 400
        season = _season()
        postseason = _postseason()
        refresh = request.args.get("refresh", "0") in ("1", "true", "yes")
        try:
            df, as_of_week, path = load_rankings_df(
                kind,
                season,
                postseason=postseason,
                refresh=refresh,
            )
            rows = _enrich_rankings(kind, df, season, postseason)
            top25 = rows[:25]
            also_ran = rows[25:35]
            return jsonify(
                {
                    "kind": kind,
                    "season": season,
                    "postseason": postseason,
                    "week": as_of_week,
                    "as_of": rows[0].get("as_of") if rows else None,
                    "rows": top25,
                    "also_ran": also_ran,
                }
            )
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    @app.get("/api/matchup")
    def api_matchup() -> object:
        team_a = request.args.get("team_a", "").strip()
        team_b = request.args.get("team_b", "").strip()
        site = request.args.get("site", "neutral")
        season = _season()
        postseason = _postseason()

        if not team_a or not team_b:
            return jsonify({"error": "team_a and team_b are required"}), 400

        client = CFBDClient(use_cache=True)
        try:
            teams = get_fbs_teams(client, season)
            school_a = resolve_team_name(team_a, teams)
            school_b = resolve_team_name(team_b, teams)
            profiles = get_team_profiles(client, season)
            prediction = predict_matchup(
                team_a=team_a,
                team_b=team_b,
                site=site,
                season=season,
                params=get_active_params(),
                include_postseason=postseason,
            )
            payload = prediction.to_dict()
            payload["team_a"] = school_a
            payload["team_b"] = school_b
            if prediction.home_team == school_a:
                payload["predicted_margin_a"] = payload["predicted_margin_home"]
                payload["win_prob_a"] = payload["home_win_probability"]
                payload["win_prob_b"] = payload["away_win_probability"]
                payload["rank_a"] = payload["home_bcpi_rank"]
                payload["rank_b"] = payload["away_bcpi_rank"]
                payload["power_rating_a"] = payload["home_power_rating"]
                payload["power_rating_b"] = payload["away_power_rating"]
            else:
                payload["predicted_margin_a"] = -payload["predicted_margin_home"]
                payload["win_prob_a"] = payload["away_win_probability"]
                payload["win_prob_b"] = payload["home_win_probability"]
                payload["rank_a"] = payload["away_bcpi_rank"]
                payload["rank_b"] = payload["home_bcpi_rank"]
                payload["power_rating_a"] = payload["away_power_rating"]
                payload["power_rating_b"] = payload["home_power_rating"]
            for key, school in (("team_a", school_a), ("team_b", school_b)):
                profile = profiles.get(school, {})
                payload[f"{key}_profile"] = {
                    "school": school,
                    "logo": profile.get("logo"),
                    "logo_dark": profile.get("logo_dark"),
                    "color": profile.get("color"),
                    "venue_name": profile.get("venue_name"),
                    "venue_location": profile.get("venue_location"),
                }
            pa = profiles.get(school_a, {})
            pb = profiles.get(school_b, {})
            if site == "home_a":
                payload["venue_label"] = pa.get("venue_name")
                payload["venue_location"] = pa.get("venue_location")
            elif site == "home_b":
                payload["venue_label"] = pb.get("venue_name")
                payload["venue_location"] = pb.get("venue_location")
            else:
                payload["venue_label"] = "Neutral site"
                payload["venue_location"] = "No home field advantage"
            return jsonify(payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        finally:
            client.close()

    return app


def main(host: str = "127.0.0.1", port: int = 8765, debug: bool = False) -> None:
    import os

    port = int(os.environ.get("PORT", port))
    host = os.environ.get("HOST", host)
    app = create_app()
    print(f"BCPI Press Box Ledger: http://{host}:{port}")
    print(f"Season default: {TARGET_SEASON}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
