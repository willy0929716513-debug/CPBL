"""NPB/KBO Ensemble — MC×70% + NormalCDF×30%，封頂22-76%"""
from __future__ import annotations
from . import bayesian


def ensemble(
    elo_prob:    float,
    model_prob:  float,
    market_prob: float = 0.5,
    mc_mean:     float | None = None,
    mc_norm_cdf: float | None = None,
    memory:      dict | None  = None,
) -> dict:
    """
    Layer 4 勝率計算：
        model_win_p = MC×70% + NormalCDF×30%
    封頂 22%-76%

    elo_prob:    ELO 基礎勝率（僅供 metadata 記錄）
    model_prob:  9因子 ML 模型輸出（備用，無MC時使用）
    market_prob: 市場隱含勝率（顯示用，不參與計算）
    mc_mean:     Poisson MC 平均勝率
    mc_norm_cdf: NormalCDF(期望得分差 / σ)
    memory:      RL 記憶（Bayesian 微調）
    """
    # ── MC 有效性 ─────────────────────────────────────────────────────
    mc_valid   = mc_mean    is not None and 0.05 < mc_mean    < 0.95
    norm_valid = mc_norm_cdf is not None and 0.05 < mc_norm_cdf < 0.95

    if mc_valid and norm_valid:
        raw = mc_mean * 0.70 + mc_norm_cdf * 0.30
    elif mc_valid:
        raw = mc_mean * 0.85 + model_prob * 0.15
    elif norm_valid:
        raw = mc_norm_cdf * 0.70 + model_prob * 0.30
    else:
        raw = model_prob

    # ── Bayesian 微調（資料夠多才啟動）───────────────────────────────
    bayes_adj = 1.0
    if memory and memory.get("total_games", 0) >= 10:
        fa     = memory.get("factor_accuracy", {})
        keys   = ["pitcher", "lineup", "bullpen", "form"]
        bw     = [bayesian.bayesian_weight(fa, k) for k in keys]
        bayes_adj = round(sum(bw) / len(bw), 3)
        bayes_adj = max(0.85, min(1.15, bayes_adj))
        # 向中值方向輕微拉伸/壓縮
        raw = 0.5 + (raw - 0.5) * bayes_adj

    # ── 封頂 22%-76% ─────────────────────────────────────────────────
    prob = round(max(0.22, min(0.76, raw)), 4)

    return {
        "prob":         prob,
        "weights": {
            "mc":       0.70 if mc_valid else 0.0,
            "norm_cdf": 0.30 if norm_valid else 0.0,
            "ml":       0.0 if (mc_valid or norm_valid) else 1.0,
        },
        "model_probs": {
            "elo":      round(elo_prob,    4),
            "ml":       round(model_prob,  4),
            "mc":       round(mc_mean,     4) if mc_valid    else None,
            "norm_cdf": round(mc_norm_cdf, 4) if norm_valid  else None,
            "market":   round(market_prob, 4) if 0.05 < market_prob < 0.95 else None,
        },
        "bayesian_adj": bayes_adj,
    }
