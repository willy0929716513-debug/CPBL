#!/usr/bin/env python3
"""Generate static GitHub Pages site from the latest predictions JSON."""
import json
from pathlib import Path
from datetime import date as _date

TEAM_NAMES = {
    "AEL": "中信兄弟", "CT": "統一7-ELEVEn獅",
    "FG": "富邦悍將", "WL": "樂天桃猿", "TSG": "台鋼雄鷹",
}
TEAM_COLORS = {
    "AEL": "#3b82f6", "CT": "#f59e0b",
    "FG": "#ef4444",  "WL": "#8b5cf6", "TSG": "#14b8a6",
}

def load_latest():
    pred_dir = Path("predictions")
    if not pred_dir.exists():
        return None, []
    files = sorted(pred_dir.glob("*.json"), reverse=True)
    if not files:
        return None, []
    with open(files[0], encoding="utf-8") as f:
        return files[0].stem, json.load(f)

def game_card(g):
    p = g.get("prediction") or {}
    away = g.get("away", "")
    home = g.get("home", "")
    away_name = g.get("away_name") or TEAM_NAMES.get(away, away)
    home_name = g.get("home_name") or TEAM_NAMES.get(home, home)
    away_color = TEAM_COLORS.get(away, "#6b7280")
    home_color = TEAM_COLORS.get(home, "#6b7280")

    if not p:
        return f'<div class="card"><div class="no-pred">{away_name} vs {home_name} — 無預測資料</div></div>'

    home_prob = float(p.get("home_win_prob", 0.5))
    hw = int(home_prob * 100)
    aw = 100 - hw
    winner = p.get("winner", "")
    conf = p.get("confidence", 0)
    winner_name = home_name if winner == "home" else away_name

    away_sp = g.get("away_sp") or {}
    home_sp = g.get("home_sp") or {}
    away_pitcher = away_sp.get("name") or g.get("away_pitcher", "TBD")
    home_pitcher = home_sp.get("name") or g.get("home_pitcher", "TBD")
    away_era = f"ERA {away_sp['era']}" if away_sp.get("era") else ""
    home_era = f"ERA {home_sp['era']}" if home_sp.get("era") else ""

    # Odds panel
    of = p.get("factors", {}).get("odds", {})
    odds_html = ""
    if of and of.get("curr_home_odds"):
        h_odds = of.get("curr_home_odds", "?")
        a_odds = of.get("curr_away_odds", "?")
        mkt = of.get("market_home_prob", "?")
        analysis = of.get("analysis") or {}
        vg = analysis.get("value_gap", 0)
        vg_color = "#22c55e" if vg > 3 else "#ef4444" if vg < -3 else "#94a3b8"
        sigs = of.get("signals", [])
        sig_spans = "".join(f'<span class="sig">{s}</span>' for s in sigs[:3])
        odds_html = f"""
        <div class="odds-row">
          <span>賠率 客 <b>{a_odds}</b> / 主 <b>{h_odds}</b></span>
          <span>市場主隊 <b>{mkt}%</b></span>
          <span style="color:{vg_color}">差距 <b>{vg:+.0f}%</b></span>
          {sig_spans}
        </div>"""

    time_str = g.get("time", "")
    venue_str = g.get("venue", "")

    return f"""
<div class="card">
  <div class="card-meta">{time_str}{"&nbsp;·&nbsp;" + venue_str if venue_str else ""}</div>
  <div class="matchup">
    <div class="team">
      <div class="tname" style="color:{away_color}">{away_name}</div>
      <div class="pitcher">{away_pitcher} {away_era}</div>
      <div class="prob" style="color:{away_color}">{aw}%</div>
    </div>
    <div class="vs-col">
      <div class="vs">VS</div>
    </div>
    <div class="team right">
      <div class="tname" style="color:{home_color}">{home_name}</div>
      <div class="pitcher">{home_pitcher} {home_era}</div>
      <div class="prob" style="color:{home_color}">{hw}%</div>
    </div>
  </div>
  <div class="bar">
    <div style="width:{aw}%;background:{away_color}"></div>
    <div style="width:{hw}%;background:{home_color}"></div>
  </div>
  <div class="winner">🏆 預測 <strong>{winner_name}</strong> 獲勝（信心 {conf:.0f}%）</div>
  {odds_html}
</div>"""


