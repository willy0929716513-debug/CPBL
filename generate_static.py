#!/usr/bin/env python3
"""Generate static GitHub Pages site from prediction JSONs."""
import json
import subprocess
from pathlib import Path
from datetime import date as _date

TEAM_NAMES = {
    "AEL": "中信兄弟", "CT": "統一7-ELEVEn獅",
    "FG": "富邦悍將",  "WL": "樂天桃猿", "TSG": "台鋼雄鷹",
}
TEAM_COLORS = {
    "AEL": "#3b82f6", "CT": "#f59e0b",
    "FG": "#ef4444",  "WL": "#8b5cf6", "TSG": "#14b8a6",
}

# ── helpers ────────────────────────────────────────────────────────────────

def get_repo_slug():
    """Parse owner/repo from git remote URL."""
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], text=True
        ).strip()
        for sep in ["/github.com/", ":github.com:", ":github.com/"]:
            if sep in url:
                slug = url.split(sep, 1)[1].removesuffix(".git")
                return slug
    except Exception:
        pass
    return "OWNER/REPO"

def get_gist_id():
    """Find the CPBL Predictions Archive gist ID from local cache file."""
    cache = Path("docs/.gist_id")
    if cache.exists():
        return cache.read_text().strip()
    return ""

def load_all_predictions():
    """Return sorted list of (date_str, games) tuples, newest first."""
    pred_dir = Path("predictions")
    if not pred_dir.exists():
        return []
    results = []
    for f in sorted(pred_dir.glob("*.json"), reverse=True):
        try:
            with open(f, encoding="utf-8") as fh:
                results.append((f.stem, json.load(fh)))
        except Exception:
            pass
    return results

# ── card rendering ─────────────────────────────────────────────────────────

def game_card(g):
    p = g.get("prediction") or {}
    away  = g.get("away", "")
    home  = g.get("home", "")
    aname = g.get("away_name") or TEAM_NAMES.get(away, away)
    hname = g.get("home_name") or TEAM_NAMES.get(home, home)
    ac    = TEAM_COLORS.get(away, "#6b7280")
    hc    = TEAM_COLORS.get(home, "#6b7280")

    if not p:
        return (f'<div class="card"><div class="no-pred">'
                f'{aname} vs {hname} — 無預測資料</div></div>')

    hp   = float(p.get("home_win_prob", 0.5))
    hw   = int(hp * 100)
    aw   = 100 - hw
    win  = p.get("winner", "")
    conf = p.get("confidence", 0)
    wn   = hname if win == "home" else aname

    asp = g.get("away_sp") or {}
    hsp = g.get("home_sp") or {}
    ap  = asp.get("name") or g.get("away_pitcher", "TBD")
    hpp = hsp.get("name") or g.get("home_pitcher", "TBD")
    ae  = f"ERA {asp['era']}" if asp.get("era") else ""
    he  = f"ERA {hsp['era']}" if hsp.get("era") else ""

    of        = p.get("factors", {}).get("odds", {})
    odds_html = ""
    if of and of.get("curr_home_odds"):
        h_odds = of.get("curr_home_odds", "?")
        a_odds = of.get("curr_away_odds", "?")
        mkt    = of.get("market_home_prob", "?")
        vg     = (of.get("analysis") or {}).get("value_gap", 0)
        vc     = "#22c55e" if vg > 3 else "#ef4444" if vg < -3 else "#94a3b8"
        sigs   = of.get("signals", [])
        sspan  = "".join(f'<span class="sig">{s}</span>' for s in sigs[:3])
        odds_html = f"""
        <div class="odds-row">
          <span>賠率 客 <b>{a_odds}</b> / 主 <b>{h_odds}</b></span>
          <span>市場主隊 <b>{mkt}%</b></span>
          <span style="color:{vc}">差距 <b>{vg:+.0f}%</b></span>
          {sspan}
        </div>"""

    venue = g.get("venue", "")
    time  = g.get("time", "")
    meta  = time + ("&nbsp;·&nbsp;" + venue if venue else "")

    return f"""
<div class="card">
  <div class="card-meta">{meta}</div>
  <div class="matchup">
    <div class="team">
      <div class="tname" style="color:{ac}">{aname}</div>
      <div class="pitcher">{ap} {ae}</div>
      <div class="prob" style="color:{ac}">{aw}%</div>
    </div>
    <div class="vs-col"><div class="vs">VS</div></div>
    <div class="team right">
      <div class="tname" style="color:{hc}">{hname}</div>
      <div class="pitcher">{hpp} {he}</div>
      <div class="prob" style="color:{hc}">{hw}%</div>
    </div>
  </div>
  <div class="bar">
    <div style="width:{aw}%;background:{ac}"></div>
    <div style="width:{hw}%;background:{hc}"></div>
  </div>
  <div class="winner">🏆 預測 <strong>{wn}</strong> 獲勝（信心 {conf:.0f}%）</div>
  {odds_html}
</div>"""

