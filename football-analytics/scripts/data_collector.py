"""
data_collector.py — Stage 1-4: Fixture collection + parallel data fetching.

Stages:
  1. Fetch NS fixtures for today + tomorrow
  2. Load metadata (bookmakers, bets) — cached
  3. Coverage check (odds/mapping)
  4. Per-fixture parallel data collection:
     - predictions (raw stats only)
     - odds (if high coverage)
     - standings
     - past N fixtures (home + away, for feature engineering)

Output: /tmp/raw_data.json

Reference: KESTRA-AGENT-IMPLEMENTATION-BRIEF.md Section III
"""

import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from utils.api_client import (
    APIFootballClient,
    fetch_fixtures,
    fetch_predictions,
    fetch_odds,
    fetch_standings,
    fetch_odds_mapping,
    fetch_bookmakers,
    fetch_bets,
    fetch_past_fixtures,
)
from utils.validators import extract_raw_stats_only, validate_predictions_raw
from utils.timezone import (
    today_istanbul,
    tomorrow_istanbul,
    api_date_param,
    format_istanbul,
    timestamp_to_istanbul,
    output_filename_suffix,
    now_istanbul,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("data_collector")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OUTPUT_PATH = os.getenv("OUTPUT_PATH", "/tmp/raw_data.json")
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))
PAST_FIXTURES_WINDOW = int(os.getenv("PAST_FIXTURES_WINDOW", "20"))
PRIORITY_LEAGUES = {
    39,   # Premier League
    140,  # La Liga
    135,  # Serie A
    78,   # Bundesliga
    61,   # Ligue 1
    203,  # Süper Lig
    2,    # Champions League
    3,    # Europa League
    88,   # Eredivisie
    94,   # Primeira Liga
}


# ---------------------------------------------------------------------------
# Stage 1: Fixture collection
# ---------------------------------------------------------------------------

def collect_fixtures(client: APIFootballClient) -> list[dict]:
    """Fetch NS fixtures for today and tomorrow (Istanbul time).

    Returns list of normalized fixture dicts.
    """
    today = today_istanbul()
    tomorrow = tomorrow_istanbul()

    logger.info(f"Fetching NS fixtures for {today} and {tomorrow} (Istanbul)")

    all_raw = []
    for d in [today, tomorrow]:
        raw = fetch_fixtures(client, date=api_date_param(d), status="NS")
        all_raw.extend(raw)
        logger.info(f"  {api_date_param(d)}: {len(raw)} fixtures")

    fixtures = []
    for item in all_raw:
        try:
            ts = item["fixture"]["timestamp"]
            match_time = timestamp_to_istanbul(ts)

            fixtures.append({
                "fixture_id": item["fixture"]["id"],
                "match_time_istanbul": format_istanbul(match_time),
                "league": {
                    "id": item["league"]["id"],
                    "name": item["league"]["name"],
                    "season": item["league"]["season"],
                },
                "home": {
                    "id": item["teams"]["home"]["id"],
                    "name": item["teams"]["home"]["name"],
                },
                "away": {
                    "id": item["teams"]["away"]["id"],
                    "name": item["teams"]["away"]["name"],
                },
                "is_priority": item["league"]["id"] in PRIORITY_LEAGUES,
            })
        except (KeyError, TypeError) as e:
            logger.warning(f"Skipping malformed fixture: {e}")

    logger.info(f"Stage 1 complete: {len(fixtures)} total NS fixtures")
    return fixtures


# ---------------------------------------------------------------------------
# Stage 2: Metadata (bookmakers + bets dict)
# ---------------------------------------------------------------------------

def load_metadata(client: APIFootballClient) -> dict:
    """Load bookmaker and bet type dictionaries.

    These change rarely — in production this would be cached 24h.
    """
    logger.info("Stage 2: Loading metadata (bookmakers, bets)")
    bookmakers = fetch_bookmakers(client)
    bets = fetch_bets(client)
    logger.info(f"  {len(bookmakers)} bookmakers, {len(bets)} bet types")
    return {"bookmakers": bookmakers, "bets": bets}


# ---------------------------------------------------------------------------
# Stage 3: Coverage check
# ---------------------------------------------------------------------------

def check_coverage(client: APIFootballClient, fixtures: list[dict]) -> tuple[set[int], set[int]]:
    """Determine which fixtures have odds coverage.

    Returns:
        (high_coverage_ids, low_coverage_ids)
    """
    logger.info("Stage 3: Checking odds coverage")
    covered = fetch_odds_mapping(client)

    fixture_ids = {f["fixture_id"] for f in fixtures}
    high = fixture_ids & covered
    low = fixture_ids - covered

    logger.info(f"  High coverage: {len(high)}, Low coverage: {len(low)}")
    return high, low


# ---------------------------------------------------------------------------
# Stage 4: Per-fixture data collection
# ---------------------------------------------------------------------------

