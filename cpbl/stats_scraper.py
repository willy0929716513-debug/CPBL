"""
V8 Stats Scraper — 多來源投手數據抓取器 (NPB / KBO)

優先順序：
  1. ESPN 非官方 API （免費、JSON、不需金鑰、不擋 GH Actions）
     NPB: /baseball/jlb/  KBO: /baseball/kor/
  2. 從已抓到的 K/BB/HR/IP 自動計算 FIP / K% / BB%

FIP 公式：FIP = (13×HR + 3×(BB+HBP) - 2×K) / IP + FIP_C
  NPB FIP_C ≈ 3.20  KBO FIP_C ≈ 3.60
"""
import os
import re
import math
import logging
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timezone, timedelta
from typing import Optional

log = logging.getLogger(__name__)

BASE_ESPN_NPB      = "https://site.api.espn.com/apis/site/v2/sports/baseball/jlb"
BASE_ESPN_KBO      = "https://site.api.espn.com/apis/site/v2/sports/baseball/kor"
BASE_ESPN_WEB_NPB  = "https://site.web.api.espn.com/apis/site/v2/sports/baseball/jlb"
BASE_ESPN_WEB_KBO  = "https://site.web.api.espn.com/apis/site/v2/sports/baseball/kor"

_FIP_CONSTANT_NPB = 3.20
_FIP_CONSTANT_KBO = 3.60
_FIP_CONSTANT     = 3.35  # blended default
_LG_IP_PER_GS     = 5.8   # 日韓聯盟平均先發局數

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "ja,ko,en-US;q=0.8",
}

# ESPN / Odds API 球隊顯示名稱 → 內部代碼
_ESPN_TEAM_MAP = {
    # NPB — 完整名稱（Odds API 帶城市前綴）
    "Yomiuri Giants":                "GNT", "Giants":                "GNT",
    "Hanshin Tigers":                "HNS", "Tigers":                "HNS",
    "Hiroshima Toyo Carp":           "HRC", "Hiroshima Carp":        "HRC", "Carp": "HRC",
    "Yokohama DeNA BayStars":        "YDB", "DeNA BayStars":         "YDB", "BayStars": "YDB",
    "Tokyo Yakult Swallows":         "YKL", "Yakult Swallows":       "YKL", "Swallows": "YKL",
    "Chunichi Dragons":              "CND", "Dragons":               "CND",
    "Fukuoka SoftBank Hawks":        "SBH", "SoftBank Hawks":        "SBH", "Hawks": "SBH",
    "Orix Buffaloes":                "ORX", "Buffaloes":             "ORX",
    "Tohoku Rakuten Golden Eagles":  "RKT", "Rakuten Eagles":        "RKT", "Eagles": "RKT",
    "Chiba Lotte Marines":           "LTT", "Lotte Marines":         "LTT", "Marines": "LTT",
    "Saitama Seibu Lions":           "SEI", "Seibu Lions":           "SEI", "Lions": "SEI",
    "Hokkaido Nippon-Ham Fighters":  "HAM", "Nippon-Ham Fighters":   "HAM", "Fighters": "HAM",
    # KBO
    "Samsung Lions":    "SSL",
    "LG Twins":         "LGT",
    "Doosan Bears":     "DSB",
    "KT Wiz":           "KTW",
    "SSG Landers":      "SSG",
    "NC Dinos":         "NCD",
    "KIA Tigers":       "KIA",
    "Lotte Giants":     "LTG",
    "Hanwha Eagles":    "HWE",
    "Kiwoom Heroes":    "KWH",
}


# ─────────────────────────────────────────────────────────────
# 衍生指標計算
# ─────────────────────────────────────────────────────────────

def calc_fip(hr: float, bb: float, k: float, ip: float,
             hbp: float = 0.0, constant: float = _FIP_CONSTANT) -> Optional[float]:
    """FIP = (13×HR + 3×(BB+HBP) - 2×K) / IP + constant"""
    if ip <= 0:
        return None
    return round((13 * hr + 3 * (bb + hbp) - 2 * k) / ip + constant, 2)


