"""
Data validation utilities.

Validates raw API responses before feature engineering.
Enforces the critical rule: predictions.predictions.* is NEVER extracted.

Reference: KESTRA-AGENT-IMPLEMENTATION-BRIEF.md Section VI.2
Reference: CRITICAL-CORRECTION-PREDICTIONS-USAGE.md
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def validate_predictions_raw(data: dict) -> bool:
    """Verify predictions data does NOT contain the forbidden API predictions block.

    CRITICAL RULE: We NEVER use predictions.predictions.* fields.
    These are API-Football's own ML output, not our feature inputs.
    """
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
                raise ValueError(
                    f"CRITICAL: predictions.predictions.* block found with keys: {forbidden_found}. "
                    "Extract ONLY teams.*.league.*, teams.*.last_5.*, h2h, comparison. "
                    "See CRITICAL-CORRECTION-PREDICTIONS-USAGE.md"
                )

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
                logger.warning(f"Missing required path in predictions: {'.'.join(path)}")
                return False
            obj = obj[key]

    return True


def extract_raw_stats_only(predictions_response: dict) -> dict:
    """Extract ONLY raw statistics from predictions response.

    Explicitly drops predictions.predictions.* block.
    This is the safe entry point for all prediction data.
    """
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
    """Safely traverse nested dict with default fallback."""
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
    """Convert to float safely."""
    if value is None:
        return default
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Convert to int safely."""
    if value is None:
        return default
    try:
        return int(str(value).strip().rstrip("%"))
    except (ValueError, TypeError):
        return default


def safe_percent(value: Any, default: float = 0.0) -> float:
    """Parse percentage string like '45%' to 0.45."""
    if value is None:
        return default
    try:
        s = str(value).strip().rstrip("%")
        return float(s) / 100.0
    except (ValueError, TypeError):
        return default


def safe_goals_avg(value: Any, default: float = 0.0) -> float:
    """Parse goals average, never negative."""
    f = safe_float(value, default)
    return max(0.0, f)


def parse_past_fixture(fixture: dict, team_id: int) -> Optional[dict]:
    """Parse a completed fixture into a normalized match record."""
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

        if goals_for > goals_against:
            result = "W"
        elif goals_for < goals_against:
            result = "L"
        else:
            result = "D"

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
    """Parse a list of past fixtures, filtering failures."""
    parsed = [parse_past_fixture(f, team_id) for f in fixtures]
    return [p for p in parsed if p is not None]


def find_bet_values(odds_response: dict, bet_id: int) -> list:
    """Find value-odd pairs for a given bet type across bookmakers."""
    if not odds_response:
        return []
    bookmakers = odds_response.get("bookmakers", [])
    for bookmaker in bookmakers:
        for bet in bookmaker.get("bets", []):
            if bet.get("id") == bet_id:
                return bet.get("values", [])
    return []


def get_odds_value(values: list, label: str) -> Optional[float]:
    """Extract odd for a specific value label (e.g. 'Over 2.5', 'Yes')."""
    for v in values:
        if v.get("value", "").strip() == label:
            return safe_float(v.get("odd"), None)
    return None


def implied_probability(odd) -> Optional[float]:
    """Convert decimal odd to implied probability (1/odd)."""
    if odd is None or odd <= 0:
        return None
    return 1.0 / odd
