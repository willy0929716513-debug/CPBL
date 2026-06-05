"""
NPB / KBO 賽程爬蟲 — 使用 ESPN 免費 API (不受 WAF 封鎖)
NPB: https://site.api.espn.com/apis/site/v2/sports/baseball/jlb/scoreboard
KBO: https://site.api.espn.com/apis/site/v2/sports/baseball/kor/scoreboard
"""
import logging
import requests
from datetime import date
from typing import Optional

log = logging.getLogger(__name__)

_ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/baseball"
_WEATHER_API = "https://wttr.in"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

# ESPN 球隊名稱 → 我們的代碼
_NPB_NAME_MAP: dict[str, str] = {
    # 読売
    "giants": "GNT", "yomiuri": "GNT", "yomiuri giants": "GNT",
    # 阪神
    "tigers": "HNS", "hanshin": "HNS", "hanshin tigers": "HNS",
    # 広島
    "carp": "HRC", "hiroshima": "HRC", "hiroshima carp": "HRC",
    # DeNA
    "baystars": "YDB", "bay stars": "YDB", "yokohama": "YDB",
    "debaystars": "YDB", "dena baystars": "YDB",
    # ヤクルト
    "swallows": "YKL", "yakult": "YKL", "yakult swallows": "YKL",
    # 中日
    "dragons": "CND", "chunichi": "CND", "chunichi dragons": "CND",
    # ソフトバンク
    "hawks": "SBH", "softbank": "SBH", "fukuoka softbank hawks": "SBH",
    "softbank hawks": "SBH",
    # オリックス
    "buffaloes": "ORX", "orix": "ORX", "orix buffaloes": "ORX",
    # 楽天
    "eagles": "RKT", "rakuten": "RKT", "rakuten eagles": "RKT",
    "tohoku rakuten golden eagles": "RKT",
    # ロッテ
    "marines": "LTT", "lotte": "LTT", "chiba lotte marines": "LTT",
    "lotte marines": "LTT",
    # 西武
    "lions": "SEI", "seibu": "SEI", "saitama seibu lions": "SEI",
    "seibu lions": "SEI",
    # 日ハム
    "fighters": "HAM", "nippon-ham": "HAM", "hokkaido nippon-ham fighters": "HAM",
    "ham fighters": "HAM", "nippon ham fighters": "HAM",
}

_KBO_NAME_MAP: dict[str, str] = {
    # 삼성
    "samsung": "SSL", "lions": "SSL", "samsung lions": "SSL",
    # LG
    "lg": "LGT", "twins": "LGT", "lg twins": "LGT",
    # 두산
    "doosan": "DSB", "bears": "DSB", "doosan bears": "DSB",
    # KT
    "kt": "KTW", "wiz": "KTW", "kt wiz": "KTW",
    # SSG
    "ssg": "SSG", "landers": "SSG", "ssg landers": "SSG",
    # NC
    "nc": "NCD", "dinos": "NCD", "nc dinos": "NCD",
    # KIA
    "kia": "KIA", "kia tigers": "KIA",
    # 롯데
    "lotte": "LTG", "giants": "LTG", "lotte giants": "LTG",
    # 한화
    "hanwha": "HWE", "eagles": "HWE", "hanwha eagles": "HWE",
    # 키움
    "kiwoom": "KWH", "heroes": "KWH", "kiwoom heroes": "KWH",
}


def _name_to_code(name: str, league: str) -> Optional[str]:
    """ESPN 隊名（英文）→ 內部代碼"""
    n = name.lower().strip()
    mapping = _NPB_NAME_MAP if league == "NPB" else _KBO_NAME_MAP
    # 完整比對
    if n in mapping:
        return mapping[n]
    # 部分比對
    for key, code in mapping.items():
        if key in n or n in key:
            return code
    return None


class MultiLeagueScraper:
    """抓取 NPB + KBO 今日賽程（ESPN 免費 API）"""

    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)

    def fetch_schedule(self, game_date: str = None) -> list[dict]:
        """
        回傳今日所有 NPB + KBO 賽事
        每筆: {away, home, time, venue, league, status, away_score, home_score}
        """
        if game_date is None:
            game_date = str(date.today())
        date_str = game_date.replace("-", "")  # YYYYMMDD

        games: list[dict] = []
        for league, endpoint in [("NPB", "jlb"), ("KBO", "kor")]:
            try:
                raw = self._fetch_espn(endpoint, date_str)
                games.extend(self._parse_events(raw, league))
            except Exception as e:
                log.warning("ESPN [%s] 失敗: %s", league, e)

        return games

    def _fetch_espn(self, endpoint: str, date_str: str) -> list:
        url = f"{_ESPN_BASE}/{endpoint}/scoreboard"
        params = {"dates": date_str}
        resp = self._session.get(url, params=params, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        return data.get("events", [])

    def _parse_events(self, events: list, league: str) -> list[dict]:
        result = []
        for ev in events:
            try:
                game = self._parse_single(ev, league)
                if game:
                    result.append(game)
            except Exception as e:
                log.debug("ESPN 解析失敗: %s", e)
        return result

    def _parse_single(self, ev: dict, league: str) -> Optional[dict]:
        competitions = ev.get("competitions", [])
        if not competitions:
            return None
        comp = competitions[0]

        home_data = away_data = None
        for comp_team in comp.get("competitors", []):
            if comp_team.get("homeAway") == "home":
                home_data = comp_team
            elif comp_team.get("homeAway") == "away":
                away_data = comp_team

        if not home_data or not away_data:
            return None

        home_name = home_data.get("team", {}).get("displayName", "")
        away_name = away_data.get("team", {}).get("displayName", "")

        home_code = _name_to_code(home_name, league)
        away_code = _name_to_code(away_name, league)

        if not home_code or not away_code:
            log.debug("未知球隊: %s / %s (%s)", home_name, away_name, league)
            return None

        # 比賽狀態
        status = ev.get("status", {}).get("type", {}).get("name", "STATUS_SCHEDULED")
        home_score = home_data.get("score", "0")
        away_score = away_data.get("score", "0")

        # 球場
        venue = comp.get("venue", {}).get("fullName", "")

        # 比賽時間
        game_time = ev.get("date", "")[:16].replace("T", " ")

        return {
            "away":       away_code,
            "home":       home_code,
            "away_name":  away_name,
            "home_name":  home_name,
            "time":       game_time,
            "venue":      venue,
            "league":     league,
            "status":     status,
            "away_score": int(away_score) if str(away_score).isdigit() else 0,
            "home_score": int(home_score) if str(home_score).isdigit() else 0,
        }

    def fetch_weather(self, city: str) -> Optional[dict]:
        """抓取城市天氣（wttr.in）"""
        try:
            url = f"{_WEATHER_API}/{city}?format=j1&lang=zh-tw"
            resp = self._session.get(url, timeout=8)
            resp.raise_for_status()
            data = resp.json()
            current = data.get("current_condition", [{}])[0]
            return {
                "temp_c":    current.get("temp_C", "?"),
                "humidity":  current.get("humidity", "?"),
                "wind_kmph": current.get("windspeedKmph", "?"),
                "desc":      current.get("weatherDesc", [{}])[0].get("value", "?"),
            }
        except Exception as e:
            log.debug("天氣抓取失敗 [%s]: %s", city, e)
            return None


# 保留舊名稱 alias，避免其他模組 import 失敗
CPBLScraper = MultiLeagueScraper