def calc_k_pct(k9: float, bb9: float, ip: float = 0) -> tuple[float, float]:
    """
    從 K/9 和 BB/9 估算 K% 和 BB%。
    公式：K% ≈ K9 / (K9 + BB9 + (27 / IP_per_PA_factor))
    簡化版：K% = K9 / (K9 + 18)  BB% = BB9 / (BB9 + 18)
    （CPBL 平均每 9 局約 27 個打席 → 1K9 ≈ 1/27 ≈ 3.7%）
    """
    k_pct  = round(k9 / (k9 + 18) * 100, 1) if k9 > 0 else 0.0
    bb_pct = round(bb9 / (bb9 + 18) * 100, 1) if bb9 > 0 else 0.0
    return k_pct, bb_pct


def calc_xfip(k: float, bb: float, fb: float, ip: float,
              lg_hr_fb: float = 0.115) -> Optional[float]:
    """
    xFIP = (13×(FB×lgHR/FB) + 3×BB - 2×K) / IP + FIP_C
    lgHR/FB ≈ 0.115 for CPBL
    """
    if ip <= 0 or fb < 0:
        return None
    exp_hr = fb * lg_hr_fb
    return round((13 * exp_hr + 3 * bb - 2 * k) / ip + _FIP_CONSTANT, 2)


def enrich_pitcher(p: dict) -> dict:
    """
    從已有欄位推算缺少的進階指標。
    原地修改並回傳 dict。
    """
    ip  = float(p.get("innings",   p.get("ip", 0)))
    k9  = float(p.get("k9",   0))
    bb9 = float(p.get("bb9",  0))
    era = float(p.get("era",  4.0))

    # K/9 → 全季三振次數 估算
    k_total  = round(k9  * ip / 9, 1) if ip > 0 else 0
    bb_total = round(bb9 * ip / 9, 1) if ip > 0 else 0

    # K% / BB% 估算（若沒有直接值）
    if "k_pct" not in p:
        k_pct, bb_pct = calc_k_pct(k9, bb9, ip)
        p["k_pct"]  = k_pct
        p["bb_pct"] = bb_pct

    # FIP（若有 HR 資料）
    if "fip" not in p:
        hr9  = float(p.get("hr9", p.get("hr_per9", 1.0)))
        hr   = round(hr9 * ip / 9, 1) if ip > 0 else 0
        fip  = calc_fip(hr, bb_total, k_total, ip)
        if fip is not None:
            p["fip"] = fip
            p.setdefault("xfip", round(fip * 0.97, 2))  # xFIP ≈ FIP × 0.97（簡化）

    # BABIP 推算（若沒有）
    if "babip" not in p:
        # 統計關係：BABIP ≈ 0.300 + (ERA - FIP) × 0.04
        fip = p.get("fip", era)
        p["babip"] = round(max(0.200, min(0.380, 0.300 + (era - fip) * 0.04)), 3)

    # LOB% 推算（若沒有）
    if "lob_pct" not in p:
        # LOB% 與 ERA/FIP 差值有關，高 ERA vs FIP → 低 LOB%
        p["lob_pct"] = round(max(55.0, min(85.0, 72.0 + (p.get("fip", era) - era) * 4.0)), 1)

    # K-BB%（若沒有）
    if "k_bb_pct" not in p:
        p["k_bb_pct"] = round(p.get("k_pct", 0) - p.get("bb_pct", 0), 1)

    return p


# ─────────────────────────────────────────────────────────────
# ESPN 非官方 API
# ─────────────────────────────────────────────────────────────

def fetch_espn_schedule(game_date: date) -> list[dict]:
    """
    從 ESPN API 取得 NPB + KBO 賽程。
    不需 API key，通常不被 WAF 封鎖。
    """
    date_str = game_date.strftime("%Y%m%d")
    games: list[dict] = []
    for league, base_url in [("NPB", BASE_ESPN_NPB), ("KBO", BASE_ESPN_KBO)]:
        url = f"{base_url}/scoreboard?dates={date_str}"
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            resp.raise_for_status()
            data   = resp.json()
            events = data.get("events", [])
            log.info("ESPN [%s]: %d events on %s", league, len(events), game_date)
            games.extend(_parse_espn_events(events, str(game_date), league))
        except Exception as e:
            log.warning("ESPN [%s] schedule fetch failed: %s", league, e)
    return games


