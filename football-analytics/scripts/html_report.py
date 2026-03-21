"""
html_report.py — Interactive HTML report for all fixtures.

Reads /tmp/analysis_data.json
Writes /output/report_{timestamp}.html

Features:
- Filterable by league, confidence, coverage
- Searchable by team name
- Color-coded signals
- Sortable by time or HIGH signal count
"""

import json
import os
import sys
from pathlib import Path

INPUT_PATH = os.getenv("INPUT_PATH", "/tmp/analysis_data.json")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/output")


def confidence_class(c):
    return {"HIGH": "high", "MEDIUM": "medium", "LOW": "low", "N/A": "na"}.get(c, "na")


def signal_emoji(c):
    return {"HIGH": "🔥", "MEDIUM": "⚠️", "LOW": "ℹ️", "N/A": "⏭️"}.get(c, "")


def build_fixture_card(f):
    meta = f.get("fixture_meta", {})
    home = meta.get("home", {}).get("name", "?")
    away = meta.get("away", {}).get("name", "?")
    league = meta.get("league", {}).get("name", "?")
    match_time = meta.get("match_time_istanbul", "?")[:16].replace("T", " ")
    coverage = f.get("coverage", "low")
    hc = f.get("high_confidence_count", 0)
    value_bet = f.get("has_value_bet", False)
    analysis = f.get("analysis", {})
    our_pred = f.get("our_prediction", {})
    market_edge = f.get("market_edge")

    # prediction bar
    hp = our_pred.get("home_win_probability", 0.33) * 100
    dp = our_pred.get("draw_probability", 0.34) * 100
    ap = our_pred.get("away_win_probability", 0.33) * 100

    pred_html = f"""
    <div class="pred-bar">
      <div class="pred-home" style="width:{hp:.0f}%">Ev {hp:.0f}%</div>
      <div class="pred-draw" style="width:{dp:.0f}%">X {dp:.0f}%</div>
      <div class="pred-away" style="width:{ap:.0f}%">Dep {ap:.0f}%</div>
    </div>"""

    # market edge
    edge_html = ""
    if market_edge:
        parts = []
        if market_edge.get("home_value"):
            parts.append(f"🔥 HOME +{market_edge['home_edge']:.0%} @ {market_edge.get('home_odd','?')}")
        if market_edge.get("away_value"):
            parts.append(f"🔥 AWAY +{market_edge['away_edge']:.0%} @ {market_edge.get('away_odd','?')}")
        if market_edge.get("draw_value"):
            parts.append(f"🔥 DRAW +{market_edge['draw_edge']:.0%} @ {market_edge.get('draw_odd','?')}")
        if parts:
            edge_html = f'<div class="value-bet">{"  |  ".join(parts)}</div>'

    # questions
    q_rows = ""
    for key, ans in analysis.items():
        if ans.get("skipped"):
            continue
        conf = ans.get("confidence", "N/A")
        q = ans.get("question", key)
        conclusion = ans.get("conclusion", "")
        cls = confidence_class(conf)
        emoji = signal_emoji(conf)
        q_rows += f'<tr class="q-row q-{cls}"><td>{emoji}</td><td>{q}</td><td>{conclusion}</td></tr>'

    value_badge = '<span class="badge-value">VALUE</span>' if value_bet else ""
    cov_badge = f'<span class="badge-cov badge-{coverage}">{coverage.upper()}</span>'

    return f"""
<div class="fixture-card" 
     data-league="{league}" 
     data-hc="{hc}" 
     data-time="{match_time}"
     data-teams="{home} {away}"
     data-coverage="{coverage}"
     data-value="{str(value_bet).lower()}">
  <div class="card-header">
    <div class="match-title">
      <span class="team-names">{home} <span class="vs">vs</span> {away}</span>
      {value_badge}
    </div>
    <div class="match-meta">
      <span class="league">{league}</span>
      {cov_badge}
      <span class="time">🕐 {match_time}</span>
      <span class="hc-count">🔥 {hc} HIGH</span>
    </div>
  </div>
  <div class="card-body">
    {pred_html}
    {edge_html}
    <details>
      <summary>11 Soru Analizi</summary>
      <table class="q-table">
        <tbody>{q_rows}</tbody>
      </table>
    </details>
  </div>
</div>"""


