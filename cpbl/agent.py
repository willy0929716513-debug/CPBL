"""V8 Decision Agent — EV + Risk-Adjusted EV + CLV + Bayesian cold-start guard"""
from __future__ import annotations
from typing import Optional
from . import bayesian

# ── 下注參數 ────────────────────────────────────────────────────────────────
CONF_MIN      = 0.22   # real mode:  完整暖機後勝率 ≥ ~61%
CONF_MIN_DEMO = 0.15   # demo mode:  勝率 ≥ ~58%
BANK          = 1000.0
KELLY_FRAC    = 0.25   # 25% fractional Kelly（保守）
KELLY_FLOOR   = 50.0
KELLY_MAX     = 200.0

# V8 風險懲罰參數
RISK_PENALTY  = 3.5    # EV 扣減 = mc_std² × RISK_PENALTY

# 各信心等級對應的最低 Edge 門檻（實際模式）
_EDGE_MIN = {
    1: 0.06,   # 💎 頂級
    2: 0.035,  # 🔥 強力
    3: 0.02,   # ⭐ 穩定
}

TIER_EMOJI = {1: "💎", 2: "🔥", 3: "⭐"}
TIER_LABEL = {1: "💎 頂級", 2: "🔥 強力", 3: "⭐ 穩定"}


def _devig(home_odds: float, away_odds: float) -> tuple[float, float]:
    """去抽水：把莊家抽水去掉後的真實隱含概率。"""
    if home_odds <= 1.0 or away_odds <= 1.0:
        return 0.5, 0.5
    h_implied = 1.0 / home_odds
    a_implied = 1.0 / away_odds
    total = h_implied + a_implied
    if total <= 0:
        return 0.5, 0.5
    return round(h_implied / total, 4), round(a_implied / total, 4)


def kelly_stake(p_win: float, dec_odds: float, other_odds: float = 0.0) -> float:
    b = dec_odds - 1.0
    if b <= 0:
        return 0.0
    # kp = 模型勝率×50% + Devigged市場概率×50%
    if other_odds > 1.0:
        dv, _ = _devig(dec_odds, other_odds)
        kp = p_win * 0.50 + dv * 0.50
    else:
        kp = p_win
    k = (b * kp - (1 - kp)) / b
    if k <= 0:
        return 0.0
    stake = k * KELLY_FRAC * BANK
    return round(min(max(stake, KELLY_FLOOR), KELLY_MAX), 0)


def calc_edge(p_model: float, dec_odds: float, other_odds: float = 0.0) -> float:
    """edge = 模型勝率 - Devigged市場概率"""
    if dec_odds <= 1.0:
        return 0.0
    if other_odds > 1.0:
        dv, _ = _devig(dec_odds, other_odds)
        return round(p_model - dv, 4)
    return round(p_model - 1.0 / dec_odds, 4)


def get_tier(conf: float) -> int:
    if conf >= 0.64:
        return 1
    if conf >= 0.44:
        return 2
    return 3


def _expected_value(p_win: float, dec_odds: float) -> float:
    """EV = p_win * (dec_odds - 1) - (1 - p_win)"""
    return p_win * (dec_odds - 1.0) - (1.0 - p_win)


def _risk_adjusted_ev(ev: float, mc_std: float,
                      market_ev_boost: float = 0.0) -> float:
    """
    V8 風險調整 EV：
    score = EV - (variance × RISK_PENALTY) + market_ev_boost
    variance = mc_std²
    """
    variance_penalty = (mc_std ** 2) * RISK_PENALTY
    return ev - variance_penalty + market_ev_boost


