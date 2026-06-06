"""
V8 Stats Scraper — 多來源投手數據抓取器 (NPB / KBO)

NPB/KBO 自成獨立體系，完全不依賴 MLB 任何 API。

賽程與先發投手來源：
  NPB: Yahoo Japan Baseball (baseball.yahoo.co.jp) — 日文名自動轉中文
  KBO: koreabaseball.com 官方 → Naver Sports KBO
  保底: The Odds API /events — 有賽程，無先發

先發保底（原生官網）：
  NPB: npb.jp 官方月賽程（baseball.yahoo.co.jp 找不到投手時觸發）
  KBO: Daum Sports KBO 賽程（koreabaseball.com / Naver 找不到投手時觸發）

FIP 公式：FIP = (13×HR + 3×(BB+HBP) - 2×K) / IP + FIP_C
  NPB FIP_C ≈ 3.20  KBO FIP_C ≈ 3.60
"""
import os
import re
import math
import time
import random
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

# NPB-only team map (used for baseball_npb Odds API key)
_NPB_TEAM_MAP = {
    "Yomiuri Giants":               "GNT", "Giants":              "GNT",
    "Hanshin Tigers":               "HNS", "Tigers":              "HNS",
    "Hiroshima Toyo Carp":          "HRC", "Hiroshima Carp":      "HRC", "Carp": "HRC",
    "Yokohama DeNA BayStars":       "YDB", "DeNA BayStars":       "YDB", "BayStars": "YDB",
    "Tokyo Yakult Swallows":        "YKL", "Yakult Swallows":     "YKL", "Swallows": "YKL",
    "Chunichi Dragons":             "CND", "Dragons":             "CND",
    "Fukuoka SoftBank Hawks":       "SBH", "SoftBank Hawks":      "SBH", "Hawks": "SBH",
    "Orix Buffaloes":               "ORX", "Buffaloes":           "ORX",
    "Tohoku Rakuten Golden Eagles": "RKT", "Rakuten Eagles":      "RKT", "Eagles": "RKT",
    "Chiba Lotte Marines":          "LTT", "Lotte Marines":       "LTT", "Marines": "LTT",
    "Saitama Seibu Lions":          "SEI", "Seibu Lions":         "SEI", "Lions": "SEI",
    "Hokkaido Nippon-Ham Fighters": "HAM", "Nippon-Ham Fighters": "HAM", "Fighters": "HAM",
}

# KBO-only team map (used for baseball_kbo Odds API key)
_KBO_TEAM_MAP = {
    "Samsung Lions":  "SSL",
    "LG Twins":       "LGT",
    "Doosan Bears":   "DSB",
    "KT Wiz":         "KTW",
    "SSG Landers":    "SSG",
    "NC Dinos":       "NCD",
    "KIA Tigers":     "KIA",
    "Lotte Giants":   "LTG",
    "Hanwha Eagles":  "HWE",
    "Kiwoom Heroes":  "KWH",
}

# Combined map kept for ESPN functions only (ESPN is blocked but code still referenced)
_ESPN_TEAM_MAP = {**_NPB_TEAM_MAP, **_KBO_TEAM_MAP}


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


# ─────────────────────────────────────────────────────────────
# KBO 官方與韓國媒體賽程（不使用 MLB API，KBO 自成一體）
# ─────────────────────────────────────────────────────────────

_KBO_OFFICIAL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
    "Accept-Language": "ko,en-US;q=0.8,en;q=0.6",
    "Referer": "https://www.koreabaseball.com/",
}

# koreabaseball.com 隊名文字 → 內部代碼
_KBO_OFFICIAL_TEAM_MAP = {
    "삼성":  "SSL", "Samsung":  "SSL",
    "LG":    "LGT",
    "두산":  "DSB", "Doosan":   "DSB",
    "KT":    "KTW",
    "SSG":   "SSG",
    "NC":    "NCD",
    "KIA":   "KIA",
    "롯데":  "LTG", "Lotte":    "LTG",
    "한화":  "HWE", "Hanwha":   "HWE",
    "키움":  "KWH", "Kiwoom":   "KWH",
}


def _kbo_official_team_code(text: str) -> str:
    t = text.strip()
    for k, v in _KBO_OFFICIAL_TEAM_MAP.items():
        if k == t or k in t:
            return v
    return ""


def fetch_kbo_schedule(game_date: date) -> list[dict]:
    """
    KBO 賽程抓取 — 只使用韓國本地資料來源，不依賴 MLB API。
    嘗試順序：mykbostats.com（日期特定）→ koreabaseball.com → Naver Sports KBO → 空列表
    先發投手若頁面有則抓，無則留空（由 rotation 補漏）。
    mykbostats.com 排第一是因為它提供日期特定 URL，不會把整個月的賽事重複回傳。
    """
    date_str = game_date.isoformat()
    y, m, d  = game_date.year, game_date.month, game_date.day

    # 1. mykbostats.com — 日期特定 URL，最可靠，含 Probable Pitchers
    try:
        time.sleep(random.uniform(0.5, 1.5))
        mykbo_games = fetch_mykbo_schedule(game_date)
        if mykbo_games:
            log.info("KBO schedule from MyKBO Stats: %d games (with pitchers)", len(mykbo_games))
            return mykbo_games
    except Exception as e:
        log.debug("MyKBO Stats failed: %s", e)

    # 2. koreabaseball.com 官方網站（只用帶日期的 URL，避免無日期版本永遠回傳今天賽程）
    kbo_urls = [
        f"https://www.koreabaseball.com/Schedule/Schedule.aspx?leId=1&srId=0&date={y:04d}{m:02d}{d:02d}",
    ]
    for url in kbo_urls:
        try:
            resp = requests.get(url, headers=_KBO_OFFICIAL_HEADERS, timeout=15)
            if resp.status_code == 403:
                log.debug("koreabaseball.com 403 for %s", url)
                continue
            if resp.status_code != 200:
                log.debug("koreabaseball.com HTTP %s for %s", resp.status_code, url)
                continue
            resp.encoding = resp.apparent_encoding or "utf-8"
            games = _parse_koreabaseball_html(resp.text, date_str)
            if games:
                log.info("KBO schedule from koreabaseball.com: %d games", len(games))
                return games
        except Exception as e:
            log.debug("koreabaseball.com %s: %s", url, e)

    # 3. Naver Sports KBO 賽程
    naver_urls = [
        f"https://sports.news.naver.com/kbaseball/schedule/index.nhn?year={y}&month={m:02d}",
        "https://sports.news.naver.com/kbaseball/schedule/index.nhn",
    ]
    for url in naver_urls:
        try:
            resp = requests.get(url, headers=_KBO_OFFICIAL_HEADERS, timeout=15)
            if resp.status_code != 200:
                log.debug("Naver KBO HTTP %s", resp.status_code)
                continue
            resp.encoding = resp.apparent_encoding or "utf-8"
            games = _parse_naver_kbo_html(resp.text, date_str)
            if games:
                log.info("KBO schedule from Naver Sports: %d games", len(games))
                return games
        except Exception as e:
            log.debug("Naver KBO %s: %s", url, e)

    return []


def _parse_koreabaseball_html(html: str, date_str: str) -> list[dict]:
    """
    Parse koreabaseball.com schedule page.
    Uses text-scan approach (same as Yahoo Japan parser) for robustness.
    Pitcher enrichment runs BEFORE script tags are removed (Phase 0).
    """
    soup = BeautifulSoup(html, "html.parser")

    # Phase 0 + team scan must share the same soup (scripts still present)
    sorted_keys = sorted(_KBO_OFFICIAL_TEAM_MAP.keys(), key=len, reverse=True)
    pattern = re.compile('(' + '|'.join(re.escape(k) for k in sorted_keys) + ')')

    # Collect team codes from non-script text nodes
    codes_in_order: list[str] = []
    for node in soup.find_all(string=True):
        if node.parent and node.parent.name in ('script', 'style', 'noscript', 'head'):
            continue
        text = node.strip()
        if not text or len(text) > 50:
            continue
        for m in pattern.finditer(text):
            code = _kbo_official_team_code(m.group())
            if code and (not codes_in_order or codes_in_order[-1] != code):
                codes_in_order.append(code)

    games = _pair_team_codes(codes_in_order, date_str, "KBO", "koreabaseball")
    # Enrich pitchers BEFORE decomposing scripts (Phase 0 needs script content)
    _enrich_kbo_pitchers_from_html(soup, games)
    return games


def _parse_naver_kbo_html(html: str, date_str: str) -> list[dict]:
    """Parse Naver Sports KBO schedule page using text-scan approach."""
    soup = BeautifulSoup(html, "html.parser")

    sorted_keys = sorted(_KBO_OFFICIAL_TEAM_MAP.keys(), key=len, reverse=True)
    pattern = re.compile('(' + '|'.join(re.escape(k) for k in sorted_keys) + ')')

    codes_in_order: list[str] = []
    for node in soup.find_all(string=True):
        if node.parent and node.parent.name in ('script', 'style', 'noscript', 'head'):
            continue
        text = node.strip()
        if not text or len(text) > 50:
            continue
        for m in pattern.finditer(text):
            code = _kbo_official_team_code(m.group())
            if code and (not codes_in_order or codes_in_order[-1] != code):
                codes_in_order.append(code)

    games = _pair_team_codes(codes_in_order, date_str, "KBO", "naver_kbo")
    _enrich_kbo_pitchers_from_html(soup, games)
    return games


def _pair_team_codes(codes: list[str], date_str: str, league: str, source: str) -> list[dict]:
    """Pair consecutive different team codes into games (shared by NPB and KBO parsers)."""
    games: list[dict] = []
    seen: set[tuple] = set()
    i = 0
    while i < len(codes) - 1:
        c1, c2 = codes[i], codes[i + 1]
        if c1 != c2:
            key = tuple(sorted((c1, c2)))
            if key not in seen:
                seen.add(key)
                games.append({
                    "game_id":      f"{date_str}-{c1}-{c2}",
                    "date":         date_str,
                    "time":         "",
                    "away":         c1,
                    "away_name":    "",
                    "home":         c2,
                    "home_name":    "",
                    "venue":        "",
                    "league":       league,
                    "status":       "預定",
                    "away_score":   None,
                    "home_score":   None,
                    "away_pitcher": "",
                    "home_pitcher": "",
                    "_source":      source,
                })
            i += 2
        else:
            i += 1
    return games


def _enrich_kbo_pitchers_from_html(soup_before_decompose, games: list[dict]) -> None:
    """
    Phase 0 + Phase 2 for KBO HTML pages (koreabaseball.com / Naver Sports).

    Phase 0: scan <script> tags before they are removed for Hangul pitcher names
    embedded in JavaScript data blobs (same pattern as Yahoo Japan).
    Phase 2: scan regular text nodes for Hangul pitcher names.

    Both phases translate via _KBO_PITCHER_KR_MAP, then assign each pitcher to
    the game whose team code matches _KBO_PITCHER_TEAM (same approach as NPB).
    """
    if not games or not _KBO_PITCHER_KR_MAP:
        return

    sorted_kr_keys = sorted(_KBO_PITCHER_KR_MAP.keys(), key=len, reverse=True)
    kr_pattern = re.compile('(' + '|'.join(re.escape(k) for k in sorted_kr_keys) + ')')

    # Phase 0: scan script tag content before decompose
    found_zh: set[str] = set()
    for script in soup_before_decompose.find_all('script'):
        sc = script.get_text() or ""
        for m in kr_pattern.finditer(sc):
            found_zh.add(_KBO_PITCHER_KR_MAP[m.group()])

    # Phase 2: scan regular text nodes (soup may already have scripts removed by caller)
    for node in soup_before_decompose.find_all(string=True):
        text = node.strip()
        if not text or len(text) > 50:
            continue
        for m in kr_pattern.finditer(text):
            found_zh.add(_KBO_PITCHER_KR_MAP[m.group()])

    if found_zh:
        log.info("KBO HTML Phase-0/2: found pitcher names %s", found_zh)
    else:
        log.debug("KBO HTML: no Korean pitcher names found")
        return

    # Assign by team membership
    for g in games:
        for zh in found_zh:
            team = _KBO_PITCHER_TEAM.get(zh, "")
            if team == g["away"] and not g["away_pitcher"]:
                g["away_pitcher"] = zh
            elif team == g["home"] and not g["home_pitcher"]:
                g["home_pitcher"] = zh


