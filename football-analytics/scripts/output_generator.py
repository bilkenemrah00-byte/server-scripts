"""
output_generator.py — Stage 6: JSON + Markdown report generation.

Reads /tmp/analysis_data.json (from analyzer.py)
Writes:
  /output/analysis_{timestamp}.json
  /output/report_{timestamp}.md

Reference: KESTRA-AGENT-IMPLEMENTATION-BRIEF.md Section V
"""

import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime

from utils.timezone import now_istanbul, output_filename_suffix, analysis_timestamp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("output_generator")

INPUT_PATH = os.getenv("INPUT_PATH", "/tmp/analysis_data.json")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/output")

CONFIDENCE_EMOJI = {"HIGH": "🔥", "MEDIUM": "⚠️", "LOW": "ℹ️", "N/A": "⏭️"}


# ---------------------------------------------------------------------------
# JSON output (structured, full data)
# ---------------------------------------------------------------------------

def write_json_output(data: dict, output_dir: Path) -> Path:
    """Write the full analysis as JSON."""
    suffix = output_filename_suffix()
    path = output_dir / f"analysis_{suffix}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"JSON output: {path}")
    return path


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def format_fixture_header(fixture: dict) -> str:
    meta = fixture.get("fixture_meta", {})
    home = meta.get("home", {}).get("name", "?")
    away = meta.get("away", {}).get("name", "?")
    league = meta.get("league", {}).get("name", "?")
    match_time = meta.get("match_time_istanbul", "?")
    coverage = fixture.get("coverage", "?")
    return f"### {home} vs {away}\n**Saat:** {match_time} | **Lig:** {league} | **Coverage:** {coverage}"


def format_our_prediction(our_pred: dict) -> str:
    if not our_pred:
        return ""
    h = our_pred.get("home_win_probability", 0)
    d = our_pred.get("draw_probability", 0)
    a = our_pred.get("away_win_probability", 0)
    return f"**Bizim tahminimiz:** Ev {h:.0%} | Beraberlik {d:.0%} | Deplasman {a:.0%}"


def format_market_edge(edge: dict) -> str:
    if not edge:
        return ""
    parts = []
    if edge.get("home_value"):
        parts.append(f"🔥 HOME VALUE (+{edge['home_edge']:.0%} edge, oran: {edge.get('home_odd', '?')})")
    if edge.get("away_value"):
        parts.append(f"🔥 AWAY VALUE (+{edge['away_edge']:.0%} edge, oran: {edge.get('away_odd', '?')})")
    if edge.get("draw_value"):
        parts.append(f"🔥 DRAW VALUE (+{edge['draw_edge']:.0%} edge, oran: {edge.get('draw_odd', '?')})")
    if not parts:
        return "Market edge: belirgin değer yok"
    return " | ".join(parts)


def format_analysis_summary(analysis: dict) -> str:
    lines = []
    for key, ans in analysis.items():
        if ans.get("skipped"):
            continue
        emoji = CONFIDENCE_EMOJI.get(ans.get("confidence", "N/A"), "")
        q_short = ans.get("question", key)
        conclusion = ans.get("conclusion", "")
        lines.append(f"- {emoji} **{q_short}:** {conclusion}")
    return "\n".join(lines)


def generate_markdown(data: dict) -> str:
    fixtures = data.get("fixtures", [])
    summary = data.get("summary", {})

    lines = [
        "# Football Fixture Analysis Report",
        f"**Analiz Zamanı:** {analysis_timestamp()}",
        f"**Toplam Maç:** {data.get('total_fixtures', 0)} | "
        f"**High Coverage:** {summary.get('high_coverage', 0)} | "
        f"**Low Coverage:** {summary.get('low_coverage', 0)}",
        "",
        "---",
        "",
        "## 🔥 Öne Çıkan Fırsatlar",
        "",
    ]

    # Top fixtures: value bets + high confidence
    top = [f for f in fixtures if f.get("has_value_bet") or f.get("high_confidence_count", 0) >= 3]
    top = top[:10]

    if top:
        for i, fixture in enumerate(top, 1):
            lines.append(f"### {i}. {format_fixture_header(fixture)}")
            lines.append("")
            if fixture.get("our_prediction"):
                lines.append(format_our_prediction(fixture["our_prediction"]))
            if fixture.get("market_edge"):
                lines.append(format_market_edge(fixture["market_edge"]))
            lines.append("")
            lines.append(format_analysis_summary(fixture.get("analysis", {})))
            lines.append("")
            lines.append("---")
            lines.append("")
    else:
        lines.append("Bu gün için belirgin fırsat tespit edilmedi.")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Quick stats
    lines += [
        "## 📊 Hızlı İstatistikler",
        "",
    ]

    def count_high(q_key):
        return sum(
            1 for f in fixtures
            if f.get("analysis", {}).get(q_key, {}).get("confidence") == "HIGH"
        )

    lines.append(f"- **Gol olur (HIGH):** {count_high('U1_gol_olur_mu')} maç")
    lines.append(f"- **Over 2.5 (HIGH):** {count_high('U2_over_2_5')} maç")
    lines.append(f"- **BTTS Yes (HIGH):** {count_high('U3_btts')} maç")
    lines.append(f"- **Upset riski (HIGH):** {count_high('U10_upset')} maç")
    lines.append(f"- **Form-Odds çelişkisi (HIGH):** {count_high('U11_form_odds_celiskisi')} maç")
    lines.append(f"- **Value bet tespit edilen:** {summary.get('with_value_bets', 0)} maç")
    lines.append("")
    lines.append("---")
    lines.append("")

    # All fixtures (brief)
    lines.append("## 📋 Tüm Maçlar")
    lines.append("")

    for fixture in fixtures:
        meta = fixture.get("fixture_meta", {})
        home = meta.get("home", {}).get("name", "?")
        away = meta.get("away", {}).get("name", "?")
        league = meta.get("league", {}).get("name", "?")
        time_str = meta.get("match_time_istanbul", "?")[:16]
        hc = fixture.get("high_confidence_count", 0)
        vb = " 🔥VALUE" if fixture.get("has_value_bet") else ""
        lines.append(f"- **{time_str}** {home} vs {away} ({league}) — {hc} HIGH sinyal{vb}")

    lines.append("")
    lines.append("---")
    lines.append(f"*Rapor: {now_istanbul().strftime('%Y-%m-%d %H:%M')} İstanbul*")

    return "\n".join(lines)


def write_markdown_output(data: dict, output_dir: Path) -> Path:
    suffix = output_filename_suffix()
    path = output_dir / f"report_{suffix}.md"
    path.write_text(generate_markdown(data), encoding="utf-8")
    logger.info(f"Markdown output: {path}")
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 60)
    logger.info("Football Analytics — Output Generator (Stage 6)")
    logger.info("=" * 60)

    input_path = Path(INPUT_PATH)
    if not input_path.exists():
        logger.error(f"Input file not found: {INPUT_PATH}")
        sys.exit(1)

    data = json.loads(input_path.read_text(encoding="utf-8"))

    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = write_json_output(data, output_dir)
    md_path = write_markdown_output(data, output_dir)

    logger.info(f"JSON: {json_path}")
    logger.info(f"Markdown: {md_path}")
    logger.info("Output generation complete.")


if __name__ == "__main__":
    main()
