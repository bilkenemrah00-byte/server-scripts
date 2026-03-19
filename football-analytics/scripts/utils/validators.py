"""
Data validation utilities.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def validate_predictions_raw(data: dict) -> bool:
    """Validate predictions data — forbidden block is stripped, not fatal."""
    if not data:
        logger.warning("Empty predictions data")
        return False

    if "predictions" in data:
        pred_block = data["predictions"]
        if isinstance(pred_block, dict):
            forbidden_found = [
                k for k in ["winner", "percent", "advice", "goals"]
                if k in pred_block
            ]
            if forbidden_found:
                logger.debug(f"Predictions block has forbidden keys {forbidden_found} — will be stripped by extract_raw_stats_only")
                # Not fatal — extract_raw_stats_only handles this

    required = [
        ("teams", "home", "league"),
        ("teams", "away", "league"),
        ("teams", "home", "last_5"),
        ("teams", "away", "last_5"),
    ]

    for path in required:
        obj = data
        for key in path:
            if not isinstance(obj, dict) or key not in obj:
                logger.warning(f"Missing required path: {'.'.join(path)}")
                return False
            obj = obj[key]

    return True


def extract_raw_stats_only(predictions_response: dict) -> dict:
    """Extract ONLY raw statistics — drops predictions.predictions.* block."""
    if not predictions_response:
        return {}

    return {
        "teams": {
            "home": {
                "league": safe_get(predictions_response, "teams", "home", "league") or {},
                "last_5": safe_get(predictions_response, "teams", "home", "last_5") or {},
            },
            "away": {
                "league": safe_get(predictions_response, "teams", "away", "league") or {},
                "last_5": safe_get(predictions_response, "teams", "away", "last_5") or {},
            },
        },
        "h2h": predictions_response.get("h2h", []),
        "comparison": predictions_response.get("comparison", {}),
    }


def safe_get(obj: Any, *keys, default=None) -> Any:
    for key in keys:
        if obj is None:
            return default
        if isinstance(obj, dict):
            obj = obj.get(key)
        elif isinstance(obj, list) and isinstance(key, int):
            obj = obj[key] if 0 <= key < len(obj) else None
        else:
            return default
    return obj if obj is not None else default


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(str(value).strip().rstrip("%"))
    except (ValueError, TypeError):
        return default


def safe_percent(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(str(value).strip().rstrip("%")) / 100.0
    except (ValueError, TypeError):
        return default


def safe_goals_avg(value: Any, default: float = 0.0) -> float:
    return max(0.0, safe_float(value, default))


def parse_past_fixture(fixture: dict, team_id: int) -> Optional[dict]:
    try:
        home_id = safe_get(fixture, "teams", "home", "id")
        is_home = home_id == team_id

        if is_home:
            goals_for = safe_int(safe_get(fixture, "goals", "home"), 0)
            goals_against = safe_int(safe_get(fixture, "goals", "away"), 0)
            ht_for = safe_int(safe_get(fixture, "score", "halftime", "home"), 0)
            ht_against = safe_int(safe_get(fixture, "score", "halftime", "away"), 0)
            opponent_id = safe_get(fixture, "teams", "away", "id")
        else:
            goals_for = safe_int(safe_get(fixture, "goals", "away"), 0)
            goals_against = safe_int(safe_get(fixture, "goals", "home"), 0)
            ht_for = safe_int(safe_get(fixture, "score", "halftime", "away"), 0)
            ht_against = safe_int(safe_get(fixture, "score", "halftime", "home"), 0)
            opponent_id = safe_get(fixture, "teams", "home", "id")

        result = "W" if goals_for > goals_against else "L" if goals_for < goals_against else "D"

        return {
            "fixture_id": fixture["fixture"]["id"],
            "date": fixture["fixture"]["date"],
            "is_home": is_home,
            "opponent_id": opponent_id,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "halftime_for": ht_for,
            "halftime_against": ht_against,
            "result": result,
        }
    except Exception as e:
        logger.warning(f"Failed to parse past fixture: {e}")
        return None


def parse_past_fixtures(fixtures: list, team_id: int) -> list:
    parsed = [parse_past_fixture(f, team_id) for f in fixtures]
    return [p for p in parsed if p is not None]


def find_bet_values(odds_response: dict, bet_id: int) -> list:
    if not odds_response:
        return []
    for bookmaker in odds_response.get("bookmakers", []):
        for bet in bookmaker.get("bets", []):
            if bet.get("id") == bet_id:
                return bet.get("values", [])
    return []


def get_odds_value(values: list, label: str) -> Optional[float]:
    for v in values:
        if v.get("value", "").strip() == label:
            return safe_float(v.get("odd"), None)
    return None


def implied_probability(odd) -> Optional[float]:
    if odd is None or odd <= 0:
        return None
    return 1.0 / odd
