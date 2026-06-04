#!/usr/bin/env python3
"""CPBL Protector - 中華職棒即時比賽偵測與防暴雷工具"""

import requests
from bs4 import BeautifulSoup
import json
import re
import sys
import os
import time
import argparse
from datetime import date, datetime
from typing import List, Dict, Optional

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

console = Console() if HAS_RICH else None

# ──────────────────────────────────────────────
# 球隊資料
# ──────────────────────────────────────────────

CPBL_TEAMS = {
    "AEL": "中信兄弟",
    "CT":  "統一7-ELEVEn獅",
    "FG":  "富邦悍將",
    "WL":  "樂天桃猿",
    "TSG": "台鋼雄鷹",
}

CPBL_BASE = "https://www.cpbl.com.tw"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.cpbl.com.tw/",
}

# ──────────────────────────────────────────────
# Demo 資料（測試 / 離線用）
# ──────────────────────────────────────────────

DEMO_GAMES: List[Dict] = [
    {
        "date": str(date.today()),
        "time": "17:05",
        "away": "中信兄弟",
        "home": "樂天桃猿",
        "away_score": 3,
        "home_score": 5,
        "score": "3:5",
        "venue": "桃園棒球場",
        "inning": "9",
        "status": "結束",
    },
    {
        "date": str(date.today()),
        "time": "18:35",
        "away": "富邦悍將",
        "home": "統一7-ELEVEn獅",
        "away_score": 2,
        "home_score": 2,
        "score": "2:2",
        "venue": "台南棒球場",
        "inning": "7",
        "status": "進行中",
    },
    {
        "date": str(date.today()),
        "time": "18:35",
        "away": "台鋼雄鷹",
        "home": "中信兄弟",
        "away_score": None,
        "home_score": None,
        "score": "vs",
        "venue": "洲際棒球場",
        "inning": "",
        "status": "預定",
    },
]

# ──────────────────────────────────────────────
# 資料抓取
# ──────────────────────────────────────────────

def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        # 先訪問主頁取得 cookie
        session.get(CPBL_BASE, timeout=8)
    except Exception:
        pass
    return session


def fetch_schedule_page(game_date: date) -> List[Dict]:
    """抓取 cpbl.com.tw 賽程頁面（HTML 解析）"""
    session = _make_session()
    url = (
        f"{CPBL_BASE}/schedule/lists"
        f"?year={game_date.year}"
        f"&month={game_date.month:02d}"
        f"&day={game_date.day:02d}"
        f"&kind=A"
    )
    resp = session.get(url, timeout=10)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    return _parse_schedule_html(soup, game_date)


def _parse_schedule_html(soup: BeautifulSoup, game_date: date) -> List[Dict]:
    games: List[Dict] = []

    # 先試 .schedule-list 結構
    game_blocks = soup.select(".game-item, .schedule-game, tr.game-row")

    if not game_blocks:
        # 備用：掃所有 <tr>
        game_blocks = soup.select("tr")

    for block in game_blocks:
        cols = block.find_all("td")
        if len(cols) < 4:
            continue

        texts = [c.get_text(" ", strip=True) for c in cols]
        game: Dict = {"date": str(game_date)}

        try:
            game["time"]  = texts[0]
            game["away"]  = texts[1]
            raw_score     = texts[2]
            game["home"]  = texts[3]
            game["venue"] = texts[4] if len(texts) > 4 else ""

            m = re.search(r"(\d+)\s*[:\-]\s*(\d+)", raw_score)
            if m:
                game["away_score"] = int(m.group(1))
                game["home_score"] = int(m.group(2))
                game["score"]      = f"{m.group(1)}:{m.group(2)}"
                game["status"]     = _infer_status(game_date)
            else:
                game["away_score"] = None
                game["home_score"] = None
                game["score"]      = "vs"
                game["status"]     = "預定"

            game["inning"] = ""

            if game.get("away") or game.get("home"):
                games.append(game)
        except (IndexError, ValueError):
            continue

    return games


def _infer_status(game_date: date) -> str:
    now = datetime.now()
    if game_date < now.date():
        return "結束"
    if game_date == now.date() and 12 <= now.hour <= 23:
        return "進行中"
    return "預定"