def fetch_npb_official_schedule(game_date: date) -> list[dict]:
    """
    npb.jp 官方月賽程頁面取得指定日期的 NPB 賽程與先發投手。

    URL: https://npb.jp/games/{year}/schedule_{month:02d}_detail.html
    作為 Yahoo Japan 失敗時的 NPB 主要賽程備援來源。
    同時提取先發投手（透過 _JP_PITCHER_NAME_MAP + _NPB_PITCHER_TEAM）。
    """
    date_str = game_date.isoformat()
    url = (f"https://npb.jp/games/{game_date.year}/"
           f"schedule_{game_date.month:02d}_detail.html")
    try:
        resp = requests.get(url, headers=_YAHOO_JP_HEADERS, timeout=15)
        if resp.status_code != 200:
            log.warning("NPB official HTTP %s for %s", resp.status_code, url)
            return []
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        # ── pitcher Phase 0: script tags ──────────────────────────────────
        sorted_pk = sorted(_JP_PITCHER_NAME_MAP.keys(), key=len, reverse=True)
        pitcher_pat = re.compile('(' + '|'.join(re.escape(k) for k in sorted_pk) + ')')
        found_zh: set[str] = set()
        for script in soup.find_all('script'):
            for m in pitcher_pat.finditer(script.get_text() or ""):
                found_zh.add(_JP_PITCHER_NAME_MAP[m.group()])

        # ── team Phase 0.5: script tags ───────────────────────────────────
        sorted_tk = sorted(_YAHOO_NPB_TEAM_MAP.keys(), key=len, reverse=True)
        team_pat = re.compile('(' + '|'.join(re.escape(k) for k in sorted_tk) + ')')
        team_codes_scripts: list[str] = []
        for script in soup.find_all('script'):
            for m in team_pat.finditer(script.get_text() or ""):
                code = _YAHOO_NPB_TEAM_MAP[m.group()]
                if not team_codes_scripts or team_codes_scripts[-1] != code:
                    team_codes_scripts.append(code)

        for tag in soup.find_all(['script', 'style', 'noscript', 'head', 'nav', 'footer']):
            tag.decompose()

        # ── team Phase 1: text nodes（日期過濾）─────────────────────────────
        # npb.jp 月賽程頁面按日期分段。只收集目標日期段落內的隊名，
        # 避免把整個月的比賽全部歸入同一天。
        # 重要：codes_in_order 不從 script 掃描結果初始化（script 無日期上下文）
        target_day_jp = f"{game_date.month}月{game_date.day}日"
        in_target_section = False
        codes_in_order: list[str] = []
        date_re_jp = re.compile(r'\d+月\d+日')
        for node in soup.find_all(string=True):
            text = node.strip()
            if not text:
                continue
            # 偵測目標日期的段落標題
            if target_day_jp in text:
                in_target_section = True
                continue  # 日期文字本身不含隊名，跳過
            # 遇到下一個不同日期就停止
            if in_target_section and date_re_jp.search(text) and target_day_jp not in text:
                break
            # 只處理目標日期段落內的節點
            if not in_target_section:
                continue
            if len(text) > 50:
                continue
            for m in team_pat.finditer(text):
                code = _YAHOO_NPB_TEAM_MAP[m.group()]
                if not codes_in_order or codes_in_order[-1] != code:
                    codes_in_order.append(code)

        # Pitcher Phase 2: text nodes
        for node in soup.find_all(string=True):
            text = node.strip()
            if not text or len(text) > 50:
                continue
            for m in pitcher_pat.finditer(text):
                found_zh.add(_JP_PITCHER_NAME_MAP[m.group()])

        if not codes_in_order:
            log.warning("NPB official: no team codes found for %s in %s", game_date, url)
            return []

        games = _pair_team_codes(codes_in_order, date_str, "NPB", "npb_official")

        # assign pitchers by team membership
        for zh in found_zh:
            team = _NPB_PITCHER_TEAM.get(zh, "")
            for g in games:
                if team == g["away"] and not g.get("away_pitcher"):
                    g["away_pitcher"] = zh
                elif team == g["home"] and not g.get("home_pitcher"):
                    g["home_pitcher"] = zh

        log.info("NPB official: %d games, pitchers found: %s", len(games), found_zh or "(none)")
        return games
    except Exception as e:
        log.debug("NPB official fetch failed: %s", e)
        return []


def fetch_npb_official_pitchers(game_date: date, games: list[dict]) -> None:
    """先發投手補強版：只填 games 裡缺少投手的欄位，不建立新 game 物件。"""
    if not games:
        return
    enriched = fetch_npb_official_schedule(game_date)
    if not enriched:
        return
    enriched_by_id = {g["game_id"]: g for g in enriched}
    for g in games:
        src = enriched_by_id.get(g["game_id"])
        if src:
            if src.get("away_pitcher") and not g.get("away_pitcher"):
                g["away_pitcher"] = src["away_pitcher"]
            if src.get("home_pitcher") and not g.get("home_pitcher"):
                g["home_pitcher"] = src["home_pitcher"]


def fetch_daum_kbo_pitchers(game_date: date, games: list[dict]) -> None:
    """
    Daum Sports KBO 賽程頁面取得先發投手並填入 games。

    URL: https://sports.daum.net/schedule/kbo?date={YYYYMMDD}
    使用與 koreabaseball.com 相同的 Phase 0/2 掃描法：
    掃 <script> 及文字節點，透過 _KBO_PITCHER_KR_MAP 轉譯，
    再由 _KBO_PITCHER_TEAM 指派到比賽。
    """
    if not games:
        return
    date_str = game_date.strftime("%Y%m%d")
    url = f"https://sports.daum.net/schedule/kbo?date={date_str}"
    _daum_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
        "Referer": "https://sports.daum.net/",
    }
    try:
        resp = requests.get(url, headers=_daum_headers, timeout=15)
        if resp.status_code != 200:
            log.debug("Daum KBO HTTP %s for %s", resp.status_code, url)
            return
        resp.encoding = resp.apparent_encoding or "utf-8"
        soup = BeautifulSoup(resp.text, "html.parser")

        if not _KBO_PITCHER_KR_MAP:
            return
        sorted_kr = sorted(_KBO_PITCHER_KR_MAP.keys(), key=len, reverse=True)
        pat = re.compile('(' + '|'.join(re.escape(k) for k in sorted_kr) + ')')

        found_zh: set[str] = set()

        # Phase 0 — script tags
        for script in soup.find_all('script'):
            for m in pat.finditer(script.get_text() or ""):
                found_zh.add(_KBO_PITCHER_KR_MAP[m.group()])
        if found_zh:
            log.info("Daum KBO Phase-0: found %s", found_zh)

        for tag in soup.find_all(['script', 'style', 'noscript', 'head', 'nav', 'footer']):
            tag.decompose()

        # Phase 2 — text nodes
        for node in soup.find_all(string=True):
            text = node.strip()
            if not text or len(text) > 50:
                continue
            for m in pat.finditer(text):
                found_zh.add(_KBO_PITCHER_KR_MAP[m.group()])

        if not found_zh:
            log.debug("Daum KBO: no pitcher names found for %s", game_date)
            return
        log.info("Daum KBO: found pitchers %s", found_zh)

        for g in games:
            for zh in found_zh:
                team = _KBO_PITCHER_TEAM.get(zh, "")
                if team == g["away"] and not g.get("away_pitcher"):
                    g["away_pitcher"] = zh
                elif team == g["home"] and not g.get("home_pitcher"):
                    g["home_pitcher"] = zh
    except Exception as e:
        log.debug("Daum KBO fetch failed: %s", e)


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
    # Try both NPB and KBO sport keys, using league-specific team maps to prevent cross-league contamination
    for sport_key, league in [("baseball_npb", "NPB"), ("baseball_kbo", "KBO")]:
        team_map = _NPB_TEAM_MAP if league == "NPB" else _KBO_TEAM_MAP
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
            before = len(results)
            for ev in events:
                home_name = ev.get("home_team", "")
                away_name = ev.get("away_team", "")
                # Exact match first, then case-insensitive substring — within the correct league map only
                home_code = team_map.get(home_name)
                away_code = team_map.get(away_name)
                if not home_code:
                    home_lower = home_name.lower()
                    for k, v in team_map.items():
                        if k.lower() == home_lower or k.lower() in home_lower:
                            home_code = v
                            break
                if not away_code:
                    away_lower = away_name.lower()
                    for k, v in team_map.items():
                        if k.lower() == away_lower or k.lower() in away_lower:
                            away_code = v
                            break
                # If either code is still unknown, skip — never guess with [:3]
                if not home_code or not away_code:
                    log.debug("Odds API [%s]: unknown team %s@%s — skip", sport_key, away_name, home_name)
                    continue
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
            log.info("Odds API events [%s]: %d games", sport_key, len(results) - before)
        except Exception as e:
            log.debug("Odds API events [%s]: %s", sport_key, e)

    return results


