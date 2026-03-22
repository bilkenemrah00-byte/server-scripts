"""
results_fetcher.py — Stage 7: Fetch FT results and enrich analysis JSON + HTML

Reads:  OUTPUT_DIR/analysis_*.json (latest)
Writes: OUTPUT_DIR/results_*.json
        OUTPUT_DIR/results_*.html  (enriched report with outcomes)
"""

import json
import os
import sys
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(name)s — %(message)s")
logger = logging.getLogger("results_fetcher")

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "/output")


def load_latest_analysis(output_dir: Path) -> tuple[dict, Path]:
    files = sorted(output_dir.glob("analysis_*_istanbul.json"))
    if not files:
        raise FileNotFoundError("No analysis file found")
    latest = files[-1]
    logger.info(f"Loading: {latest.name}")
    return json.loads(latest.read_text()), latest


def fetch_fixture_result(client, fixture_id: int) -> dict:
    data = client.get('/fixtures', params={'id': fixture_id})
    for r in data.get('response', []):
        status = r['fixture']['status']['short']
        if status != 'FT':
            return {'status': status}

        goals = r.get('goals', {})
        home_goals = goals.get('home', 0) or 0
        away_goals = goals.get('away', 0) or 0

        # Gol olayları
        goal_events = []
        for e in r.get('events', []):
            if e['type'] == 'Goal':
                goal_events.append({
                    'minute': e.get('time', {}).get('elapsed'),
                    'player': e.get('player', {}).get('name', '?'),
                    'team': e.get('team', {}).get('name', '?'),
                    'detail': e.get('detail', 'Normal Goal'),
                })

        # İstatistikler
        stats = {}
        for team_stats in r.get('statistics', []):
            team_name = team_stats.get('team', {}).get('name', '?')
            team_id = team_stats.get('team', {}).get('id')
            team_data = {}
            for s in team_stats.get('statistics', []):
                t = s['type']
                v = s['value']
                if t == 'Corner Kicks': team_data['corners'] = v or 0
                elif t == 'Total Shots': team_data['shots'] = v or 0
                elif t == 'Shots on Goal': team_data['shots_on_goal'] = v or 0
                elif t == 'Ball Possession': team_data['possession'] = v or '?'
                elif t == 'Yellow Cards': team_data['yellow_cards'] = v or 0
                elif t == 'Red Cards': team_data['red_cards'] = v or 0
            stats[team_id] = {'name': team_name, **team_data}

        # Halftime
        halftime = r.get('score', {}).get('halftime', {})

        return {
            'status': 'FT',
            'home_goals': home_goals,
            'away_goals': away_goals,
            'halftime_home': halftime.get('home', '?'),
            'halftime_away': halftime.get('away', '?'),
            'goal_events': goal_events,
            'stats': stats,
            'total_corners': sum(v.get('corners', 0) for v in stats.values()),
            'total_goals': home_goals + away_goals,
        }
    return {'status': 'NS'}


