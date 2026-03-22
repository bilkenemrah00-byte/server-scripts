"""
feature_engineer.py — Feature engineering from raw API data.

Generates features for OUR prediction model.
We do NOT use predictions.predictions.* (API's own model output).
We fetch our own past N fixtures and engineer our own features.

Feature categories:
  A. Form features (win rate, streaks, momentum — multiple windows)
  B. Goal features (averages, trends, clean sheets)
  C. Positional features (standings rank, points)
  D. Matchup features (attack vs defense)
  E. H2H features

Reference: FEATURE-ENGINEERING-GUIDE.md
Reference: CRITICAL-CORRECTION-PREDICTIONS-USAGE.md
"""

import logging
import math
from typing import Optional

from utils.validators import (
    parse_past_fixtures,
    safe_get, safe_float, safe_int, safe_percent, safe_goals_avg,
)

logger = logging.getLogger(__name__)

WINDOWS = [3, 5, 10, 20]


# ---------------------------------------------------------------------------
# A. Form features
# ---------------------------------------------------------------------------

def calculate_win_rate(matches: list, window: Optional[int] = None) -> float:
    """Win rate for last N matches. W=1.0, D=0.5, L=0.0."""
    if window:
        matches = matches[:window]
    if not matches:
        return 0.33
    wins = sum(1 for m in matches if m["result"] == "W")
    return wins / len(matches)


def calculate_points_rate(matches: list, window: Optional[int] = None) -> float:
    """Points per game rate (W=3, D=1, L=0), normalized to [0,1]."""
    if window:
        matches = matches[:window]
    if not matches:
        return 0.33
    pts = sum(3 if m["result"] == "W" else 1 if m["result"] == "D" else 0 for m in matches)
    return pts / (len(matches) * 3)


def calculate_form_momentum(matches: list) -> float:
    """Form momentum: win_rate(last 3) - win_rate(prev 3).

    Positive = improving, negative = declining.
    """
    if len(matches) < 6:
        return 0.0
    recent = calculate_win_rate(matches[:3])
    previous = calculate_win_rate(matches[3:6])
    return recent - previous


def calculate_current_streak(matches: list) -> dict:
    """Current result streak.

    Returns: {"type": "W"/"D"/"L", "count": int}
    """
    if not matches:
        return {"type": None, "count": 0}
    current = matches[0]["result"]
    count = 1
    for m in matches[1:]:
        if m["result"] == current:
            count += 1
        else:
            break
    return {"type": current, "count": count}


def calculate_unbeaten_streak(matches: list) -> int:
    """Current unbeaten streak (W or D)."""
    count = 0
    for m in matches:
        if m["result"] in ("W", "D"):
            count += 1
        else:
            break
    return count


# ---------------------------------------------------------------------------
# B. Goal features
# ---------------------------------------------------------------------------

def calculate_goals_avg(matches: list, goal_type: str, window: Optional[int] = None) -> float:
    """Average goals per match. goal_type: 'for' or 'against'."""
    if window:
        matches = matches[:window]
    if not matches:
        return 1.0
    field = "goals_for" if goal_type == "for" else "goals_against"
    return sum(m.get(field, 0) for m in matches) / len(matches)


def calculate_clean_sheet_rate(matches: list, window: Optional[int] = None) -> float:
    """Rate of matches with 0 goals against."""
    if window:
        matches = matches[:window]
    if not matches:
        return 0.2
    cs = sum(1 for m in matches if m.get("goals_against", 1) == 0)
    return cs / len(matches)


def calculate_failed_to_score_rate(matches: list, window: Optional[int] = None) -> float:
    """Rate of matches with 0 goals for."""
    if window:
        matches = matches[:window]
    if not matches:
        return 0.2
    fts = sum(1 for m in matches if m.get("goals_for", 1) == 0)
    return fts / len(matches)


def calculate_btts_rate(matches: list, window: Optional[int] = None) -> float:
    """Rate of matches where both teams scored."""
    if window:
        matches = matches[:window]
    if not matches:
        return 0.5
    btts = sum(
        1 for m in matches
        if m.get("goals_for", 0) > 0 and m.get("goals_against", 0) > 0
    )
    return btts / len(matches)


