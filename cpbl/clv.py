"""V8 CLV (Closing Line Value) Tracker — 檢驗你是否真的提前抓到 value"""
import json, os

_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "clv_log.json")


def clv(entry_odds: float, closing_odds: float) -> float:
    """CLV = (entry_odds - closing_odds) / closing_odds。正值 = 跑贏收盤盤口。"""
    if closing_odds <= 1.0:
        return 0.0
    return round((entry_odds - closing_odds) / closing_odds, 4)


def load() -> list:
    try:
        with open(os.path.abspath(_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save(records: list):
    path = os.path.abspath(_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def add_entry(records: list, date: str, game_key: str,
              entry_odds: float, side: str,
              closing_odds: float = 0.0, won: bool | None = None) -> list:
    records.append({
        "date":          date,
        "game":          game_key,
        "side":          side,
        "entry_odds":    round(entry_odds, 3),
        "closing_odds":  round(closing_odds, 3),
        "clv":           clv(entry_odds, closing_odds) if closing_odds > 1 else None,
        "won":           won,
    })
    return records[-500:]


def update_closing(records: list, game_key: str, closing_odds: float, won: bool | None):
    """收盤後補登 closing odds 和結果。"""
    for r in reversed(records):
        if r["game"] == game_key and r.get("closing_odds", 0) == 0:
            r["closing_odds"] = round(closing_odds, 3)
            r["clv"]          = clv(r["entry_odds"], closing_odds)
            r["won"]          = won
            break


def summary(records: list) -> dict:
    filled = [r for r in records if r.get("closing_odds", 0) > 1]
    if not filled:
        return {"n": 0, "avg_clv": 0.0, "positive_clv_pct": 0.0, "clv_win_corr": 0.0}
    avg  = sum(r["clv"] for r in filled) / len(filled)
    pos  = sum(1 for r in filled if r["clv"] > 0) / len(filled)
    # CLV vs win correlation（簡單版）
    with_result = [r for r in filled if r.get("won") is not None]
    corr = 0.0
    if len(with_result) >= 5:
        clvs = [r["clv"] for r in with_result]
        wins = [1.0 if r["won"] else 0.0 for r in with_result]
        mc   = sum(clvs) / len(clvs)
        mw   = sum(wins) / len(wins)
        num  = sum((c - mc) * (w - mw) for c, w in zip(clvs, wins))
        dc   = (sum((c - mc)**2 for c in clvs) * sum((w - mw)**2 for w in wins)) ** 0.5
        corr = round(num / dc, 3) if dc > 0 else 0.0
    return {
        "n":                len(filled),
        "avg_clv":          round(avg, 4),
        "positive_clv_pct": round(pos, 3),
        "clv_win_corr":     corr,
    }