def generate(date_str, games):
    cards = "\n".join(game_card(g) for g in games) if games else '<p class="empty">今日無賽事資料</p>'
    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CPBL 賽前預測 {date_str}</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0f172a;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}}
header{{background:#1e293b;border-bottom:2px solid #334155;padding:20px 24px;display:flex;align-items:center;gap:12px}}
header h1{{font-size:1.4rem;font-weight:800;color:#f8fafc;flex:1}}
header .badge{{background:#0ea5e9;color:#fff;font-size:.75rem;padding:4px 10px;border-radius:20px;font-weight:600}}
.sub{{font-size:.8rem;color:#64748b;padding:10px 24px;background:#1e293b;border-bottom:1px solid #1e293b}}
main{{max-width:980px;margin:0 auto;padding:24px 16px}}
h2{{font-size:.9rem;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-bottom:16px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(440px,1fr));gap:18px;margin-bottom:32px}}
.card{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px;transition:border-color .2s}}
.card:hover{{border-color:#475569}}
.card-meta{{font-size:.75rem;color:#475569;margin-bottom:10px}}
.matchup{{display:flex;align-items:center;gap:8px;margin-bottom:12px}}
.team{{flex:1}}
.team.right{{text-align:right}}
.tname{{font-size:1.05rem;font-weight:700}}
.pitcher{{font-size:.78rem;color:#94a3b8;margin-top:2px}}
.prob{{font-size:1.3rem;font-weight:800;margin-top:4px}}
.vs-col{{text-align:center;flex-shrink:0}}
.vs{{font-size:.7rem;color:#475569;font-weight:700;background:#0f172a;padding:6px 8px;border-radius:6px}}
.bar{{display:flex;height:22px;border-radius:11px;overflow:hidden;margin-bottom:10px}}
.bar div{{transition:width .3s}}
.winner{{font-size:.875rem;color:#cbd5e1;text-align:center;padding:7px 12px;background:#0f172a;border-radius:8px;margin-bottom:8px}}
.winner strong{{color:#fbbf24}}
.odds-row{{display:flex;flex-wrap:wrap;gap:6px;font-size:.75rem;color:#94a3b8;border-top:1px solid #334155;padding-top:9px}}
.odds-row span{{background:#0f172a;padding:3px 8px;border-radius:6px}}
.odds-row b{{color:#e2e8f0}}
.sig{{background:#1e3a5f!important;color:#60a5fa!important}}
.no-pred,.empty{{color:#475569;padding:20px;text-align:center}}
footer{{text-align:center;padding:28px;color:#334155;font-size:.78rem;border-top:1px solid #1e293b;margin-top:16px}}
@media(max-width:500px){{.grid{{grid-template-columns:1fr}}header h1{{font-size:1.1rem}}}}
</style>
</head>
<body>
<header>
  <h1>⚾ CPBL 中華職棒 賽前預測</h1>
  <span class="badge">📅 {date_str}</span>
</header>
<div class="sub">預測模型：先發投手 32% ／ 打線 18% ／ 牛棚 13% ／ 賠率 10% ／ 主客場 8% ／ 近況 7% ／ H2H 5% ／ 其他 7%</div>
<main>
  <h2>今日賽事預測</h2>
  <div class="grid">
    {cards}
  </div>
</main>
<footer>自動更新 每日 10:00（台灣時間）&nbsp;·&nbsp; 僅供參考，請理性投注 &nbsp;·&nbsp; 資料來源：cpbl.com.tw / The Odds API</footer>
</body>
</html>"""


if __name__ == "__main__":
    date_str, games = load_latest()
    if not date_str:
        date_str = str(_date.today())
    html = generate(date_str, games)
    out = Path("docs/index.html")
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"Generated {out}  ({len(html):,} bytes)  date={date_str}  games={len(games)}")