def _parse_espn_events(events: list, date_str: str, league: str = "NPB") -> list[dict]:
    games = []
    for ev in events:
        try:
            comps = ev.get("competitions", [{}])[0]
            competitors = comps.get("competitors", [])
            if len(competitors) < 2:
                continue

            # ESPN 通常以 homeAway 欄位區分
            home_c = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
            away_c = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

            home_name = home_c.get("team", {}).get("displayName", "")
            away_name = away_c.get("team", {}).get("displayName", "")

            home_code = _ESPN_TEAM_MAP.get(home_name, home_name[:3].upper())
            away_code = _ESPN_TEAM_MAP.get(away_name, away_name[:3].upper())

            # 比賽時間
            status    = ev.get("status", {}).get("type", {})
            state     = status.get("state", "pre")   # pre / in / post
            game_time = ""
            venue     = comps.get("venue", {}).get("fullName", "")

            if state == "pre":
                start_raw = ev.get("date", "")
                # 轉換為台灣時間 HH:MM
                import datetime
                try:
                    dt_utc = datetime.datetime.strptime(start_raw[:19], "%Y-%m-%dT%H:%M:%S")
                    dt_tw  = dt_utc + datetime.timedelta(hours=8)
                    game_time = dt_tw.strftime("%H:%M")
                except Exception:
                    game_time = ""

            home_score = None
            away_score = None
            if state == "post":
                try:
                    home_score = int(home_c.get("score", "0"))
                    away_score = int(away_c.get("score", "0"))
                except (ValueError, TypeError):
                    pass

            # 先發投手（ESPN 有時會提供）
            away_pitcher = _espn_starter(away_c)
            home_pitcher = _espn_starter(home_c)

            games.append({
                "game_id":      f"{date_str}-{away_code}-{home_code}",
                "date":         date_str,
                "time":         game_time,
                "away":         away_code,
                "away_name":    away_name,
                "home":         home_code,
                "home_name":    home_name,
                "venue":        venue,
                "league":       league,
                "status":       "結束" if state == "post" else "預定",
                "away_score":   away_score,
                "home_score":   home_score,
                "away_pitcher": away_pitcher,
                "home_pitcher": home_pitcher,
                "_source":      "espn",
            })
        except Exception as e:
            log.debug("ESPN event parse error: %s", e)
            continue

    return games


def _espn_starter(competitor: dict) -> str:
    """嘗試從 ESPN competitor 物件取得先發投手姓名。"""
    # ESPN 不一定有投手資料，通常在 probables 或 statistics 裡
    for athlete in competitor.get("probables", []):
        name = athlete.get("athlete", {}).get("displayName", "")
        if name:
            return name
    return ""


def fetch_espn_pitcher_stats(year: int) -> dict[str, dict]:
    """
    從 ESPN API 嘗試取得 NPB + KBO 投手成績。
    """
    stats: dict[str, dict] = {}
    for league, base_url in [("NPB", BASE_ESPN_NPB), ("KBO", BASE_ESPN_KBO)]:
        url = f"{base_url}/leaders?year={year}&season=2&limit=50"
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            result = _parse_espn_leaders(data)
            stats.update(result)
            log.info("ESPN [%s] pitcher stats: %d players", league, len(result))
        except Exception as e:
            log.warning("ESPN [%s] pitcher stats failed: %s", league, e)
    return stats


def _parse_espn_leaders(data: dict) -> dict[str, dict]:
    stats = {}
    for category in data.get("leaders", []):
        stat_name = category.get("name", "")
        for entry in category.get("leaders", []):
            athlete = entry.get("athlete", {})
            name    = athlete.get("displayName", "")
            value   = entry.get("value", 0)
            if not name:
                continue
            if name not in stats:
                stats[name] = {}
            # 對應到我們的欄位
            stat_map = {
                "ERA":  "era",
                "WHIP": "whip",
                "SO":   "_k_total",
                "BB":   "_bb_total",
                "IP":   "innings",
                "HR":   "_hr_total",
            }
            key = stat_map.get(stat_name)
            if key:
                stats[name][key] = float(value)
    # 後處理：計算衍生指標
    for name, p in stats.items():
        ip = p.get("innings", 0)
        if ip > 0:
            k  = p.pop("_k_total",  0)
            bb = p.pop("_bb_total", 0)
            hr = p.pop("_hr_total", 0)
            p["k9"]  = round(k  / ip * 9, 2)
            p["bb9"] = round(bb / ip * 9, 2)
            p["fip"] = calc_fip(hr, bb, k, ip) or p.get("era", 4.0)
        enrich_pitcher(p)
    return stats


