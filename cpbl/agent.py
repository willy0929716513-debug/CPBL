"""V7 Decision Agent — 統一決策中心，整合蒙地卡羅與 RL 記憶"""
from __future__ import annotations
from typing import Optional

# ── 下注參數 ────────────────────────────────────
# confidence 由 predictor 計算: abs(win_prob - 0.5) * 2
# CPBL 典型勝率範圍 55-75%，對應 conf 0.10-0.50
# 因此 CONF_MIN 用 0.35 (≈ 67.5% 勝率) 作為門檻
CONF_MIN    = 0.35   # 需勝率 >= 67.5%
CONF_MIN_DEMO = 0.25 # Demo 模式寬鬆版 (≈ 62.5% 勝率)
BANK        = 1000.0
KELLY_FRAC  = 0.25     # 使用 Kelly 值的 25%（保守）
KELLY_FLOOR = 50.0
KELLY_MAX   = 200.0

# 各信心等級對應的最低 Edge 門檻（實際模式）
_EDGE_MIN = {
    1: 0.08,   # 💎 頂級：需要更強邊際 (conf≥0.64 = 82%勝率)
    2: 0.05,   # 🔥 強力 (conf≥0.44 = 72%勝率)
    3: 0.03,   # ⭐ 穩定 (conf≥0.35 = 67.5%勝率)
}

TIER_EMOJI = {1: "💎", 2: "🔥", 3: "⭐"}
TIER_LABEL = {1: "💎 頂級", 2: "🔥 強力", 3: "⭐ 穩定"}


def kelly_stake(p_win: float, dec_odds: float) -> float:
    b = dec_odds - 1.0
    if b <= 0:
        return 0.0
    k = (b * p_win - (1 - p_win)) / b
    if k <= 0:
        return 0.0
    return round(min(max(k * KELLY_FRAC * BANK, KELLY_FLOOR), KELLY_MAX), 0)


def calc_edge(p_model: float, dec_odds: float) -> float:
    if dec_odds <= 1.0:
        return 0.0
    return p_model - 1.0 / dec_odds


def get_tier(conf: float) -> int:
    if conf >= 0.82:
        return 1
    if conf >= 0.72:
        return 2
    return 3


def decide(
    game: dict,
    pred: dict,
    mc: dict | None = None,
    demo_mode: bool = False,
) -> Optional[dict]:
    """
    核心決策函式。

    game: 比賽資訊 dict（away/home/venue/time…）
    pred: predictor.predict() 輸出
    mc:   simulator.simulate() 輸出（可 None）

    Returns pick dict（推薦下注）或 None（不推薦）。
    """
    hp   = pred["home_win_prob"]
    ap   = pred["away_win_prob"]
    base_conf = pred["confidence"] / 100.0

    of      = pred.get("factors", {}).get("odds", {}) or {}
    h_odds  = float(of.get("curr_home_odds") or 0)
    a_odds  = float(of.get("curr_away_odds") or 0)

    # ── Monte Carlo 信心調整 ──────────────────────
    mc_boost = 0.0
    mc_uncertain = False
    if mc:
        mc_boost      = mc.get("conf_boost", 0.0)
        mc_uncertain  = mc.get("uncertain", False)
        if mc_uncertain:
            return None  # 高度不確定 → 不推薦

    conf = min(0.95, max(0.0, base_conf + mc_boost))
    tier = get_tier(conf)

    conf_min = CONF_MIN_DEMO if demo_mode else CONF_MIN
    # Demo 模式用最寬鬆的 edge 門檻
    edge_min = _EDGE_MIN[3] if demo_mode else _EDGE_MIN[tier]

    best: Optional[dict] = None
    for p_win, dec_odds, label, side in [
        (hp, h_odds, f"{game.get('home_name', game['home'])} 獨贏", "home"),
        (ap, a_odds, f"{game.get('away_name', game['away'])} 獨贏", "away"),
    ]:
        if dec_odds <= 1.0:
            continue
        e = calc_edge(p_win, dec_odds)
        if e < edge_min or conf < conf_min:
            continue
        if best is None or e > best["edge"]:
            best = {
                "side":      side,
                "bet_label": label,
                "btype":     "ML",
                "bp":        round(dec_odds, 2),
                "stake":     kelly_stake(p_win, dec_odds),
                "edge":      round(e, 4),
                "p_win":     round(p_win, 4),
            }

    if best is None:
        return None

    return {
        **best,
        "conf":        round(conf, 3),
        "tier":        tier,
        "mc_boost":    round(mc_boost, 3),
        "recommended": True,
        "reasoning":   _reasoning(pred, best, mc),
    }


def _reasoning(pred: dict, cand: dict, mc: dict | None) -> list[str]:
    factors = pred.get("factors", {})
    reasons = []

    adv_parts = []
    for key, label in [("starter","先發"), ("lineup","打線"),
                       ("bullpen","牛棚"), ("odds","盤口"), ("recent_form","近況")]:
        f = factors.get(key, {})
        adv = f.get("advantage", 0.0) if isinstance(f, dict) else 0.0
        if abs(adv) >= 7:
            dir_str = "主優" if adv > 0 else "客優"
            adv_parts.append(f"{label}{dir_str}{abs(adv):.0f}")

    if adv_parts:
        reasons.append("📊 " + " | ".join(adv_parts[:4]))

    if mc:
        ci = mc.get("ci_90", [0, 1])
        std = mc.get("std_dev", 0)
        reasons.append(
            f"🎲 MC {mc.get('n',0)}次: 90%CI [{ci[0]*100:.0f}%,{ci[1]*100:.0f}%] "
            f"σ={std:.3f}"
        )

    return reasons