def fetch_schedule_multi(game_date: date, odds_api_key: str = "") -> list[dict]:
    """
    多來源賽程（含先發投手），完全不使用 MLB API — NPB/KBO 自成體系。

    優先順序：
      NPB: Yahoo Japan Baseball (baseball.yahoo.co.jp, 日期特定 URL)
      KBO: koreabaseball.com 官方 → Naver Sports KBO
      保底: The Odds API /events（只有賽程，無先發）
    """
    games_kbo: list[dict] = []
    games_npb: list[dict] = []

    # 1. NPB — Yahoo Japan Baseball（日期特定 URL）
    try:
        yahoo_games = fetch_yahoo_npb_schedule(game_date)
        if yahoo_games:
            games_npb = yahoo_games
            log.info("Schedule NPB from Yahoo Japan: %d games", len(games_npb))
        else:
            log.warning("Yahoo Japan NPB: 0 games for %s — trying npb.jp official", game_date)
    except Exception as e:
        log.warning("Yahoo Japan NPB exception: %s — trying npb.jp official", e)

    # 1b. NPB fallback — npb.jp 官方月賽程（Yahoo Japan 失敗或回傳 0 場時觸發）
    if not games_npb:
        try:
            official_games = fetch_npb_official_schedule(game_date)
            if official_games:
                games_npb = official_games
                log.info("Schedule NPB from npb.jp official: %d games", len(games_npb))
            else:
                log.warning("npb.jp official also returned 0 games for %s", game_date)
        except Exception as e:
            log.debug("npb.jp official failed: %s", e)

    # 1c. NPB fallback — 日刊體育 nikkansports.com（靜態 HTML，予告先発含む）
    if not games_npb:
        try:
            nk_games = fetch_nikkansports_npb(game_date)
            if nk_games:
                games_npb = nk_games
                log.info("Schedule NPB from Nikkansports: %d games", len(games_npb))
            else:
                log.warning("Nikkansports NPB also returned 0 games for %s", game_date)
        except Exception as e:
            log.debug("Nikkansports NPB failed: %s", e)

    # 2. KBO — 韓國本地來源（koreabaseball.com → Naver Sports → MyKBO Stats）
    try:
        kbo_games = fetch_kbo_schedule(game_date)
        if kbo_games:
            games_kbo = kbo_games
    except Exception as e:
        log.debug("KBO schedule fetch failed: %s", e)

    # 3. The Odds API /events — 保底（有賽程但無先發）
    if not games_kbo or not games_npb:
        try:
            odds_games = fetch_odds_api_schedule(game_date, api_key=odds_api_key)
            if odds_games:
                log.info("Schedule from Odds API events: %d games", len(odds_games))
                existing_ids = {g["game_id"] for g in (games_kbo + games_npb)}
                needs_kbo = not games_kbo
                needs_npb = not games_npb
                for g in odds_games:
                    if g["game_id"] not in existing_ids:
                        league = g.get("league", "")
                        if league == "KBO" and needs_kbo:
                            games_kbo.append(g)
                        elif league == "NPB" and needs_npb:
                            games_npb.append(g)
                        existing_ids.add(g["game_id"])
        except Exception as e:
            log.debug("Odds API events failed: %s", e)

    # 4. NPB 保底：npb.jp 官方月賽程（Yahoo Japan 未找到投手時才觸發）
    if any(not g.get("away_pitcher") or not g.get("home_pitcher") for g in games_npb):
        fetch_npb_official_pitchers(game_date, games_npb)

    # 5. KBO 保底：Daum Sports（koreabaseball / Naver 未找到投手時才觸發）
    if any(not g.get("away_pitcher") or not g.get("home_pitcher") for g in games_kbo):
        fetch_daum_kbo_pitchers(game_date, games_kbo)

    result = games_kbo + games_npb
    if not result:
        log.warning("All schedule sources failed for %s", game_date)
    return result


# ── MyKBO Stats — KBO 先發投手 ────────────────────────────────────────────────

_MYKBO_TEAM_MAP = {
    # 英文全名 → 內部代碼
    "samsung lions":  "SSL", "samsung":  "SSL",
    "lg twins":       "LGT", "lg twins": "LGT",
    "doosan bears":   "DSB", "doosan":   "DSB",
    "kt wiz":         "KTW", "kt":       "KTW",
    "ssg landers":    "SSG", "ssg":      "SSG",
    "nc dinos":       "NCD", "nc":       "NCD",
    "kia tigers":     "KIA", "kia":      "KIA",
    "lotte giants":   "LTG", "lotte":    "LTG",
    "hanwha eagles":  "HWE", "hanwha":   "HWE",
    "kiwoom heroes":  "KWH", "kiwoom":   "KWH",
}

_MYKBO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://mykbostats.com/",
}

# ── Nikkansports (日刊體育) — NPB 賽程 / 予告先発 ─────────────────────────────

_NIKKANSPORTS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.nikkansports.com/",
}


def fetch_nikkansports_npb(game_date: date) -> list[dict]:
    """
    日刊體育 nikkansports.com — NPB 月賽程頁面 + 予告先発抓取。
    靜態 HTML（非 Next.js），日文隊名直接寫在文字節點，解析穩定。
    """
    date_str = game_date.isoformat()
    y, m = game_date.year, game_date.month
    urls = [
        f"https://www.nikkansports.com/baseball/professional/schedule/{y}/{m:02d}/",
        f"https://www.nikkansports.com/baseball/professional/schedule/{y}/",
        "https://www.nikkansports.com/baseball/professional/schedule/",
    ]
    for url in urls:
        try:
            time.sleep(random.uniform(1.0, 2.5))
            resp = requests.get(url, headers=_NIKKANSPORTS_HEADERS, timeout=15)
            if resp.status_code != 200:
                log.debug("Nikkansports HTTP %s for %s", resp.status_code, url)
                continue
            resp.encoding = resp.apparent_encoding or "utf-8"
            games = _parse_nikkansports_npb_html(resp.text, date_str)
            if games:
                log.info("Nikkansports NPB: %d games for %s", len(games), date_str)
                return games
        except Exception as e:
            log.debug("Nikkansports %s: %s", url, e)
    return []


def _parse_nikkansports_npb_html(html: str, date_str: str) -> list[dict]:
    """
    日刊體育 NPB 賽程 HTML 解析。
    同 Yahoo Japan 解析器：文字節點走查日文隊名，與日期段配對。
    """
    game_date = date.fromisoformat(date_str)
    target_day_jp = f"{game_date.month}月{game_date.day}日"

    # Phase 0.1: decode \\uXXXX escapes (handles any JSON blobs on page)
    decoded = re.sub(r'\\u([0-9a-fA-F]{4})',
                     lambda m_: chr(int(m_.group(1), 16)), html)
    sorted_team_keys = sorted(_YAHOO_NPB_TEAM_MAP.keys(), key=len, reverse=True)
    team_pattern = re.compile('(' + '|'.join(re.escape(k) for k in sorted_team_keys) + ')')

    # If target date not mentioned at all, skip early
    if target_day_jp not in decoded and target_day_jp not in html:
        alt = f"{game_date.month}/{game_date.day}"
        if alt not in html:
            log.debug("Nikkansports: %s not found in HTML", date_str)
            return []

    soup = BeautifulSoup(html, "html.parser")

    # Pitcher scan from script tags (before decompose)
    sorted_pitcher_keys = sorted(_JP_PITCHER_NAME_MAP.keys(), key=len, reverse=True)
    pitcher_pat = re.compile('(' + '|'.join(re.escape(k) for k in sorted_pitcher_keys) + ')')
    found_pitchers: set[str] = set()
    for script in soup.find_all('script'):
        sc = script.get_text() or ""
        for pm in pitcher_pat.finditer(sc):
            found_pitchers.add(_JP_PITCHER_NAME_MAP[pm.group()])

    for tag in soup.find_all(['script', 'style', 'noscript', 'head', 'nav', 'footer']):
        tag.decompose()

    # Walk text nodes, collecting codes only within the target-date section
    in_section = False
    codes_in_order: list[str] = []
    date_re = re.compile(r'(\d{1,2})月(\d{1,2})日')

    for node in soup.find_all(string=True):
        text = node.strip()
        if not text:
            continue
        # Detect date header
        dm = date_re.search(text)
        if dm:
            nm, nd = int(dm.group(1)), int(dm.group(2))
            in_section = (nm == game_date.month and nd == game_date.day)
        if not in_section:
            continue
        if len(text) > 50:
            continue
        for m_ in team_pattern.finditer(text):
            code = _YAHOO_NPB_TEAM_MAP[m_.group()]
            if not codes_in_order or codes_in_order[-1] != code:
                codes_in_order.append(code)

    # Fallback: scan whole page if date section not identified
    if not codes_in_order:
        for node in soup.find_all(string=True):
            text = node.strip()
            if not text or len(text) > 50:
                continue
            for m_ in team_pattern.finditer(text):
                code = _YAHOO_NPB_TEAM_MAP[m_.group()]
                if not codes_in_order or codes_in_order[-1] != code:
                    codes_in_order.append(code)

    if not codes_in_order:
        return []

    games = _pair_team_codes(codes_in_order, date_str, "NPB", "nikkansports")

    # Assign pitchers by team membership
    for g in games:
        for zh in found_pitchers:
            team = _NPB_PITCHER_TEAM.get(zh, "")
            if team == g["away"] and not g.get("away_pitcher"):
                g["away_pitcher"] = zh
            elif team == g["home"] and not g.get("home_pitcher"):
                g["home_pitcher"] = zh

    return games


def _mykbo_team_code(name: str) -> str:
    n = name.lower().strip()
    for k, v in _MYKBO_TEAM_MAP.items():
        if k in n or n in k:
            return v
    return ""


def fetch_mykbo_schedule(game_date: date) -> list[dict]:
    """
    mykbostats.com 抓今日 KBO 賽程與預計先發投手。
    URL: https://mykbostats.com/schedule/YYYY-MM-DD
    """
    date_str = game_date.isoformat()
    urls = [
        f"https://mykbostats.com/schedule/{date_str}",
        f"https://mykbostats.com/schedule?date={date_str}",
        "https://mykbostats.com/schedule",
    ]
    for url in urls:
        try:
            resp = requests.get(url, headers=_MYKBO_HEADERS, timeout=15)
            if resp.status_code == 403:
                log.debug("MyKBO 403 for %s", url)
                continue
            if resp.status_code != 200:
                log.debug("MyKBO HTTP %s for %s", resp.status_code, url)
                continue
            games = _parse_mykbo_html(resp.text, date_str)
            if games:
                log.info("MyKBO: parsed %d KBO games from %s", len(games), url)
                return games
        except Exception as e:
            log.debug("MyKBO fetch %s: %s", url, e)
    return []