# ── HTML template ──────────────────────────────────────────────────────────

CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:#0f172a;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh}
a{color:inherit;text-decoration:none}
/* header */
header{background:#1e293b;border-bottom:2px solid #334155;padding:16px 24px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
header h1{font-size:1.35rem;font-weight:800;color:#f8fafc;flex:1;min-width:200px}
.hbtn{background:#0ea5e9;color:#fff;border:none;padding:8px 16px;border-radius:8px;font-size:.85rem;font-weight:600;cursor:pointer;transition:background .2s}
.hbtn:hover{background:#0284c7}
.hbtn.hist{background:#334155}
.hbtn.hist:hover{background:#475569}
/* sub bar */
.sub{font-size:.78rem;color:#64748b;padding:8px 24px;background:#1e293b;border-bottom:1px solid #0f172a}
/* layout */
.layout{display:flex;max-width:1200px;margin:0 auto;padding:24px 16px;gap:24px;align-items:flex-start}
/* main content */
.content{flex:1;min-width:0}
h2{font-size:.85rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.07em;margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px;margin-bottom:24px}
/* game card */
.card{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:18px;transition:border-color .2s}
.card:hover{border-color:#475569}
.card-meta{font-size:.72rem;color:#475569;margin-bottom:8px}
.matchup{display:flex;align-items:center;gap:8px;margin-bottom:10px}
.team{flex:1}.team.right{text-align:right}
.tname{font-size:1rem;font-weight:700}
.pitcher{font-size:.75rem;color:#94a3b8;margin-top:2px}
.prob{font-size:1.25rem;font-weight:800;margin-top:4px}
.vs-col{flex-shrink:0}
.vs{font-size:.65rem;color:#475569;font-weight:700;background:#0f172a;padding:6px 8px;border-radius:6px}
.bar{display:flex;height:20px;border-radius:10px;overflow:hidden;margin-bottom:10px}
.bar div{transition:width .3s}
.winner{font-size:.85rem;color:#cbd5e1;text-align:center;padding:7px 12px;background:#0f172a;border-radius:8px;margin-bottom:8px}
.winner strong{color:#fbbf24}
.odds-row{display:flex;flex-wrap:wrap;gap:5px;font-size:.72rem;color:#94a3b8;border-top:1px solid #334155;padding-top:8px}
.odds-row span{background:#0f172a;padding:3px 8px;border-radius:6px}
.odds-row b{color:#e2e8f0}
.sig{background:#1e3a5f!important;color:#60a5fa!important}
.no-pred{color:#475569;padding:16px;text-align:center}
/* sidebar */
.sidebar{width:240px;flex-shrink:0}
.scard{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px;margin-bottom:16px}
.scard h3{font-size:.8rem;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px}
.date-list{list-style:none}
.date-list li{margin-bottom:4px}
.date-list a{display:flex;justify-content:space-between;align-items:center;padding:7px 10px;border-radius:7px;font-size:.82rem;color:#cbd5e1;background:#0f172a;transition:background .15s}
.date-list a:hover,.date-list a.active{background:#1e40af;color:#fff}
.date-list .cnt{font-size:.7rem;color:#64748b}
.date-list a.active .cnt{color:#93c5fd}
/* trigger modal */
.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;align-items:center;justify-content:center}
.overlay.open{display:flex}
.modal{background:#1e293b;border:1px solid #334155;border-radius:14px;padding:28px;width:420px;max-width:95vw}
.modal h3{font-size:1.1rem;font-weight:700;color:#f8fafc;margin-bottom:8px}
.modal p{font-size:.83rem;color:#94a3b8;margin-bottom:16px;line-height:1.5}
.modal input{width:100%;background:#0f172a;border:1px solid #334155;border-radius:8px;padding:10px 12px;color:#e2e8f0;font-size:.9rem;margin-bottom:12px;outline:none}
.modal input:focus{border-color:#0ea5e9}
.modal-btns{display:flex;gap:8px;justify-content:flex-end}
.modal-btns button{padding:8px 18px;border-radius:8px;border:none;font-size:.85rem;font-weight:600;cursor:pointer}
.btn-cancel{background:#334155;color:#e2e8f0}.btn-cancel:hover{background:#475569}
.btn-ok{background:#0ea5e9;color:#fff}.btn-ok:hover{background:#0284c7}
#trigger-status{font-size:.82rem;margin-top:10px;min-height:20px;text-align:center}
/* empty / footer */
.empty{color:#475569;padding:40px;text-align:center;font-size:1rem}
footer{text-align:center;padding:24px;color:#334155;font-size:.75rem;border-top:1px solid #1e293b;margin-top:8px}
@media(max-width:680px){.layout{flex-direction:column}.sidebar{width:100%}.grid{grid-template-columns:1fr}}
"""

TRIGGER_JS = """
const REPO = '{repo}';
const WF   = 'cpbl_daily.yml';

function openTrigger() {{
  document.getElementById('modal-overlay').classList.add('open');
  const saved = localStorage.getItem('gh_pat') || '';
  document.getElementById('pat-input').value = saved;
  document.getElementById('trigger-status').textContent = '';
}}
function closeTrigger() {{
  document.getElementById('modal-overlay').classList.remove('open');
}}
async function doTrigger() {{
  const token = document.getElementById('pat-input').value.trim();
  if (!token) {{ alert('請輸入 Personal Access Token'); return; }}
  localStorage.setItem('gh_pat', token);
  const btn = document.getElementById('btn-trigger-ok');
  btn.disabled = true;
  btn.textContent = '觸發中…';
  const el = document.getElementById('trigger-status');
  try {{
    const res = await fetch(
      `https://api.github.com/repos/${{REPO}}/actions/workflows/${{WF}}/dispatches`,
      {{
        method: 'POST',
        headers: {{
          'Authorization': `Bearer ${{token}}`,
          'Accept': 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'Content-Type': 'application/json',
        }},
        body: JSON.stringify({{ ref: 'main' }}),
      }}
    );
    if (res.status === 204) {{
      el.style.color = '#22c55e';
      el.textContent = '✅ 已成功觸發！預測約需 2 分鐘完成，之後重新整理頁面。';
      setTimeout(closeTrigger, 3000);
    }} else {{
      const j = await res.json().catch(() => ({{}}));
      el.style.color = '#ef4444';
      el.textContent = '❌ 失敗：' + (j.message || res.status);
    }}
  }} catch(e) {{
    el.style.color = '#ef4444';
    el.textContent = '❌ 網路錯誤：' + e.message;
  }}
  btn.disabled = false;
  btn.textContent = '確認觸發';
}}
document.getElementById('modal-overlay').addEventListener('click', function(e) {{
  if (e.target === this) closeTrigger();
}});
"""

def build_page(date_str, games, all_dates, repo, is_latest=False, gist_id=""):
    """Render a full HTML page for one date."""
    cards = "\n".join(game_card(g) for g in games) if games else '<p class="empty">今日無賽事資料</p>'
    today_label = " （最新）" if is_latest else ""

    # Sidebar date list
    date_items = []
    for ds, gs in all_dates:
        active = "active" if ds == date_str else ""
        link   = "index.html" if is_latest and ds == date_str else f"{ds}.html"
        if ds != date_str and is_latest:
            link = f"{ds}.html"
        elif ds == date_str:
            link = "#"
        cnt = len(gs)
        date_items.append(
            f'<li><a href="{link}" class="{active}">'
            f'{ds}{today_label if ds == date_str else ""}'
            f'<span class="cnt">{cnt} 場</span></a></li>'
        )
    sidebar_dates = "\n".join(date_items[:30])  # show up to 30

    return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CPBL 預測 {date_str}</title>
<style>{CSS}</style>
</head>
<body>

<header>
  <h1>⚾ CPBL 中華職棒 賽前預測</h1>
  <button class="hbtn hist" onclick="location.href='index.html'">最新預測</button>
  {f'<a class="hbtn hist" href="https://gist.github.com/{gist_id}" target="_blank">📋 Gist 歷史庫</a>' if gist_id else ''}
  <button class="hbtn" onclick="openTrigger()">▶ 立即觸發預測</button>
</header>
<div class="sub">
  預測模型：先發投手 32% ／ 打線 18% ／ 牛棚 13% ／ 賠率 10% ／ 主客場 8% ／ 近況 7% ／ H2H 5% ／ 其他 7%
</div>

<div class="layout">
  <div class="content">
    <h2>📅 {date_str}{today_label} · {len(games)} 場賽事</h2>
    <div class="grid">
      {cards}
    </div>
  </div>

  <aside class="sidebar">
    <div class="scard">
      <h3>歷史紀錄</h3>
      <ul class="date-list">
        {sidebar_dates}
      </ul>
    </div>
  </aside>
</div>

<footer>自動更新 每日 10:00（台灣時間）&nbsp;·&nbsp; 僅供參考，請理性投注 &nbsp;·&nbsp; 資料來源：cpbl.com.tw / The Odds API</footer>

<!-- Trigger Modal -->
<div id="modal-overlay" class="overlay">
  <div class="modal">
    <h3>▶ 立即觸發預測</h3>
    <p>需要 GitHub Personal Access Token（細粒度，只需 <b>Actions: Write</b> 權限）。<br>Token 只存在你的瀏覽器 localStorage，不會上傳。</p>
    <input id="pat-input" type="password" placeholder="ghp_xxxxxxxxxxxx 或 github_pat_xxx">
    <div id="trigger-status"></div>
    <div class="modal-btns">
      <button class="btn-cancel" onclick="closeTrigger()">取消</button>
      <button class="btn-ok" id="btn-trigger-ok" onclick="doTrigger()">確認觸發</button>
    </div>
  </div>
</div>

<script>
{TRIGGER_JS.format(repo=repo)}
</script>
</body>
</html>"""


# ── main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    repo      = get_repo_slug()
    gist_id   = get_gist_id()
    all_dates = load_all_predictions()  # [(date_str, games), ...]
    out_dir   = Path("docs")
    out_dir.mkdir(exist_ok=True)

    # If GIST_ID env var is provided (from workflow), cache it for future static builds
    env_gist = os.environ.get("GIST_ID", "")
    if env_gist and env_gist != gist_id:
        (out_dir / ".gist_id").write_text(env_gist)
        gist_id = env_gist
        print(f"Cached Gist ID: {gist_id}")

    if not all_dates:
        date_str = str(_date.today())
        html = build_page(date_str, [], [(date_str, [])], repo, is_latest=True, gist_id=gist_id)
        (out_dir / "index.html").write_text(html, encoding="utf-8")
        print(f"Generated docs/index.html (placeholder, no predictions yet)")
    else:
        for i, (date_str, games) in enumerate(all_dates):
            is_latest = (i == 0)
            html = build_page(date_str, games, all_dates, repo, is_latest=is_latest, gist_id=gist_id)
            fname = "index.html" if is_latest else f"{date_str}.html"
            (out_dir / fname).write_text(html, encoding="utf-8")
            print(f"Generated docs/{fname}  ({len(games)} games)")

        print(f"Total: {len(all_dates)} pages, repo={repo}, gist={gist_id or 'none'}")