# ─────────────────────────────────────────────────────────────
# CPBL 官網（多 URL 嘗試）
# ─────────────────────────────────────────────────────────────

# CPBL 統計頁可能的 URL 格式（逐一嘗試）
_CPBL_STATS_URLS = [
    "{base}/stats/player?kind=P&year={year}&kindType=SP",
    "{base}/stats/player?kind=P&year={year}&kindType=1",
    "{base}/stats/player?kind=P&year={year}&type=0",
    "{base}/stats/toplist?type=0&kind=P&year={year}",
    "{base}/stats/record?type=0&kindType=SP&year={year}",
]


def fetch_cpbl_pitcher_stats(year: int) -> dict[str, dict]:
    """
    嘗試多種 CPBL 官網 URL 格式抓取投手成績。
    成功時回傳含 k9/bb9/era/whip/fip 的 dict。
    """
    session = requests.Session()
    session.headers.update(_HEADERS)

    for url_tmpl in _CPBL_STATS_URLS:
        url = url_tmpl.format(base=BASE_CPBL, year=year)
        try:
            resp = session.get(url, timeout=12, allow_redirects=True)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            stats = _parse_cpbl_stats_html(resp.text)
            if stats:
                log.info("CPBL stats: %d players from %s", len(stats), url)
                return stats
        except Exception as e:
            log.debug("CPBL stats URL %s failed: %s", url, e)
            continue

    log.warning("CPBL stats: all URL patterns failed")
    return {}


def _parse_cpbl_stats_html(html: str) -> dict[str, dict]:
    """解析 CPBL 統計表格 HTML。"""
    soup  = BeautifulSoup(html, "html.parser")
    stats: dict[str, dict] = {}

    col_aliases = {
        "姓名": "name", "球員": "name", "Name": "name",
        "ERA":  "era",  "防禦率": "era",
        "WHIP": "whip",
        "K/9":  "k9",   "SO/9": "k9",  "三振/9": "k9",
        "BB/9": "bb9",  "四壞/9": "bb9",
        "HR/9": "hr9",
        "IP":   "innings", "局數": "innings", "投球局數": "innings",
        "K":    "_k_total",  "SO":  "_k_total",  "三振": "_k_total",
        "BB":   "_bb_total", "四壞": "_bb_total",
        "HR":   "_hr_total", "全壘打": "_hr_total",
        "HBP":  "_hbp",      "觸身": "_hbp",
        "GS":   "gs",        "先發": "gs",
        "W":    "wins",      "勝": "wins",
        "L":    "losses",    "敗": "losses",
    }

    for table in soup.find_all("table"):
        thead = table.find("thead")
        header_row = thead.find("tr") if thead else table.find("tr")
        if not header_row:
            continue
        raw_headers = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
        headers = [col_aliases.get(h, h.lower()) for h in raw_headers]

        if "name" not in headers or "era" not in headers:
            continue

        for row in table.select("tbody tr, tr")[1:]:
            cols = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cols:
                continue
            try:
                name = cols[headers.index("name")].strip()
            except (ValueError, IndexError):
                continue
            if not name or name in ("合計", "Total", "平均", ""):
                continue

            p: dict = {}
            for field in ("era", "whip", "k9", "bb9", "hr9", "innings",
                          "_k_total", "_bb_total", "_hr_total", "_hbp",
                          "gs", "wins", "losses"):
                if field not in headers:
                    continue
                raw = cols[headers.index(field)]
                raw = raw.replace("⅓", ".33").replace("⅔", ".67")
                try:
                    p[field] = float(raw)
                except (ValueError, TypeError):
                    pass

            if not p.get("era"):
                continue

            # 從累計計算 K9/BB9（若沒有直接提供）
            ip = p.pop("innings", 0)
            if ip > 0:
                p["innings"] = ip
                k  = p.pop("_k_total",  0)
                bb = p.pop("_bb_total", 0)
                hr = p.pop("_hr_total", 0)
                hbp = p.pop("_hbp", 0)
                if k  > 0 and "k9"  not in p: p["k9"]  = round(k  / ip * 9, 2)
                if bb > 0 and "bb9" not in p: p["bb9"] = round(bb / ip * 9, 2)
                if hr > 0:
                    p["_hr"]  = hr
                    p["_bb"]  = bb
                    p["_k"]   = k
                    p["_hbp"] = hbp

            enrich_pitcher(p)
            stats[name] = p

    return stats