def _parse_mykbo_html(html: str, date_str: str) -> list[dict]:
    """
    解析 mykbostats.com 賽程頁面，提取先發投手。
    使用多策略方法：先試 CSS 選取器，再試文字掃描，確保在 HTML 結構變動時仍能工作。
    """
    soup  = BeautifulSoup(html, "html.parser")
    games = []
    seen_pairs: set[tuple] = set()

    # Build team-code lookup (case-insensitive) from _MYKBO_TEAM_MAP
    # Also build a set of all known team name tokens for text scan
    _all_team_tokens = sorted(_MYKBO_TEAM_MAP.keys(), key=len, reverse=True)
    _team_text_re = re.compile(
        r'\b(' + '|'.join(re.escape(k) for k in _all_team_tokens) + r')\b',
        re.IGNORECASE,
    )

    def _find_two_teams_in_text(text: str):
        """Return (away_code, home_code) if 2+ distinct team codes found, else (None, None)."""
        found = []
        for m in _team_text_re.finditer(text):
            code = _mykbo_team_code(m.group())
            if code and (not found or found[-1] != code):
                found.append(code)
        # Return first two distinct codes
        unique = []
        for c in found:
            if c not in unique:
                unique.append(c)
            if len(unique) == 2:
                return unique[0], unique[1]
        return None, None

    def _add_game(away_code, home_code, away_name="", home_name="",
                  away_pitcher="", home_pitcher="", game_time="", source="mykbo"):
        key = tuple(sorted((away_code, home_code)))
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        games.append({
            "game_id":      f"{date_str}-{away_code}-{home_code}",
            "date":         date_str,
            "time":         game_time,
            "away":         away_code,
            "away_name":    away_name,
            "home":         home_code,
            "home_name":    home_name,
            "venue":        "",
            "league":       "KBO",
            "status":       "預定",
            "away_score":   None,
            "home_score":   None,
            "away_pitcher": away_pitcher,
            "home_pitcher": home_pitcher,
            "_source":      source,
        })

    # Pattern A: game cards / rows with team and pitcher info
    for container in soup.select(
        ".game-card, .schedule-game, .game-row, "
        "[class*='game'], [class*='match'], [class*='schedule']"
    ):
        text = container.get_text(" ", strip=True)
        # 找隊名
        team_els = container.select(
            ".team-name, .team, [class*='team'], "
            "a[href*='/teams/'], span[class*='name']"
        )
        teams_raw = [el.get_text(strip=True) for el in team_els if el.get_text(strip=True)]
        away_code = home_code = ""
        away_name = home_name = ""
        if len(teams_raw) >= 2:
            away_code = _mykbo_team_code(teams_raw[0])
            home_code = _mykbo_team_code(teams_raw[-1])
            away_name = teams_raw[0]
            home_name = teams_raw[-1]
        # Fallback: scan the whole container text
        if not away_code or not home_code or away_code == home_code:
            away_code, home_code = _find_two_teams_in_text(text)
            if not away_code or not home_code:
                continue

        # 找先發投手
        pitcher_els = container.select(
            ".pitcher, .sp, .starter, [class*='pitcher'], "
            "[class*='starter'], [class*='probable']"
        )
        pitchers = [el.get_text(strip=True) for el in pitcher_els
                    if el.get_text(strip=True) and len(el.get_text(strip=True)) > 2]

        away_pitcher = pitchers[0] if len(pitchers) > 0 else ""
        home_pitcher = pitchers[1] if len(pitchers) > 1 else ""

        # 比賽時間
        time_el = container.select_one(
            ".game-time, .time, [class*='time'], [class*='start']"
        )
        game_time = ""
        if time_el:
            t = time_el.get_text(strip=True)
            tm = re.search(r"(\d{1,2}:\d{2})", t)
            if tm:
                game_time = tm.group(1)

        _add_game(away_code, home_code, away_name, home_name,
                  away_pitcher, home_pitcher, game_time, "mykbo")

    # Pattern B: 表格結構（行 = 一場比賽）
    if not games:
        for row in soup.select("table tr, tbody tr"):
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            row_text = " ".join(cells)
            away_code, home_code = _find_two_teams_in_text(row_text)
            if not away_code or not home_code:
                continue
            _add_game(away_code, home_code, source="mykbo_table")

    # Pattern C: aggressive text-scan — look for any element containing 2+ known team names
    # (links, spans, divs that mykbostats.com uses for matchup display)
    if not games:
        # Try links that contain team names (e.g. /teams/samsung-lions/)
        for a_tag in soup.find_all("a", href=re.compile(r'/teams?/', re.I)):
            href = a_tag.get("href", "")
            text = a_tag.get_text(strip=True)
            code = _mykbo_team_code(text) or _mykbo_team_code(href)
            if code:
                log.debug("mykbo link team: %s → %s", text or href, code)

        # Walk all visible text and collect consecutive team codes
        codes_in_order: list[str] = []
        for node in soup.find_all(string=True):
            if node.parent and node.parent.name in ('script', 'style', 'noscript', 'head'):
                continue
            text = node.strip()
            if not text:
                continue
            for m in _team_text_re.finditer(text):
                code = _mykbo_team_code(m.group())
                if code and (not codes_in_order or codes_in_order[-1] != code):
                    codes_in_order.append(code)

        i = 0
        while i < len(codes_in_order) - 1:
            c1, c2 = codes_in_order[i], codes_in_order[i + 1]
            if c1 != c2:
                _add_game(c1, c2, source="mykbo_scan")
                i += 2
            else:
                i += 1

    return games


# ── Yahoo Japan Baseball — NPB 先發投手 ───────────────────────────────────────

_YAHOO_JP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
    "Referer": "https://baseball.yahoo.co.jp/",
}

# 日職隊名 (Yahoo Japan 日文) → 內部代碼
_YAHOO_NPB_TEAM_MAP = {
    "巨人":       "GNT", "読売":    "GNT", "読売ジャイアンツ": "GNT",
    "阪神":       "HNS", "タイガース": "HNS",
    "広島":       "HRC", "カープ":  "HRC",
    "ＤｅＮＡ":  "YDB", "DeNA":   "YDB", "ベイスターズ": "YDB",
    "ヤクルト":   "YKL", "スワローズ": "YKL",
    "中日":       "CND", "ドラゴンズ": "CND",
    "ソフトバンク": "SBH", "ホークス": "SBH", "福岡": "SBH",
    "オリックス": "ORX", "バファローズ": "ORX",
    "楽天":       "RKT", "イーグルス": "RKT",
    "ロッテ":     "LTT", "マリーンズ": "LTT",
    "西武":       "SEI", "ライオンズ": "SEI",
    "日本ハム":   "HAM", "ファイターズ": "HAM",
}

# 投手日文名 → 中文名（我們 PITCHERS 使用的中文名）
_JP_PITCHER_NAME_MAP = {
    # GNT
    "菅野智之": "菅野智之", "戸郷翔征": "戶鄉翔征", "グリフィン": "葛瑞芬",
    "赤星優志": "赤星優志",
    # HNS
    "才木浩人": "才木浩人", "村上頌樹": "村上頌樹", "西勇輝": "西勇輝",
    "ビーズリー": "比茲利",
    # HRC
    "大瀬良大地": "大瀨良大地", "床田寛樹": "床田寬樹", "九里亜蓮": "九里亞蓮",
    "ハーン": "漢恩",
    # YDB
    "東克樹": "東克樹", "石田裕太郎": "石田裕太郎", "大貫晋一": "大貫晉一",
    "ジャクソン": "傑克森",
    # YKL
    "小川泰弘": "小川泰弘", "高橋奎二": "高橋奎二", "サイスニード": "賽斯尼德",
    "吉村貢司郎": "吉村貢司郎",
    # CND
    "大野雄大": "大野雄大", "柳裕也": "柳裕也", "メヒア": "梅希亞",
    "涌井秀章": "涌井秀章",
    # SBH
    "モイネロ": "莫伊內羅", "有原航平": "有原航平", "東浜巨": "東濱巨",
    "スチュワート・ジュニア": "史都華特二世",
    # ORX
    "山下舜平大": "山下舜平太", "田嶋大樹": "田嶋大樹", "宮城大弥": "宮城大彌",
    "エスピノーザ": "艾斯皮諾薩",
    # RKT
    "早川隆久": "早川隆久", "岸孝之": "岸孝之", "ターリー": "塔利",
    "田中将大": "田中將大",
    # LTT
    "佐々木朗希": "佐佐木朗希", "小島和哉": "小島和哉", "種市篤暉": "種市篤暉",
    "メルセデス": "梅賽德斯",
    # SEI
    "高橋光成": "高橋光成", "平良海馬": "平良海馬", "今井達也": "今井達也",
    "ボー・タカハシ": "寶高橋",
    # HAM
    "伊藤大海": "伊藤大海", "加藤貴之": "加藤貴之", "金村尚真": "金村尚真",
    "マルティネス": "馬丁尼斯",
}

# 中文投手名 → NPB 球隊代碼（用於把頁面上找到的投手對應到正確球隊）
_NPB_PITCHER_TEAM: dict[str, str] = {
    # GNT 讀賣巨人
    "菅野智之": "GNT", "戶鄉翔征": "GNT", "葛瑞芬": "GNT", "赤星優志": "GNT",
    # HNS 阪神虎
    "才木浩人": "HNS", "村上頌樹": "HNS", "西勇輝": "HNS", "比茲利": "HNS",
    # HRC 廣島鯉魚
    "大瀨良大地": "HRC", "床田寬樹": "HRC", "九里亞蓮": "HRC", "漢恩": "HRC",
    # YDB 橫濱DeNA海星
    "東克樹": "YDB", "石田裕太郎": "YDB", "傑克森": "YDB", "大貫晉一": "YDB",
    # YKL 養樂多燕子
    "小川泰弘": "YKL", "高橋奎二": "YKL", "賽斯尼德": "YKL", "吉村貢司郎": "YKL",
    # CND 中日龍
    "大野雄大": "CND", "柳裕也": "CND", "梅希亞": "CND", "涌井秀章": "CND",
    # SBH 福岡軟銀鷹
    "莫伊內羅": "SBH", "有原航平": "SBH", "史都華特二世": "SBH", "東濱巨": "SBH",
    # ORX 歐力士水牛
    "山下舜平太": "ORX", "田嶋大樹": "ORX", "宮城大彌": "ORX", "艾斯皮諾薩": "ORX",
    # RKT 東北樂天金鷹
    "早川隆久": "RKT", "岸孝之": "RKT", "田中將大": "RKT", "塔利": "RKT",
    # LTT 千葉羅德水手
    "佐佐木朗希": "LTT", "小島和哉": "LTT", "種市篤暉": "LTT", "梅賽德斯": "LTT",
    # SEI 埼玉西武獅
    "高橋光成": "SEI", "平良海馬": "SEI", "今井達也": "SEI", "寶高橋": "SEI",
    # HAM 北海道火腿鬥士
    "伊藤大海": "HAM", "加藤貴之": "HAM", "金村尚真": "HAM", "馬丁尼斯": "HAM",
}

# 中文投手名 → KBO 球隊代碼
_KBO_PITCHER_TEAM: dict[str, str] = {
    # SSL 三星雄獅
    "元泰仁": "SSL", "阿貝吉": "SSL", "李在現": "SSL", "白正賢": "SSL",
    # LGT LG雙子星
    "林贊圭": "LGT", "凱利": "LGT", "孫柱榮": "LGT", "普魯特科": "LGT",
    # DSB 斗山熊
    "佛雷斯特": "DSB", "洪建熙": "DSB", "金澤亨": "DSB", "李承珍": "DSB",
    # KTW KT巫師
    "班傑明": "KTW", "奎瓦斯": "KTW", "高英杓": "KTW", "威爾克森": "KTW",
    # SSG SSG藍德
    "金廣鉉": "SSG", "朴鐘勳": "SSG", "羅薩里奧": "SSG", "吳源石": "SSG",
    # NCD NC恐龍
    "魯欽斯基": "NCD", "申敏爀": "NCD", "費迪": "NCD", "具昌模": "NCD",
    # KIA KIA老虎
    "梁鉉種": "KIA", "納夫": "KIA", "李義利": "KIA", "尹永哲": "KIA",
    # LTG 釜山樂天
    "格洛弗": "LTG", "史特萊利": "LTG", "朴世雄": "LTG", "姜賢浩": "LTG",
    # HWE 韓華老鷹
    "柳賢振": "HWE", "文東柱": "HWE", "卡特": "HWE", "查德貝爾": "HWE",
    # KWH 基咖英雄
    "安祐真": "KWH", "河榮敏": "KWH", "埃雷迪亞": "KWH", "金善紀": "KWH",
}