def evaluate_predictions(fix: dict, result: dict) -> dict:
    if result.get('status') != 'FT':
        return {}

    our = fix.get('our_prediction', {}) or {}
    edge = fix.get('market_edge', {}) or {}
    analysis = fix.get('analysis', {}) or {}

    hg = result['home_goals']
    ag = result['away_goals']
    total = result['total_goals']
    corners = result.get('total_corners', 0)

    actual_outcome = 'home' if hg > ag else ('away' if ag > hg else 'draw')

    # 1X2 tahmini
    probs = {
        'home': our.get('home_win_probability', 0),
        'draw': our.get('draw_probability', 0),
        'away': our.get('away_win_probability', 0),
    }
    our_pick = max(probs, key=probs.get)
    our_correct = our_pick == actual_outcome

    mkt_probs = {
        'home': edge.get('market_home_prob', 0),
        'draw': edge.get('market_draw_prob', 0),
        'away': edge.get('market_away_prob', 0),
    }
    mkt_pick = max(mkt_probs, key=mkt_probs.get) if mkt_probs else None
    mkt_correct = mkt_pick == actual_outcome if mkt_pick else None

    # Over/Under tahmin kontrolü
    over_predicted = None
    over_correct = None
    u2_analysis = analysis.get('u02_over_under', {})
    if u2_analysis:
        conf = u2_analysis.get('confidence', '')
        conc = u2_analysis.get('conclusion', '')
        if 'GÜÇLÜ' in conc or conf == 'HIGH':
            over_predicted = True
        elif 'Under' in conc:
            over_predicted = False
        if over_predicted is not None:
            over_correct = (total > 2.5) == over_predicted

    # BTTS kontrolü
    btts_predicted = None
    btts_correct = None
    u3_analysis = analysis.get('u03_btts', {})
    if u3_analysis:
        conc = u3_analysis.get('conclusion', '')
        conf = u3_analysis.get('confidence', '')
        if 'GÜÇLÜ' in conc and 'Yes' in conc:
            btts_predicted = True
        elif 'No' in conc:
            btts_predicted = False
        actual_btts = hg > 0 and ag > 0
        if btts_predicted is not None:
            btts_correct = actual_btts == btts_predicted

    # Korner tahmini
    corner_predicted = None
    corner_correct = None
    u9_analysis = analysis.get('u09_corners', {})
    if u9_analysis:
        conc = u9_analysis.get('conclusion', '')
        if 'YÜKSEK' in conc:
            corner_predicted = True
        elif 'Düşük' in conc.lower() or 'düşük' in conc:
            corner_predicted = False
        if corner_predicted is not None:
            corner_correct = (corners > 10) == corner_predicted

    return {
        'actual_outcome': actual_outcome,
        'our_pick': our_pick,
        'our_correct': our_correct,
        'mkt_pick': mkt_pick,
        'mkt_correct': mkt_correct,
        'over_25_actual': total > 2.5,
        'over_predicted': over_predicted,
        'over_correct': over_correct,
        'btts_actual': hg > 0 and ag > 0,
        'btts_predicted': btts_predicted,
        'btts_correct': btts_correct,
        'corners_actual': corners,
        'corner_high_predicted': corner_predicted,
        'corner_correct': corner_correct,
    }