def calculate_over_rate(matches: list, threshold: float = 2.5, window: Optional[int] = None) -> float:
    """Rate of matches with total goals > threshold."""
    if window:
        matches = matches[:window]
    if not matches:
        return 0.45
    over = sum(
        1 for m in matches
        if m.get("goals_for", 0) + m.get("goals_against", 0) > threshold
    )
    return over / len(matches)


def calculate_goals_trend(matches: list, goal_type: str, window: int = 10) -> float:
    """Linear trend of goals per match (positive = improving).

    Uses simple slope of goals over time (oldest to newest).
    """
    if len(matches) < 4:
        return 0.0
    matches = matches[:window]
    field = "goals_for" if goal_type == "for" else "goals_against"
    goals = list(reversed([m.get(field, 0) for m in matches]))  # oldest first
    n = len(goals)
    x_mean = (n - 1) / 2
    y_mean = sum(goals) / n
    numerator = sum((i - x_mean) * (goals[i] - y_mean) for i in range(n))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    return numerator / denominator if denominator > 0 else 0.0


def calculate_first_half_goal_rate(matches: list, window: Optional[int] = None) -> float:
    """Rate of matches where team scored in first half."""
    if window:
        matches = matches[:window]
    if not matches:
        return 0.5
    fh = sum(1 for m in matches if m.get("halftime_for", 0) > 0)
    return fh / len(matches)


def calculate_concede_first_half_rate(matches: list, window: Optional[int] = None) -> float:
    """Rate of matches where team conceded in first half."""
    if window:
        matches = matches[:window]
    if not matches:
        return 0.5
    fh = sum(1 for m in matches if m.get("halftime_against", 0) > 0)
    return fh / len(matches)


# ---------------------------------------------------------------------------
# C. Positional features (from standings)
# ---------------------------------------------------------------------------

def extract_team_standing(standings: list, team_id: int) -> Optional[dict]:
    """Find a team's standing entry by team ID."""
    for entry in standings:
        if safe_get(entry, "team", "id") == team_id:
            return entry
    return None


def calculate_positional_features(standings: list, home_id: int, away_id: int) -> dict:
    """Extract rank, points, goal diff for both teams."""
    home_s = extract_team_standing(standings, home_id)
    away_s = extract_team_standing(standings, away_id)

    def standing_features(s, prefix):
        if not s:
            return {f"{prefix}_rank": 10, f"{prefix}_points": 30, f"{prefix}_goal_diff": 0}
        return {
            f"{prefix}_rank": safe_int(s.get("rank"), 10),
            f"{prefix}_points": safe_int(s.get("points"), 30),
            f"{prefix}_goal_diff": safe_int(s.get("goalsDiff"), 0),
        }

    feats = {}
    feats.update(standing_features(home_s, "home"))
    feats.update(standing_features(away_s, "away"))

    # Derived
    feats["rank_difference"] = feats["home_rank"] - feats["away_rank"]
    feats["points_difference"] = feats["home_points"] - feats["away_points"]

    return feats


# ---------------------------------------------------------------------------
# D. Matchup features (from predictions comparison block)
# ---------------------------------------------------------------------------

def calculate_matchup_features(predictions_raw: dict) -> dict:
    """Extract attack/defense comparison percentages."""
    comparison = predictions_raw.get("comparison", {})
    if not comparison:
        return {
            "comparison_att_home": 0.5,
            "comparison_att_away": 0.5,
            "comparison_def_home": 0.5,
            "comparison_def_away": 0.5,
        }

    return {
        "comparison_att_home": safe_percent(safe_get(comparison, "att", "home"), 0.5),
        "comparison_att_away": safe_percent(safe_get(comparison, "att", "away"), 0.5),
        "comparison_def_home": safe_percent(safe_get(comparison, "def", "home"), 0.5),
        "comparison_def_away": safe_percent(safe_get(comparison, "def", "away"), 0.5),
    }


# ---------------------------------------------------------------------------
# E. H2H features
# ---------------------------------------------------------------------------