# 韓文 Hangul 投手名 → 中文名（koreabaseball.com / Naver Sports 頁面）
_KBO_PITCHER_KR_MAP: dict[str, str] = {
    # SSL 三星雄獅
    "원태인": "元泰仁", "이재현": "李在現", "백정현": "白正賢",
    # LGT LG雙子星
    "임찬규": "林贊圭", "손주영": "孫柱榮",
    "켈리": "凱利", "프루트코": "普魯特科",
    # DSB 斗山熊
    "홍건희": "洪建熙", "김택형": "金澤亨", "이승진": "李承珍",
    "포레스트": "佛雷斯特",
    # KTW KT巫師
    "고영표": "高英杓",
    "벤자민": "班傑明", "쿠에바스": "奎瓦斯", "윌커슨": "威爾克森",
    # SSG SSG藍德
    "김광현": "金廣鉉", "박종훈": "朴鐘勳", "오원석": "吳源石",
    "로사리오": "羅薩里奧",
    # NCD NC恐龍
    "신민혁": "申敏爀", "구창모": "具昌模",
    "루친스키": "魯欽斯基", "피디": "費迪",
    # KIA KIA老虎
    "양현종": "梁鉉種", "이의리": "李義利", "윤영철": "尹永哲",
    "네이브": "納夫",
    # LTG 釜山樂天
    "박세웅": "朴世雄", "강현호": "姜賢浩",
    "글로버": "格洛弗", "스트레일리": "史特萊利",
    # HWE 韓華老鷹
    "류현진": "柳賢振", "문동주": "文東柱",
    "카터": "卡特", "채드웰": "查德貝爾",
    # KWH 基咖英雄
    "안우진": "安祐真", "하영민": "河榮敏", "김선기": "金善紀",
    "에레디아": "埃雷迪亞",
}


def _yahoo_team_code(text: str) -> str:
    t = text.strip()
    for k, v in _YAHOO_NPB_TEAM_MAP.items():
        if k in t:
            return v
    return ""


def _translate_jp_pitcher(jp_name: str) -> str:
    """日文投手名 → 我們使用的中文名（找不到則原樣回傳）"""
    return _JP_PITCHER_NAME_MAP.get(jp_name.strip(), jp_name.strip())


def fetch_yahoo_npb_schedule(game_date: date) -> list[dict]:
    """
    baseball.yahoo.co.jp 抓 NPB 賽程與先發投手。
    只嘗試日期特定 URL，絕不回退到今日通用頁面（避免把今天的比賽寫入錯誤日期）。
    """
    date_str = game_date.isoformat()
    y, m, d  = game_date.year, game_date.month, game_date.day
    urls = [
        f"https://baseball.yahoo.co.jp/npb/schedule/{y:04d}{m:02d}{d:02d}/",
        f"https://baseball.yahoo.co.jp/npb/schedule/?date={y:04d}{m:02d}{d:02d}",
        # NOTE: do NOT add the dateless fallback URL here.
        # The generic URL always returns today's schedule, which would corrupt
        # future-date entries in schedule.json with today's games.
    ]
    for url in urls:
        try:
            time.sleep(random.uniform(1.0, 3.0))
            resp = requests.get(url, headers=_YAHOO_JP_HEADERS, timeout=15)
            if resp.status_code == 403:
                log.warning("Yahoo Japan NPB 403 (WAF blocked) for %s", url)
                continue
            if resp.status_code != 200:
                log.warning("Yahoo Japan NPB HTTP %s for %s", resp.status_code, url)
                continue
            resp.encoding = resp.apparent_encoding or "utf-8"
            games = _parse_yahoo_npb_html(resp.text, date_str)
            if games:
                log.info("Yahoo Japan NPB: parsed %d games from %s", len(games), url)
                return games
            else:
                log.warning("Yahoo Japan NPB: HTTP 200 but 0 games parsed from %s | "
                            "HTML len=%d title=%s",
                            url, len(resp.text),
                            (resp.text[:500].split('<title>')[1].split('</title>')[0].strip()
                             if '<title>' in resp.text else '(no title)'))
        except Exception as e:
            log.debug("Yahoo Japan NPB fetch %s: %s", url, e)
    return []


def _parse_yahoo_npb_html(html: str, date_str: str) -> list[dict]:
    """
    Parse Yahoo Japan NPB schedule using multi-phase text-scan approach.

    Phase 0.1: decode JSON \\uXXXX escapes in raw HTML, then search for team
               names (catches Next.js __NEXT_DATA__ JSON blobs with escaped Unicode).
    Phase 0.2: scan raw HTML for Yahoo Japan team URL patterns (/npb/teams/{code}/)
               as a structural fallback — stable even when team names are encoded.
    Phase 0:   scan <script> tags for pitcher names (before decompose).
    Phase 0.5: scan <script> text for team names (Japanese, via BeautifulSoup).
    Phase 1:   scan text nodes for team names (server-rendered content).
    Phase 2:   assign pitcher names to games by team membership.
    """
    # ── Phase 0.1: decode \\uXXXX then search decoded raw HTML for team codes ──
    # Next.js __NEXT_DATA__ JSON often stores Japanese chars as \\u5de8\\u4eba etc.
    decoded = re.sub(r'\\u([0-9a-fA-F]{4})',
                     lambda m: chr(int(m.group(1), 16)), html)
    sorted_team_keys_01 = sorted(_YAHOO_NPB_TEAM_MAP.keys(), key=len, reverse=True)
    team_pattern_01 = re.compile(
        '(' + '|'.join(re.escape(k) for k in sorted_team_keys_01) + ')'
    )
    codes_from_decoded: list[str] = []
    for m in team_pattern_01.finditer(decoded):
        code = _YAHOO_NPB_TEAM_MAP[m.group()]
        if not codes_from_decoded or codes_from_decoded[-1] != code:
            codes_from_decoded.append(code)
    if codes_from_decoded:
        log.info("Yahoo Japan Phase-0.1 (decoded HTML): %d entries %s",
                 len(codes_from_decoded), codes_from_decoded[:12])

    # ── Phase 0.2: scan raw HTML for Yahoo Japan team URL codes ───────────────
    # e.g. href="/npb/teams/g/" → Giants,  href="/npb/teams/sb/" → SoftBank
    # URL structure is stable even when all text content is client-side rendered.
    _YAHOO_URL_CODE: dict[str, str] = {
        "g": "GNT", "t": "HNS", "c": "HRC", "db": "YDB",
        "s": "YKL", "d": "CND", "sb": "SBH", "b": "ORX",
        "e": "RKT", "m": "LTT", "l": "SEI", "f": "HAM",
    }
    _team_url_re = re.compile(r'/npb/(?:team|teams)/([a-z]+)(?:/|")')
    codes_from_urls: list[str] = []
    for m in _team_url_re.finditer(html):
        code = _YAHOO_URL_CODE.get(m.group(1))
        if code and (not codes_from_urls or codes_from_urls[-1] != code):
            codes_from_urls.append(code)
    if codes_from_urls:
        log.info("Yahoo Japan Phase-0.2 (URL codes): %d entries %s",
                 len(codes_from_urls), codes_from_urls[:12])

    soup = BeautifulSoup(html, "html.parser")

    # ── Phase 0: scan <script> tags BEFORE removing them ─────────────────
    # Yahoo Japan (and many modern JP sites) embed pitcher data in JS/JSON blobs.
    # We must check script content before the decompose loop throws it away.
    sorted_pitcher_keys_p0 = sorted(_JP_PITCHER_NAME_MAP.keys(), key=len, reverse=True)
    pitcher_pattern_p0 = re.compile(
        '(' + '|'.join(re.escape(k) for k in sorted_pitcher_keys_p0) + ')'
    )
    found_in_scripts: set[str] = set()
    for script in soup.find_all('script'):
        sc = script.get_text() or ""
        for m in pitcher_pattern_p0.finditer(sc):
            found_in_scripts.add(_JP_PITCHER_NAME_MAP[m.group()])
    if found_in_scripts:
        log.info("Yahoo Japan Phase-0 (scripts): found pitchers %s", found_in_scripts)
    else:
        log.debug("Yahoo Japan Phase-0 (scripts): no pitcher names found in script tags")

    # ── Phase 0.5: scan script content for team codes (handles Next.js JSON blobs) ──
    # Modern Yahoo Japan pages (Next.js/React) embed schedule data in <script> tags.
    # Phase 1 below only reads short text nodes, missing the JSON blob entirely.
    sorted_team_keys_p05 = sorted(_YAHOO_NPB_TEAM_MAP.keys(), key=len, reverse=True)
    team_pattern_p05 = re.compile(
        '(' + '|'.join(re.escape(k) for k in sorted_team_keys_p05) + ')'
    )
    codes_from_scripts: list[str] = []
    for script in soup.find_all('script'):
        sc = script.get_text() or ""
        if not sc.strip():
            continue
        for m in team_pattern_p05.finditer(sc):
            code = _YAHOO_NPB_TEAM_MAP[m.group()]
            if not codes_from_scripts or codes_from_scripts[-1] != code:
                codes_from_scripts.append(code)
    if codes_from_scripts:
        log.info("Yahoo Japan Phase-0.5 (scripts team scan): %d code entries %s",
                 len(codes_from_scripts), codes_from_scripts[:12])
    else:
        log.warning("Yahoo Japan Phase-0.5: no team codes found in script tags either")

    # Choose best candidate for seeding codes_in_order (prefer decoded-HTML result,
    # fall back to Phase 0.5 scripts result, then Phase 0.2 URL codes as last resort)
    if codes_from_decoded:
        seed_codes = codes_from_decoded
    elif codes_from_scripts:
        seed_codes = codes_from_scripts
    else:
        seed_codes = codes_from_urls
        if codes_from_urls:
            log.info("Yahoo Japan: falling back to URL-code seed (%d entries)", len(codes_from_urls))

    for tag in soup.find_all(['script', 'style', 'noscript', 'head', 'nav', 'footer']):
        tag.decompose()

    # ── Phase 1: Team code extraction (text nodes, picks up server-rendered content) ──
    sorted_team_keys = sorted(_YAHOO_NPB_TEAM_MAP.keys(), key=len, reverse=True)
    team_pattern = re.compile('(' + '|'.join(re.escape(k) for k in sorted_team_keys) + ')')

    # Start with best seed; text node scan appends additional matches
    codes_in_order: list[str] = list(seed_codes)
    for node in soup.find_all(string=True):
        text = node.strip()
        if not text or len(text) > 50:
            continue
        for m in team_pattern.finditer(text):
            code = _YAHOO_NPB_TEAM_MAP[m.group()]
            if not codes_in_order or codes_in_order[-1] != code:
                codes_in_order.append(code)

    games: list[dict] = []
    seen: set[tuple] = set()
    i = 0
    while i < len(codes_in_order) - 1:
        c1, c2 = codes_in_order[i], codes_in_order[i + 1]
        if c1 != c2:
            key = tuple(sorted((c1, c2)))
            if key not in seen:
                seen.add(key)
                games.append({
                    "game_id":      f"{date_str}-{c1}-{c2}",
                    "date":         date_str,
                    "time":         "",
                    "away":         c1,
                    "away_name":    "",
                    "home":         c2,
                    "home_name":    "",
                    "venue":        "",
                    "league":       "NPB",
                    "status":       "預定",
                    "away_score":   None,
                    "home_score":   None,
                    "away_pitcher": "",
                    "home_pitcher": "",
                    "_source":      "yahoo_jp",
                })
            i += 2
        else:
            i += 1

    # ── Phase 2: Pitcher name extraction ─────────────────────────────────
    if games and _JP_PITCHER_NAME_MAP:
        sorted_pitcher_keys = sorted(_JP_PITCHER_NAME_MAP.keys(), key=len, reverse=True)
        pitcher_pattern = re.compile(
            '(' + '|'.join(re.escape(k) for k in sorted_pitcher_keys) + ')'
        )
        # Collect from regular text nodes (no length cap — let the pattern do the filtering)
        found_zh: set[str] = set(found_in_scripts)  # seed with script-tag finds
        for node in soup.find_all(string=True):
            text = node.strip()
            if not text or len(text) > 50:
                continue
            for m in pitcher_pattern.finditer(text):
                found_zh.add(_JP_PITCHER_NAME_MAP[m.group()])
        log.info("Yahoo Japan Phase-2: found pitcher names %s", found_zh or "(none)")

        # Assign each found pitcher to the game matching their team
        for g in games:
            for zh in found_zh:
                team = _NPB_PITCHER_TEAM.get(zh, "")
                if team == g["away"] and not g["away_pitcher"]:
                    g["away_pitcher"] = zh
                elif team == g["home"] and not g["home_pitcher"]:
                    g["home_pitcher"] = zh

        pitcher_count = sum(1 for g in games if g["away_pitcher"] or g["home_pitcher"])
        if pitcher_count:
            log.info("Yahoo Japan: extracted pitchers for %d/%d games", pitcher_count, len(games))

    # ── Validate ──────────────────────────────────────────────────────────
    valid = [g for g in games
             if g["away"] in _YAHOO_NPB_TEAM_MAP.values()
             and g["home"] in _YAHOO_NPB_TEAM_MAP.values()]
    if len(valid) != len(games):
        log.debug("Yahoo Japan: dropped %d games with unknown team codes", len(games) - len(valid))
    return valid