# ─────────────────────────────────────────────────────────────
# 主要入口（合併多來源）
# ─────────────────────────────────────────────────────────────

def fetch_all_pitcher_stats(year: int) -> dict[str, dict]:
    """
    多來源取投手成績，回傳合併後的最完整資料。
    順序：ESPN NPB → ESPN KBO
    """
    stats: dict[str, dict] = {}

    espn = fetch_espn_pitcher_stats(year)
    stats.update(espn)

    # 對所有投手補算缺少的衍生指標
    for p in stats.values():
        enrich_pitcher(p)

    log.info("Stats merged: %d pitchers (ESPN=%d)", len(stats), len(espn))
    return stats


def fetch_espn_web_schedule(game_date: date) -> list[dict]:
    """ESPN site.web.api 備援（不同子網域，較少被 GH Actions IP 封鎖）。"""
    date_str = game_date.strftime("%Y%m%d")
    games: list[dict] = []
    for league, base_url in [("NPB", BASE_ESPN_WEB_NPB), ("KBO", BASE_ESPN_WEB_KBO)]:
        url = f"{base_url}/scoreboard?dates={date_str}&lang=en&region=us"
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            resp.raise_for_status()
            events = resp.json().get("events", [])
            games.extend(_parse_espn_events(events, game_date.isoformat(), league))
        except Exception as e:
            log.debug("ESPN web [%s]: %s", league, e)
    return games


def fetch_mlbstats_schedule(game_date: date) -> list[dict]:
    """MLB Stats API 備援（statsapi.mlb.com，sportId=6 NPB / sportId=5 KBO）。"""
    date_str_us = game_date.strftime("%m/%d/%Y")
    date_iso    = game_date.isoformat()
    games: list[dict] = []
    for sport_id, league in [(6, "NPB"), (5, "KBO")]:
        url = f"https://statsapi.mlb.com/api/v1/schedule?sportId={sport_id}&date={date_str_us}"
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            if resp.status_code != 200:
                continue
            for date_entry in resp.json().get("dates", []):
                for game in date_entry.get("games", []):
                    home = game.get("teams", {}).get("home", {}).get("team", {})
                    away = game.get("teams", {}).get("away", {}).get("team", {})
                    home_name = home.get("name", "")
                    away_name = away.get("name", "")
                    home_code = _ESPN_TEAM_MAP.get(home_name, home.get("abbreviation", (home_name[:3].upper() if home_name else "???")))
                    away_code = _ESPN_TEAM_MAP.get(away_name, away.get("abbreviation", (away_name[:3].upper() if away_name else "???")))
                    state = game.get("status", {}).get("abstractGameState", "Preview")
                    games.append({
                        "game_id":      f"{date_iso}-{away_code}-{home_code}",
                        "date":         date_iso,
                        "time":         "",
                        "away":         away_code,
                        "away_name":    away_name,
                        "home":         home_code,
                        "home_name":    home_name,
                        "venue":        game.get("venue", {}).get("name", ""),
                        "league":       league,
                        "status":       "結束" if state == "Final" else "預定",
                        "away_score":   None,
                        "home_score":   None,
                        "away_pitcher": "",
                        "home_pitcher": "",
                        "_source":      "mlbstats",
                    })
        except Exception as e:
            log.debug("MLB Stats API [sport=%s]: %s", sport_id, e)
    return games