def decide(
    game:       dict,
    pred:       dict,
    mc:         dict | None = None,
    demo_mode:  bool        = False,
    memory:     dict | None = None,
    ensemble:   dict | None = None,  # ensemble.ensemble() 輸出
    market_sig: dict | None = None,  # market.analyze() 輸出
) -> Optional[dict]:
    """
    V8 核心決策函式。

    V8 升級點：
    1. 使用 ensemble 概率（若有）取代單一 model 概率
    2. EV → risk-adjusted EV（扣 MC variance penalty）
    3. Market signal ev_boost（sharp money 加分）
    4. Bayesian cold-start factor 壓縮信心
    5. Rolling window 準確率決定是否進一步壓縮

    Returns pick dict 或 None。
    """
    # ── 取最終概率（ensemble 優先）────────────────────────────────
    if ensemble:
        hp = ensemble["prob"]
        ap = 1.0 - hp
    else:
        hp = pred["home_win_prob"]
        ap = pred["away_win_prob"]

    base_conf = pred["confidence"] / 100.0

    of     = pred.get("factors", {}).get("odds", {}) or {}
    h_odds = float(of.get("curr_home_odds") or 0)
    a_odds = float(of.get("curr_away_odds") or 0)

    # ── Monte Carlo 過濾 & 信心調整 ──────────────────────────────
    mc_boost     = 0.0
    mc_std       = 0.12  # 預設標準差（未做 MC 時）
    mc_uncertain = False
    if mc:
        mc_boost     = mc.get("conf_boost", 0.0)
        mc_std       = mc.get("std_dev", 0.12)
        mc_uncertain = mc.get("uncertain", False)
        if mc_uncertain:
            return None

    conf = min(0.95, max(0.0, base_conf + mc_boost))

    # ── V8 Bayesian Cold-start 壓縮 ──────────────────────────────
    total_games = memory.get("total_games", 0) if memory else 0
    cs_factor   = bayesian.cold_start_factor(total_games)
    conf        = round(conf * cs_factor, 3)

    # ── Market signal ev_boost ────────────────────────────────────
    market_ev_boost = 0.0
    sharp_signal    = None
    if market_sig:
        market_ev_boost = market_sig.get("ev_boost", 0.0)
        sharp_signal    = market_sig.get("sharp_signal")

    tier     = get_tier(conf)
    conf_min = CONF_MIN_DEMO if demo_mode else CONF_MIN
    edge_min = _EDGE_MIN[3]  if demo_mode else _EDGE_MIN[tier]

    best: Optional[dict] = None

    for p_win, dec_odds, other_dec_odds, label, side in [
        (hp, h_odds, a_odds, f"{game.get('home_name', game['home'])} 獨贏", "home"),
        (ap, a_odds, h_odds, f"{game.get('away_name', game['away'])} 獨贏", "away"),
    ]:
        if dec_odds <= 1.0:
            continue
        # 賠率範圍過濾 1.35-2.80
        if dec_odds < 1.35 or dec_odds > 2.80:
            continue
        # 最低模型勝率 55%
        if p_win < 0.55:
            continue

        edge = calc_edge(p_win, dec_odds, other_dec_odds)

        # 低賠額外門檻
        effective_edge_min = edge_min
        if dec_odds < 1.65:
            effective_edge_min = max(edge_min, 0.06)

        if edge < effective_edge_min or conf < conf_min:
            continue

        # ── V8 EV scoring ────────────────────────────────────────
        ev        = _expected_value(p_win, dec_odds)
        mkt_boost = market_ev_boost if sharp_signal == side else 0.0
        ra_ev     = _risk_adjusted_ev(ev, mc_std, mkt_boost)

        # 市場 sharp signal 與模型方向一致時給 edge 加成
        if sharp_signal == side:
            edge = round(edge + market_ev_boost * 0.5, 4)

        # 低迷期折扣
        from . import memory as mem_mod
        slump_factor = 1.0
        if memory and hasattr(mem_mod, 'rolling_accuracy'):
            try:
                roll_acc = mem_mod.rolling_accuracy(memory)
                if roll_acc < 0.40:
                    slump_factor = 0.75
            except Exception:
                pass

        if best is None or ra_ev > best["ra_ev"]:
            raw_stake = kelly_stake(p_win, dec_odds, other_dec_odds)
            best = {
                "side":         side,
                "bet_label":    label,
                "btype":        "ML",
                "bp":           round(dec_odds, 2),
                "stake":        round(raw_stake * slump_factor, 0),
                "edge":         round(edge, 4),
                "p_win":        round(p_win, 4),
                "ev":           round(ev, 4),
                "ra_ev":        round(ra_ev, 4),
                "slump_factor": slump_factor,
            }

    if best is None:
        return None

    return {
        **best,
        "conf":          conf,
        "tier":          tier,
        "mc_boost":      round(mc_boost, 3),
        "cs_factor":     round(cs_factor, 3),
        "mc_std":        round(mc_std, 4),
        "recommended":   True,
        "ensemble_used": ensemble is not None,
        "sharp_signal":  sharp_signal,
        "reasoning":     _reasoning(pred, best, mc, ensemble, market_sig),
    }


def _reasoning(pred: dict, cand: dict, mc: dict | None,
               ens: dict | None, mkt: dict | None) -> list[str]:
    factors = pred.get("factors", {})
    reasons = []

    # 主要因子優勢
    adv_parts = []
    for key, label in [("starter","先發"), ("lineup","打線"),
                       ("bullpen","牛棚"), ("odds","盤口"), ("recent_form","近況")]:
        f   = factors.get(key, {})
        adv = f.get("advantage", 0.0) if isinstance(f, dict) else 0.0
        if abs(adv) >= 7:
            adv_parts.append(f"{label}{'主' if adv > 0 else '客'}優{abs(adv):.0f}")
    if adv_parts:
        reasons.append("📊 " + " | ".join(adv_parts[:4]))

    # V8 EV 摘要
    ev   = cand.get("ev", 0)
    ra_ev = cand.get("ra_ev", 0)
    reasons.append(
        f"💹 EV={ev*100:+.1f}% → 風險調整後 EV={ra_ev*100:+.1f}%  "
        f"cold-start×{cand.get('cs_factor', 1.0):.2f}"
    )

    # Monte Carlo
    if mc:
        ci  = mc.get("ci_90", [0, 1])
        std = mc.get("std_dev", 0)
        reasons.append(
            f"🎲 MC {mc.get('n',0)}次: 90%CI [{ci[0]*100:.0f}%,{ci[1]*100:.0f}%] "
            f"σ={std:.3f}"
        )

    # Ensemble 模型分解
    if ens:
        mp = ens.get("model_probs", {})
        reasons.append(
            f"🧩 Ensemble: ELO={mp.get('elo','-')} ML={mp.get('ml','-')} "
            f"市場={mp.get('market','-')} MC={mp.get('mc','-')} "
            f"→ {ens['prob']:.3f}"
        )

    # Sharp money 訊號
    if mkt and mkt.get("sharp_signal"):
        for sig in mkt.get("signals", [])[:1]:
            reasons.append(sig)

    return reasons
