"""
CPBL 賠率模組
─ 台灣運彩爬蟲
─ Mock 賠率資料 (Demo / fallback)
─ 盤口分析函式
"""
import re
import requests
from bs4 import BeautifulSoup
from typing import Optional

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Referer": "https://www.sportslottery.com.tw/",
}

# 台灣運彩 CPBL 頁面
_SL_URL = "https://www.sportslottery.com.tw/sport/baseball/cpbl"
_SL_API = "https://api2.sportslottery.com.tw/sport/events?sport=baseball&league=cpbl"

# ──────────────────────────────────────────────
# Mock 資料  (game_key = "AWAY_CODE-HOME_CODE")
# ──────────────────────────────────────────────
MOCK_ODDS: dict[str, dict] = {
    "FG-WL": {
        # 勝負賠率 (decimal)
        "open_away_odds":    2.30,   # 開盤客隊
        "open_home_odds":    1.65,   # 開盤主隊
        "curr_away_odds":    2.45,   # 即時客隊
        "curr_home_odds":    1.58,   # 即時主隊
        # 讓分 (run line)  負數 = 主隊讓分
        "run_line":         -1.5,
        "rl_home_odds":      1.82,
        "rl_away_odds":      2.00,
        # 大小分 (over/under)
        "total":             8.5,
        "over_odds":         1.85,
        "under_odds":        1.95,
        # 公眾投注比例 (%)
        "public_home_pct":   62,
        "public_away_pct":   38,
        # 抽水率估計 (%)
        "vig_pct":           7.5,
        "note": "主隊賠率從 1.65 縮至 1.58 → 莊家更看好主隊；主隊讓 1.5 分仍受青睞",
    },
    "TSG-AEL": {
        "open_away_odds":    2.20,
        "open_home_odds":    1.72,
        "curr_away_odds":    2.15,
        "curr_home_odds":    1.72,
        "run_line":         -1.0,
        "rl_home_odds":      1.88,
        "rl_away_odds":      1.92,
        "total":             7.5,
        "over_odds":         1.90,
        "under_odds":        1.90,
        "public_home_pct":   55,
        "public_away_pct":   45,
        "vig_pct":           7.5,
        "note": "盤口穩定；客隊賠率微縮（2.20→2.15）有部分資金流入客隊",
    },
}


# ──────────────────────────────────────────────
# 爬蟲
# ──────────────────────────────────────────────

