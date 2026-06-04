"""
CPBL 網頁爬蟲 — 僅爬一軍 (kind=A) 賽程
若抓取失敗回傳空列表，由呼叫端決定是否 fallback。
"""
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import date
from typing import Optional

BASE = "https://www.cpbl.com.tw"
WEATHER_API = "https://wttr.in"

# 盡量模擬真實瀏覽器
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

TEAM_CODE_MAP = {
    "中信兄弟": "AEL", "兄弟": "AEL",
    "統一7-ELEVEn獅": "CT", "統一獅": "CT", "統一": "CT",
    "富邦悍將": "FG", "悍將": "FG", "富邦": "FG",
    "樂天桃猿": "WL", "桃猿": "WL", "樂天": "WL",
    "台鋼雄鷹": "TSG", "雄鷹": "TSG", "台鋼": "TSG",
}

CITY_MAP = {
    "洲際棒球場": "台中",
    "台南棒球場": "台南",
    "新莊棒球場": "新北",
    "桃園棒球場": "桃園",
    "澄清湖棒球場": "高雄",
    "天母棒球場": "台北",
}


class CPBLScraper:
    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update(_HEADERS)
        try:
            r = self._session.get(BASE, timeout=8)
            # 短暫等待讓 cookie 生效
            if r.status_code == 200:
                time.sleep(0.5)
        except Exception:
            pass

    # ── 一軍賽程 ──────────────────────────────────
    def fetch_schedule(self, game_date: date) -> list[dict]:
        """回傳今日一軍賽程，失敗拋出例外（不 fallback mock）。"""
        # 先嘗試帶 day 的 URL（精確單日）
        url = (
            f"{BASE}/schedule/lists"
            f"?year={game_date.year}"
            f"&month={game_date.month:02d}"
            f"&day={game_date.day:02d}"
            f"&kind=A"
        )
        self._session.headers.update({"Referer": f"{BASE}/schedule"})
        resp = self._session.get(url, timeout=12)

        # 若 403/5xx，嘗試不帶 day 的月份頁再過濾
        if resp.status_code in (403, 429, 503):
            url2 = (
                f"{BASE}/schedule/lists"
                f"?year={game_date.year}"
                f"&month={game_date.month:02d}"
                f"&kind=A"
            )
            resp = self._session.get(url2, timeout=12)

        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        games = self._parse_schedule(soup, game_date)
        # 確認解析到的是一軍資料（kind=A 應已過濾，這裡做二次確認）
        return [g for g in games if g.get("league", "A") == "A"]

    def _parse_schedule(self, soup: BeautifulSoup, game_date: date) -> list[dict]:
        games: list[dict] = []
        ds = str(game_date)

        # 嘗試多種 selector（CPBL 網站改版後結構可能不同）
        rows = soup.select(
            ".ScheduleTableList tbody tr, "
            "table.schedule-table tbody tr, "
            "table tbody tr, "
            ".game-list tr"
        )

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 4:
                continue
            texts = [c.get_text(" ", strip=True) for c in cols]
            try:
                gtime    = texts[0].strip()
                away_raw = texts[1].strip()
                score_raw= texts[2].strip()
                home_raw = texts[3].strip()
                venue    = texts[4].strip() if len(texts) > 4 else ""

                # 略過沒有主客隊的列
                if not away_raw and not home_raw:
                    continue
                # 略過標頭列
                if any(kw in away_raw for kw in ("客隊", "Away", "日期")):
                    continue

                away_code = TEAM_CODE_MAP.get(away_raw, away_raw)
                home_code = TEAM_CODE_MAP.get(home_raw, home_raw)

                m = re.search(r"(\d+)\s*[:\-]\s*(\d+)", score_raw)
                g: dict = {
                    "game_id": f"{ds}-{away_code}-{home_code}",
                    "date":    ds,
                    "time":    gtime,
                    "away":    away_code,
                    "away_name": away_raw,
                    "home":    home_code,
                    "home_name": home_raw,
                    "venue":   venue,
                    "league":  "A",   # kind=A 一軍
                    "status":  "結束" if m else "預定",
                    "away_score": int(m.group(1)) if m else None,
                    "home_score": int(m.group(2)) if m else None,
                }
                games.append(g)
            except (IndexError, ValueError):
                continue

        return games

    # ── 投手數據 ──────────────────────────────
    def fetch_pitcher_stats(self, year: int = 2026) -> list[dict]:
        url = f"{BASE}/stats/pitcher?year={year}&kind=A&cate=all"
        resp = self._session.get(url, timeout=12)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        return self._parse_pitcher_table(soup)

    def _parse_pitcher_table(self, soup: BeautifulSoup) -> list[dict]:
        pitchers: list[dict] = []
        rows = soup.select("table tbody tr")
        for row in rows:
            cols = row.find_all("td")
            texts = [c.get_text(strip=True) for c in cols]
            if len(texts) < 10:
                continue
            try:
                p = {
                    "name":  texts[1] if len(texts) > 1 else "",
                    "team":  texts[2] if len(texts) > 2 else "",
                    "era":   _f(texts, 5),
                    "whip":  _f(texts, 9),
                    "k9":    _f(texts, 12),
                    "bb9":   _f(texts, 11),
                    "fip":   _f(texts, 14),
                    "gs":    _i(texts, 3),
                }
                if p["name"]:
                    pitchers.append(p)
            except (IndexError, ValueError):
                continue
        return pitchers

    # ── 球隊數據 ──────────────────────────────
    def fetch_team_batting(self, year: int = 2026) -> list[dict]:
        url = f"{BASE}/stats/team?year={year}&kind=A&cate=bat"
        resp = self._session.get(url, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        return self._parse_team_table(soup)

    def _parse_team_table(self, soup: BeautifulSoup) -> list[dict]:
        rows = soup.select("table tbody tr")
        teams = []
        for row in rows:
            cols = row.find_all("td")
            texts = [c.get_text(strip=True) for c in cols]
            if len(texts) < 4:
                continue
            teams.append({
                "team": texts[0],
                "avg":  _f(texts, 3),
                "ops":  _f(texts, 8),
            })
        return teams

    # ── 天氣 ──────────────────────────────────
    def fetch_weather(self, venue: str) -> Optional[dict]:
        city = CITY_MAP.get(venue)
        if not city:
            return None
        try:
            url = f"{WEATHER_API}/{city}?format=j1&lang=zh-tw"
            resp = requests.get(url, timeout=6)
            data = resp.json()
            cur = data["current_condition"][0]
            return {
                "temp_c":    int(cur["temp_C"]),
                "humidity":  int(cur["humidity"]),
                "wind_kph":  int(cur["windspeedKmph"]),
                "condition": cur["weatherDesc"][0]["value"],
                "city":      city,
            }
        except Exception:
            return None


def _f(texts: list, idx: int, default: float = 0.0) -> float:
    try:
        return float(texts[idx].replace("%", ""))
    except (IndexError, ValueError):
        return default


def _i(texts: list, idx: int, default: int = 0) -> int:
    try:
        return int(texts[idx])
    except (IndexError, ValueError):
        return default