def fetch_api(game_date: date) -> Optional[List[Dict]]:
    """嘗試 CPBL JSON API（若官方有提供）"""
    api_url = f"{CPBL_BASE}/api/game/list?date={game_date.strftime('%Y-%m-%d')}"
    try:
        resp = requests.get(api_url, headers=HEADERS, timeout=6)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and data:
                return _normalize_api(data, game_date)
    except Exception:
        pass
    return None


def _normalize_api(raw: List[Dict], game_date: date) -> List[Dict]:
    games = []
    for item in raw:
        score_a = item.get("AwayScore", item.get("VisitScore"))
        score_h = item.get("HomeScore")
        g: Dict = {
            "date":        str(game_date),
            "time":        item.get("StartTime", ""),
            "away":        item.get("AwayTeamName", item.get("VisitTeam", "")),
            "home":        item.get("HomeTeamName", item.get("HomeTeam", "")),
            "away_score":  score_a,
            "home_score":  score_h,
            "score":       f"{score_a}:{score_h}" if score_a is not None else "vs",
            "venue":       item.get("StadiumName", item.get("Stadium", "")),
            "inning":      str(item.get("Inning", "")),
            "status":      item.get("Status", _infer_status(game_date)),
        }
        games.append(g)
    return games


def fetch_games(game_date: date) -> List[Dict]:
    """
    依序嘗試：
      1. JSON API
      2. 網頁 HTML 解析
    若都失敗回傳錯誤訊息。
    """
    # 試 API
    try:
        result = fetch_api(game_date)
        if result:
            return result
    except Exception:
        pass

    # 試 HTML
    try:
        result = fetch_schedule_page(game_date)
        if result:
            return result
    except requests.HTTPError as e:
        return [{"error": f"HTTP {e.response.status_code}：cpbl.com.tw 拒絕連線（可能需要在台灣 IP 執行）"}]
    except requests.ConnectionError:
        return [{"error": "無法連線至 cpbl.com.tw，請確認網路連線"}]
    except requests.Timeout:
        return [{"error": "連線逾時（cpbl.com.tw）"}]
    except Exception as e:
        return [{"error": str(e)}]

    return [{"error": f"查無 {game_date} 的賽程資料"}]


# ──────────────────────────────────────────────
# 顯示
# ──────────────────────────────────────────────

def _status_style(status: str) -> str:
    return {"進行中": "bold green", "結束": "dim"}.get(status, "yellow")


def _score_cell(g: Dict, protect: bool) -> str:
    is_final = g.get("status") == "結束"
    if protect and is_final:
        return "[dim]██ : ██[/dim]"
    if g.get("away_score") is not None:
        return f"[bold white]{g['away_score']} : {g['home_score']}[/bold white]"
    return "[dim]  vs  [/dim]"


def display_rich(games: List[Dict], target_date: date, protect: bool):
    title = f"⚾  中華職棒 CPBL Protector   {target_date.strftime('%Y / %m / %d')}"

    if not games or (len(games) == 1 and "error" in games[0]):
        msg = games[0].get("error", "今日無賽事") if games else "今日無賽事"
        console.print(Panel(f"[red]{msg}[/red]", title=title))
        return

    table = Table(
        title=title,
        header_style="bold cyan",
        border_style="blue",
        expand=True,
    )
    table.add_column("時間",   style="dim",      width=7)
    table.add_column("客隊",   justify="right",  width=16)
    table.add_column("比分",   justify="center", width=10)
    table.add_column("主隊",   justify="left",   width=16)
    table.add_column("狀態",   justify="center", width=8)
    table.add_column("局數",   justify="center", width=5)
    table.add_column("場地",   style="dim",      width=14)

    live_count = 0
    for g in games:
        if "error" in g:
            continue
        status = g.get("status", "")
        if status == "進行中":
            live_count += 1
        inning = str(g.get("inning", "")) if status == "進行中" else ""
        table.add_row(
            g.get("time", ""),
            g.get("away", ""),
            _score_cell(g, protect),
            g.get("home", ""),
            Text(status, style=_status_style(status)),
            inning,
            g.get("venue", ""),
        )

    console.print(table)

    if protect:
        console.print("[yellow]🛡️  防暴雷模式：已結束比賽的分數已隱藏[/yellow]")
    if live_count > 0:
        console.print(f"[bold green]🔴  目前有 {live_count} 場比賽進行中[/bold green]")