class OddsScraper:
    def __init__(self):
        self._s = requests.Session()
        self._s.headers.update(_HEADERS)

    def fetch(self, away_code: str, home_code: str) -> Optional[dict]:
        """先試 JSON API，再試 HTML，失敗回 None"""
        key = f"{away_code}-{home_code}"
        try:
            result = self._try_api(away_code, home_code)
            if result:
                return result
        except Exception:
            pass
        try:
            result = self._try_html(away_code, home_code)
            if result:
                return result
        except Exception:
            pass
        return None

    def _try_api(self, away: str, home: str) -> Optional[dict]:
        resp = self._s.get(_SL_API, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        for event in data.get("events", []):
            teams = event.get("teams", [])
            names = [t.get("name", "") for t in teams]
            if _team_match(away, names) and _team_match(home, names):
                return _parse_api_event(event, away, home)
        return None

    def _try_html(self, away: str, home: str) -> Optional[dict]:
        resp = self._s.get(_SL_URL, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        return _parse_html_odds(soup, away, home)


def _team_match(code: str, names: list[str]) -> bool:
    from .mock_data import TEAM_INFO
    team_name = TEAM_INFO.get(code, {}).get("name", "")
    short     = TEAM_INFO.get(code, {}).get("short", "")
    return any(team_name in n or short in n for n in names)


def _parse_api_event(event: dict, away: str, home: str) -> Optional[dict]:
    """將運彩 API 格式標準化"""
    odds_list = event.get("odds", [])
    result: dict = {"note": "來自台灣運彩 API"}
    for o in odds_list:
        kind = o.get("kind", "")
        if kind == "win":
            away_odds, home_odds = _extract_win_odds(o, away, home)
            result.update({
                "curr_away_odds": away_odds,
                "curr_home_odds": home_odds,
                "open_away_odds": o.get("openAwayOdds", away_odds),
                "open_home_odds": o.get("openHomeOdds", home_odds),
            })
        elif kind == "runline":
            result["run_line"]     = float(o.get("line", -1.5))
            result["rl_home_odds"] = float(o.get("homeOdds", 1.90))
            result["rl_away_odds"] = float(o.get("awayOdds", 1.90))
        elif kind == "total":
            result["total"]       = float(o.get("line", 8.5))
            result["over_odds"]   = float(o.get("overOdds", 1.90))
            result["under_odds"]  = float(o.get("underOdds", 1.90))
    result.setdefault("public_home_pct", 50)
    result.setdefault("public_away_pct", 50)
    result.setdefault("vig_pct", 7.5)
    return result if "curr_home_odds" in result else None


def _extract_win_odds(o: dict, away: str, home: str):
    return (
        float(o.get("awayOdds", 1.90)),
        float(o.get("homeOdds", 1.90)),
    )


def _parse_html_odds(soup: BeautifulSoup, away: str, home: str) -> Optional[dict]:
    """備用 HTML 解析（依運彩實際 DOM 調整）"""
    from .mock_data import TEAM_INFO
    home_name = TEAM_INFO.get(home, {}).get("short", "")
    away_name = TEAM_INFO.get(away, {}).get("short", "")

    rows = soup.select(".game-row, .match-item, tr")
    for row in rows:
        text = row.get_text()
        if home_name in text and away_name in text:
            odds_els = row.select(".odds, .odd-value, td.odds")
            vals = []
            for el in odds_els:
                try:
                    vals.append(float(el.get_text(strip=True)))
                except ValueError:
                    pass
            if len(vals) >= 2:
                return {
                    "curr_away_odds": vals[0],
                    "curr_home_odds": vals[1],
                    "open_away_odds": vals[0],
                    "open_home_odds": vals[1],
                    "run_line":       -1.5,
                    "rl_home_odds":    1.90,
                    "rl_away_odds":    1.90,
                    "total":           8.5,
                    "over_odds":       1.90,
                    "under_odds":      1.90,
                    "public_home_pct": 50,
                    "public_away_pct": 50,
                    "vig_pct":         7.5,
                    "note":            "來自台灣運彩網頁",
                }
    return None


# ──────────────────────────────────────────────
# 盤口分析
# ──────────────────────────────────────────────

def analyze(odds: dict, model_home_prob: float) -> dict:
    """
    輸入賠率資料 + 模型主隊勝率
    回傳盤口分析結果，包含 advantage (-50~+50)
    """
    h  = float(odds.get("curr_home_odds", 1.90))
    a  = float(odds.get("curr_away_odds", 1.90))
    oh = float(odds.get("open_home_odds", h))
    oa = float(odds.get("open_away_odds", a))
    pub_h = float(odds.get("public_home_pct", 50)) / 100.0

    # ── 市場隱含勝率 (去除抽水) ─────────────
    raw_h = 1.0 / h
    raw_a = 1.0 / a
    market_prob = raw_h / (raw_h + raw_a)   # 主隊市場隱含勝率

    # ── 模型 vs 市場差距 ─────────────────────
    # 正 = 模型比市場更看好主隊 (value bet on home)
    value_gap = model_home_prob - market_prob

    # ── 盤口移動方向 ─────────────────────────
    # 主隊賠率縮短 = 莊家更看好主隊 → 正分
    h_move = oh - h      # 正 = 縮短 (bullish home)
    a_move = oa - a      # 正 = 縮短 (bullish away)

    # ── 逆向盤口偵測 ─────────────────────────
    # 公眾押主隊 but 主隊賠率拉長 = 莊家與公眾反向 → 看衰主隊
    rlm_against_home = (pub_h > 0.55 and h_move < -0.03)
    # 公眾押客隊 but 客隊賠率拉長 = 莊家反向 → 看好主隊
    rlm_for_home     = (pub_h < 0.45 and a_move < -0.03)

    # ── 讓分解讀 ─────────────────────────────
    run_line = float(odds.get("run_line", -1.5))
    # 讓分越大 = 主隊越被看好
    rl_signal = max(-1.0, min(1.0, -run_line / 3.0))  # -1~+1

    # ── 加總優勢分 ───────────────────────────
    adv = 0.0
    adv += value_gap * 100.0    # 最重要：模型比市場看好主隊多少
    adv += h_move * 20.0        # 盤口移動貢獻
    adv += rl_signal * 15.0     # 讓分大小
    if rlm_for_home:
        adv += 12.0             # 逆向盤口看好主隊
    elif rlm_against_home:
        adv -= 12.0             # 逆向盤口看衰主隊

    adv = max(-50.0, min(50.0, adv))

    # ── 文字描述 ─────────────────────────────
    signals = []
    if abs(value_gap) > 0.08:
        if value_gap > 0:
            signals.append(f"📈 模型比市場高估主隊 {value_gap*100:.0f}% (Value)")
        else:
            signals.append(f"📉 市場比模型更看好主隊 {abs(value_gap)*100:.0f}%")
    if abs(h_move) > 0.03:
        if h_move > 0:
            signals.append(f"📉 主隊賠率縮短 {oh}→{h} (莊家看好主隊)")
        else:
            signals.append(f"📈 主隊賠率拉長 {oh}→{h} (莊家看衰主隊)")
    if rlm_for_home:
        signals.append("⚡ 逆向盤口：資金流入主隊")
    elif rlm_against_home:
        signals.append("⚡ 逆向盤口：資金流入客隊")

    return {
        "market_home_prob": round(market_prob * 100, 1),
        "value_gap":        round(value_gap * 100, 1),
        "h_movement":       round(h_move, 2),
        "a_movement":       round(a_move, 2),
        "rlm_for_home":     rlm_for_home,
        "rlm_against_home": rlm_against_home,
        "signals":          signals,
        "advantage":        round(adv, 1),
        "detail": (
            f"主隊賠率 {h} (開 {oh}) | 客隊賠率 {a} (開 {oa}) | "
            f"讓分 {run_line:+.1f} | "
            f"大小 {odds.get('total','-')} | "
            f"公眾 主{int(pub_h*100)}% / 客{100-int(pub_h*100)}% | "
            + (odds.get("note", ""))
        ),
    }
