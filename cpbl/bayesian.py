"""V8 Bayesian Update Layer — 比純 RL 更穩定的概率校正（小樣本 CPBL 特別重要）"""
from __future__ import annotations
import math


# ── Beta 分布工具 ────────────────────────────────────────────────────────────

def beta_update(alpha: float, beta_v: float, wins: int, losses: int) -> tuple[float, float]:
    """Beta 分布後驗更新：先驗 (alpha, beta_v) + 實際 (wins, losses)。"""
    return alpha + wins, beta_v + losses


def beta_mean(alpha: float, beta_v: float) -> float:
    return alpha / (alpha + beta_v)


def beta_ci(alpha: float, beta_v: float, level: float = 0.90) -> tuple[float, float]:
    """使用 Wilson interval 近似 Beta 分布信賴區間。"""
    n   = alpha + beta_v
    p   = alpha / n
    z   = {0.90: 1.645, 0.95: 1.960, 0.80: 1.282}.get(level, 1.645)
    den = 1 + z**2 / n
    ctr = (p + z**2 / (2 * n)) / den
    mar = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / den
    return (max(0.01, ctr - mar), min(0.99, ctr + mar))


# ── 因子準確率的 Bayesian 權重 ────────────────────────────────────────────────

def prior_from_history(factor_accuracy: dict, factor_key: str,
                       prior_n: float = 8.0) -> tuple[float, float]:
    """
    從 memory.factor_accuracy 派生 Beta 先驗。
    prior_n: 虛擬樣本數（對應 50% 基準，越大代表對先驗越保守）。
    """
    fa   = factor_accuracy.get(factor_key, [0, 0])
    wins, total = fa[0], fa[1]
    losses = total - wins
    return (prior_n / 2 + wins, prior_n / 2 + losses)


def bayesian_weight(factor_accuracy: dict, factor_key: str) -> float:
    """
    根據歷史準確率給出 Bayesian 調整乘數 (0.65 ~ 1.50)。
    後驗均值 50% → 乘數 1.0（中性）
    後驗均值 70% → 乘數 1.44
    後驗均值 35% → 乘數 0.73（因子方向常錯）
    """
    alpha, beta_v = prior_from_history(factor_accuracy, factor_key)
    pm = beta_mean(alpha, beta_v)           # posterior mean
    return round(max(0.65, min(1.50, 0.65 + pm * 1.70)), 3)


# ── 概率融合（幾何加權平均 on log-odds）────────────────────────────────────────

def combine_probs(probs: list[tuple[float, float]]) -> float:
    """
    幾何加權融合多個概率估計。
    probs: [(probability, weight), ...]
    使用 log-odds 空間加權，避免線性平均的端點壓縮問題。
    """
    total_w = sum(w for _, w in probs)
    if total_w == 0:
        return 0.5
    log_odds_sum = 0.0
    for p, w in probs:
        p = max(0.01, min(0.99, p))
        log_odds_sum += math.log(p / (1 - p)) * w
    log_odds_avg = log_odds_sum / total_w
    return round(1.0 / (1.0 + math.exp(-log_odds_avg)), 4)


# ── 全局 Bayesian 概率校正 ─────────────────────────────────────────────────────

def posterior_prob(prior: float, model_prob: float, confidence: float,
                   n_obs: int = 0) -> float:
    """
    用 Bayesian 思維混合先驗（聯盟均值）與模型輸出。

    prior:      先驗概率（CPBL 主場勝率約 0.53）
    model_prob: 模型輸出概率
    confidence: 模型信心 (0~1)
    n_obs:      已觀測場次數（越多越相信模型）

    Returns: posterior probability
    """
    # 樣本越多，越相信模型；樣本少時回縮到先驗
    shrink = min(1.0, (n_obs / 30.0) ** 0.5)   # 0場=0%, 30場=100%, 10場≈58%
    model_weight = confidence * shrink
    prior_weight = 1.0 - model_weight * 0.6     # 保留至少 40% 先驗影響
    return combine_probs([(prior, prior_weight), (model_prob, model_weight)])


# ── 小樣本冷啟動修正因子 ──────────────────────────────────────────────────────

def cold_start_factor(total_games: int) -> float:
    """
    回傳信心壓縮因子 (0.75 ~ 1.00)。
    樣本不足時輕微壓縮 EV，避免過度下注。
    """
    if total_games < 5:
        return 0.75
    if total_games < 15:
        return 0.85
    if total_games < 30:
        return 0.92
    if total_games < 50:
        return 0.97
    return 1.00
