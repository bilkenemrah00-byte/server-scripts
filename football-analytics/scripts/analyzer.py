"""
analyzer.py — Stage 5: Question-based analysis for all fixtures.

Reads /tmp/raw_data.json (from data_collector.py)
Writes /tmp/analysis_data.json

For each fixture:
  1. Engineer features
  2. Generate OUR prediction
  3. Calculate market edge (vs odds)
  4. Answer all 11 questions (U.1-U.11)

Reference: KESTRA-AGENT-IMPLEMENTATION-BRIEF.md Section IV
"""

import json
import logging
import os
import sys
from pathlib import Path

from feature_engineer import engineer_features
from prediction_model import generate_prediction, calculate_market_edge
from questions import (
    u1_gol_olur_mu, u2_over_2_5, u3_btts,
    u4_home_gercekten_guclu, u5_away_yanlis_fiyatlanmis,
    u6_ilk_yari_gol, u7_ikinci_yari_gol, u8_mac_temposu,
    u9_korner, u10_upset, u11_form_odds_celiskisi,
)
from utils.timezone import format_istanbul, now_istanbul

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("analyzer")

INPUT_PATH = os.getenv("INPUT_PATH", "/tmp/raw_data.json")
OUTPUT_PATH = os.getenv("OUTPUT_PATH", "/tmp/analysis_data.json")


def analyze_fixture(fixture_data: dict) -> dict:
    """Run full analysis for a single fixture.

    Returns fixture_data enriched with analysis results.
    """
    fid = fixture_data.get("fixture_id", "?")
    meta = fixture_data.get("fixture_meta", {})
    predictions_raw = fixture_data.get("predictions_raw") or {}
    odds_response = fixture_data.get("odds")
    standings = fixture_data.get("standings") or []

    result = {
        "fixture_id": fid,
        "fixture_meta": meta,
        "coverage": fixture_data.get("coverage", "low"),
        "analysis_errors": [],
        "analysis": {},
    }

    # --- Feature engineering ---
    try:
        features = engineer_features(fixture_data)
    except Exception as e:
        logger.error(f"[{fid}] Feature engineering failed: {e}")
        result["analysis_errors"].append(f"feature_engineering: {e}")
        features = {}

    # --- Our prediction ---
    try:
        our_prediction = generate_prediction(features)
    except Exception as e:
        logger.error(f"[{fid}] Prediction generation failed: {e}")
        result["analysis_errors"].append(f"prediction_model: {e}")
        our_prediction = {
            "home_win_probability": 0.33,
            "draw_probability": 0.34,
            "away_win_probability": 0.33,
            "model_version": "fallback",
        }

    result["our_prediction"] = our_prediction

    # --- Market edge ---
    try:
        market_edge = calculate_market_edge(our_prediction, odds_response)
    except Exception as e:
        logger.warning(f"[{fid}] Market edge calculation failed: {e}")
        market_edge = None

    result["market_edge"] = market_edge

    # --- Answer all 11 questions ---
    def safe_question(fn, *args, label="?"):
        try:
            return fn(*args)
        except Exception as e:
            logger.error(f"[{fid}] Question {label} failed: {e}")
            return {
                "question": label,
                "conclusion": f"Analiz hatası: {e}",
                "confidence": "N/A",
                "signals": {"positive": 0, "total": 0, "details": []},
                "data_sources": [],
                "skipped": True,
                "reason": f"error: {e}",
            }

    result["analysis"] = {
        "U1_gol_olur_mu": safe_question(
            u1_gol_olur_mu, features, predictions_raw, odds_response, label="U.1"
        ),
        "U2_over_2_5": safe_question(
            u2_over_2_5, features, predictions_raw, odds_response, label="U.2"
        ),
        "U3_btts": safe_question(
            u3_btts, features, predictions_raw, odds_response, label="U.3"
        ),
        "U4_home_gercekten_guclu": safe_question(
            u4_home_gercekten_guclu, features, predictions_raw, standings, label="U.4"
        ),
        "U5_away_yanlis_fiyatlanmis": safe_question(
            u5_away_yanlis_fiyatlanmis, features, our_prediction, market_edge, odds_response, label="U.5"
        ),
        "U6_ilk_yari_gol": safe_question(
            u6_ilk_yari_gol, features, predictions_raw, odds_response, label="U.6"
        ),
        "U7_ikinci_yari_gol": safe_question(
            u7_ikinci_yari_gol, features, predictions_raw, odds_response, label="U.7"
        ),
        "U8_mac_temposu": safe_question(
            u8_mac_temposu, features, predictions_raw, label="U.8"
        ),
        "U9_korner": safe_question(
            u9_korner, features, predictions_raw, label="U.9"
        ),
        "U10_upset": safe_question(
            u10_upset, features, our_prediction, market_edge, odds_response, label="U.10"
        ),
        "U11_form_odds_celiskisi": safe_question(
            u11_form_odds_celiskisi, features, our_prediction, market_edge, odds_response, label="U.11"
        ),
    }

    # Collect HIGH confidence signals for report ranking
    high_signals = [
        key for key, ans in result["analysis"].items()
        if ans.get("confidence") == "HIGH" and not ans.get("skipped")
    ]
    result["high_confidence_count"] = len(high_signals)
    result["high_confidence_questions"] = high_signals

    # Value bet flag
    result["has_value_bet"] = bool(
        market_edge and (
            market_edge.get("home_value") or
            market_edge.get("away_value") or
            market_edge.get("draw_value")
        )
    )

    return result