def calculate_h2h_features(h2h_matches: list, home_id: int) -> dict:
    """H2H win rate and goal averages from perspective of home team."""
    if not h2h_matches:
        return {
            "h2h_home_win_rate": 0.33,
            "h2h_avg_total_goals": 2.5,
            "h2h_home_avg_goals": 1.25,
            "h2h_count": 0,
        }

    wins = 0
    total_goals = []
    home_goals = []

    for match in h2h_matches:
        is_home_here = safe_get(match, "teams", "home", "id") == home_id
        if is_home_here:
            gf = safe_int(safe_get(match, "goals", "home"), 0)
            ga = safe_int(safe_get(match, "goals", "away"), 0)
        else:
            gf = safe_int(safe_get(match, "goals", "away"), 0)
            ga = safe_int(safe_get(match, "goals", "home"), 0)

        if gf > ga:
            wins += 1
        total_goals.append(gf + ga)
        home_goals.append(gf)

    n = len(h2h_matches)
    return {
        "h2h_home_win_rate": wins / n,
        "h2h_avg_total_goals": sum(total_goals) / n,
        "h2h_home_avg_goals": sum(home_goals) / n,
        "h2h_count": n,
    }


# ---------------------------------------------------------------------------
# League stats features (from predictions raw)
# ---------------------------------------------------------------------------

def calculate_league_stat_features(predictions_raw: dict, side: str) -> dict:
    """Extract season-wide league stats for home or away team.

    side: 'home' or 'away'
    """
    league = safe_get(predictions_raw, "teams", side, "league") or {}
    goals = league.get("goals", {})
    fixtures = league.get("fixtures", {})
    played = safe_int(safe_get(fixtures, "played", "total"), 1)

    goals_for_total = safe_int(safe_get(goals, "for", "total", "total"), 0)
    goals_against_total = safe_int(safe_get(goals, "against", "total", "total"), 0)
    clean_sheet_total = safe_int(safe_get(league, "clean_sheet", "total"), 0)
    failed_to_score_total = safe_int(safe_get(league, "failed_to_score", "total"), 0)

    goals_for_avg = safe_goals_avg(safe_get(goals, "for", "average", "total"), 1.0)
    goals_against_avg = safe_goals_avg(safe_get(goals, "against", "average", "total"), 1.0)

    under_over_25_over = safe_int(
        safe_get(goals, "for", "under_over", "2.5", "over"), 0
    )

    p = side
    return {
        f"{p}_season_goals_for_avg": goals_for_avg,
        f"{p}_season_goals_against_avg": goals_against_avg,
        f"{p}_season_clean_sheet_rate": clean_sheet_total / played if played else 0.2,
        f"{p}_season_failed_to_score_rate": failed_to_score_total / played if played else 0.2,
        f"{p}_season_over_2_5_for_rate": under_over_25_over / played if played else 0.4,
    }


# ---------------------------------------------------------------------------
# Main feature engineering function
# ---------------------------------------------------------------------------

