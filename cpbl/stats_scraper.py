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
    嘗試順序：koreabaseball.com → Naver Sports KBO → 空列表
    先發投手若頁面有則抓，無則留空（由 rotation 補漏）。
    """
    date_str = game_date.isoformat()
    y, m, d  = game_date.year, game_date.month, game_date.day

    # 1. koreabaseball.com 官方網站（只用帶日期的 URL，避免無日期版本永遠回傳今天賽程）
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

    # 2. Naver Sports KBO 賽程
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

        # ── team Phase 1: text nodes ──────────────────────────────────────
        # npb.jp is server-rendered (not SPA); team names appear in static HTML.
        # Narrow the scan to the target date's section using a kanji date anchor.
        target_day_jp = f"{game_date.month}月{game_date.day}日"
        in_target_section = False
        codes_in_order: list[str] = list(team_codes_scripts)
        for node in soup.find_all(string=True):
            text = node.strip()
            if not text:
                continue
            # Detect date section header (e.g. "6月5日" or "6月5日（木）")
            if target_day_jp in text:
                in_target_section = True
            # Stop when we hit the NEXT date section
            elif in_target_section and re.search(r'\d+月\d+日', text) and target_day_jp not in text:
                break
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

    # 2. KBO — 韓國本地來源（koreabaseball.com → Naver Sports）
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
    """解析 mykbostats.com 賽程頁面，提取先發投手。"""
    soup  = BeautifulSoup(html, "html.parser")
    games = []

    # 嘗試各種可能的 CSS 結構
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
        teams = [el.get_text(strip=True) for el in team_els if el.get_text(strip=True)]
        if len(teams) < 2:
            continue
        away_code = _mykbo_team_code(teams[0])
        home_code = _mykbo_team_code(teams[-1])
        if not away_code or not home_code or away_code == home_code:
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
            m = re.search(r"(\d{1,2}:\d{2})", t)
            if m:
                game_time = m.group(1)

        games.append({
            "game_id":      f"{date_str}-{away_code}-{home_code}",
            "date":         date_str,
            "time":         game_time,
            "away":         away_code,
            "away_name":    teams[0],
            "home":         home_code,
            "home_name":    teams[-1],
            "venue":        "",
            "league":       "KBO",
            "status":       "預定",
            "away_score":   None,
            "home_score":   None,
            "away_pitcher": away_pitcher,
            "home_pitcher": home_pitcher,
            "_source":      "mykbo",
        })

    # Pattern B: 表格結構（行 = 一場比賽）
    if not games:
        for row in soup.select("table tr, tbody tr"):
            cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
            if len(cells) < 4:
                continue
            # 嘗試找隊名欄位
            away_code = home_code = ""
            for c in cells:
                code = _mykbo_team_code(c)
                if code and not away_code:
                    away_code = code
                elif code and code != away_code:
                    home_code = code
                    break
            if not away_code or not home_code:
                continue
            games.append({
                "game_id":      f"{date_str}-{away_code}-{home_code}",
                "date":         date_str,
                "time":         "",
                "away":         away_code,
                "away_name":    "",
                "home":         home_code,
                "home_name":    "",
                "venue":        "",
                "league":       "KBO",
                "status":       "預定",
                "away_score":   None,
                "home_score":   None,
                "away_pitcher": "",
                "home_pitcher": "",
                "_source":      "mykbo_table",
            })

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
    Parse Yahoo Japan NPB schedule using two-phase text-scan approach.

    Phase 1: scan every small text node for known team names; pair consecutive
    different codes into games (HTML-structure-agnostic, avoids concatenation bugs).

    Phase 2: scan for Japanese pitcher names from _JP_PITCHER_NAME_MAP, convert
    to Chinese names, then assign each pitcher to the game whose team matches
    the pitcher's team in _NPB_PITCHER_TEAM. This works regardless of where
    in the HTML the pitcher names appear.
    """
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

    for tag in soup.find_all(['script', 'style', 'noscript', 'head', 'nav', 'footer']):
        tag.decompose()

    # ── Phase 1: Team code extraction (text nodes, picks up server-rendered content) ──
    sorted_team_keys = sorted(_YAHOO_NPB_TEAM_MAP.keys(), key=len, reverse=True)
    team_pattern = re.compile('(' + '|'.join(re.escape(k) for k in sorted_team_keys) + ')')

    # Start with codes found in scripts; text node scan appends additional matches
    codes_in_order: list[str] = list(codes_from_scripts)
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
