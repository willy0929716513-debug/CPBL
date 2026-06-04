"""V8 Ensemble Model — ELO + ML + Market + MC 加權融合"""
from __future__ import annotations
from . import bayesian

# 基礎模型權重
_W_ELO    = 0.12
_W_ML     = 0.48
_W_MARKET = 0.28
_W_MC     = 0.12


def ensemble(
    elo_prob:    float,
    model_prob:  float,
    market_prob: float = 0.5,
    mc_mean:     float | None = None,
    memory:      dict | None  = None,
) -> dict:
    """
    四模型加權 ensemble。

    elo_prob:    ELO 勝率（純歷史紀錄）
    model_prob:  9因子 ML 模型輸出
    market_prob: 市場隱含勝率（從賠率換算）
    mc_mean:     Monte Carlo 模擬均值
    memory:      RL 記憶 dict（用於 Bayesian 調整 ML 權重）

    Returns:
        prob:        ensemble 最終機率
        weights:     各模型實際使用權重
        model_probs: 各模型輸出機率
        bayesian_adj: ML 的 Bayesian 調整乘數
    """
    w_elo    = _W_ELO
    w_model  = _W_ML
    w_market = _W_MARKET
    w_mc     = _W_MC

    # ── Bayesian 調整 ML 模型權重 ─────────────────────────────────
    bayes_adj = 1.0
    if memory and memory.get("total_games", 0) >= 10:
        fa     = memory.get("factor_accuracy", {})
        keys   = ["pitcher", "lineup", "bullpen", "market", "form"]
        bw_vals = [bayesian.bayesian_weight(fa, k) for k in keys]
        bayes_adj = round(sum(bw_vals) / len(bw_vals), 3)
        # 調整範圍限 0.75~1.25（避免 Bayesian 過度影響）
        bayes_adj = max(0.75, min(1.25, bayes_adj))
        w_model  = min(0.65, _W_ML * bayes_adj)
        surplus  = _W_ML * bayes_adj - _W_ML
        # 多出來的權重分給 ELO 和 Market
        w_elo    = _W_ELO    + surplus * 0.35
        w_market = _W_MARKET + surplus * 0.65

    # ── 市場資料有效性檢查 ─────────────────────────────────────────
    market_valid = 0.05 < market_prob < 0.95
    if not market_valid:
        # 無市場資料：把 market 權重平分給 ML 和 ELO
        w_model  += w_market * 0.70
        w_elo    += w_market * 0.30
        w_market  = 0.0

    # ── MC 資料有效性 ─────────────────────────────────────────────
    mc_valid = mc_mean is not None and 0.05 < mc_mean < 0.95
    if not mc_valid:
        w_model += w_mc * 0.60
        w_elo   += w_mc * 0.40
        w_mc     = 0.0

    # ── 組裝 probs list ───────────────────────────────────────────
    probs: list[tuple[float, float]] = [
        (elo_prob,   w_elo),
        (model_prob, w_model),
    ]
    if market_valid:
        probs.append((market_prob, w_market))
    if mc_valid:
        probs.append((mc_mean, w_mc))

    combined = bayesian.combine_probs(probs)

    return {
        "prob":         combined,
        "weights": {
            "elo":    round(w_elo,    3),
            "ml":     round(w_model,  3),
            "market": round(w_market, 3),
            "mc":     round(w_mc,     3),
        },
        "model_probs": {
            "elo":    round(elo_prob,    4),
            "ml":     round(model_prob,  4),
            "market": round(market_prob, 4) if market_valid else None,
            "mc":     round(mc_mean,     4) if mc_valid     else None,
        },
        "bayesian_adj": bayes_adj,
    }
