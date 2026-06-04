"""V8 Market Movement Detector — Sharp money / Reverse line movement / Steam move"""
import json, os

_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "market_moves.json")


def load() -> dict:
    try:
        with open(os.path.abspath(_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(data: dict):
    path = os.path.abspath(_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _dec_to_prob(dec_odds: float) -> float:
    if dec_odds <= 1.0:
        return 0.5
    return 1.0 / dec_odds


def record_move(data: dict, game_key: str, odds_data: dict) -> dict:
    """
    從 odds_data 記錄開盤 → 現在盤口移動。
    odds_data keys: open_home_odds, open_away_odds,
                    curr_home_odds, curr_away_odds,
                    public_home_pct
    """
    o_h = float(odds_data.get("open_home_odds") or 0)
    o_a = float(odds_data.get("open_away_odds") or 0)
    c_h = float(odds_data.get("curr_home_odds") or 0)
    c_a = float(odds_data.get("curr_away_odds") or 0)
    pub = float(odds_data.get("public_home_pct") or 50)

    if o_h > 1 and c_h > 1:
        home_prob_open = _dec_to_prob(o_h)
        home_prob_curr = _dec_to_prob(c_h)
        home_move      = home_prob_curr - home_prob_open
    else:
        home_prob_open = 0.5
        home_prob_curr = 0.5
        home_move      = 0.0

    data[game_key] = {
        "open_home_odds":  o_h,
        "open_away_odds":  o_a,
        "curr_home_odds":  c_h,
        "curr_away_odds":  c_a,
        "home_prob_open":  round(home_prob_open, 4),
        "home_prob_curr":  round(home_prob_curr, 4),
        "home_move":       round(home_move, 4),
        "public_home_pct": pub,
    }
    return data


def analyze(data: dict, game_key: str) -> dict:
    """
    偵測盤口訊號：
    - Reverse Line Movement (RLM): 公眾押一方，盤口卻往反方向移動
    - Steam Move: 短時間盤口移動 > 3%
    - Fade Public: 公眾一面倒 > 70% 但盤口未動

    Returns: {sharp_signal, line_move, public_home_pct, signals, ev_boost}
    """
    entry = data.get(game_key, {})
    if not entry:
        return {"sharp_signal": None, "line_move": 0.0,
                "public_home_pct": 50.0, "signals": [], "ev_boost": 0.0}

    home_move = entry.get("home_move", 0.0)
    pub_home  = entry.get("public_home_pct", 50.0)
    signals   = []
    sharp_signal = None
    ev_boost  = 0.0

    # ── Reverse Line Movement ─────────────────────────────────────
    if pub_home > 62 and home_move < -0.025:
        signals.append("⚡ RLM：公眾偏主隊但盤口向客隊移動（Sharp money 看客隊）")
        sharp_signal = "away"
        ev_boost     = 0.025   # 加分給客隊 edge
    elif pub_home < 38 and home_move > 0.025:
        signals.append("⚡ RLM：公眾偏客隊但盤口向主隊移動（Sharp money 看主隊）")
        sharp_signal = "home"
        ev_boost     = 0.025

    # ── Steam Move（快速大幅移動）─────────────────────────────────
    elif abs(home_move) > 0.04:
        dir_cn = "主隊" if home_move > 0 else "客隊"
        signals.append(f"🔥 Steam：盤口快速向{dir_cn}移動 ({home_move*100:+.1f}%)")
        sharp_signal = "home" if home_move > 0 else "away"
        ev_boost     = 0.015

    # ── Fade Public（大眾一面倒，反向操作機會）───────────────────
    if pub_home > 72 and home_move <= 0.01:
        signals.append(f"🎯 大眾壓主隊 ({pub_home:.0f}%)，反向價值存在")
    elif pub_home < 28 and home_move >= -0.01:
        signals.append(f"🎯 大眾壓客隊 ({100-pub_home:.0f}%)，反向價值存在")

    # ── Fake Favorite Trap（重押一方但賠率沒動）─────────────────
    if pub_home > 65 and abs(home_move) < 0.01:
        signals.append("⚠️ 疑似假熱門：大眾壓注但盤口無反應")

    return {
        "sharp_signal":    sharp_signal,
        "line_move":       round(home_move, 4),
        "public_home_pct": pub_home,
        "signals":         signals,
        "ev_boost":        round(ev_boost, 4),
    }
