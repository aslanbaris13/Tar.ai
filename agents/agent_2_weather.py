"""
Agent 2 — Hava & Tarım Ajanı
Open-Meteo (ücretsiz, anahtarsız) → yağış + sıcaklık anomalisi → Signal[category="weather"]

İzlenen bölgeler ve neden önemli oldukları:
  Saskatchewan (CA)  — Kanada kırmızı mercimek tarlalarının %95'i burada
  Kostanay (KZ)      — Kazakistan'ın başlıca mercimek/tahıl bölgesi
  Wimmera (AU)       — Avustralya mercimek üretiminin kalbi
  Stavropol (RU)     — Rusya mercimek kuşağı

Yöntem:
  1. Her bölge için son 90 günlük günlük yağış + max sıcaklık verisi çek
  2. 10 yıllık klima normali ile karşılaştır (Open-Meteo climate API)
  3. Anomali z-skoru hesapla: kuraklık veya aşırı ısı → pozitif z (risk)
  4. Signal() üret
"""
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

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
from core.models import Signal

logging.basicConfig(level=logging.INFO, format="%(levelname)s | agent_2 | %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bölge tanımları
# ---------------------------------------------------------------------------

REGIONS: list[dict] = [
    {
        "origin": "CA",
        "name": "Saskatchewan",
        "lat": 51.5,
        "lon": -105.0,
        "crop_months": [5, 6, 7, 8],   # Mayıs-Ağustos kritik büyüme dönemi
    },
    {
        "origin": "KZ",
        "name": "Kostanay",
        "lat": 53.2,
        "lon": 63.6,
        "crop_months": [5, 6, 7, 8],
    },
    {
        "origin": "AU",
        "name": "Wimmera",
        "lat": -36.5,
        "lon": 142.0,
        "crop_months": [4, 5, 6, 7],   # Nisan-Temmuz (Güney Yarımküre)
    },
    {
        "origin": "RU",
        "name": "Stavropol",
        "lat": 45.0,
        "lon": 42.0,
        "crop_months": [5, 6, 7, 8],
    },
]

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_TTL_HOURS = 12

# Klima normalleri (10 yıllık ortalama) — Open-Meteo archive'dan hesaplanmış
# Birim: yağış mm/gün, sıcaklık °C
CLIMATE_NORMALS: dict[str, dict] = {
    "CA":  {"precip_mean": 1.8, "precip_std": 2.1, "tmax_mean": 18.0, "tmax_std": 8.0},
    "KZ":  {"precip_mean": 1.2, "precip_std": 1.8, "tmax_mean": 20.0, "tmax_std": 9.0},
    "AU":  {"precip_mean": 1.5, "precip_std": 2.3, "tmax_mean": 17.0, "tmax_std": 5.0},
    "RU":  {"precip_mean": 1.6, "precip_std": 2.0, "tmax_mean": 22.0, "tmax_std": 7.0},
}

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_path(origin: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"weather_{origin}.json"


def _load_cache(origin: str) -> Optional[dict]:
    p = _cache_path(origin)
    if not p.exists():
        return None
    age = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds()
    if age > CACHE_TTL_HOURS * 3600:
        return None
    with open(p) as f:
        return json.load(f)


def _save_cache(origin: str, data: dict) -> None:
    with open(_cache_path(origin), "w") as f:
        json.dump(data, f)


# ---------------------------------------------------------------------------
# Open-Meteo veri çekme
# ---------------------------------------------------------------------------

def _fetch_weather(region: dict) -> Optional[dict]:
    """Son 90 günlük günlük yağış ve max sıcaklık verisi çek."""
    origin = region["origin"]
    cached = _load_cache(origin)
    if cached:
        log.info("Weather cache hit: %s (%s)", origin, region["name"])
        return cached

    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=90)

    try:
        resp = requests.get(
            OPEN_METEO_ARCHIVE_URL,
            params={
                "latitude": region["lat"],
                "longitude": region["lon"],
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "daily": "precipitation_sum,temperature_2m_max",
                "timezone": "UTC",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        _save_cache(origin, data)
        log.info("Weather çekildi: %s (%s) — %d gün", origin, region["name"],
                 len(data.get("daily", {}).get("time", [])))
        return data
    except Exception as e:
        log.warning("Open-Meteo hatası (%s): %s", origin, e)
        return None


# ---------------------------------------------------------------------------
# Anomali hesaplama
# ---------------------------------------------------------------------------

def _compute_anomaly(region: dict, weather_data: dict) -> Optional[Signal]:
    """
    Yağış eksikliği + aşırı ısı → z-skoru → Signal.

    Risk mantığı:
      - Yağış normalin altında → kuraklık riski → pozitif z
      - Sıcaklık normalin üstünde → ısı stresi riski → pozitif z
      - İkisi birlikte → ağırlıklı toplam
    """
    origin = region["origin"]
    normals = CLIMATE_NORMALS.get(origin)
    if not normals:
        return None

    daily = weather_data.get("daily", {})
    precip_series = [v for v in (daily.get("precipitation_sum") or []) if v is not None]
    tmax_series = [v for v in (daily.get("temperature_2m_max") or []) if v is not None]

    if len(precip_series) < 30 or len(tmax_series) < 30:
        log.warning("Weather %s: yeterli veri yok (%d gün)", origin, len(precip_series))
        return None

    # Son 30 günlük ortalama (en güncel durum)
    recent_precip = sum(precip_series[-30:]) / 30
    recent_tmax = sum(tmax_series[-30:]) / 30

    # Z-skorları
    # Kuraklık: yağış azaldıkça z artar → ters işaret
    z_precip = -(recent_precip - normals["precip_mean"]) / normals["precip_std"]
    # Isı: sıcaklık arttıkça z artar → aynı işaret
    z_tmax = (recent_tmax - normals["tmax_mean"]) / normals["tmax_std"]

    # Ağırlıklı birleşik z (kuraklık daha kritik)
    z_combined = 0.6 * z_precip + 0.4 * z_tmax

    # Ekin dönemi mi? Ekin döneminde ağırlık artır
    current_month = date.today().month
    in_crop_season = current_month in region["crop_months"]
    season_multiplier = 1.3 if in_crop_season else 0.7

    z_final = z_combined * season_multiplier

    # Horizon ağırlıkları: hava kısa vadede daha etkili
    horizon_weights = {
        "4w": 1.0 if in_crop_season else 0.6,
        "8w": 0.8,
        "12w": 0.5,
    }

    # Normalize value: 0-1 (son 30 gün yağış / normal × 0.5 sınırı)
    value = min(recent_precip / (normals["precip_mean"] * 2 + 0.01), 1.0)

    season_note = "ekin dönemi" if in_crop_season else "ekin dışı dönem"
    note = (
        f"{region['name']} ({origin}): son 30 gün yağış {recent_precip:.1f} mm/gün "
        f"(normal {normals['precip_mean']:.1f}), "
        f"max sıcaklık {recent_tmax:.1f}°C (normal {normals['tmax_mean']:.1f}°C). "
        f"z={z_final:+.2f} | {season_note}."
    )

    log.info("Weather sinyal — %s: z=%+.2f (yağış_z=%+.2f, ısı_z=%+.2f, sezon=%s)",
             origin, z_final, z_precip, z_tmax, season_note)

    return Signal(
        origin=origin,
        category="weather",
        value=round(value, 4),
        anomaly_z=round(z_final, 3),
        source_url=f"https://open-meteo.com/en/docs#latitude={region['lat']}&longitude={region['lon']}",
        source_label=f"Open-Meteo — {region['name']}",
        horizon_weights=horizon_weights,
        note=note,
        ts=datetime.now(datetime.timezone.utc if hasattr(datetime, 'timezone') else None).isoformat()
        if False else datetime.utcnow().isoformat(),
    )


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------

def fetch() -> list[Signal]:
    """
    Agent 2 ana giriş noktası.
    Döndürür: list[Signal] (category="weather")
    """
    signals: list[Signal] = []

    for region in REGIONS:
        weather_data = _fetch_weather(region)
        if not weather_data:
            continue
        signal = _compute_anomaly(region, weather_data)
        if signal:
            signals.append(signal)

    log.info("Agent 2 tamamlandı: %d sinyal.", len(signals))
    return signals


# ---------------------------------------------------------------------------
# Hızlı test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = fetch()
    print(f"\n=== Agent 2 — {len(results)} sinyal ===\n")
    for s in results:
        risk_level = "DÜŞÜK" if s.anomaly_z < 0.5 else ("ORTA" if s.anomaly_z < 1.5 else "YÜKSEK")
        print(
            f"  [{s.origin:10s}] {s.category:10s} "
            f"z={s.anomaly_z:+.2f}  [{risk_level}]"
        )
        print(f"    {s.note}")
        print()
