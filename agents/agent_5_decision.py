"""
Agent 5 — Karar Ajanı (Orkestrasyon)
1+2+3+4 ajanlarını çağırır → compute_scores() → generate_rationale() → final karar JSON üretir

Çıktı formatı (API'nin tükettiği):
{
  "generated_at": "2026-06-08T...",
  "matrix": [
    {
      "origin": "CA",
      "horizon": "4w",
      "score": 11.8,
      "confidence": "Orta",
      "recommendation": "şimdi al",
      "rationale": "...",
      "key_factors": ["...", "..."],
      "cited_sources": ["url1", "url2"]
    },
    ...
  ]
}
"""
import json
import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    _env_file = Path(__file__).parent.parent / ".env"
    if _env_file.exists():
        for _line in _env_file.read_text().splitlines():
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

sys.path.insert(0, str(Path(__file__).parent))
from core.models import Signal, ORIGINS, HORIZONS
from core.scoring import compute_scores, ScoreResult
from core.reasoning import generate_rationale

logging.basicConfig(level=logging.INFO, format="%(levelname)s | agent_5 | %(message)s")
log = logging.getLogger(__name__)

RESULT_CACHE_PATH = Path(__file__).parent / "cache" / "decision_result.json"
RESULT_CACHE_TTL_HOURS = 6


# ---------------------------------------------------------------------------
# Ajan import'ları (zarif bozulma: bir ajan düşse diğerleri çalışır)
# ---------------------------------------------------------------------------

def _run_agent(name: str, fetch_fn) -> list[Signal]:
    """Tek bir ajanı çalıştır. Hata olursa boş liste döner, sistem çökmez."""
    try:
        signals = fetch_fn()
        log.info("%s: %d sinyal", name, len(signals))
        return signals
    except Exception as e:
        log.error("%s başarısız: %s — boş liste ile devam.", name, e)
        return []


def _collect_signals(as_of: Optional[date] = None) -> list[Signal]:
    """Tüm ajanları çalıştır ve sinyalleri birleştir."""
    all_signals: list[Signal] = []

    # Agent 1 — Fiyat (backtest modu destekliyor)
    try:
        from agent_1_price import fetch as f1
        all_signals.extend(_run_agent("Agent1/Fiyat", lambda: f1(as_of=as_of)))
    except ImportError:
        log.error("agent_1_price import edilemedi.")

    # Agent 2 — Hava
    try:
        from agent_2_weather import fetch as f2
        all_signals.extend(_run_agent("Agent2/Hava", f2))
    except ImportError:
        log.error("agent_2_weather import edilemedi.")

    # Agent 3 — Haber
    try:
        from agent_3_news import fetch as f3
        all_signals.extend(_run_agent("Agent3/Haber", f3))
    except ImportError:
        log.error("agent_3_news import edilemedi.")

    # Agent 4 — Piyasa
    try:
        from agent_4_market import fetch as f4
        all_signals.extend(_run_agent("Agent4/Piyasa", f4))
    except ImportError:
        log.error("agent_4_market import edilemedi.")

    log.info("Toplam sinyal: %d", len(all_signals))
    return all_signals


# ---------------------------------------------------------------------------
# Senaryo analizi
# ---------------------------------------------------------------------------

def run_scenario(
    origin: str,
    signal_category: str,
    delta_z: float,
    base_signals: Optional[list[Signal]] = None,
) -> dict:
    """
    What-if analizi: belirli bir sinyalin z-skorunu delta kadar değiştir,
    yeni skoru hesapla ve farkı döndür.

    Örnek: {"origin": "CA", "signal": "weather", "delta_z": 2.0}
    → "Kanada'da kuraklık çıksaydı skor ne olurdu?"
    """
    if base_signals is None:
        base_signals = _collect_signals()

    # Senaryolu sinyal listesi: ilgili sinyallere delta ekle
    scenario_signals = []
    for s in base_signals:
        if s.origin == origin and s.category == signal_category:
            from dataclasses import replace
            scenario_signals.append(replace(s, anomaly_z=s.anomaly_z + delta_z))
        else:
            scenario_signals.append(s)

    base_results = {(r.origin, r.horizon): r for r in compute_scores(base_signals)}
    scenario_results = {(r.origin, r.horizon): r for r in compute_scores(scenario_signals)}

    deltas = []
    for horizon in HORIZONS:
        key = (origin, horizon)
        base = base_results.get(key)
        scen = scenario_results.get(key)
        if base and scen:
            deltas.append({
                "horizon": horizon,
                "base_score": base.score,
                "scenario_score": scen.score,
                "delta": round(scen.score - base.score, 1),
                "base_recommendation": base.recommendation,
                "scenario_recommendation": scen.recommendation,
            })

    return {
        "origin": origin,
        "signal_category": signal_category,
        "delta_z": delta_z,
        "description": f"{origin} {signal_category} sinyali {delta_z:+.1f}z değişirse",
        "results": deltas,
    }


# ---------------------------------------------------------------------------
# Ana orkestrasyon
# ---------------------------------------------------------------------------