def collect_fixture_data(
    client: APIFootballClient,
    fixture: dict,
    high_coverage_ids: set[int],
) -> dict:
    """Collect all raw data for a single fixture.

    Fetches:
    - predictions (raw stats only — forbidden block stripped)
    - odds (only if high coverage)
    - standings
    - past 20 fixtures for home team
    - past 20 fixtures for away team

    Returns normalized fixture data dict.
    """
    fid = fixture["fixture_id"]
    home_id = fixture["home"]["id"]
    away_id = fixture["away"]["id"]
    league_id = fixture["league"]["id"]
    season = fixture["league"]["season"]

    result = {
        "fixture_id": fid,
        "fixture_meta": fixture,
        "coverage": "high" if fid in high_coverage_ids else "low",
        "predictions_raw": None,
        "odds": None,
        "standings": None,
        "home_past_matches": [],
        "away_past_matches": [],
        "errors": [],
    }

    # --- Predictions (always) ---
    try:
        pred = fetch_predictions(client, fid)
        if pred:
            if validate_predictions_raw(pred):
                result["predictions_raw"] = extract_raw_stats_only(pred)
            else:
                logger.warning(f"[{fid}] Predictions validation failed")
                result["errors"].append("predictions_validation_failed")
        else:
            result["errors"].append("predictions_empty")
    except Exception as e:
        logger.error(f"[{fid}] Predictions fetch error: {e}")
        result["errors"].append(f"predictions_error: {e}")

    # --- Odds (only if high coverage) ---
    if fid in high_coverage_ids:
        try:
            odds = fetch_odds(client, fid)
            if odds:
                result["odds"] = odds
            else:
                result["errors"].append("odds_empty")
        except Exception as e:
            logger.error(f"[{fid}] Odds fetch error: {e}")
            result["errors"].append(f"odds_error: {e}")

    # --- Standings ---
    try:
        standings = fetch_standings(client, league_id, season)
        if standings:
            result["standings"] = standings
        else:
            result["errors"].append("standings_empty")
    except Exception as e:
        logger.error(f"[{fid}] Standings fetch error: {e}")
        result["errors"].append(f"standings_error: {e}")

    # --- Past fixtures: home team ---
    try:
        home_past_raw = fetch_past_fixtures(
            client, home_id,
            last=PAST_FIXTURES_WINDOW,
            league_id=league_id,
            season=season,
        )
        result["home_past_raw"] = home_past_raw
        logger.debug(f"[{fid}] Home past: {len(home_past_raw)} matches")
    except Exception as e:
        logger.error(f"[{fid}] Home past fixtures error: {e}")
        result["errors"].append(f"home_past_error: {e}")
        result["home_past_raw"] = []

    # --- Past fixtures: away team ---
    try:
        away_past_raw = fetch_past_fixtures(
            client, away_id,
            last=PAST_FIXTURES_WINDOW,
            league_id=league_id,
            season=season,
        )
        result["away_past_raw"] = away_past_raw
        logger.debug(f"[{fid}] Away past: {len(away_past_raw)} matches")
    except Exception as e:
        logger.error(f"[{fid}] Away past fixtures error: {e}")
        result["errors"].append(f"away_past_error: {e}")
        result["away_past_raw"] = []

    return result


def collect_all_fixtures_parallel(
    client: APIFootballClient,
    fixtures: list[dict],
    high_coverage_ids: set[int],
) -> list[dict]:
    """Collect data for all fixtures using a thread pool.

    Uses MAX_WORKERS threads to parallelize API calls per fixture.
    Rate limiting is enforced inside each API call.
    """
    logger.info(f"Stage 4: Collecting data for {len(fixtures)} fixtures ({MAX_WORKERS} workers)")

    results = []
    completed = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_fixture = {
            executor.submit(collect_fixture_data, client, f, high_coverage_ids): f
            for f in fixtures
        }

        for future in as_completed(future_to_fixture):
            fixture = future_to_fixture[future]
            fid = fixture["fixture_id"]
            try:
                data = future.result()
                results.append(data)
                completed += 1

                if completed % 10 == 0:
                    logger.info(f"  Progress: {completed}/{len(fixtures)} fixtures collected")

            except Exception as e:
                logger.error(f"[{fid}] Fatal error in fixture collection: {e}")
                failed += 1
                results.append({
                    "fixture_id": fid,
                    "fixture_meta": fixture,
                    "coverage": "unknown",
                    "predictions_raw": None,
                    "odds": None,
                    "standings": None,
                    "home_past_raw": [],
                    "away_past_raw": [],
                    "errors": [f"fatal: {e}"],
                })

    logger.info(f"Stage 4 complete: {completed} ok, {failed} failed")
    return results


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 60)
    logger.info("Football Analytics — Data Collector")
    logger.info(f"Run time: {now_istanbul().strftime('%Y-%m-%d %H:%M %Z')}")
    logger.info("=" * 60)

    with APIFootballClient() as client:
        # Stage 1
        fixtures = collect_fixtures(client)
        if not fixtures:
            logger.warning("No NS fixtures found. Exiting.")
            output = {
                "collection_time_istanbul": format_istanbul(now_istanbul()),
                "total_fixtures": 0,
                "fixtures_data": [],
                "metadata": {},
                "summary": {"high_coverage": 0, "low_coverage": 0},
            }
            Path(OUTPUT_PATH).write_text(json.dumps(output, ensure_ascii=False, indent=2))
            sys.exit(0)

        # Stage 2
        metadata = load_metadata(client)

        # Stage 3
        high_coverage_ids, low_coverage_ids = check_coverage(client, fixtures)

        # Stage 4
        fixtures_data = collect_all_fixtures_parallel(client, fixtures, high_coverage_ids)

    # Build output
    output = {
        "collection_time_istanbul": format_istanbul(now_istanbul()),
        "total_fixtures": len(fixtures),
        "summary": {
            "high_coverage": len(high_coverage_ids),
            "low_coverage": len(low_coverage_ids),
            "with_predictions": sum(1 for f in fixtures_data if f.get("predictions_raw")),
            "with_odds": sum(1 for f in fixtures_data if f.get("odds")),
            "with_standings": sum(1 for f in fixtures_data if f.get("standings")),
            "errors": sum(1 for f in fixtures_data if f.get("errors")),
        },
        "metadata": metadata,
        "fixtures_data": fixtures_data,
    }

    Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(OUTPUT_PATH).write_text(json.dumps(output, ensure_ascii=False, indent=2))

    logger.info(f"Output written to {OUTPUT_PATH}")
    logger.info(f"Summary: {output['summary']}")
    logger.info("Data collection complete.")


if __name__ == "__main__":
    main()