def fetch_odds_api_schedule(game_date: date, api_key: str = "") -> list[dict]:
    """
    The Odds API /events 端點（免費，不扣額度）取得 NPB/KBO 賽程。
    API key 從參數或環境變數 ODDS_API_KEY 讀取。
    """
    if not api_key:
        api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        log.debug("fetch_odds_api_schedule: no ODDS_API_KEY")
        return []

    date_str = game_date.isoformat()
    # Taiwan = UTC+8 ; filter events starting on this calendar day in TW time
    tw_midnight = datetime(game_date.year, game_date.month, game_date.day,
                           tzinfo=timezone(timedelta(hours=8)))
    from_utc = tw_midnight.astimezone(timezone.utc)
    to_utc   = (tw_midnight + timedelta(hours=24)).astimezone(timezone.utc)

    results: list[dict] = []
    # Try both NPB and KBO sport keys
    for sport_key, league in [("baseball_npb", "NPB"), ("baseball_kbo", "KBO")]:
        url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events"
        params = {
            "apiKey":          api_key,
            "dateFormat":      "iso",
            "commenceTimeFrom": from_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "commenceTimeTo":   to_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        try:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=10)
            if resp.status_code == 404:
                log.debug("Odds API: sport key %s not found", sport_key)
                continue
            if resp.status_code == 401:
                log.warning("Odds API: invalid or missing API key")
                break
            if resp.status_code != 200:
                log.debug("Odds API events [%s]: HTTP %s", sport_key, resp.status_code)
                continue
            events = resp.json()
            if not isinstance(events, list):
                log.debug("Odds API events [%s]: unexpected response", sport_key)
                continue
            for ev in events:
                home_name = ev.get("home_team", "")
                away_name = ev.get("away_team", "")
                home_lower = home_name.lower()
                away_lower = away_name.lower()
                home_code = _ESPN_TEAM_MAP.get(home_name)
                away_code = _ESPN_TEAM_MAP.get(away_name)
                # Fallback: case-insensitive exact, then substring match
                if not home_code:
                    home_lower = home_name.lower()
                    for k, v in _ESPN_TEAM_MAP.items():
                        if k.lower() == home_lower or k.lower() in home_lower:
                            home_code = v
                            break
                if not away_code:
                    away_lower = away_name.lower()
                    for k, v in _ESPN_TEAM_MAP.items():
                        if k.lower() == away_lower or k.lower() in away_lower:
                            away_code = v
                            break
                home_code = home_code or home_name[:3].upper()
                away_code = away_code or away_name[:3].upper()
                # Parse game time to Taiwan local time
                game_time = ""
                try:
                    dt_utc = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
                    dt_tw  = dt_utc.astimezone(timezone(timedelta(hours=8)))
                    game_time = dt_tw.strftime("%H:%M")
                except Exception:
                    pass
                results.append({
                    "game_id":      f"{date_str}-{away_code}-{home_code}",
                    "date":         date_str,
                    "time":         game_time,
                    "away":         away_code,
                    "away_name":    away_name,
                    "home":         home_code,
                    "home_name":    home_name,
                    "venue":        "",
                    "league":       league,
                    "status":       "預定",
                    "away_score":   None,
                    "home_score":   None,
                    "away_pitcher": "",
                    "home_pitcher": "",
                    "_source":      "odds_api_events",
                })
            log.info("Odds API events [%s]: %d games", sport_key, len([r for r in results if r["league"] == league]))
        except Exception as e:
            log.debug("Odds API events [%s]: %s", sport_key, e)

    return results


def fetch_schedule_multi(game_date: date, odds_api_key: str = "") -> list[dict]:
    """多來源賽程：ESPN → ESPN Web → MLB Stats API → The Odds API /events"""
    # 1. ESPN (primary)
    games = fetch_espn_schedule(game_date)
    if games:
        log.info("Schedule from ESPN: %d games", len(games))
        return games

    # 2. ESPN web API (different subdomain)
    games = fetch_espn_web_schedule(game_date)
    if games:
        log.info("Schedule from ESPN web: %d games", len(games))
        return games

    # 3. MLB Stats API (statsapi.mlb.com, covers NPB/KBO international leagues)
    games = fetch_mlbstats_schedule(game_date)
    if games:
        log.info("Schedule from MLB Stats API: %d games", len(games))
        return games

    # 4. The Odds API /events (free, no quota cost) — works from GH Actions
    games = fetch_odds_api_schedule(game_date, api_key=odds_api_key)
    if games:
        log.info("Schedule from Odds API events: %d games", len(games))
        return games

    log.warning("All schedule sources failed for %s", game_date)
    return []


# 删除舊的 CPBL 官網函數，保留 stub 避免 import 錯誤
def fetch_cpbl_pitcher_stats(year: int) -> dict[str, dict]:
    """廢棄 — CPBL 官網已被 WAF 封鎖。回傳空 dict。"""
    log.debug("fetch_cpbl_pitcher_stats: CPBL site removed, returning empty")
    return {}
