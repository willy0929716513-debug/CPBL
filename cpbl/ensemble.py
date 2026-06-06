"""
Ensemble Model — ELO + ML + MC 三模型融合。

⚠️ 重要架構決策：市場賠率（market_prob）不再納入 ensemble 計算。
原因：若把賠率混入勝率計算，再拿這個勝率去跟賠率比較，邏輯上是循環推理。
正確做法：模型勝率完全獨立計算，賠率只用於最後 edge 比較階段。
"""
from __future__ import annotations
from . import bayesian

# 基礎模型權重（三模型：ELO 歷史 + ML 9因子 + MC 模擬）
_W_ELO   = 0.18
_W_ML    = 0.67
_W_MC    = 0.15


def ensemble(
    elo_prob:    float,
    model_prob:  float,
    market_prob: float = 0.5,  # 僅供記錄，不納入計算
    mc_mean:     float | None = None,
    memory:      dict | None  = None,
) -> dict:
    """
    三模型加權 ensemble（ELO + ML + MC）。

    market_prob 僅保留供呼叫方記錄/顯示，不影響最終 prob。
    """
    w_elo   = _W_ELO
    w_model = _W_ML
    w_mc    = _W_MC

    # ── Bayesian 調整 ML 模型權重 ─────────────────────────────────
    bayes_adj = 1.0
    if memory and memory.get("total_games", 0) >= 10:
        fa      = memory.get("factor_accuracy", {})
        keys    = ["pitcher", "lineup", "bullpen", "form"]
        bw_vals = [bayesian.bayesian_weight(fa, k) for k in keys]
        bayes_adj = round(sum(bw_vals) / len(bw_vals), 3)
        bayes_adj = max(0.75, min(1.25, bayes_adj))
        w_model   = min(0.75, _W_ML * bayes_adj)
        surplus   = w_model - _W_ML
        w_elo     = max(0.05, _W_ELO - surplus * 0.40)
        w_mc      = max(0.05, _W_MC  - surplus * 0.60)

    # ── MC 資料有效性 ─────────────────────────────────────────────
    mc_valid = mc_mean is not None and 0.05 < mc_mean < 0.95
    if not mc_valid:
        w_model += w_mc * 0.60
        w_elo   += w_mc * 0.40
        w_mc     = 0.0

    probs: list[tuple[float, float]] = [
        (elo_prob,   w_elo),
        (model_prob, w_model),
    ]
    if mc_valid:
        probs.append((mc_mean, w_mc))

    combined = bayesian.combine_probs(probs)

    return {
        "prob":         combined,
        "weights": {
            "elo":    round(w_elo,   3),
            "ml":     round(w_model, 3),
            "market": 0.0,  # 已移除
            "mc":     round(w_mc,    3),
        },
        "model_probs": {
            "elo":    round(elo_prob,   4),
            "ml":     round(model_prob, 4),
            "market": round(market_prob, 4) if 0.05 < market_prob < 0.95 else None,
            "mc":     round(mc_mean,    4) if mc_valid else None,
        },
        "bayesian_adj": bayes_adj,
    }
