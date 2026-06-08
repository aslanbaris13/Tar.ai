"""
TARAI — FastAPI Backend
API_CONTRACT.md'deki formata birebir uyan endpoint'ler.

Çalıştırma:
  cd Tar.ai
  source .venv/bin/activate
  uvicorn api.main:app --reload --port 8000
"""
import os
import sys
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# .env yükle
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

# Agents klasörü Python path'ine ekle
AGENTS_DIR = Path(__file__).parent.parent / "agents"
sys.path.insert(0, str(AGENTS_DIR))

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s | api | %(message)s")

# ---------------------------------------------------------------------------
# Uygulama
# ---------------------------------------------------------------------------

app = FastAPI(
    title="TARAI — Armada Co-Pilot API",
    description="Kırmızı mercimek tedarik riski erken uyarı sistemi",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Sabitler — Origin meta verisi
# ---------------------------------------------------------------------------

ORIGIN_META: dict[str, dict] = {
    "CA":        {"name": "Kanada",      "flag": "🇨🇦"},
    "KZ":        {"name": "Kazakistan",  "flag": "🇰🇿"},
    "RU":        {"name": "Rusya",       "flag": "🇷🇺"},
    "IN":        {"name": "Hindistan",   "flag": "🇮🇳"},
    "AU":        {"name": "Avustralya",  "flag": "🇦🇺"},
    "SY":        {"name": "Suriye",      "flag": "🇸🇾"},
    "TR_MERSIN": {"name": "Türkiye",     "flag": "🇹🇷"},
}

# Horizon: API int → internal string
def _h(horizon: int) -> str:
    return f"{horizon}w"

# Karar metni normalleştirme (internal → API kontratı)
DECISION_MAP = {
    "şimdi al":              "Şimdi Al",
    "bekle":                 "Bekle",
    "kısmi al":              "Kısmi Al",
    "normal al":             "Kısmi Al",
    "alternatif origin":     "Alternatif Bak",
    "veri yetersiz — izle":  "Bekle",
}

def _decision(raw: str) -> str:
    return DECISION_MAP.get(raw.lower(), "Kısmi Al")

# Senaryo şok tanımları
SHOCKS: dict[str, dict] = {
    "india_export_ban":  {"origin": "IN", "category": "regulation", "delta_z": 3.0,
                          "name": "Hindistan ihracatı kapatır"},
    "canada_drought":    {"origin": "CA", "category": "weather",    "delta_z": 3.0,
                          "name": "Kanada kuraklık derinleşir"},
    "russia_embargo":    {"origin": "RU", "category": "regulation", "delta_z": 3.0,
                          "name": "Rusya ambargo"},
    "kazakhstan_quota":  {"origin": "KZ", "category": "regulation", "delta_z": 2.5,
                          "name": "Kazakistan ihracat kotası"},
}

# ---------------------------------------------------------------------------
# Ajan yükleyiciler (lazy, hata toleranslı)
# ---------------------------------------------------------------------------

def _get_full_result(use_cache: bool = True) -> dict:
    """Agent 5'i çalıştır veya cache'den döndür."""
    from agent_5_decision import run
    return run(use_cache=use_cache, with_rationale=True)


def _get_signals():
    """Tüm ajanlardan sinyal topla."""
    from agent_5_decision import _collect_signals
    return _collect_signals()


def _get_price_series() -> dict:
    """Armada Excel'den haftalık fiyat serisi çıkar."""
    import pandas as pd
    from agent_1_price import _load_armada, ORIGIN_MAP

    df = _load_armada()
    df["hafta"] = df["Belge tarihi"].dt.to_period("W").apply(lambda p: p.start_time.date())

    series: dict[str, list] = {}
    dates_set = set()

    for origin, group in df.groupby("origin"):
        if origin not in ORIGIN_META:
            continue
        weekly = group.groupby("hafta")["Net fiyat"].mean().round(1)
        series[origin] = {str(k): v for k, v in weekly.items()}
        dates_set.update(weekly.index)

    sorted_dates = sorted(dates_set)
    return {"dates": [str(d) for d in sorted_dates], "series": series}


# ---------------------------------------------------------------------------
# Endpoint 1 — GET /risk/all
# ---------------------------------------------------------------------------

@app.get("/risk/all")
def risk_all(horizon: int = Query(4, description="Zaman ufku (4, 8 veya 12 hafta)")):
    """
    Tüm originlerin risk skorunu döndürür.
    Oyku → Ana Dashboard grid kartları buradan beslenir.
    """
    if horizon not in (4, 8, 12):
        raise HTTPException(400, "horizon 4, 8 veya 12 olmalı")

    result = _get_full_result()
    h = _h(horizon)

    origins_out = []
    for code, meta in ORIGIN_META.items():
        cell = next((c for c in result["matrix"]
                     if c["origin"] == code and c["horizon"] == h), None)
        if not cell:
            continue
        origins_out.append({
            "code": code,
            "name": meta["name"],
            "flag": meta["flag"],
            "risk_score": int(round(cell["score"])),
            "decision": _decision(cell["recommendation"]),
            "confidence": cell["confidence"],
            "reason": cell.get("rationale", "")[:120],
        })

    return {
        "updated_at": result["generated_at"],
        "horizon": horizon,
        "origins": origins_out,
    }


# ---------------------------------------------------------------------------
# Endpoint 2 — GET /risk/{origin}
# ---------------------------------------------------------------------------

@app.get("/risk/{origin_code}")
def risk_detail(origin_code: str, horizon: int = Query(4)):
    """
    Tek origin detayı: fiyat + hava + haber + AI gerekçe + tüm horizon'lar.
    Oyku → Origin Detay sayfası buradan beslenir.
    """
    origin_code = origin_code.upper()
    if origin_code not in ORIGIN_META:
        raise HTTPException(404, f"Origin bulunamadı: {origin_code}")
    if horizon not in (4, 8, 12):
        raise HTTPException(400, "horizon 4, 8 veya 12 olmalı")

    result = _get_full_result()
    signals = _get_signals()
    meta = ORIGIN_META[origin_code]
    h = _h(horizon)

    cell = next((c for c in result["matrix"]
                 if c["origin"] == origin_code and c["horizon"] == h), None)
    if not cell:
        raise HTTPException(503, "Veri hesaplanamadı")

    # Origin'e ait sinyalleri kategoriye göre grupla
    origin_signals = [s for s in signals if s.origin == origin_code]

    def _cat_info(category: str) -> dict:
        sigs = [s for s in origin_signals if s.category == category]
        if not sigs:
            return {"risk": "Bilinmiyor", "detail": "Veri yok", "source": "—"}
        top = max(sigs, key=lambda s: abs(s.anomaly_z))
        z = top.anomaly_z
        risk = "Yüksek" if z > 1.0 else ("Orta" if z > 0.3 else "Düşük")
        return {
            "risk": risk,
            "detail": top.note[:80] if top.note else "—",
            "source": top.source_label or "—",
        }

    # Fiyat bilgisi
    price_sigs = [s for s in origin_signals if s.category == "price"]
    price_info: dict = {"value": None, "change_pct": None, "trend": None, "source": "Armada"}
    if price_sigs:
        # note'dan fiyat parse et
        import re
        note = price_sigs[0].note
        m = re.search(r"son fiyat (\d+)", note)
        m2 = re.search(r"trend: ([+\-\d.]+)%", note)
        if m:
            price_info["value"] = int(m.group(1))
        if m2:
            pct = float(m2.group(1))
            price_info["change_pct"] = pct
            price_info["trend"] = "up" if pct > 0 else "down"

    # Tüm horizon'lardaki karar
    horizons_out = {}
    for h_int in (4, 8, 12):
        h_str = _h(h_int)
        c = next((x for x in result["matrix"]
                  if x["origin"] == origin_code and x["horizon"] == h_str), None)
        if c:
            horizons_out[str(h_int)] = {
                "decision": _decision(c["recommendation"]),
                "confidence": c["confidence"],
                "score": int(round(c["score"])),
            }

    return {
        "code": origin_code,
        "name": meta["name"],
        "flag": meta["flag"],
        "risk_score": int(round(cell["score"])),
        "decision": _decision(cell["recommendation"]),
        "confidence": cell["confidence"],
        "horizon": horizon,
        "weather": _cat_info("weather"),
        "news": _cat_info("regulation"),
        "price": price_info,
        "ai_reason": cell.get("rationale", ""),
        "sources": list({s.source_label for s in origin_signals if s.source_label}),
        "horizons": horizons_out,
    }


# ---------------------------------------------------------------------------
# Endpoint 3 — GET /prices/trend
# ---------------------------------------------------------------------------

@app.get("/prices/trend")
def prices_trend(horizon: int = Query(8)):
    """
    Haftalık fiyat serisi + özet.
    Oyku → Fiyat Analizi sayfası, grafik 1 ve 2.
    """
    try:
        price_data = _get_price_series()
    except Exception as e:
        log.error("Fiyat serisi oluşturulamadı: %s", e)
        raise HTTPException(503, "Fiyat verisi alınamadı")

    dates = price_data["dates"]
    series = price_data["series"]

    # Horizon'a göre son N haftalık dilim
    weeks = horizon * 2  # ufkun 2 katı geçmiş göster
    dates_slice = dates[-weeks:] if len(dates) > weeks else dates

    series_sliced = {}
    for origin, weekly in series.items():
        values = [weekly.get(d) for d in dates_slice]
        series_sliced[origin] = values

    # Özet: en ucuz, en pahalı, en çok artan, en çok düşen
    last_prices = {}
    first_prices = {}
    for origin, vals in series_sliced.items():
        clean = [v for v in vals if v is not None]
        if clean:
            last_prices[origin] = clean[-1]
            first_prices[origin] = clean[0]

    changes = {o: last_prices[o] - first_prices[o]
               for o in last_prices if o in first_prices}

    summary = {}
    if last_prices:
        summary["lowest_origin"] = min(last_prices, key=last_prices.get)
        summary["highest_origin"] = max(last_prices, key=last_prices.get)
    if changes:
        summary["biggest_riser"] = max(changes, key=changes.get)
        summary["biggest_faller"] = min(changes, key=changes.get)

    # Forecast: horizon kadar hafta için linear trend extrapolation
    # Son 8 haftanın eğimini alıp ileriye projeksiyon
    forecast_weeks = horizon  # kaç hafta ileri
    forecast: dict[str, list] = {}
    for origin, vals in series_sliced.items():
        clean = [(i, v) for i, v in enumerate(vals) if v is not None]
        if len(clean) < 4:
            forecast[origin] = [None] * forecast_weeks
            continue
        # Son 8 nokta (veya tüm seri) üzerinden slope hesapla
        tail = clean[-8:]
        n = len(tail)
        xs = [p[0] for p in tail]
        ys = [p[1] for p in tail]
        x_mean = sum(xs) / n
        y_mean = sum(ys) / n
        num = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
        den = sum((xs[i] - x_mean) ** 2 for i in range(n))
        slope = num / den if den != 0 else 0
        # Aşırı değişimi sınırla: haftalık max ±%1.5
        max_weekly_change = y_mean * 0.015
        slope = max(-max_weekly_change, min(max_weekly_change, slope))
        last_val = ys[-1]
        fcast = [round(last_val + slope * (i + 1), 1) for i in range(forecast_weeks)]
        forecast[origin] = fcast

    return {
        "horizon": horizon,
        "unit": "USD/MT",
        "dates": dates_slice,
        "series": series_sliced,
        "forecast": forecast,
        "forecast_weeks": forecast_weeks,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# Endpoint 4 — GET /alerts
# ---------------------------------------------------------------------------

@app.get("/alerts")
def alerts():
    """
    Tüm aktif uyarılar (haber + hava sinyalleri).
    Oyku → Son Uyarılar sayfası.
    """
    signals = _get_signals()

    TYPE_MAP = {
        "regulation": "Politika",
        "weather":    "Hava",
        "price":      "Fiyat",
        "supply":     "Jeopolitik",
        "market":     "Piyasa",
    }

    alert_list = []
    for sig in signals:
        if sig.anomaly_z <= 0.2:
            continue  # düşük anomali → uyarı değil

        z = sig.anomaly_z
        severity = "high" if z > 1.5 else ("medium" if z > 0.7 else "low")

        alert_list.append({
            "time": sig.ts[:10] if sig.ts else "—",
            "type": TYPE_MAP.get(sig.category, "Diğer"),
            "text": sig.note[:120] if sig.note else "—",
            "source": sig.source_label or "—",
            "origin": sig.origin,
            "severity": severity,
            "score": round(z, 2),
        })

    # En yüksek anomaliden en düşüğe sırala
    alert_list.sort(key=lambda a: a["score"], reverse=True)

    return {"alerts": alert_list}


# ---------------------------------------------------------------------------
# Endpoint 5 — POST /scenario
# ---------------------------------------------------------------------------

class ScenarioRequest(BaseModel):
    shock: str  # "india_export_ban" | "canada_drought" | "russia_embargo" | "kazakhstan_quota"


@app.post("/scenario")
def scenario(req: ScenarioRequest):
    """
    Senaryo simülatörü: belirli bir şok gerçekleşirse skor nasıl değişir?
    Oyku → Senaryo Simülatörü sayfası.
    """
    shock_def = SHOCKS.get(req.shock)
    if not shock_def:
        raise HTTPException(400, f"Bilinmeyen şok: {req.shock}. "
                                 f"Geçerli değerler: {list(SHOCKS.keys())}")

    from agent_5_decision import run_scenario, _collect_signals
    from core.scoring import compute_scores

    base_signals = _collect_signals()
    base_results = {(r.origin, r.horizon): r for r in compute_scores(base_signals)}

    scen = run_scenario(
        origin=shock_def["origin"],
        signal_category=shock_def["category"],
        delta_z=shock_def["delta_z"],
        base_signals=base_signals,
    )

    # Her origin için 4w bazında before/after
    results_out = []
    from core.scoring import compute_scores as cs
    from dataclasses import replace as dc_replace

    # Senaryolu tüm sinyaller (sadece hedef origin değişir)
    scenario_signals = []
    for s in base_signals:
        if s.origin == shock_def["origin"] and s.category == shock_def["category"]:
            scenario_signals.append(dc_replace(s, anomaly_z=s.anomaly_z + shock_def["delta_z"]))
        else:
            scenario_signals.append(s)
    scenario_results = {(r.origin, r.horizon): r for r in cs(scenario_signals)}

    # FOB fiyat tahmini için fiyat sinyallerinden son fiyatı al
    fob_prices: dict[str, float] = {}
    for s in base_signals:
        if s.category == "price" and s.note:
            import re as _re
            m = _re.search(r"son fiyat (\d+)", s.note)
            if m:
                fob_prices[s.origin] = float(m.group(1))

    for code, meta in ORIGIN_META.items():
        base = base_results.get((code, "4w"))
        scen_r = scenario_results.get((code, "4w"))
        if not base or not scen_r:
            continue

        # FOB fiyat etkisi: risk skoru farkını fiyat değişimine dönüştür
        # Her 10 puan risk artışı ≈ %2 fiyat artışı (kaba tahmin)
        fob_base = fob_prices.get(code)
        risk_delta = scen_r.score - base.score
        if fob_base and fob_base > 0:
            fob_change_pct = risk_delta * 0.2   # 10 puan risk → %2 fiyat artışı
            fob_after = round(fob_base * (1 + fob_change_pct / 100), 1)
            fob_delta_pct = round(fob_change_pct, 1)
        else:
            fob_after = None
            fob_delta_pct = None

        results_out.append({
            "code": code,
            "name": meta["name"],
            "flag": meta["flag"],
            "before": int(round(base.score)),
            "after": int(round(scen_r.score)),
            "delta": int(round(risk_delta)),
            "fob_before": fob_base,
            "fob_after": fob_after,
            "fob_delta_pct": fob_delta_pct,
        })

    # Öneri: en çok etkilenen origin'leri vurgula
    risen = sorted([r for r in results_out if r["delta"] > 0],
                   key=lambda r: r["delta"], reverse=True)
    safe = sorted([r for r in results_out if r["after"] < 40],
                  key=lambda r: r["after"])

    if safe:
        rec_names = " ve ".join(m["name"] for m in safe[:2])
        recommendation = f"{rec_names} origin'lerinden hemen pozisyon al."
    elif risen:
        rec_names = risen[0]["name"]
        recommendation = f"{rec_names} için alternatif origin ara."
    else:
        recommendation = "Mevcut pozisyonu koru, gelişmeleri izle."

    return {
        "shock_name": shock_def["name"],
        "results": results_out,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/")
def health():
    return {
        "status": "ok",
        "service": "TARAI Armada Co-Pilot API",
        "version": "1.0.0",
        "docs": "/docs",
    }


# ---------------------------------------------------------------------------
# Direkt çalıştırma
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