def generate_html(data: dict) -> str:
    fixtures = data.get("fixtures", [])
    summary = data.get("summary", {})
    analysis_time = data.get("analysis_time_istanbul", "?")

    leagues = sorted(set(
        f.get("fixture_meta", {}).get("league", {}).get("name", "?")
        for f in fixtures
    ))
    league_options = "\n".join(f'<option value="{l}">{l}</option>' for l in leagues)

    cards = "\n".join(build_fixture_card(f) for f in fixtures)

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Football Analysis — {analysis_time[:10]}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; 
         background: #0f1117; color: #e0e0e0; padding: 16px; }}
  
  .header {{ background: #1a1d2e; border-radius: 12px; padding: 20px; margin-bottom: 16px; }}
  .header h1 {{ font-size: 1.4rem; color: #fff; margin-bottom: 8px; }}
  .stats {{ display: flex; gap: 16px; flex-wrap: wrap; }}
  .stat {{ background: #252840; padding: 8px 14px; border-radius: 8px; font-size: 0.85rem; }}
  .stat span {{ color: #7c8cf8; font-weight: bold; }}

  .controls {{ background: #1a1d2e; border-radius: 12px; padding: 16px; margin-bottom: 16px;
               display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }}
  .controls input, .controls select {{ 
    background: #252840; border: 1px solid #3a3d5c; color: #e0e0e0;
    padding: 8px 12px; border-radius: 8px; font-size: 0.9rem; }}
  .controls input {{ flex: 1; min-width: 200px; }}
  .controls label {{ font-size: 0.85rem; color: #888; }}
  #result-count {{ color: #888; font-size: 0.85rem; margin-left: auto; }}

  .fixture-card {{ background: #1a1d2e; border-radius: 12px; margin-bottom: 12px;
                   border: 1px solid #2a2d3e; overflow: hidden; }}
  .fixture-card[data-value="true"] {{ border-color: #f59e0b; }}
  
  .card-header {{ padding: 14px 16px; cursor: pointer; }}
  .match-title {{ display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }}
  .team-names {{ font-size: 1rem; font-weight: 600; color: #fff; }}
  .vs {{ color: #666; font-weight: 400; }}
  .match-meta {{ display: flex; gap: 10px; flex-wrap: wrap; align-items: center; font-size: 0.8rem; }}
  .league {{ color: #7c8cf8; }}
  .time {{ color: #888; }}
  .hc-count {{ color: #f59e0b; font-weight: bold; }}
  
  .badge-value {{ background: #f59e0b; color: #000; padding: 2px 8px; border-radius: 4px; 
                  font-size: 0.75rem; font-weight: bold; }}
  .badge-cov {{ padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; }}
  .badge-high {{ background: #065f46; color: #6ee7b7; }}
  .badge-low {{ background: #374151; color: #9ca3af; }}

  .card-body {{ padding: 0 16px 14px; }}
  
  .pred-bar {{ display: flex; height: 28px; border-radius: 6px; overflow: hidden; margin-bottom: 10px; }}
  .pred-home {{ background: #1d4ed8; display: flex; align-items: center; justify-content: center;
                font-size: 0.75rem; color: #fff; font-weight: 600; min-width: 40px; }}
  .pred-draw {{ background: #4b5563; display: flex; align-items: center; justify-content: center;
                font-size: 0.75rem; color: #fff; font-weight: 600; min-width: 35px; }}
  .pred-away {{ background: #b45309; display: flex; align-items: center; justify-content: center;
                font-size: 0.75rem; color: #fff; font-weight: 600; min-width: 40px; }}

  .value-bet {{ background: #1c1400; border: 1px solid #f59e0b; color: #f59e0b;
                padding: 6px 10px; border-radius: 6px; font-size: 0.85rem; 
                margin-bottom: 10px; font-weight: 600; }}

  details {{ margin-top: 6px; }}
  summary {{ cursor: pointer; color: #7c8cf8; font-size: 0.85rem; padding: 4px 0;
             user-select: none; }}
  summary:hover {{ color: #a5b4fc; }}
  
  .q-table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 0.82rem; }}
  .q-table td {{ padding: 4px 8px; vertical-align: top; }}
  .q-table td:first-child {{ width: 24px; text-align: center; }}
  .q-row.q-high {{ background: #0a1a0a; }}
  .q-row.q-medium {{ background: #1a1500; }}
  .q-row.q-low {{ background: #111; }}
  .q-row td:last-child {{ color: #ccc; }}

  .hidden {{ display: none !important; }}
</style>
</head>
<body>

<div class="header">
  <h1>🏆 Football Fixture Analysis</h1>
  <p style="color:#888;font-size:0.85rem;margin-bottom:12px">Analiz: {analysis_time} | Toplam: {len(fixtures)} maç</p>
  <div class="stats">
    <div class="stat">High Coverage: <span>{summary.get('high_coverage', 0)}</span></div>
    <div class="stat">Value Bet: <span>{summary.get('with_value_bets', 0)}</span></div>
    <div class="stat">HIGH Sinyalli: <span>{summary.get('high_confidence_any', 0)}</span></div>
  </div>
</div>

<div class="controls">
  <input type="text" id="search" placeholder="Takım ara..." oninput="filterCards()">
  <select id="league-filter" onchange="filterCards()">
    <option value="">Tüm Ligler</option>
    {league_options}
  </select>
  <select id="coverage-filter" onchange="filterCards()">
    <option value="">Tüm Coverage</option>
    <option value="high">High Coverage</option>
    <option value="low">Low Coverage</option>
  </select>
  <select id="value-filter" onchange="filterCards()">
    <option value="">Tümü</option>
    <option value="true">Sadece Value Bet</option>
  </select>
  <select id="hc-filter" onchange="filterCards()">
    <option value="0">Min HIGH sinyal: 0+</option>
    <option value="2">2+</option>
    <option value="3">3+</option>
    <option value="4">4+</option>
    <option value="5">5+</option>
  </select>
  <span id="result-count"></span>
</div>

<div id="fixture-list">
{cards}
</div>

<script>
function filterCards() {{
  const search = document.getElementById('search').value.toLowerCase();
  const league = document.getElementById('league-filter').value;
  const coverage = document.getElementById('coverage-filter').value;
  const valueOnly = document.getElementById('value-filter').value;
  const minHc = parseInt(document.getElementById('hc-filter').value);
  
  const cards = document.querySelectorAll('.fixture-card');
  let visible = 0;
  
  cards.forEach(card => {{
    const teams = card.dataset.teams.toLowerCase();
    const cardLeague = card.dataset.league;
    const cardCov = card.dataset.coverage;
    const cardValue = card.dataset.value;
    const cardHc = parseInt(card.dataset.hc);
    
    const ok = (
      (!search || teams.includes(search)) &&
      (!league || cardLeague === league) &&
      (!coverage || cardCov === coverage) &&
      (!valueOnly || cardValue === valueOnly) &&
      (cardHc >= minHc)
    );
    
    card.classList.toggle('hidden', !ok);
    if (ok) visible++;
  }});
  
  document.getElementById('result-count').textContent = visible + ' maç gösteriliyor';
}}

filterCards();
</script>
</body>
</html>"""


def main():
    input_path = Path(INPUT_PATH)
    if not input_path.exists():
        print(f"Input not found: {INPUT_PATH}")
        sys.exit(1)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Timestamp from analysis_time
    ts = data.get("analysis_time_istanbul", "")[:16].replace("-", "").replace("T", "_").replace(":", "")
    html_path = output_dir / f"report_{ts}_istanbul.html"
    html_path.write_text(generate_html(data), encoding="utf-8")
    print(f"HTML report: {html_path}")


if __name__ == "__main__":
    main()
