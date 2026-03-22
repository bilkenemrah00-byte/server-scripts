"""
prediction_model.py — OUR prediction model + market edge calculation.

We generate our own win probabilities from engineered features.
We do NOT use predictions.predictions.percent or .winner.

Model: Weighted scoring v1 (tunable weights, upgradeable to ML)

Reference: FEATURE-ENGINEERING-GUIDE.md Section 6-7
Reference: CRITICAL-CORRECTION-PREDICTIONS-USAGE.md Section II
"""

import logging
from typing import Optional

from utils.validators import find_bet_values, get_odds_value, implied_probability

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model weights (v1) — tunable, A/B testable
# ---------------------------------------------------------------------------

WEIGHTS_V1 = {
    "win_rate_last_5":        0.22,
    "win_rate_last_10":       0.13,
    "form_momentum":          0.12,
    "attack_defense_matchup": 0.10,
    "h2h_advantage":          0.06,   # düşürüldü — H2H az maç, gürültülü
    "rank_advantage":         0.10,
    "goals_avg_matchup":      0.10,
    "points_advantage":       0.05,
    "home_advantage":         0.12,   # YENİ — ev sahibi doğal avantajı
}

HOME_ADVANTAGE_BONUS = 0.12   # Home team'e sabit bonus puan

VALUE_BET_THRESHOLD = 0.10   # 10% edge = value bet
MODEL_VERSION = "weighted_v1"


# ---------------------------------------------------------------------------
# Prediction generation
# ---------------------------------------------------------------------------

def generate_prediction(features: dict) -> dict:
    """Generate home/draw/away win probabilities from features.

    Returns:
        {
            "home_win_probability": float,
            "draw_probability": float,
            "away_win_probability": float,
            "model_version": str,
        }
    """
    home_score = _calculate_team_score(features, "home")
    away_score = _calculate_team_score(features, "away")

    total = home_score + away_score
    if total <= 0:
        logger.warning("Zero total score in prediction — using neutral")
        home_prob, away_prob = 0.33, 0.33
    else:
        home_prob = home_score / total
        away_prob = away_score / total

    # Draw probability: higher when teams are evenly matched
    balance = 1.0 - abs(home_prob - away_prob)   # 0-1
    draw_prob = 0.25 + (0.10 * balance)           # 0.25-0.35

    # Re-normalize
    win_total = home_prob + away_prob
    if win_total > 0:
        scale = (1.0 - draw_prob) / win_total
        home_prob *= scale
        away_prob *= scale

    # Clamp to [0.05, 0.90]
    home_prob = max(0.05, min(0.90, home_prob))
    away_prob = max(0.05, min(0.90, away_prob))
    draw_prob = max(0.05, min(0.50, draw_prob))

    # Final normalize to exactly 1.0
    total_final = home_prob + draw_prob + away_prob
    home_prob /= total_final
    draw_prob /= total_final
    away_prob /= total_final

    return {
        "home_win_probability": round(home_prob, 4),
        "draw_probability": round(draw_prob, 4),
        "away_win_probability": round(away_prob, 4),
        "model_version": MODEL_VERSION,
    }