def generate_results_html(analysis: dict, enriched_fixtures: list) -> str:
    ft_fixtures = [f for f in enriched_fixtures if f.get('result', {}).get('status') == 'FT']
    ns_fixtures = [f for f in enriched_fixtures if f.get('result', {}).get('status') != 'FT']

    # İstatistikler
    total_pred = sum(1 for f in ft_fixtures if f.get('eval', {}).get('our_pick'))
    correct_pred = sum(1 for f in ft_fixtures if f.get('eval', {}).get('our_correct'))
    total_mkt = sum(1 for f in ft_fixtures if f.get('eval', {}).get('mkt_pick'))
    correct_mkt = sum(1 for f in ft_fixtures if f.get('eval', {}).get('mkt_correct'))
    over_total = sum(1 for f in ft_fixtures if f.get('eval', {}).get('over_predicted') is not None)
    over_correct = sum(1 for f in ft_fixtures if f.get('eval', {}).get('over_correct'))
    btts_total = sum(1 for f in ft_fixtures if f.get('eval', {}).get('btts_predicted') is not None)
    btts_correct = sum(1 for f in ft_fixtures if f.get('eval', {}).get('btts_correct'))

    acc_our = f"{correct_pred/total_pred:.0%}" if total_pred else "—"
    acc_mkt = f"{correct_mkt/total_mkt:.0%}" if total_mkt else "—"
    acc_over = f"{over_correct/over_total:.0%}" if over_total else "—"
    acc_btts = f"{btts_correct/btts_total:.0%}" if btts_total else "—"

    # FT fixture kartları
    ft_cards = ""
    for f in sorted(ft_fixtures, key=lambda x: x['fixture_meta'].get('match_time_istanbul', '')):
        meta = f['fixture_meta']
        result = f['result']
        ev = f.get('eval', {})
        our = f.get('our_prediction', {}) or {}
        edge = f.get('market_edge', {}) or {}
        home_name = meta['home']['name']
        away_name = meta['away']['name']
        league = meta['league']['name']
        match_time = meta.get('match_time_istanbul', '')[:16].replace('T', ' ')
        hg = result['home_goals']
        ag = result['away_goals']
        ht_h = result.get('halftime_home', '?')
        ht_a = result.get('halftime_away', '?')
        total_g = result['total_goals']
        corners = result.get('total_corners', 0)

        # Skor rengi
        outcome = ev.get('actual_outcome', '')
        score_color = '#4ade80' if outcome == 'home' else '#f87171' if outcome == 'away' else '#fbbf24'

        # Tahmin badge'leri
        our_badge = f'<span class="badge-{"ok" if ev.get("our_correct") else "fail"}">Bizim: {ev.get("our_pick","?").upper()} {"✓" if ev.get("our_correct") else "✗"}</span>'
        mkt_badge = f'<span class="badge-{"ok" if ev.get("mkt_correct") else "fail"}">Market: {ev.get("mkt_pick","?").upper()} {"✓" if ev.get("mkt_correct") else "✗"}</span>' if ev.get('mkt_pick') else ''

        # Over/BTTS badge
        over_badge = ""
        if ev.get('over_predicted') is not None:
            over_badge = f'<span class="badge-{"ok" if ev.get("over_correct") else "fail"}">Over2.5: {"✓" if ev.get("over_25_actual") else "✗"} (pred:{"Yes" if ev.get("over_predicted") else "No"})</span>'
        btts_badge = ""
        if ev.get('btts_predicted') is not None:
            btts_badge = f'<span class="badge-{"ok" if ev.get("btts_correct") else "fail"}">BTTS: {"✓" if ev.get("btts_actual") else "✗"} (pred:{"Yes" if ev.get("btts_predicted") else "No"})</span>'

        # Gol olayları
        goal_timeline = ""
        for ge in result.get('goal_events', []):
            icon = "⚽" if "Penalty" not in ge.get('detail', '') else "🥅"
            goal_timeline += f'<span class="goal-event">{icon} {ge["minute"]}\' {ge["player"]} <span class="goal-team">({ge["team"]})</span></span>'

        # İstatistikler
        stats_html = ""
        stats = result.get('stats', {})
        home_id = meta['home']['id']
        away_id = meta['away']['id']
        hs = stats.get(home_id, {})
        as_ = stats.get(away_id, {})
        if hs or as_:
            stats_html = f"""
            <div class="stats-row">
                <span>🔲 Korner: {hs.get('corners',0)}-{as_.get('corners',0)}</span>
                <span>🎯 Şut: {hs.get('shots',0)}-{as_.get('shots',0)}</span>
                <span>🥅 İsabetli: {hs.get('shots_on_goal',0)}-{as_.get('shots_on_goal',0)}</span>
                <span>🟨 Kart: {hs.get('yellow_cards',0)}-{as_.get('yellow_cards',0)}</span>
            </div>"""

        # Tahmin yüzdeleri
        hp = our.get('home_win_probability', 0) * 100
        dp = our.get('draw_probability', 0) * 100
        ap = our.get('away_win_probability', 0) * 100

        ft_cards += f"""
<div class="result-card">
  <div class="rc-header">
    <div class="rc-teams">
      <span class="rc-home">{home_name}</span>
      <span class="rc-score" style="color:{score_color}">{hg} - {ag}</span>
      <span class="rc-away">{away_name}</span>
    </div>
    <div class="rc-meta">
      <span class="rc-league">{league}</span>
      <span class="rc-time">🕐 {match_time}</span>
      <span class="rc-ht">HT: {ht_h}-{ht_a}</span>
      <span class="rc-over">{"Over2.5 ✓" if total_g > 2.5 else "Under2.5 ✓"}</span>
    </div>
  </div>
  <div class="rc-body">
    <div class="rc-badges">{our_badge}{mkt_badge}{over_badge}{btts_badge}</div>
    <div class="rc-goals">{goal_timeline if goal_timeline else '<span style="color:#666">Gol bilgisi yok</span>'}</div>
    {stats_html}
    <div class="rc-probs">
      <div class="pred-bar">
        <div class="pred-home" style="width:{hp:.0f}%">Ev {hp:.0f}%</div>
        <div class="pred-draw" style="width:{dp:.0f}%">X {dp:.0f}%</div>
        <div class="pred-away" style="width:{ap:.0f}%">Dep {ap:.0f}%</div>
      </div>
    </div>
  </div>
</div>"""

    # NS fixture listesi
    ns_rows = ""
    for f in sorted(ns_fixtures, key=lambda x: x['fixture_meta'].get('match_time_istanbul', '')):
        meta = f['fixture_meta']
        our = f.get('our_prediction', {}) or {}
        hc = f.get('high_confidence_count', 0)
        coverage = f.get('coverage', 'low')
        home_name = meta['home']['name']
        away_name = meta['away']['name']
        league = meta['league']['name']
        match_time = meta.get('match_time_istanbul', '')[:16].replace('T', ' ')
        hp = our.get('home_win_probability', 0.33) * 100
        dp = our.get('draw_probability', 0.34) * 100
        ap = our.get('away_win_probability', 0.33) * 100
        value = '🔥VALUE' if f.get('has_value_bet') else ''
        cov_badge = f'<span class="badge-cov badge-{coverage}">{coverage.upper()}</span>'
        ns_rows += f"""
<tr class="ns-row">
  <td>{match_time}</td>
  <td><strong>{home_name}</strong> vs <strong>{away_name}</strong> {value}</td>
  <td>{league} {cov_badge}</td>
  <td>
    <div class="pred-bar-sm">
      <div class="pred-home" style="width:{hp:.0f}%">{hp:.0f}%</div>
      <div class="pred-draw" style="width:{dp:.0f}%">{dp:.0f}%</div>
      <div class="pred-away" style="width:{ap:.0f}%">{ap:.0f}%</div>
    </div>
  </td>
  <td>🔥{hc}</td>
</tr>"""

    analysis_time = analysis.get('analysis_time_istanbul', '')[:16].replace('T', ' ')

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Football Results — {analysis_time[:10]}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f1117; color: #e0e0e0; padding: 16px; }}

  .header {{ background: #1a1d2e; border-radius: 12px; padding: 20px; margin-bottom: 16px; }}
  .header h1 {{ font-size: 1.4rem; color: #fff; margin-bottom: 12px; }}
  .accuracy-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }}
  .acc-card {{ background: #252840; border-radius: 8px; padding: 12px; text-align: center; }}
  .acc-label {{ font-size: 0.75rem; color: #888; margin-bottom: 4px; }}
  .acc-value {{ font-size: 1.4rem; font-weight: bold; color: #7c8cf8; }}
  .acc-detail {{ font-size: 0.75rem; color: #666; }}

  h2 {{ font-size: 1.1rem; color: #ccc; margin: 20px 0 12px; padding-bottom: 6px;
        border-bottom: 1px solid #2a2d3e; }}

  .result-card {{ background: #1a1d2e; border-radius: 12px; margin-bottom: 10px;
                  border: 1px solid #2a2d3e; overflow: hidden; }}
  .rc-header {{ padding: 12px 16px; background: #1e2235; }}
  .rc-teams {{ display: flex; align-items: center; gap: 12px; margin-bottom: 6px; }}
  .rc-home, .rc-away {{ font-size: 0.95rem; font-weight: 600; color: #fff; }}
  .rc-score {{ font-size: 1.3rem; font-weight: bold; min-width: 60px; text-align: center; }}
  .rc-away {{ color: #bbb; }}
  .rc-meta {{ display: flex; gap: 10px; flex-wrap: wrap; font-size: 0.78rem; color: #888; }}
  .rc-league {{ color: #7c8cf8; }}
  .rc-over {{ color: #4ade80; font-weight: 600; }}
  .rc-ht {{ color: #888; }}
  .rc-body {{ padding: 10px 16px 12px; }}
  .rc-badges {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }}
  .badge-ok {{ background: #064e2b; color: #4ade80; padding: 3px 10px; border-radius: 4px; font-size: 0.78rem; font-weight: 600; }}
  .badge-fail {{ background: #4a0000; color: #f87171; padding: 3px 10px; border-radius: 4px; font-size: 0.78rem; font-weight: 600; }}
  .rc-goals {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 8px; font-size: 0.82rem; }}
  .goal-event {{ background: #252840; padding: 3px 8px; border-radius: 4px; }}
  .goal-team {{ color: #888; font-size: 0.75rem; }}
  .stats-row {{ display: flex; gap: 14px; flex-wrap: wrap; font-size: 0.8rem;
                color: #aaa; margin-bottom: 8px; }}
  .rc-probs {{ margin-top: 6px; }}

  .pred-bar {{ display: flex; height: 24px; border-radius: 6px; overflow: hidden; }}
  .pred-bar-sm {{ display: flex; height: 20px; border-radius: 4px; overflow: hidden; }}
  .pred-home {{ background: #1d4ed8; display: flex; align-items: center; justify-content: center;
                font-size: 0.72rem; color: #fff; font-weight: 600; min-width: 32px; }}
  .pred-draw {{ background: #4b5563; display: flex; align-items: center; justify-content: center;
                font-size: 0.72rem; color: #fff; font-weight: 600; min-width: 28px; }}
  .pred-away {{ background: #b45309; display: flex; align-items: center; justify-content: center;
                font-size: 0.72rem; color: #fff; font-weight: 600; min-width: 32px; }}

  table {{ width: 100%; border-collapse: collapse; }}
  .ns-row td {{ padding: 8px 10px; border-bottom: 1px solid #1e2235; font-size: 0.82rem; vertical-align: middle; }}
  .ns-row:hover td {{ background: #1e2235; }}
  .badge-cov {{ padding: 2px 6px; border-radius: 4px; font-size: 0.72rem; }}
  .badge-high {{ background: #065f46; color: #6ee7b7; }}
  .badge-low {{ background: #374151; color: #9ca3af; }}
</style>
</head>
<body>

<div class="header">
  <h1>📊 Football Results & Accuracy</h1>
  <p style="color:#888;font-size:0.85rem;margin-bottom:14px">
    Analiz: {analysis_time} | FT: {len(ft_fixtures)} maç | Bekleyen: {len(ns_fixtures)} maç
  </p>
  <div class="accuracy-grid">
    <div class="acc-card">
      <div class="acc-label">Bizim 1X2</div>
      <div class="acc-value">{acc_our}</div>
      <div class="acc-detail">{correct_pred}/{total_pred} doğru</div>
    </div>
    <div class="acc-card">
      <div class="acc-label">Market 1X2</div>
      <div class="acc-value">{acc_mkt}</div>
      <div class="acc-detail">{correct_mkt}/{total_mkt} doğru</div>
    </div>
    <div class="acc-card">
      <div class="acc-label">Over 2.5</div>
      <div class="acc-value">{acc_over}</div>
      <div class="acc-detail">{over_correct}/{over_total} doğru</div>
    </div>
    <div class="acc-card">
      <div class="acc-label">BTTS</div>
      <div class="acc-value">{acc_btts}</div>
      <div class="acc-detail">{btts_correct}/{btts_total} doğru</div>
    </div>
  </div>
</div>

<h2>✅ Tamamlanan Maçlar ({len(ft_fixtures)})</h2>
{ft_cards if ft_cards else '<p style="color:#666;padding:20px">Henüz tamamlanan maç yok.</p>'}

<h2>⏳ Bekleyen Maçlar ({len(ns_fixtures)})</h2>
<table>
  <tbody>{ns_rows}</tbody>
</table>

</body>
</html>"""


def main():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, '/app')
    from utils.api_client import APIFootballClient

    analysis, analysis_path = load_latest_analysis(output_dir)
    fixtures = analysis.get('fixtures', [])
    logger.info(f"Total fixtures: {len(fixtures)}")

    enriched = []
    ft_count = 0

    with APIFootballClient() as client:
        for i, fix in enumerate(fixtures):
            fid = fix['fixture_id']
            result = fetch_fixture_result(client, fid)
            ev = evaluate_predictions(fix, result) if result.get('status') == 'FT' else {}
            if result.get('status') == 'FT':
                ft_count += 1
            enriched.append({**fix, 'result': result, 'eval': ev})

            if (i + 1) % 20 == 0:
                logger.info(f"Progress: {i+1}/{len(fixtures)}, FT: {ft_count}")

    logger.info(f"FT: {ft_count}/{len(fixtures)}")

    # Timestamp
    from utils.timezone import now_istanbul as get_istanbul_now
    ts = get_istanbul_now().strftime('%Y%m%d_%H%M')

    # JSON kaydet
    results_data = {**analysis, 'fixtures': enriched, 'fetched_at': ts}
    json_path = output_dir / f"results_{ts}_istanbul.json"
    json_path.write_text(json.dumps(results_data, ensure_ascii=False, indent=2))
    logger.info(f"JSON: {json_path}")

    # HTML kaydet
    html = generate_results_html(analysis, enriched)
    html_path = output_dir / f"results_{ts}_istanbul.html"
    html_path.write_text(html, encoding='utf-8')
    logger.info(f"HTML: {html_path}")

    # results_index.html güncelle
    results_index = output_dir / 'results_index.html'
    results_index.write_text(html, encoding='utf-8')
    logger.info(f"results_index.html updated")


if __name__ == '__main__':
    main()