def display_plain(games: List[Dict], target_date: date, protect: bool):
    print(f"\n⚾  中華職棒 CPBL Protector   {target_date.strftime('%Y/%m/%d')}")
    print("=" * 66)

    if not games or (len(games) == 1 and "error" in games[0]):
        msg = games[0].get("error", "今日無賽事") if games else "今日無賽事"
        print(f"  ❌  {msg}")
        print()
        return

    live_count = 0
    for g in games:
        if "error" in g:
            continue
        status = g.get("status", "")
        if status == "進行中":
            live_count += 1

        if protect and status == "結束":
            score = "██ : ██"
        elif g.get("away_score") is not None:
            score = f"{g['away_score']} : {g['home_score']}"
        else:
            score = "  vs  "

        inning = f"({g['inning']}局)" if g.get("inning") and status == "進行中" else "    "
        print(
            f"  {g.get('time',''):>5}  "
            f"{g.get('away',''):>14}  "
            f"{score:^9}  "
            f"{g.get('home',''):<14}  "
            f"[{status}] {inning}"
        )

    if protect:
        print("\n🛡️  防暴雷模式：已結束比賽的分數已隱藏")
    if live_count > 0:
        print(f"\n🔴  目前有 {live_count} 場比賽進行中")
    print()


def display(games: List[Dict], target_date: date, protect: bool):
    if HAS_RICH:
        display_rich(games, target_date, protect)
    else:
        display_plain(games, target_date, protect)


# ──────────────────────────────────────────────
# 監控模式
# ──────────────────────────────────────────────

def monitor(interval: int, protect: bool):
    header = f"CPBL Protector 監控模式（每 {interval} 秒更新，Ctrl+C 離開）"
    if HAS_RICH:
        console.print(f"[bold cyan]{header}[/bold cyan]")
    else:
        print(header)

    try:
        while True:
            today = date.today()
            games = fetch_games(today)

            if HAS_RICH:
                console.clear()
            else:
                os.system("clear" if os.name != "nt" else "cls")

            display(games, today, protect)

            ts = datetime.now().strftime("%H:%M:%S")
            footer = f"最後更新：{ts}  ·  下次更新：{interval}s 後"
            if HAS_RICH:
                console.print(f"[dim]{footer}[/dim]")
            else:
                print(footer)

            time.sleep(interval)

    except KeyboardInterrupt:
        msg = "\n已離開監控模式。"
        console.print(f"[dim]{msg}[/dim]") if HAS_RICH else print(msg)


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cpbl-protector",
        description="中華職棒 CPBL Protector — 即時比賽偵測與防暴雷工具",
    )
    p.add_argument(
        "-d", "--date",
        metavar="YYYY-MM-DD",
        help="查詢特定日期（預設：今天）",
    )
    p.add_argument(
        "-p", "--protect",
        action="store_true",
        help="防暴雷模式：隱藏已結束比賽的分數",
    )
    p.add_argument(
        "-m", "--monitor",
        action="store_true",
        help="持續監控模式，自動定時刷新",
    )
    p.add_argument(
        "-i", "--interval",
        type=int,
        default=60,
        metavar="SEC",
        help="監控刷新間隔秒數（預設：60）",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="使用範例資料（不連網路，用於測試）",
    )
    return p


def main():
    args = build_parser().parse_args()

    # 解析日期
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            print(f"日期格式錯誤：{args.date}，請使用 YYYY-MM-DD")
            sys.exit(1)
    else:
        target_date = date.today()

    if args.demo:
        display(DEMO_GAMES, target_date, args.protect)
        return

    if args.monitor:
        monitor(args.interval, args.protect)
    else:
        games = fetch_games(target_date)
        display(games, target_date, args.protect)


if __name__ == "__main__":
    main()