# 删除舊的 CPBL 官網函數，保留 stub 避免 import 錯誤
def fetch_cpbl_pitcher_stats(year: int) -> dict[str, dict]:
    """廢棄 — CPBL 官網已被 WAF 封鎖。回傳空 dict。"""
    log.debug("fetch_cpbl_pitcher_stats: CPBL site removed, returning empty")
    return {}


# ── Yahoo Japan 予告先発 (dedicated starter page) ────────────────────────────

def fetch_yahoo_npb_starter_page(game_date: date) -> list[dict]:
    """
    Yahoo Japan 予告先発ページ (baseball.yahoo.co.jp/npb/starter/) から
    本日の先発投手を取得する。

    スケジュールページと異なり、このページは先発投手が主コンテンツなので
    静的辞書なしで投手名を抽出できる。
    Returns list of {away, home, away_pitcher_jp, home_pitcher_jp, date}
    """
    urls = [
        "https://baseball.yahoo.co.jp/npb/starter/",
        f"https://baseball.yahoo.co.jp/npb/starter/?date={game_date.year:04d}{game_date.month:02d}{game_date.day:02d}",
    ]
    for url in urls:
        try:
            time.sleep(random.uniform(0.5, 1.5))
            resp = requests.get(url, headers=_YAHOO_JP_HEADERS, timeout=15)
            if resp.status_code != 200:
                log.debug("Yahoo starter page HTTP %s for %s", resp.status_code, url)
                continue
            resp.encoding = resp.apparent_encoding or "utf-8"
            results = _parse_yahoo_starter_html(resp.text, game_date)
            if results:
                log.info("Yahoo starter page: %d pitcher pairs for %s", len(results), game_date)
                return results
        except Exception as e:
            log.debug("Yahoo starter page %s: %s", url, e)
    return []


def _parse_yahoo_starter_html(html: str, game_date: date) -> list[dict]:
    """
    Parse the Yahoo Japan 予告先発 (announced starters) page.

    Strategy: Find game-card elements containing two team names and two pitcher
    name slots. Extract pitcher names WITHOUT relying on a static name dictionary
    — any name found in the pitcher slot is stored as-is (in Japanese).
    """
    date_str = game_date.isoformat()
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    # Strategy A: JSON data embedded in <script> tags (Next.js / React hydration)
    for script in soup.find_all("script"):
        text = script.string or ""
        # Look for JSON structures with starter/pitcher fields
        # Pattern: "starter":{"away":"PitcherName","home":"PitcherName"}
        starter_re = re.compile(
            r'"(?:starter|予告先発|startingPitcher)"'
            r'\s*:\s*\{'
            r'[^}]*?"(?:away|visitor|client)\s*"\s*:\s*"([^"]+)"'
            r'[^}]*?"home\s*"\s*:\s*"([^"]+)"',
            re.IGNORECASE,
        )
        for m in starter_re.finditer(text):
            log.debug("Yahoo starter JSON found: %s / %s", m.group(1), m.group(2))

    # Strategy B: Structured HTML — look for game card pattern
    # Each game card should contain team names (mappable via _YAHOO_NPB_TEAM_MAP)
    # and associated pitcher names
    team_keys_sorted = sorted(_YAHOO_NPB_TEAM_MAP.keys(), key=len, reverse=True)
    team_pat = re.compile("(" + "|".join(re.escape(k) for k in team_keys_sorted) + ")")

    # Japanese name pattern: 2-6 kanji/kana characters (covers most pitcher names)
    # This catches names like 菅野智之, 才木浩人, サイスニード, etc.
    jp_name_pat = re.compile(r'[一-鿿぀-ゟ゠-ヿ＀-￯]{2,8}')

    # Remove non-content tags first
    for tag in soup.find_all(["script", "style", "noscript", "head", "nav", "footer"]):
        tag.decompose()

    # Try to find card-like containers that hold both team info and pitcher info
    # Common patterns: <li>, <div class=*game*>, <section class=*match*>, <tr>
    candidate_containers = (
        soup.find_all("li", class_=re.compile(r"game|match|card|starter", re.I))
        or soup.find_all("div", class_=re.compile(r"game|match|card|starter", re.I))
        or soup.find_all("tr", class_=re.compile(r"game|match|starter", re.I))
    )

    for container in candidate_containers:
        text = container.get_text(" ", strip=True)
        teams = team_pat.findall(text)
        if len(teams) < 2:
            continue
        away_code = _YAHOO_NPB_TEAM_MAP.get(teams[0], "")
        home_code = _YAHOO_NPB_TEAM_MAP.get(teams[-1], "")
        if not away_code or not home_code or away_code == home_code:
            continue

        # Look for pitcher name in adjacent elements (span, td, etc.)
        # Typically: child elements after the team name element
        all_jp = jp_name_pat.findall(text)
        # Remove team name tokens from the list
        pitcher_candidates = [n for n in all_jp if not team_pat.match(n) and len(n) >= 2]

        away_pitcher = pitcher_candidates[0] if len(pitcher_candidates) > 0 else ""
        home_pitcher = pitcher_candidates[1] if len(pitcher_candidates) > 1 else ""

        results.append({
            "date":             date_str,
            "away":             away_code,
            "home":             home_code,
            "away_pitcher_jp":  away_pitcher,
            "home_pitcher_jp":  home_pitcher,
        })

    if results:
        return results

    # Strategy C: simple text-scan fallback
    # Walk all text, collect (team_code, next_word) pairs
    text_nodes = [n.strip() for n in soup.find_all(string=True) if n.strip()]
    i = 0
    gathered: list[tuple[str, str]] = []  # (team_code, pitcher_name)
    while i < len(text_nodes):
        node = text_nodes[i]
        m = team_pat.search(node)
        if m:
            code = _YAHOO_NPB_TEAM_MAP[m.group()]
            # The pitcher name is often in the next 1–3 text nodes
            pitcher = ""
            for j in range(i + 1, min(i + 4, len(text_nodes))):
                candidate = text_nodes[j].strip()
                if team_pat.search(candidate):
                    break  # hit next team name — no pitcher announced
                if (jp_name_pat.match(candidate) and len(candidate) <= 8
                        and not re.search(r'\d', candidate)):
                    pitcher = candidate
                    break
            gathered.append((code, pitcher))
        i += 1

    # Pair consecutive teams into games
    j = 0
    while j + 1 < len(gathered):
        away_code, away_pitcher = gathered[j]
        home_code, home_pitcher = gathered[j + 1]
        if away_code != home_code:
            results.append({
                "date":             date_str,
                "away":             away_code,
                "home":             home_code,
                "away_pitcher_jp":  away_pitcher,
                "home_pitcher_jp":  home_pitcher,
            })
            j += 2
        else:
            j += 1

    return results


def enrich_schedule_with_starters(
    game_date: date,
    games: list[dict],
) -> None:
    """
    Use the Yahoo Japan 予告先発 page to fill in pitcher names for games
    that currently have no away_pitcher / home_pitcher set.
    Modifies games in-place.
    """
    if not games:
        return
    starters = fetch_yahoo_npb_starter_page(game_date)
    if not starters:
        log.info("enrich_schedule_with_starters: no starters found for %s", game_date)
        return

    # Index starter info by (away, home) pair
    starter_map = {(s["away"], s["home"]): s for s in starters}

    enriched = 0
    for g in games:
        if g.get("league") != "NPB":
            continue
        key = (g.get("away", ""), g.get("home", ""))
        s = starter_map.get(key)
        if not s:
            continue
        if s.get("away_pitcher_jp") and not g.get("away_pitcher"):
            # Translate JP name → Chinese if available, else keep JP
            g["away_pitcher"] = _translate_jp_pitcher(s["away_pitcher_jp"])
            enriched += 1
        if s.get("home_pitcher_jp") and not g.get("home_pitcher"):
            g["home_pitcher"] = _translate_jp_pitcher(s["home_pitcher_jp"])
            enriched += 1

    if enriched:
        log.info("enrich_schedule_with_starters: filled %d pitcher slots for %s",
                 enriched, game_date)


# ── KBO official starter page ────────────────────────────────────────────────

def fetch_koreabaseball_starters(game_date: date) -> list[dict]:
    """
    koreabaseball.com 예고선발 (announced KBO starters).
    URL: https://www.koreabaseball.com/Game/Starter.aspx
    Returns list of {away, home, away_pitcher_kr, home_pitcher_kr, date}
    """
    url = "https://www.koreabaseball.com/Game/Starter.aspx"
    _kb_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.5",
        "Referer": "https://www.koreabaseball.com/",
    }
    date_str = game_date.isoformat()
    try:
        time.sleep(random.uniform(0.5, 1.5))
        resp = requests.get(url, headers=_kb_headers, timeout=15)
        if resp.status_code != 200:
            log.debug("koreabaseball starter page HTTP %s", resp.status_code)
            return []
        resp.encoding = resp.apparent_encoding or "utf-8"
        return _parse_koreabaseball_starter_html(resp.text, date_str)
    except Exception as e:
        log.debug("koreabaseball starter page: %s", e)
        return []