def main():
    logger.info("=" * 60)
    logger.info("Football Analytics — Analyzer (Stage 5)")
    logger.info(f"Run time: {now_istanbul().strftime('%Y-%m-%d %H:%M %Z')}")
    logger.info("=" * 60)

    # Load raw data from Stage 1-4
    raw_path = Path(INPUT_PATH)
    if not raw_path.exists():
        logger.error(f"Input file not found: {INPUT_PATH}")
        sys.exit(1)

    raw_data = json.loads(raw_path.read_text(encoding="utf-8"))
    fixtures_data = raw_data.get("fixtures_data", [])

    logger.info(f"Analyzing {len(fixtures_data)} fixtures...")

    analyzed = []
    errors = 0

    for i, fd in enumerate(fixtures_data):
        fid = fd.get("fixture_id", "?")
        try:
            result = analyze_fixture(fd)
            analyzed.append(result)

            if (i + 1) % 10 == 0:
                logger.info(f"  Progress: {i + 1}/{len(fixtures_data)}")

        except Exception as e:
            logger.error(f"[{fid}] Fatal analysis error: {e}")
            errors += 1
            analyzed.append({
                "fixture_id": fid,
                "fixture_meta": fd.get("fixture_meta", {}),
                "analysis": {},
                "analysis_errors": [f"fatal: {e}"],
                "our_prediction": None,
                "market_edge": None,
                "high_confidence_count": 0,
                "has_value_bet": False,
            })

    # Sort by high confidence count (best opportunities first)
    analyzed.sort(key=lambda x: x.get("high_confidence_count", 0), reverse=True)

    output = {
        "analysis_time_istanbul": format_istanbul(now_istanbul()),
        "collection_time_istanbul": raw_data.get("collection_time_istanbul"),
        "total_fixtures": len(analyzed),
        "summary": {
            "high_coverage": raw_data.get("summary", {}).get("high_coverage", 0),
            "low_coverage": raw_data.get("summary", {}).get("low_coverage", 0),
            "with_value_bets": sum(1 for f in analyzed if f.get("has_value_bet")),
            "high_confidence_any": sum(1 for f in analyzed if f.get("high_confidence_count", 0) > 0),
            "analysis_errors": errors,
        },
        "metadata": raw_data.get("metadata", {}),
        "fixtures": analyzed,
    }

    Path(OUTPUT_PATH).write_text(json.dumps(output, ensure_ascii=False, indent=2))
    logger.info(f"Output written to {OUTPUT_PATH}")
    logger.info(f"Summary: {output['summary']}")
    logger.info("Analysis complete.")


if __name__ == "__main__":
    main()
