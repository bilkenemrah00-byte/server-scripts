"""
questions/u01_to_u11.py — All 11 question analyzers.

U.1  Bu maçta gol olur mu?
U.2  Over 2.5 olur mu?
U.3  BTTS olur mu?
U.4  Ev sahibi gerçekten güçlü mü?
U.5  Deplasman zayıf mı yoksa market yanılıyor mu?
U.6  İlk yarı gol olur mu?
U.7  İkinci yarı gol olur mu?
U.8  Maç yüksek tempolu mu?
U.9  Korner sayısı yüksek olur mu?
U.10 Sürpriz (upset) ihtimali var mı?
U.11 Form vs odds çelişkisi var mı?

Reference: API-FOOTBALL-FIXTURE-KILAVUZ.md Section U
Reference: CRITICAL-CORRECTION-PREDICTIONS-USAGE.md
"""

import logging
from typing import Optional

from utils.validators import safe_get, safe_float, safe_int, safe_percent, safe_goals_avg, implied_probability
from .base import (
    make_answer, no_odds_skip, confidence_from_signals,
    get_over_under_odds, get_btts_odds,
    get_first_half_ou_odds, get_second_half_ou_odds,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# U.1 — Bu maçta gol olur mu?
# ---------------------------------------------------------------------------

def u1_gol_olur_mu(features: dict, predictions_raw: dict, odds_response: Optional[dict]) -> dict:
    QUESTION = "Bu maçta gol olur mu?"

    home_fts = features.get("home_fts_rate_last_5", 0.3)
    away_fts = features.get("away_fts_rate_last_5", 0.3)
    expected = features.get("expected_total_goals", 2.0)

    over_0_5_odd = get_over_under_odds(odds_response, "Over 0.5") if odds_response else None
    market_confident = over_0_5_odd is not None and over_0_5_odd < 1.15

    signals = {
        "home_scores_regularly": home_fts < 0.30,
        "away_scores_regularly": away_fts < 0.30,
        "expected_goals_above_1": expected > 1.0,
        "market_confident": market_confident,
    }
    pos = sum(signals.values())
    total = len(signals)

    if pos >= 3:
        conclusion = "Maçta gol olma ihtimali YÜKSEK"
    elif pos == 2:
        conclusion = "Maçta gol olma ihtimali ORTA"
    else:
        conclusion = "Maçta gol olmama riski VAR"

    return make_answer(
        question=QUESTION,
        conclusion=conclusion,
        confidence=confidence_from_signals(pos, total),
        positive_signals=pos,
        total_signals=total,
        details=[
            f"Home gol atamama oranı: {home_fts:.0%}",
            f"Away gol atamama oranı: {away_fts:.0%}",
            f"Beklenen toplam gol: {expected:.2f}",
            f"Market over 0.5 oranı: {over_0_5_odd}" if over_0_5_odd else "Odds yok",
        ],
        data_sources=["features", "predictions_raw"] + (["odds"] if odds_response else []),
        calculation={"home_fts_rate": home_fts, "away_fts_rate": away_fts, "expected_goals": expected},
    )


# ---------------------------------------------------------------------------
# U.2 — Over 2.5 olur mu?
# ---------------------------------------------------------------------------

def u2_over_2_5(features: dict, predictions_raw: dict, odds_response: Optional[dict]) -> dict:
    QUESTION = "Over 2.5 olur mu?"

    expected = features.get("expected_total_goals", 2.0)
    home_over_rate = features.get("home_over_2_5_rate_last_5", 0.4)
    away_over_rate = features.get("away_over_2_5_rate_last_5", 0.4)
    combined_over_rate = (home_over_rate + away_over_rate) / 2

    over_2_5_odd = get_over_under_odds(odds_response, "Over 2.5") if odds_response else None
    market_supports = over_2_5_odd is not None and over_2_5_odd < 2.00

    signals = {
        "expected_goals_above_threshold": expected > 2.5,
        "home_over_rate_high": home_over_rate > 0.45,
        "away_over_rate_high": away_over_rate > 0.45,
        "market_supports_over": market_supports,
    }
    pos = sum(signals.values())
    total = len(signals)

    if pos >= 3:
        conclusion = "Over 2.5 GÜÇLÜ"
    elif pos == 2:
        conclusion = "Over 2.5 OLASI — sınırda"
    elif pos == 1:
        conclusion = "Under 2.5 daha olası"
    else:
        conclusion = "Under 2.5 GÜÇLÜ"

    return make_answer(
        question=QUESTION,
        conclusion=conclusion,
        confidence=confidence_from_signals(pos, total),
        positive_signals=pos,
        total_signals=total,
        details=[
            f"Beklenen toplam gol: {expected:.2f}",
            f"Home over 2.5 oranı (son 5): {home_over_rate:.0%}",
            f"Away over 2.5 oranı (son 5): {away_over_rate:.0%}",
            f"Over 2.5 oranı: {over_2_5_odd}" if over_2_5_odd else "Odds yok",
        ],
        data_sources=["features"] + (["odds"] if odds_response else []),
        calculation={"expected_goals": expected, "combined_over_rate": combined_over_rate},
    )


# ---------------------------------------------------------------------------
# U.3 — BTTS olur mu?
# ---------------------------------------------------------------------------

def u3_btts(features: dict, predictions_raw: dict, odds_response: Optional[dict]) -> dict:
    QUESTION = "Her iki takım da gol atar mı? (BTTS)"

    home_fts = features.get("home_fts_rate_last_5", 0.3)
    away_fts = features.get("away_fts_rate_last_5", 0.3)
    home_cs = features.get("home_clean_sheet_rate_last_5", 0.2)
    away_cs = features.get("away_clean_sheet_rate_last_5", 0.2)

    btts_prob = (1 - home_fts) * (1 - away_fts)

    btts_yes_odd = get_btts_odds(odds_response, "Yes") if odds_response else None
    market_supports = btts_yes_odd is not None and btts_yes_odd < 2.00

    signals = {
        "home_scores_regularly": home_fts < 0.30,
        "away_scores_regularly": away_fts < 0.30,
        "defenses_both_leaky": home_cs < 0.25 and away_cs < 0.25,
        "calculated_btts_prob_above_50": btts_prob > 0.50,
        "market_supports_btts": market_supports,
    }
    pos = sum(signals.values())
    total = len(signals)

    if pos >= 4:
        conclusion = "BTTS Yes GÜÇLÜ"
    elif pos == 3:
        conclusion = "BTTS Yes OLASI — sınırda"
    elif pos == 2:
        conclusion = "BTTS belirsiz"
    else:
        conclusion = "BTTS No daha olası"

    return make_answer(
        question=QUESTION,
        conclusion=conclusion,
        confidence=confidence_from_signals(pos, total),
        positive_signals=pos,
        total_signals=total,
        details=[
            f"Home gol atamama: {home_fts:.0%}, clean sheet: {home_cs:.0%}",
            f"Away gol atamama: {away_fts:.0%}, clean sheet: {away_cs:.0%}",
            f"Hesaplanan BTTS olasılığı: {btts_prob:.0%}",
            f"BTTS Yes oranı: {btts_yes_odd}" if btts_yes_odd else "Odds yok",
        ],
        data_sources=["features"] + (["odds"] if odds_response else []),
        calculation={"btts_probability": btts_prob},
    )


# ---------------------------------------------------------------------------
# U.4 — Ev sahibi gerçekten güçlü mü?
# ---------------------------------------------------------------------------

def u4_home_gercekten_guclu(features: dict, predictions_raw: dict, standings: list) -> dict:
    QUESTION = "Ev sahibi gerçekten güçlü mü?"

    home_win_5 = features.get("home_win_rate_last_5", 0.33)
    home_win_10 = features.get("home_win_rate_last_10", 0.33)
    home_momentum = features.get("home_form_momentum", 0.0)
    home_rank = features.get("home_rank", 10)
    away_rank = features.get("away_rank", 10)
    rank_diff = features.get("rank_difference", 0)

    signals = {
        "home_recent_form_strong": home_win_5 > 0.50,
        "home_sustained_form": home_win_10 > 0.45,
        "home_form_improving": home_momentum > 0.10,
        "home_ranked_higher": rank_diff < -3,  # lower rank number = higher in table
        "home_strong_attack": features.get("comparison_att_home", 0.5) > 0.55,
    }
    pos = sum(signals.values())
    total = len(signals)

    if pos >= 4:
        conclusion = "Ev sahibi GERÇEKTEN GÜÇLÜ"
    elif pos == 3:
        conclusion = "Ev sahibi ORTA güçte"
    elif pos == 2:
        conclusion = "Ev sahibi görünenden ZAYIF olabilir"
    else:
        conclusion = "Ev sahibi zayıf — home advantage minimal"

    return make_answer(
        question=QUESTION,
        conclusion=conclusion,
        confidence=confidence_from_signals(pos, total),
        positive_signals=pos,
        total_signals=total,
        details=[
            f"Home win rate son 5: {home_win_5:.0%}",
            f"Home win rate son 10: {home_win_10:.0%}",
            f"Form momentumu: {home_momentum:+.0%}",
            f"Lig sırası — Home: {home_rank}, Away: {away_rank} (fark: {rank_diff:+})",
        ],
        data_sources=["features", "standings"],
    )


# ---------------------------------------------------------------------------
# U.5 — Deplasman zayıf mı yoksa market yanılıyor mu?
# ---------------------------------------------------------------------------

def u5_away_yanlis_fiyatlanmis(
    features: dict,
    our_prediction: dict,
    market_edge: Optional[dict],
    odds_response: Optional[dict],
) -> dict:
    QUESTION = "Deplasman zayıf mı yoksa market yanılıyor mu?"

    if not odds_response or not market_edge:
        return no_odds_skip(QUESTION)

    away_edge = market_edge.get("away_edge", 0.0)
    our_away = our_prediction.get("away_win_probability", 0.33)
    market_away = market_edge.get("market_away_prob", 0.33)

    away_win_5 = features.get("away_win_rate_last_5", 0.33)
    away_momentum = features.get("away_form_momentum", 0.0)
    rank_diff = features.get("rank_difference", 0)

    signals = {
        "model_favors_away": our_away > 0.38,
        "market_undervalues_away": away_edge > 0.10,
        "away_strong_recent_form": away_win_5 > 0.50,
        "away_form_improving": away_momentum > 0.10,
        "away_ranked_higher": rank_diff > 3,  # away is higher in standings
    }
    pos = sum(signals.values())
    total = len(signals)

    if pos >= 4:
        conclusion = f"Away BÜYÜK undervalue — {away_edge:.0%} edge, market yanılıyor"
    elif pos == 3:
        conclusion = f"Away undervalue — {away_edge:.0%} edge tespit edildi"
    elif pos == 2:
        conclusion = "Away hafif undervalue — düşük güven"
    else:
        conclusion = "Away doğru fiyatlanmış veya overvalue"

    return make_answer(
        question=QUESTION,
        conclusion=conclusion,
        confidence=confidence_from_signals(pos, total),
        positive_signals=pos,
        total_signals=total,
        details=[
            f"Bizim away olasılığımız: {our_away:.0%}",
            f"Market away olasılığı: {market_away:.0%}",
            f"Edge: {away_edge:+.0%}",
            f"Away son 5 form: {away_win_5:.0%}",
            f"Away momentum: {away_momentum:+.0%}",
        ],
        data_sources=["our_prediction", "odds", "features"],
        our_prediction=our_prediction,
        market_edge=market_edge,
    )


# ---------------------------------------------------------------------------
# U.6 — İlk yarı gol olur mu?
# ---------------------------------------------------------------------------

def u6_ilk_yari_gol(features: dict, predictions_raw: dict, odds_response: Optional[dict]) -> dict:
    QUESTION = "İlk yarı gol olur mu?"

    home_fh_rate = features.get("home_first_half_goal_rate", 0.5)
    away_fh_rate = features.get("away_first_half_goal_rate", 0.5)

    # Probability at least one team scores in first half
    any_fh_prob = 1 - ((1 - home_fh_rate) * (1 - away_fh_rate))

    fh_over_0_5_odd = get_first_half_ou_odds(odds_response, "Over 0.5") if odds_response else None
    market_supports = fh_over_0_5_odd is not None and fh_over_0_5_odd < 1.80

    signals = {
        "home_scores_first_half": home_fh_rate > 0.50,
        "away_scores_first_half": away_fh_rate > 0.50,
        "combined_prob_above_60": any_fh_prob > 0.60,
        "market_supports_fh_goal": market_supports,
    }
    pos = sum(signals.values())
    total = len(signals)

    if pos >= 3:
        conclusion = "İlk yarı gol olma ihtimali YÜKSEK"
    elif pos == 2:
        conclusion = "İlk yarı gol olası"
    else:
        conclusion = "İlk yarı golsüz geçebilir"

    return make_answer(
        question=QUESTION,
        conclusion=conclusion,
        confidence=confidence_from_signals(pos, total),
        positive_signals=pos,
        total_signals=total,
        details=[
            f"Home ilk yarı gol atma oranı: {home_fh_rate:.0%}",
            f"Away ilk yarı gol atma oranı: {away_fh_rate:.0%}",
            f"En az 1 gol ihtimali: {any_fh_prob:.0%}",
            f"FH over 0.5 oranı: {fh_over_0_5_odd}" if fh_over_0_5_odd else "Odds yok",
        ],
        data_sources=["features"] + (["odds"] if odds_response else []),
        calculation={"any_first_half_goal_prob": any_fh_prob},
    )


# ---------------------------------------------------------------------------
# U.7 — İkinci yarı gol olur mu?
# ---------------------------------------------------------------------------

def u7_ikinci_yari_gol(features: dict, predictions_raw: dict, odds_response: Optional[dict]) -> dict:
    QUESTION = "İkinci yarı gol olur mu? (2. yarı yoğun mu?)"

    # Infer second half tendency from predictions league stats
    home_league = safe_get(predictions_raw, "teams", "home", "league") or {}
    away_league = safe_get(predictions_raw, "teams", "away", "league") or {}

    def second_half_pct(league):
        """% of goals scored in second half (46-90 min)."""
        minute = safe_get(league, "goals", "for", "minute") or {}
        fh_total = sum(
            safe_int(safe_get(minute, slot, "total"), 0)
            for slot in ["0-15", "16-30", "31-45"]
        )
        sh_total = sum(
            safe_int(safe_get(minute, slot, "total"), 0)
            for slot in ["46-60", "61-75", "76-90"]
        )
        total = fh_total + sh_total
        return sh_total / total if total > 0 else 0.55

    home_sh_pct = second_half_pct(home_league)
    away_sh_pct = second_half_pct(away_league)

    expected = features.get("expected_total_goals", 2.0)
    expected_sh = expected * ((home_sh_pct + away_sh_pct) / 2)

    sh_over_1_5_odd = get_second_half_ou_odds(odds_response, "Over 1.5") if odds_response else None
    market_supports = sh_over_1_5_odd is not None and sh_over_1_5_odd < 2.20

    signals = {
        "home_second_half_heavy": home_sh_pct > 0.55,
        "away_second_half_heavy": away_sh_pct > 0.55,
        "expected_sh_goals_above_1_5": expected_sh > 1.5,
        "market_supports_sh_over": market_supports,
    }
    pos = sum(signals.values())
    total = len(signals)

    if pos >= 3:
        conclusion = "İkinci yarı GOL YOĞUN — late game takımlar"
    elif pos == 2:
        conclusion = "İkinci yarı golcü olabilir"
    else:
        conclusion = "İkinci yarı hareketli olmayabilir"

    return make_answer(
        question=QUESTION,
        conclusion=conclusion,
        confidence=confidence_from_signals(pos, total),
        positive_signals=pos,
        total_signals=total,
        details=[
            f"Home 2. yarı gol yüzdesi: {home_sh_pct:.0%}",
            f"Away 2. yarı gol yüzdesi: {away_sh_pct:.0%}",
            f"Beklenen 2. yarı gol: {expected_sh:.2f}",
            f"2. yarı over 1.5 oranı: {sh_over_1_5_odd}" if sh_over_1_5_odd else "Odds yok",
        ],
        data_sources=["features", "predictions_raw"] + (["odds"] if odds_response else []),
        calculation={"expected_second_half_goals": expected_sh},
    )


# ---------------------------------------------------------------------------
# U.8 — Maç yüksek tempolu mu?
# ---------------------------------------------------------------------------

def u8_mac_temposu(features: dict, predictions_raw: dict) -> dict:
    QUESTION = "Maç yüksek tempolu mu yoksa taktiksel mi?"

    expected = features.get("expected_total_goals", 2.0)
    home_att = features.get("comparison_att_home", 0.5)
    away_att = features.get("comparison_att_away", 0.5)
    home_goals = features.get("home_goals_for_avg_last_5", 1.0)
    away_goals = features.get("away_goals_for_avg_last_5", 1.0)
    home_concede = features.get("home_goals_against_avg_last_5", 1.0)
    away_concede = features.get("away_goals_against_avg_last_5", 1.0)

    # Both teams attack-minded
    both_attack = home_att > 0.50 and away_att > 0.50
    # Both defenses leaky
    both_leaky = home_concede > 1.3 and away_concede > 1.3
    # High scoring games
    high_scoring = expected > 2.7

    signals = {
        "both_teams_attack_minded": both_attack,
        "both_defenses_leaky": both_leaky,
        "high_expected_goals": high_scoring,
        "home_high_scoring": home_goals > 1.4,
        "away_high_scoring": away_goals > 1.4,
    }
    pos = sum(signals.values())
    total = len(signals)

    if pos >= 4:
        conclusion = "YÜKSEK TEMPO — ofansif, hareketli, seyir zevki yüksek"
    elif pos == 3:
        conclusion = "Orta-yüksek tempo — dengeli maç"
    elif pos == 2:
        conclusion = "Orta tempo — taktiksel öğeler var"
    else:
        conclusion = "DÜŞÜK TEMPO — taktiksel, savunmacı maç beklentisi"

    return make_answer(
        question=QUESTION,
        conclusion=conclusion,
        confidence=confidence_from_signals(pos, total),
        positive_signals=pos,
        total_signals=total,
        details=[
            f"Beklenen toplam gol: {expected:.2f}",
            f"Home attack %: {home_att:.0%}, Away attack %: {away_att:.0%}",
            f"Home yediği ort.: {home_concede:.2f}, Away yediği ort.: {away_concede:.2f}",
        ],
        data_sources=["features", "predictions_raw"],
    )


# ---------------------------------------------------------------------------
# U.9 — Korner sayısı yüksek olur mu?
# ---------------------------------------------------------------------------

def u9_korner(features: dict, predictions_raw: dict) -> dict:
    QUESTION = "Korner sayısı yüksek olur mu?"

    # We infer corner tendency from attack pressure
    home_att = features.get("comparison_att_home", 0.5)
    away_att = features.get("comparison_att_away", 0.5)
    home_goals = features.get("home_goals_for_avg_last_5", 1.0)
    away_goals = features.get("away_goals_for_avg_last_5", 1.0)

    # Attack-heavy teams tend to generate more corners
    # Rough heuristic: high attack % + high goals for = more corners
    home_corner_est = home_att * 10 + home_goals * 1.5
    away_corner_est = away_att * 10 + away_goals * 1.5
    total_corner_est = home_corner_est + away_corner_est

    signals = {
        "home_attack_dominant": home_att > 0.55,
        "away_attack_dominant": away_att > 0.55,
        "both_teams_offensive": home_goals > 1.3 and away_goals > 1.3,
        "estimated_corners_high": total_corner_est > 10.5,
    }
    pos = sum(signals.values())
    total = len(signals)

    if pos >= 3:
        conclusion = "Korner sayısı YÜKSEK beklentisi (>10.5)"
    elif pos == 2:
        conclusion = "Ortalama korner sayısı beklentisi"
    else:
        conclusion = "Düşük korner sayısı olabilir"

    return make_answer(
        question=QUESTION,
        conclusion=conclusion,
        confidence=confidence_from_signals(pos, total),
        positive_signals=pos,
        total_signals=total,
        details=[
            f"Home attack %: {home_att:.0%}, tahmini korner: {home_corner_est:.1f}",
            f"Away attack %: {away_att:.0%}, tahmini korner: {away_corner_est:.1f}",
            f"Toplam tahmini korner: {total_corner_est:.1f}",
        ],
        data_sources=["features", "predictions_raw"],
        calculation={"estimated_total_corners": total_corner_est},
    )


# ---------------------------------------------------------------------------
# U.10 — Sürpriz (upset) ihtimali var mı?
# ---------------------------------------------------------------------------

def u10_upset(
    features: dict,
    our_prediction: dict,
    market_edge: Optional[dict],
    odds_response: Optional[dict],
) -> dict:
    QUESTION = "Sürpriz (upset) ihtimali var mı?"

    if not odds_response or not market_edge:
        return no_odds_skip(QUESTION)

    # Determine market favorite
    market_home = market_edge.get("market_home_prob", 0.33)
    market_away = market_edge.get("market_away_prob", 0.33)
    if market_home > market_away:
        favorite, underdog = "home", "away"
        underdog_our_prob = our_prediction.get("away_win_probability", 0.33)
        underdog_market_prob = market_away
        underdog_edge = market_edge.get("away_edge", 0.0)
        underdog_momentum = features.get("away_form_momentum", 0.0)
        favorite_momentum = features.get("home_form_momentum", 0.0)
    else:
        favorite, underdog = "away", "home"
        underdog_our_prob = our_prediction.get("home_win_probability", 0.33)
        underdog_market_prob = market_home
        underdog_edge = market_edge.get("home_edge", 0.0)
        underdog_momentum = features.get("home_form_momentum", 0.0)
        favorite_momentum = features.get("away_form_momentum", 0.0)

    rank_diff = abs(features.get("rank_difference", 0))
    h2h_rate = features.get("h2h_home_win_rate", 0.33)

    signals = {
        "model_favors_underdog": underdog_our_prob > 0.38,
        "market_undervalues_underdog": underdog_edge > 0.12,
        "underdog_good_form": underdog_momentum > 0.10,
        "favorite_bad_form": favorite_momentum < -0.10,
        "standings_close": rank_diff <= 4,
        "h2h_supports_upset": (underdog == "away" and h2h_rate < 0.35) or
                              (underdog == "home" and h2h_rate > 0.65),
    }
    pos = sum(signals.values())
    total = len(signals)

    if pos >= 4:
        conclusion = f"UPSET RİSKİ YÜKSEK — {underdog} favori değil ama DEĞER VAR"
    elif pos == 3:
        conclusion = f"Upset ihtimali ORTA — {underdog} sürpriz yapabilir"
    elif pos == 2:
        conclusion = "Upset potansiyeli var ama düşük güven"
    else:
        conclusion = "Upset riski düşük — favori büyük olasılıkla kazanır"

    return make_answer(
        question=QUESTION,
        conclusion=conclusion,
        confidence=confidence_from_signals(pos, total),
        positive_signals=pos,
        total_signals=total,
        details=[
            f"Market favorite: {favorite}, underdog: {underdog}",
            f"Underdog bizim tahmini: {underdog_our_prob:.0%}, market: {underdog_market_prob:.0%}",
            f"Edge: {underdog_edge:+.0%}",
            f"Lig sıra farkı: {rank_diff}",
        ],
        data_sources=["our_prediction", "odds", "features"],
        our_prediction=our_prediction,
        market_edge=market_edge,
    )


# ---------------------------------------------------------------------------
# U.11 — Form vs odds çelişkisi var mı?
# ---------------------------------------------------------------------------

def u11_form_odds_celiskisi(
    features: dict,
    our_prediction: dict,
    market_edge: Optional[dict],
    odds_response: Optional[dict],
) -> dict:
    QUESTION = "Form vs odds çelişkisi var mı?"

    if not odds_response or not market_edge:
        return no_odds_skip(QUESTION)

    home_win_3 = features.get("home_win_rate_last_3", 0.33)
    home_win_10 = features.get("home_win_rate_last_10", 0.33)
    away_win_3 = features.get("away_win_rate_last_3", 0.33)
    away_win_10 = features.get("away_win_rate_last_10", 0.33)

    home_edge = market_edge.get("home_edge", 0.0)
    away_edge = market_edge.get("away_edge", 0.0)

    conflicts = []

    # Home: strong recent form but market undervalues
    if home_win_3 > 0.60 and home_edge > 0.12:
        conflicts.append(f"Home son form güçlü ({home_win_3:.0%}) ama market düşük fiyatlamış (+{home_edge:.0%} edge)")

    # Home: weak recent form but market overvalues
    if home_win_3 < 0.25 and home_edge < -0.12:
        conflicts.append(f"Home son form kötü ({home_win_3:.0%}) ama market overvalue etmiş ({home_edge:.0%} negatif edge)")

    # Away: strong recent form but market undervalues
    if away_win_3 > 0.60 and away_edge > 0.12:
        conflicts.append(f"Away son form güçlü ({away_win_3:.0%}) ama market düşük fiyatlamış (+{away_edge:.0%} edge)")

    # Away: weak recent form but market overvalues
    if away_win_3 < 0.25 and away_edge < -0.12:
        conflicts.append(f"Away son form kötü ({away_win_3:.0%}) ama market overvalue etmiş ({away_edge:.0%} negatif edge)")

    pos = len(conflicts)
    total = 4

    if pos >= 2:
        conclusion = f"ÇELİŞKİ BÜYÜK — {pos} sinyal, market son formu görmüyor"
    elif pos == 1:
        conclusion = "Çelişki var — bir takımda form-odds uyumsuzluğu"
    else:
        conclusion = "Form ve odds uyumlu — belirgin çelişki yok"

    return make_answer(
        question=QUESTION,
        conclusion=conclusion,
        confidence="HIGH" if pos >= 2 else "MEDIUM" if pos == 1 else "LOW",
        positive_signals=pos,
        total_signals=total,
        details=[
            f"Home son 3: {home_win_3:.0%}, son 10: {home_win_10:.0%}, edge: {home_edge:+.0%}",
            f"Away son 3: {away_win_3:.0%}, son 10: {away_win_10:.0%}, edge: {away_edge:+.0%}",
        ] + conflicts,
        data_sources=["our_prediction", "odds", "features"],
        calculation={"conflicts": conflicts},
        our_prediction=our_prediction,
        market_edge=market_edge,
    )