def _parse_koreabaseball_starter_html(html: str, date_str: str) -> list[dict]:
    """
    Parse koreabaseball.com 예고선발 page.
    The page has a table with columns: 원정팀 투수 / 원정팀 / 홈팀 / 홈팀 투수
    (away pitcher / away team / home team / home pitcher)
    """
    soup = BeautifulSoup(html, "html.parser")
    results: list[dict] = []

    # KBO team map (Korean → internal code)
    _KB_TEAM_MAP = {
        "삼성":    "SSL", "라이온즈": "SSL",
        "LG":      "LGT", "트윈스":  "LGT",
        "두산":    "DSB", "베어스":  "DSB",
        "KT":      "KTW", "위즈":    "KTW",
        "SSG":     "SSG", "랜더스":  "SSG",
        "NC":      "NCD", "다이노스": "NCD",
        "KIA":     "KIA", "타이거즈": "KIA",
        "롯데":    "LTG", "자이언츠": "LTG",
        "한화":    "HWE", "이글스":  "HWE",
        "키움":    "KWH", "히어로즈": "KWH",
    }
    team_keys = sorted(_KB_TEAM_MAP.keys(), key=len, reverse=True)
    team_pat = re.compile("(" + "|".join(re.escape(k) for k in team_keys) + ")")

    # Try to find the starter table
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows[1:]:  # skip header
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 4:
                continue
            # Typical layout: [away_pitcher, away_team, home_team, home_pitcher]
            # or: [away_team, away_pitcher, home_team, home_pitcher]
            # Try to identify which cells contain team names
            team_cells = [(i, _KB_TEAM_MAP.get(c, "")) for i, c in enumerate(cells)
                          if team_pat.search(c)]
            if len(team_cells) < 2:
                continue
            away_idx, away_code = team_cells[0]
            home_idx, home_code = team_cells[-1]
            if not away_code or not home_code or away_code == home_code:
                continue
            # Pitcher is typically adjacent to the team name
            away_pitcher = cells[away_idx - 1] if away_idx > 0 else ""
            home_pitcher = cells[home_idx + 1] if home_idx + 1 < len(cells) else ""
            # Fallback: pitcher immediately after team cell
            if not away_pitcher and away_idx + 1 < len(cells):
                away_pitcher = cells[away_idx + 1]
            if not home_pitcher and home_idx > 0:
                home_pitcher = cells[home_idx - 1]

            results.append({
                "date":              date_str,
                "away":              away_code,
                "home":              home_code,
                "away_pitcher_kr":   away_pitcher,
                "home_pitcher_kr":   home_pitcher,
            })

    return results


def enrich_kbo_with_starters(game_date: date, games: list[dict]) -> None:
    """
    Use koreabaseball.com 예고선발 page to fill in KBO pitcher names.
    Modifies games in-place.
    """
    if not games:
        return
    starters = fetch_koreabaseball_starters(game_date)
    if not starters:
        log.debug("enrich_kbo_with_starters: no starters for %s", game_date)
        return

    starter_map = {(s["away"], s["home"]): s for s in starters}
    enriched = 0
    for g in games:
        if g.get("league") != "KBO":
            continue
        key = (g.get("away", ""), g.get("home", ""))
        s = starter_map.get(key)
        if not s:
            continue
        if s.get("away_pitcher_kr") and not g.get("away_pitcher"):
            zh = _KBO_PITCHER_KR_MAP.get(s["away_pitcher_kr"], s["away_pitcher_kr"])
            g["away_pitcher"] = zh
            enriched += 1
        if s.get("home_pitcher_kr") and not g.get("home_pitcher"):
            zh = _KBO_PITCHER_KR_MAP.get(s["home_pitcher_kr"], s["home_pitcher_kr"])
            g["home_pitcher"] = zh
            enriched += 1

    if enriched:
        log.info("enrich_kbo_with_starters: filled %d KBO pitcher slots for %s",
                 enriched, game_date)


# ── nk-datasets 整合：NPB/KBO 真實投打數據 ─────────────────────────────────

# nk-datasets teamID → 本系統 team code
_NK_NPB_TEAM = {
    "YOMIURI": "GNT", "HANSHIN": "HNS", "HIROSHIMA": "HRC",
    "DENA": "YDB",    "YAKULT":  "YKL", "CHUNICHI":  "CND",
    "SOFTBANK":"SBH",  "ORIX":   "ORX", "RAKUTEN":   "RKT",
    "LOTTE":   "LTT",  "SEIBU":  "SEI", "NIPPON-HAM":"HAM",
}
_NK_KBO_TEAM = {
    "Samsung": "SSL", "LG":      "LGT", "Doosan": "DSB",
    "KT":      "KTW", "SSG":     "SSG", "NC":     "NCD",
    "KIA":     "KIA", "Lotte":   "LTG", "Hanwha": "HWE",
    "Kiwoom":  "KWH",
}


def _calc_fip(hr, bb, hbp, k, ip_val, fip_c):
    if ip_val <= 0:
        return None
    return round(((hr * 13 + (bb + hbp) * 3 - k * 2) / ip_val) + fip_c, 3)


def _safe(val, default=0.0):
    try:
        v = float(val)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def fetch_pitcher_stats_nk(year: int | None = None) -> dict:
    """
    nk-datasets から NPB/KBO 投手成績を取得し pitcher_stats.json 形式で返す。

    Returns: dict  {player_name: {team, era, fip, whip, k9, bb9, ...}, ...}
    """
    try:
        import nk
        import pandas as pd
    except ImportError:
        log.warning("nk-datasets not installed — run: pip install nk-datasets pandas")
        return {}

    import warnings
    warnings.filterwarnings("ignore")

    current_year = year or date.today().year
    prev_year = current_year - 1

    result: dict = {}

    def _process_pitchers(df_pit, df_people, team_map, fip_c, league):
        for yr in [current_year, prev_year]:
            mask = pd.to_numeric(df_pit.get("yearID", pd.Series(dtype=str)), errors="coerce") == yr
            yr_df = df_pit[mask].copy()
            if yr_df.empty:
                continue

            # Merge player names
            people_cols = [c for c in ["playerID", "nameLast", "nameFirst"] if c in df_people.columns]
            if len(people_cols) >= 1:
                yr_df = yr_df.merge(df_people[people_cols], on="playerID", how="left")
                yr_df["_name"] = (yr_df.get("nameFirst", pd.Series([""] * len(yr_df))).fillna("") +
                                  " " +
                                  yr_df.get("nameLast", pd.Series([""] * len(yr_df))).fillna("")).str.strip()
            else:
                yr_df["_name"] = yr_df["playerID"].astype(str)

            for _, row in yr_df.iterrows():
                name = str(row.get("_name", "")).strip()
                if not name or name == "nan":
                    continue
                tid = str(row.get("teamID", "")).strip()
                team_code = team_map.get(tid, "")
                if not team_code:
                    continue

                ipo   = _safe(row.get("IPouts"), 0.0)
                ip    = ipo / 3.0
                er    = _safe(row.get("ER"),  0.0)
                so    = _safe(row.get("SO"),  0.0)
                bb    = _safe(row.get("BB"),  0.0)
                hbp   = _safe(row.get("HBP"), 0.0)
                hr    = _safe(row.get("HR"),  0.0)
                h_val = _safe(row.get("H"),   0.0)
                g_val = _safe(row.get("G"),   1.0)

                if ip < 3.0:
                    continue  # 太少局數，跳過

                era  = round(er / ip * 9, 3) if ip > 0 else None
                raw_era = _safe(row.get("ERA"), era or 4.0)
                if era is None:
                    era = raw_era

                whip  = round((h_val + bb) / ip, 3) if ip > 0 else None
                k9    = round(so / ip * 9, 3)       if ip > 0 else None
                bb9   = round(bb / ip * 9, 3)       if ip > 0 else None
                hr9   = round(hr / ip * 9, 3)       if ip > 0 else None
                fip   = _calc_fip(hr, bb, hbp, so, ip, fip_c)
                avg_ip_per_g = round(ip / g_val, 2) if g_val > 0 else None

                # 先發 vs 牛棚判斷
                gs_val = _safe(row.get("GS"), None)
                if gs_val is None:
                    is_starter = (avg_ip_per_g or 0) >= 4.5
                else:
                    is_starter = gs_val >= (g_val * 0.5)

                entry = {
                    "team":       team_code,
                    "league":     league,
                    "year":       int(yr),
                    "era":        era,
                    "fip":        fip,
                    "whip":       whip,
                    "k9":         k9,
                    "bb9":        bb9,
                    "hr9":        hr9,
                    "ip":         round(ip, 1),
                    "g":          int(g_val),
                    "avg_ip":     avg_ip_per_g,
                    "is_starter": is_starter,
                    "source":     "nk-datasets",
                }
                # 只保留最新年份（若同名投手有多年，新年份覆蓋舊的）
                existing = result.get(name, {})
                if not existing or existing.get("year", 0) <= yr:
                    result[name] = entry

    # ── NPB ──────────────────────────────────────────────────────────────
    try:
        npb_pit    = nk.load_npb_pitching()
        npb_people = nk.load_npb_people()
        _process_pitchers(npb_pit, npb_people, _NK_NPB_TEAM, _FIP_CONSTANT_NPB, "NPB")
        log.info("nk-datasets NPB pitchers loaded: %d entries", sum(1 for v in result.values() if v.get("league") == "NPB"))
    except Exception as e:
        log.warning("nk-datasets NPB pitching failed: %s", e)

    # ── KBO ──────────────────────────────────────────────────────────────
    try:
        kbo_pit    = nk.load_kbo_pitching()
        kbo_people = nk.load_kbo_people()
        _process_pitchers(kbo_pit, kbo_people, _NK_KBO_TEAM, _FIP_CONSTANT_KBO, "KBO")
        log.info("nk-datasets KBO pitchers loaded: %d entries", sum(1 for v in result.values() if v.get("league") == "KBO"))
    except Exception as e:
        log.warning("nk-datasets KBO pitching failed: %s", e)

    return result