def run(
    as_of: Optional[date] = None,
    use_cache: bool = True,
    with_rationale: bool = True,
) -> dict:
    """
    Tam analiz pipeline'ı.
    as_of: backtest tarihi (None = bugün)
    use_cache: son 6 saatte çalıştıysa cache döndür
    with_rationale: LLM gerekçe üret (yavaş, demo için True)
    """
    # Cache kontrolü (sadece bugünkü çalışmalar için)
    if use_cache and as_of is None and RESULT_CACHE_PATH.exists():
        age = (datetime.now() - datetime.fromtimestamp(
            RESULT_CACHE_PATH.stat().st_mtime)).total_seconds()
        if age < RESULT_CACHE_TTL_HOURS * 3600:
            log.info("Decision cache hit (%.0f dk önce).", age / 60)
            with open(RESULT_CACHE_PATH) as f:
                return json.load(f)

    t0 = time.time()
    log.info("=== Agent 5 başladı (as_of=%s) ===", as_of or "bugün")

    # 1. Tüm sinyalleri topla
    signals = _collect_signals(as_of=as_of)

    # 2. Skorla
    score_results = compute_scores(signals)
    log.info("Skorlama tamamlandı: %d hücre", len(score_results))

    # 3. Her hücre için gerekçe üret
    matrix = []
    for result in score_results:
        cell: dict = {
            "origin": result.origin,
            "horizon": result.horizon,
            "score": result.score,
            "confidence": result.confidence,
            "recommendation": result.recommendation,
            "category_scores": result.category_scores,
        }

        if with_rationale:
            rationale_data = generate_rationale(result, signals)
            cell["rationale"] = rationale_data.get("rationale", "")
            cell["key_factors"] = rationale_data.get("key_factors", [])
            cell["cited_sources"] = rationale_data.get("cited_sources", [])
        else:
            cell["rationale"] = ""
            cell["key_factors"] = []
            cell["cited_sources"] = []

        matrix.append(cell)

    elapsed = time.time() - t0
    output = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "as_of": as_of.isoformat() if as_of else None,
        "elapsed_seconds": round(elapsed, 1),
        "signal_count": len(signals),
        "matrix": matrix,
    }

    # Cache kaydet (sadece bugünkü çalışmalar)
    if as_of is None:
        RESULT_CACHE_PATH.parent.mkdir(exist_ok=True)
        with open(RESULT_CACHE_PATH, "w") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

    log.info("=== Agent 5 tamamlandı (%.1fs, %d sinyal, %d hücre) ===",
             elapsed, len(signals), len(matrix))
    return output


# ---------------------------------------------------------------------------
# Kolay erişim: sadece belirli origin/horizon
# ---------------------------------------------------------------------------

def get_cell(origin: str, horizon: str, result: Optional[dict] = None) -> Optional[dict]:
    """Tek hücre döndür. result yoksa run() çağırır."""
    if result is None:
        result = run(with_rationale=True)
    for cell in result.get("matrix", []):
        if cell["origin"] == origin and cell["horizon"] == horizon:
            return cell
    return None


# ---------------------------------------------------------------------------
# Hızlı test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", help="YYYY-MM-DD formatında backtest tarihi")
    parser.add_argument("--no-rationale", action="store_true", help="LLM gerekçe üretme (hızlı)")
    parser.add_argument("--scenario", help="origin:category:delta_z  örn: CA:weather:2.0")
    args = parser.parse_args()

    if args.scenario:
        parts = args.scenario.split(":")
        origin, category, delta_z = parts[0], parts[1], float(parts[2])
        result = run(with_rationale=False, use_cache=False)
        signals = _collect_signals()
        scen = run_scenario(origin, category, delta_z, signals)
        print(f"\n=== Senaryo: {scen['description']} ===\n")
        for d in scen["results"]:
            arrow = "↑" if d["delta"] > 0 else ("↓" if d["delta"] < 0 else "→")
            print(f"  {d['horizon']}: {d['base_score']:.1f} {arrow} {d['scenario_score']:.1f} "
                  f"({d['delta']:+.1f})  |  {d['base_recommendation']} → {d['scenario_recommendation']}")
        print()
    else:
        as_of_date = date.fromisoformat(args.backtest) if args.backtest else None
        result = run(
            as_of=as_of_date,
            use_cache=False,
            with_rationale=not args.no_rationale,
        )

        print(f"\n=== Skor Matrisi ({result['generated_at'][:10]}) ===")
        print(f"    {result['signal_count']} sinyal | {result['elapsed_seconds']}s\n")
        print(f"{'Origin':<12} {'4w':>6} {'8w':>6} {'12w':>6}  {'Güven':<8}  Öneri")
        print("─" * 62)

        for origin in ORIGINS:
            cells = {c["horizon"]: c for c in result["matrix"] if c["origin"] == origin}
            if not cells:
                continue
            c4, c8, c12 = cells.get("4w", {}), cells.get("8w", {}), cells.get("12w", {})
            print(f"{origin:<12} "
                  f"{c4.get('score', 0):>6.1f} "
                  f"{c8.get('score', 0):>6.1f} "
                  f"{c12.get('score', 0):>6.1f}  "
                  f"{c4.get('confidence', '?'):<8}  "
                  f"{c4.get('recommendation', '?')}")

        print()
        # CA 4w gerekçesini göster
        ca_4w = get_cell("CA", "4w", result)
        if ca_4w and ca_4w.get("rationale"):
            print("=== CA / 4 Hafta Gerekçe ===")
            print(ca_4w["rationale"])
            if ca_4w.get("cited_sources"):
                print("Kaynaklar:", ca_4w["cited_sources"])
