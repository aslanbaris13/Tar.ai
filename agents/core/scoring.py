"""Deterministik skorlama motoru. Aynı sinyaller → aynı skor."""
import math
from dataclasses import dataclass, field
from typing import List

from .models import Signal, ORIGINS, HORIZONS

# Kategori ağırlıkları ufka göre (PRD §5)
WEIGHTS: dict[str, dict[str, float]] = {
    "price":      {"4w": 0.50, "8w": 0.35, "12w": 0.25},
    "weather":    {"4w": 0.30, "8w": 0.25, "12w": 0.20},
    "regulation": {"4w": 0.20, "8w": 0.25, "12w": 0.20},
    "market":     {"4w": 0.15, "8w": 0.20, "12w": 0.25},
    "supply":     {"4w": 0.10, "8w": 0.20, "12w": 0.30},
}


@dataclass
class ScoreResult:
    origin: str
    horizon: str
    score: float           # 0-100
    confidence: str        # "Düşük" | "Orta" | "Yüksek"
    top_signals: list = field(default_factory=list)
    recommendation: str = ""  # "şimdi al" | "bekle" | "kısmi al" | "alternatif origin"
    category_scores: dict = field(default_factory=dict)


def _sigmoid(x: float) -> float:
    """0-1 aralığına sıkıştır."""
    return 1.0 / (1.0 + math.exp(-x))


def _confidence(signals: list[Signal], covered_categories: set[str]) -> str:
    """Veri kapsamı × sinyal yön uyumuna göre güven hesapla."""
    required = {"price", "weather", "regulation", "market"}
    coverage = len(covered_categories & required) / len(required)

    if not signals:
        return "Düşük"

    # Sinyal yön uyumu: z-skorları birbirine ne kadar tutarlı?
    z_values = [s.anomaly_z for s in signals]
    mean_z = sum(z_values) / len(z_values)
    variance = sum((z - mean_z) ** 2 for z in z_values) / len(z_values)
    consistency = 1.0 / (1.0 + variance)

    combined = 0.6 * coverage + 0.4 * consistency
    if combined >= 0.7:
        return "Yüksek"
    elif combined >= 0.4:
        return "Orta"
    return "Düşük"


def _recommendation(score: float, confidence: str) -> str:
    if confidence == "Düşük":
        return "veri yetersiz — izle"
    if score >= 70:
        return "bekle"
    elif score >= 50:
        return "kısmi al"
    elif score <= 25:
        return "şimdi al"
    return "normal al"


def compute_scores(signals: list[Signal]) -> list[ScoreResult]:
    """
    Her (origin × horizon) için ScoreResult üret.
    Deterministik: aynı sinyaller → aynı skor.
    """
    results: list[ScoreResult] = []

    for origin in ORIGINS:
        origin_signals = [s for s in signals if s.origin == origin]
        covered = {s.category for s in origin_signals}

        for horizon in HORIZONS:
            weighted_sum = 0.0
            weight_total = 0.0
            cat_scores: dict[str, float] = {}
            contributing: list[Signal] = []

            for sig in origin_signals:
                cat = sig.category
                if cat not in WEIGHTS:
                    continue
                w_base = WEIGHTS[cat].get(horizon, 0.0)
                w_horizon = sig.horizon_weights.get(horizon, 1.0)
                effective_w = w_base * w_horizon

                weighted_sum += effective_w * sig.anomaly_z
                weight_total += effective_w
                cat_scores[cat] = cat_scores.get(cat, 0.0) + effective_w * sig.anomaly_z
                contributing.append(sig)

            if weight_total == 0:
                raw_score = 0.0
            else:
                normalized_z = weighted_sum / weight_total
                # sigmoid → 0-1 → 0-100 ölçek. z=0 → 50, z=2 → ~88, z=-2 → ~12
                raw_score = _sigmoid(normalized_z * 1.5) * 100

            top = sorted(contributing, key=lambda s: abs(s.anomaly_z), reverse=True)[:3]
            confidence = _confidence(origin_signals, covered)
            rec = _recommendation(raw_score, confidence)

            results.append(ScoreResult(
                origin=origin,
                horizon=horizon,
                score=round(raw_score, 1),
                confidence=confidence,
                top_signals=top,
                recommendation=rec,
                category_scores={k: round(v, 3) for k, v in cat_scores.items()},
            ))

    return results