def _calculate_team_score(features: dict, side: str) -> float:
    """Weighted score for one side (home or away)."""
    opp = "away" if side == "home" else "home"
    score = 0.0

    # Win rate last 5 — genel
    score += features.get(f"{side}_win_rate_last_5", 0.33) * WEIGHTS_V1["win_rate_last_5"]

    # Win rate last 10 — genel
    score += features.get(f"{side}_win_rate_last_10", 0.33) * WEIGHTS_V1["win_rate_last_10"]

    # Home/Away split win rate (kritik — venue-specific performans)
    if side == "home":
        venue_wr = features.get("home_win_rate_at_home", features.get("home_win_rate_last_5", 0.33))
        score += venue_wr * 0.15  # evdeki gerçek performans
    else:
        venue_wr = features.get("away_win_rate_away", features.get("away_win_rate_last_5", 0.33))
        score += venue_wr * 0.15  # deplasmanındaki gerçek performans

    # Form momentum (bonus if improving)
    momentum = features.get(f"{side}_form_momentum", 0.0)
    score += max(0.0, momentum) * WEIGHTS_V1["form_momentum"]

    # Attack vs defense matchup (our att% vs opponent def%)
    att = features.get(f"comparison_att_{side}", 0.5)
    opp_def = features.get(f"comparison_def_{opp}", 0.5)
    matchup = att - opp_def
    score += max(0.0, matchup) * WEIGHTS_V1["attack_defense_matchup"]

    # H2H (home perspective)
    if side == "home":
        h2h = features.get("h2h_home_win_rate", 0.33)
        score += (h2h - 0.33) * WEIGHTS_V1["h2h_advantage"]
    else:
        h2h = 1.0 - features.get("h2h_home_win_rate", 0.33)
        score += (h2h - 0.33) * WEIGHTS_V1["h2h_advantage"]

    # Rank advantage (lower rank number = higher in table = better)
    home_rank = features.get("home_rank", 10)
    away_rank = features.get("away_rank", 10)
    if side == "home":
        rank_adv = max(0.0, away_rank - home_rank) / 20.0   # normalize
    else:
        rank_adv = max(0.0, home_rank - away_rank) / 20.0
    score += rank_adv * WEIGHTS_V1["rank_advantage"]

    # Goals avg matchup
    our_goals = features.get(f"{side}_goals_for_avg_last_5", 1.0)
    opp_concede = features.get(f"{opp}_goals_against_avg_last_5", 1.0)
    goals_adv = (our_goals / max(opp_concede, 0.1)) - 1.0
    score += max(0.0, goals_adv) * WEIGHTS_V1["goals_avg_matchup"]

    # Points advantage
    home_pts = features.get("home_points", 30)
    away_pts = features.get("away_points", 30)
    if side == "home":
        pts_adv = max(0.0, home_pts - away_pts) / 50.0
    else:
        pts_adv = max(0.0, away_pts - home_pts) / 50.0
    score += pts_adv * WEIGHTS_V1["points_advantage"]

    # Home advantage bonus — ev sahibi doğal avantajı
    if side == "home":
        score += HOME_ADVANTAGE_BONUS * WEIGHTS_V1["home_advantage"]

    return max(0.01, score)


# ---------------------------------------------------------------------------
# Market edge
# ---------------------------------------------------------------------------

def calculate_market_edge(our_prediction: dict, odds_response: Optional[dict]) -> Optional[dict]:
    """Compare our probabilities with market implied probabilities.

    Returns edge dict or None if odds unavailable.

    Positive edge = our probability > market → potential value bet.
    """
    if not odds_response:
        return None

    # Extract Match Winner odds (bet_id = 1)
    values = find_bet_values(odds_response, bet_id=1)
    if not values:
        return None

    home_odd = get_odds_value(values, "Home")
    draw_odd = get_odds_value(values, "Draw")
    away_odd = get_odds_value(values, "Away")

    if not all([home_odd, draw_odd, away_odd]):
        return None

    market_home = implied_probability(home_odd)
    market_draw = implied_probability(draw_odd)
    market_away = implied_probability(away_odd)

    our_home = our_prediction["home_win_probability"]
    our_draw = our_prediction["draw_probability"]
    our_away = our_prediction["away_win_probability"]

    home_edge = our_home - market_home
    draw_edge = our_draw - market_draw
    away_edge = our_away - market_away

    return {
        "home_edge": round(home_edge, 4),
        "draw_edge": round(draw_edge, 4),
        "away_edge": round(away_edge, 4),
        "home_value": home_edge > VALUE_BET_THRESHOLD,
        "draw_value": draw_edge > VALUE_BET_THRESHOLD,
        "away_value": away_edge > VALUE_BET_THRESHOLD,
        "market_home_prob": round(market_home, 4),
        "market_draw_prob": round(market_draw, 4),
        "market_away_prob": round(market_away, 4),
        "home_odd": home_odd,
        "draw_odd": draw_odd,
        "away_odd": away_odd,
    }


def determine_market_favorite(edge_data: dict) -> tuple[str, str]:
    """Determine market favorite and underdog from edge data.

    Returns: (favorite_side, underdog_side) — 'home', 'draw', or 'away'
    """
    probs = {
        "home": edge_data["market_home_prob"],
        "draw": edge_data["market_draw_prob"],
        "away": edge_data["market_away_prob"],
    }
    favorite = max(probs, key=probs.get)
    underdog = min(probs, key=probs.get)
    return favorite, underdog