def fetch_team_stats_nk(year: int | None = None) -> dict:
    """
    nk-datasets から NPB/KBO チーム打撃/投球成績を取得。

    Returns: dict  {team_code: {"batting": {...}, "pitching": {...}}}
    """
    try:
        import nk
        import pandas as pd
    except ImportError:
        return {}

    import warnings
    warnings.filterwarnings("ignore")

    current_year = year or date.today().year
    prev_year    = current_year - 1
    result: dict = {}

    def _team_bat(df_bat, team_map, fip_c, league):
        for yr in [current_year, prev_year]:
            mask  = pd.to_numeric(df_bat.get("yearID", pd.Series(dtype=str)), errors="coerce") == yr
            yr_df = df_bat[mask].copy()
            if yr_df.empty:
                continue
            for col in ["AB", "H", "HR", "BB", "HBP", "SF", "TB", "R", "PA", "G",
                        "OPS", "OBP", "SLG", "AVG", "wRC+"]:
                if col in yr_df.columns:
                    yr_df[col] = pd.to_numeric(yr_df[col], errors="coerce").fillna(0)
            team_grp = yr_df.groupby("teamID")
            for tid, grp in team_grp:
                tc = team_map.get(tid, "")
                if not tc:
                    continue
                total_ab = grp["AB"].sum()
                total_h  = grp["H"].sum()
                total_hr = grp["HR"].sum()
                total_bb = grp["BB"].sum()
                total_g  = grp["G"].sum()
                # weighted avg OPS (by AB) — use None if data is absent/zero
                ops = None
                if "OPS" in grp.columns and total_ab > 0:
                    raw_ops = float((grp["OPS"] * grp["AB"]).sum() / total_ab)
                    if raw_ops > 0.01:
                        ops = raw_ops
                if ops is None and "TB" in grp.columns:
                    total_tb = grp["TB"].sum()
                    if total_tb > 0 and total_ab > 0:
                        obp = (total_h + total_bb) / max(1, total_ab + total_bb)
                        slg = total_tb / total_ab
                        ops = obp + slg
                wrc_col = "wRC+" if "wRC+" in grp.columns else None
                wrc_raw = float((grp[wrc_col] * grp["AB"]).sum() / max(1, total_ab)) if wrc_col else 0.0
                wrc = wrc_raw if wrc_raw > 1.0 else None
                hrpg = total_hr / max(1, total_g / 9)
                bat: dict = {
                    "hr_per_game":  round(float(hrpg), 3),
                    "runs_per_game": round(float(grp["R"].sum() / max(1, total_g / 9)), 3),
                    "year":         int(yr),
                }
                if ops is not None:
                    bat["ops"] = round(ops, 4)
                if wrc is not None:
                    bat["wrc_plus"] = round(wrc, 1)
                existing = result.setdefault(tc, {})
                if not existing.get("batting") or existing["batting"].get("year", 0) <= yr:
                    existing["batting"] = bat
                    existing["league"]  = league

    def _team_pit(df_pit, team_map, fip_c, league):
        for yr in [current_year, prev_year]:
            mask  = pd.to_numeric(df_pit.get("yearID", pd.Series(dtype=str)), errors="coerce") == yr
            yr_df = df_pit[mask].copy()
            if yr_df.empty:
                continue
            for col in ["IPouts", "ER", "SO", "BB", "HBP", "HR", "H", "G"]:
                if col in yr_df.columns:
                    yr_df[col] = pd.to_numeric(yr_df[col], errors="coerce").fillna(0)
            team_grp = yr_df.groupby("teamID")
            for tid, grp in team_grp:
                tc = team_map.get(tid, "")
                if not tc:
                    continue
                ip   = grp["IPouts"].sum() / 3.0
                er   = grp["ER"].sum()
                so   = grp["SO"].sum()
                bb   = grp["BB"].sum()
                hbp  = grp["HBP"].sum()
                hr   = grp["HR"].sum()
                h_v  = grp["H"].sum()
                era  = round(er / max(1, ip) * 9,  3)
                whip = round((h_v + bb) / max(1, ip), 3)
                k9   = round(so / max(1, ip) * 9,  3)
                bb9  = round(bb / max(1, ip) * 9,  3)
                fip  = _calc_fip(hr, bb, hbp, so, ip, fip_c)
                pit  = {"era": era, "whip": whip, "k9": k9, "bb9": bb9,
                        "fip": fip, "year": int(yr)}
                existing = result.setdefault(tc, {})
                if not existing.get("pitching") or existing["pitching"].get("year", 0) <= yr:
                    existing["pitching"] = pit

    try:
        import nk
        npb_bat = nk.load_npb_batting()
        npb_pit = nk.load_npb_pitching()
        _team_bat(npb_bat, _NK_NPB_TEAM, _FIP_CONSTANT_NPB, "NPB")
        _team_pit(npb_pit, _NK_NPB_TEAM, _FIP_CONSTANT_NPB, "NPB")
    except Exception as e:
        log.warning("nk-datasets NPB team stats failed: %s", e)

    try:
        import nk
        kbo_bat = nk.load_kbo_batting()
        kbo_pit = nk.load_kbo_pitching()
        _team_bat(kbo_bat, _NK_KBO_TEAM, _FIP_CONSTANT_KBO, "KBO")
        _team_pit(kbo_pit, _NK_KBO_TEAM, _FIP_CONSTANT_KBO, "KBO")
    except Exception as e:
        log.warning("nk-datasets KBO team stats failed: %s", e)

    log.info("nk-datasets team stats: %d teams", len(result))
    return result


# ── FanGraphs International (NPB / KBO only — never MLB) ─────────────────────

# FanGraphs column name → internal field name
_FG_COL_MAP = {
    "ERA":   "era",   "FIP":   "fip",   "xFIP":  "xfip",
    "WHIP":  "whip",  "K/9":   "k9",    "BB/9":  "bb9",
    "K%":    "k_pct", "BB%":   "bb_pct","BABIP": "babip",
    "LOB%":  "lob_pct","IP":   "innings","W":     "wins",
    "L":     "losses","G":     "g",     "GS":    "gs",
}

# FanGraphs team name → internal code (NPB)
_FG_NPB_TEAM_MAP = {
    "Giants":    "GNT", "Tigers":    "HNS", "Carp":      "HRC",
    "BayStars":  "YDB", "Swallows":  "YKL", "Dragons":   "CND",
    "Hawks":     "SBH", "Buffaloes": "ORX", "Eagles":    "RKT",
    "Marines":   "LTT", "Lions":     "SEI", "Fighters":  "HAM",
}

# FanGraphs team name → internal code (KBO)
_FG_KBO_TEAM_MAP = {
    "Samsung": "SSL", "LG":      "LGT", "Doosan": "DSB",
    "KT":      "KTW", "SSG":     "SSG", "NC":     "NCD",
    "KIA":     "KIA", "Lotte":   "LTG", "Hanwha": "HWE",
    "Kiwoom":  "KWH",
}


def _parse_fangraphs_intl(data, league: str) -> dict:
    """
    Parse FanGraphs international leaders JSON response.
    league must be 'NPB' or 'KBO' (never MLB).
    """
    team_map = _FG_NPB_TEAM_MAP if league == "NPB" else _FG_KBO_TEAM_MAP

    # FanGraphs API returns either {"data": [...]} or a list directly
    rows = data if isinstance(data, list) else data.get("data", [])
    if not rows:
        return {}

    result: dict = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        # Possible player name keys
        name = (row.get("PlayerName") or row.get("playerName")
                or row.get("Name") or row.get("name") or "").strip()
        if not name:
            continue

        p: dict = {"league": league}

        # Map numeric stat columns
        for fg_col, our_key in _FG_COL_MAP.items():
            raw = row.get(fg_col)
            if raw is None:
                continue
            val_str = str(raw).replace("%", "").strip()
            try:
                p[our_key] = float(val_str)
            except (ValueError, TypeError):
                pass

        if "era" not in p:
            continue

        # Map team name
        team_raw = (row.get("Team") or row.get("team") or "").strip()
        team_code = team_map.get(team_raw, "")
        if not team_code:
            # Fuzzy match
            for k, v in team_map.items():
                if k.lower() in team_raw.lower() or team_raw.lower() in k.lower():
                    team_code = v
                    break
        if team_code:
            p["team"] = team_code

        enrich_pitcher(p)
        result[name] = p

    log.info("FanGraphs %s: parsed %d pitchers", league, len(result))
    return result


def fetch_fangraphs_international(year: int | None = None, league: str = "NPB") -> dict:
    """
    FanGraphs international pitcher stats — NPB or KBO ONLY (never MLB).
    Tries the internal /api/leaders/international/data endpoint first (returns JSON).
    league: 'NPB' or 'KBO'
    """
    _year = year or date.today().year
    # FanGraphs internal API — returns JSON without JS rendering
    api_url = (
        f"https://www.fangraphs.com/api/leaders/international/data"
        f"?pos=P&stats=pit&lg={league}&qual=0&season={_year}&type=8"
        f"&month=0&ind=0&team=0&pageitems=500&pagenum=1"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "en-US,en;q=0.9,ja;q=0.8,ko;q=0.7",
        "Referer": f"https://www.fangraphs.com/leaders/international?lg={league}&stats=pit&pos=P",
        "X-Requested-With": "XMLHttpRequest",
    }
    try:
        resp = requests.get(api_url, headers=headers, timeout=15)
        if resp.status_code in (403, 429):
            log.debug("FanGraphs %s API: HTTP %s", league, resp.status_code)
            return {}
        resp.raise_for_status()
        data = resp.json()
        return _parse_fangraphs_intl(data, league)
    except Exception as e:
        log.debug("FanGraphs %s: %s", league, e)
        return {}


def fetch_fangraphs_npb_kbo(year: int | None = None) -> dict:
    """Fetch both NPB and KBO from FanGraphs (NO MLB)."""
    result = {}
    for lg in ("NPB", "KBO"):
        result.update(fetch_fangraphs_international(year, lg))
    return result


# ── baseballdata.jp — NPB pitcher stats (static HTML tables) ─────────────────

# baseballdata.jp team abbreviation → internal code
_BD_NPB_TEAM_MAP = {
    "G": "GNT", "T": "HNS", "C": "HRC", "DB": "YDB",
    "S": "YKL", "D": "CND", "H": "SBH", "B":  "ORX",
    "E": "RKT", "M": "LTT", "L": "SEI", "F":  "HAM",
}

_BD_COL_MAP = {
    "Name":    "name",  "Player":  "name",  "選手":   "name",
    "Team":    "team",  "球団":    "team",
    "ERA":     "era",   "防御率":  "era",
    "FIP":     "fip",   "xFIP":   "xfip",
    "WHIP":    "whip",
    "K/9":     "k9",    "BB/9":   "bb9",
    "K%":      "k_pct", "BB%":    "bb_pct",
    "BABIP":   "babip", "LOB%":   "lob_pct",
    "IP":      "innings","W":      "wins",
    "L":       "losses","G":      "g",     "GS":    "gs",
}

_BD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


def fetch_baseballdata_jp(year: int | None = None) -> dict:
    """
    baseballdata.jp — NPB pitcher stats, static HTML tables.
    """
    _year = year or date.today().year
    urls = [
        f"https://baseballdata.jp/en/pitching/{_year}/",
        f"https://baseballdata.jp/en/pitching/?year={_year}",
        "https://baseballdata.jp/en/pitching/",
    ]

    for url in urls:
        try:
            resp = requests.get(url, headers=_BD_HEADERS, timeout=15)
            if resp.status_code == 403:
                log.debug("baseballdata.jp 403 for %s", url)
                return {}
            if resp.status_code != 200:
                log.debug("baseballdata.jp HTTP %s for %s", resp.status_code, url)
                continue
            resp.encoding = resp.apparent_encoding or "utf-8"
            stats = _parse_baseballdata_jp_html(resp.text)
            if stats:
                log.info("baseballdata.jp: %d NPB pitchers from %s", len(stats), url)
                return stats
        except Exception as e:
            log.debug("baseballdata.jp %s: %s", url, e)

    return {}


def _parse_baseballdata_jp_html(html: str) -> dict:
    """Parse baseballdata.jp HTML pitcher stats table."""
    soup = BeautifulSoup(html, "html.parser")
    result: dict = {}

    for table in soup.find_all("table"):
        thead = table.find("thead")
        header_row = thead.find("tr") if thead else (table.find_all("tr") or [None])[0]
        if not header_row:
            continue

        raw_hdrs = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
        hdrs = [_BD_COL_MAP.get(h, h.lower()) for h in raw_hdrs]

        if "name" not in hdrs or "era" not in hdrs:
            continue

        data_rows = table.select("tbody tr") or table.find_all("tr")[1:]
        for row in data_rows:
            tds = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if not tds or len(tds) < 3:
                continue
            try:
                name = tds[hdrs.index("name")].strip()
            except (ValueError, IndexError):
                continue
            if not name or name in ("Total", "合計", "平均", ""):
                continue

            p: dict = {"league": "NPB"}

            # Team mapping
            if "team" in hdrs:
                try:
                    raw_team = tds[hdrs.index("team")].strip()
                    team_code = _BD_NPB_TEAM_MAP.get(raw_team, "")
                    if not team_code:
                        # Try full name fallback
                        for k, v in _NPB_TEAM_MAP.items():
                            if k.lower() in raw_team.lower():
                                team_code = v
                                break
                    if team_code:
                        p["team"] = team_code
                except Exception:
                    pass

            for field in ("era", "fip", "xfip", "whip", "k9", "bb9",
                          "k_pct", "bb_pct", "babip", "lob_pct",
                          "innings", "wins", "losses", "g", "gs"):
                if field not in hdrs:
                    continue
                raw_val = tds[hdrs.index(field)]
                raw_val = raw_val.replace("%", "").replace(",", "").strip()
                try:
                    p[field] = float(raw_val)
                except (ValueError, TypeError):
                    pass

            if "era" not in p:
                continue

            enrich_pitcher(p)
            result[name] = p

    return result