def engineer_features(fixture_data: dict) -> dict:
    """Generate all features for a fixture from collected raw data.

    Args:
        fixture_data: Output from data_collector.collect_fixture_data()

    Returns:
        Dict of feature_name -> float, ready for prediction model.
    """
    home_id = safe_get(fixture_data, "fixture_meta", "home", "id")
    away_id = safe_get(fixture_data, "fixture_meta", "away", "id")
    predictions_raw = fixture_data.get("predictions_raw") or {}
    standings = fixture_data.get("standings") or []
    h2h = safe_get(predictions_raw, "h2h") or []

    # Parse past fixtures
    home_past = parse_past_fixtures(fixture_data.get("home_past_raw") or [], home_id)
    away_past = parse_past_fixtures(fixture_data.get("away_past_raw") or [], away_id)

    features = {}

    # --- A0. Home/Away split features (kritik) ---
    home_home_matches = [m for m in home_past if m.get('is_home', True)]
    home_away_matches = [m for m in home_past if not m.get('is_home', True)]
    away_home_matches = [m for m in away_past if m.get('is_home', True)]
    away_away_matches = [m for m in away_past if not m.get('is_home', True)]

    # Home takımının evdeki performansı (bu maçta ev sahibi)
    features["home_win_rate_at_home"] = calculate_win_rate(home_home_matches, min(5, len(home_home_matches)) or 1)
    features["home_goals_for_at_home"] = calculate_goals_avg(home_home_matches, "for", min(5, len(home_home_matches)) or 1)
    features["home_goals_against_at_home"] = calculate_goals_avg(home_home_matches, "against", min(5, len(home_home_matches)) or 1)

    # Away takımının deplasman performansı (bu maçta deplasman)
    features["away_win_rate_away"] = calculate_win_rate(away_away_matches, min(5, len(away_away_matches)) or 1)
    features["away_goals_for_away"] = calculate_goals_avg(away_away_matches, "for", min(5, len(away_away_matches)) or 1)
    features["away_goals_against_away"] = calculate_goals_avg(away_away_matches, "against", min(5, len(away_away_matches)) or 1)

    # --- A. Form features (multiple windows) ---
    for side, matches in [("home", home_past), ("away", away_past)]:
        for w in WINDOWS:
            if len(matches) >= w:
                features[f"{side}_win_rate_last_{w}"] = calculate_win_rate(matches, w)
                features[f"{side}_goals_for_avg_last_{w}"] = calculate_goals_avg(matches, "for", w)
                features[f"{side}_goals_against_avg_last_{w}"] = calculate_goals_avg(matches, "against", w)
                features[f"{side}_clean_sheet_rate_last_{w}"] = calculate_clean_sheet_rate(matches, w)
                features[f"{side}_fts_rate_last_{w}"] = calculate_failed_to_score_rate(matches, w)
                features[f"{side}_btts_rate_last_{w}"] = calculate_btts_rate(matches, w)
                features[f"{side}_over_2_5_rate_last_{w}"] = calculate_over_rate(matches, 2.5, w)
        
        # Fallback to available matches if shorter than smallest window
        available = min(len(matches), 5) if matches else 1
        if f"{side}_win_rate_last_5" not in features:
            features[f"{side}_win_rate_last_5"] = calculate_win_rate(matches, available)
            features[f"{side}_goals_for_avg_last_5"] = calculate_goals_avg(matches, "for", available)
            features[f"{side}_goals_against_avg_last_5"] = calculate_goals_avg(matches, "against", available)
            features[f"{side}_clean_sheet_rate_last_5"] = calculate_clean_sheet_rate(matches, available)
            features[f"{side}_fts_rate_last_5"] = calculate_failed_to_score_rate(matches, available)
            features[f"{side}_btts_rate_last_5"] = calculate_btts_rate(matches, available)
            features[f"{side}_over_2_5_rate_last_5"] = calculate_over_rate(matches, 2.5, available)

        features[f"{side}_form_momentum"] = calculate_form_momentum(matches)
        features[f"{side}_unbeaten_streak"] = calculate_unbeaten_streak(matches)
        features[f"{side}_goals_for_trend"] = calculate_goals_trend(matches, "for")
        features[f"{side}_first_half_goal_rate"] = calculate_first_half_goal_rate(matches, 10)
        features[f"{side}_concede_first_half_rate"] = calculate_concede_first_half_rate(matches, 10)

        streak = calculate_current_streak(matches)
        features[f"{side}_win_streak"] = streak["count"] if streak["type"] == "W" else 0
        features[f"{side}_loss_streak"] = streak["count"] if streak["type"] == "L" else 0

    # --- C. Positional features ---
    if standings:
        features.update(calculate_positional_features(standings, home_id, away_id))
    else:
        features.update({
            "home_rank": 10, "away_rank": 10,
            "home_points": 30, "away_points": 30,
            "home_goal_diff": 0, "away_goal_diff": 0,
            "rank_difference": 0, "points_difference": 0,
        })

    # --- D. Matchup features ---
    features.update(calculate_matchup_features(predictions_raw))

    # --- E. H2H features ---
    features.update(calculate_h2h_features(h2h, home_id))

    # --- League stats (season-wide from predictions) ---
    if predictions_raw:
        features.update(calculate_league_stat_features(predictions_raw, "home"))
        features.update(calculate_league_stat_features(predictions_raw, "away"))

    # --- Derived matchup signals ---
    features["expected_total_goals"] = (
        features.get("home_goals_for_avg_last_5", 1.0) +
        features.get("away_goals_for_avg_last_5", 1.0)
    )
    features["attack_balance"] = (
        features.get("home_goals_for_avg_last_5", 1.0) /
        max(features.get("away_goals_for_avg_last_5", 1.0), 0.1)
    )

    return features
