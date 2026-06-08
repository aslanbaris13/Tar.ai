"""
Agent 4 — Piyasa & Talep Ajanı
Hindistan Mandi/MSP + sarı bezelye fiyatı + WFP ihale takibi → Signal[category="market"]

Akış:
  1. Agmarknet (Hindistan Mandi): masoor dal spot fiyatı vs MSP → "swing buyer" riski
     Masoor Mandi < MSP → Hindistan ihracat yapmaz → CA/KZ'ye talep kayması
  2. Sarı bezelye (yellow pea) fiyatı: CA/AU → kırmızı mercimek ikame tavanı
     Sarı bezelye pahalanırsa → kırmızı mercimeğe talep artar → yukarı baskı
  3. WFP ihale takibi: büyük anlık talep patlaması sinyali
"""
import json
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
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

logging.basicConfig(level=logging.INFO, format="%(levelname)s | agent_4 | %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_TTL_HOURS = 12

# Hindistan MSP (Minimum Destek Fiyatı) 2025-26 kırmızı mercimek (masoor)
# Kaynak: https://cacp.dacnet.nic.in  — yıllık güncellenir
INDIA_MSP_USD_PER_MT = 480.0  # 2025-26 tahmini (INR 6000/quintal ≈ 720 USD/MT → iç piyasa)
# Not: INR/USD kurunu dinamik çekmek yerine sabit tutuyoruz (MVP)

# Agmarknet API (ücretsiz, anonim)
AGMARKNET_URL = "https://agmarknet.gov.in/SearchCmmMkt.aspx"
# Alternatif: data.gov.in API
DATA_GOV_IN_URL = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"
DATA_GOV_IN_KEY = os.getenv("DATA_GOV_IN_KEY", "579b464db66ec23bdd000001cdd3946e44ce4aab825d19e8d86c3dbe")

# WFP tender RSS/JSON
WFP_TENDER_URL = "https://www.wfp.org/procurement/food-tenders/rss"

# Yellow pea (sarı bezelye) referans fiyat proxy — Quandl/Statista olmadan
# Alternatif: World Bank Pink Sheet "Yellow Pea" kolonu (aynı dosya)
WB_CACHE_PATH = Path(__file__).parent / "cache" / "wb_pink_sheet.xlsx"
WB_PINK_SHEET_URL = (
    "https://thedocs.worldbank.org/en/doc/"
    "74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx"
)

# Tarihsel sarı bezelye uzun dönem ortalama (USD/MT) — MVP fallback
YELLOW_PEA_HIST_AVG = 280.0
YELLOW_PEA_HIST_STD = 55.0

# Tarihsel masoor Mandi ortalama (USD/MT) — MVP fallback
MASOOR_HIST_AVG = 450.0
MASOOR_HIST_STD = 80.0


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"market_{name}.json"


def _load_cache(name: str) -> Optional[dict]:
    p = _cache_path(name)
    if not p.exists():
        return None
    age = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds()
    if age > CACHE_TTL_HOURS * 3600:
        return None
    with open(p) as f:
        return json.load(f)


def _save_cache(name: str, data: dict) -> None:
    with open(_cache_path(name), "w") as f:
        json.dump(data, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 1. Hindistan Mandi — masoor dal fiyatı
# ---------------------------------------------------------------------------

def _fetch_mandi_price() -> Optional[float]:
    """
    data.gov.in API'den masoor dal (kırmızı mercimek) son Mandi fiyatını çek (INR/quintal).
    Başarısız olursa None döner.
    """
    cached = _load_cache("mandi")
    if cached:
        log.info("Mandi: cache hit")
        return cached.get("price_usd_mt")

    try:
        resp = requests.get(
            DATA_GOV_IN_URL,
            params={
                "api-key": DATA_GOV_IN_KEY,
                "format": "json",
                "filters[Commodity]": "Masoor Dal",
                "limit": 50,
                "sort[Arrival_Date]": "desc",
            },
            timeout=15,
        )
        resp.raise_for_status()
        records = resp.json().get("records", [])
        if not records:
            log.warning("Mandi: kayıt bulunamadı.")
            return None

        # Son fiyat (INR/quintal → USD/MT: 1 quintal = 100 kg)
        # USD dönüşüm: yaklaşık 1 USD = 83 INR (MVP sabit kur)
        INR_USD = 1 / 83.0
        prices = []
        for r in records[:20]:
            try:
                price_inr = float(r.get("Modal_Price") or r.get("Max_Price") or 0)
                if price_inr > 0:
                    prices.append(price_inr * INR_USD * 10)  # quintal→MT (*10)
            except (ValueError, TypeError):
                continue

        if not prices:
            return None

        price_usd_mt = sum(prices) / len(prices)
        _save_cache("mandi", {"price_usd_mt": price_usd_mt, "n": len(prices)})
        log.info("Mandi masoor: %.1f USD/MT (%d kayıt)", price_usd_mt, len(prices))
        return price_usd_mt

    except Exception as e:
        log.warning("Mandi API hatası: %s", e)
        return None


def _mandi_signal(mandi_price: Optional[float]) -> list[Signal]:
    """
    Mandi fiyatı vs MSP karşılaştırması → "swing buyer" riski.
    Mandi < MSP → Hindistan iç piyasada destek alıyor → ihracat yok → CA/KZ'ye talep artar.
    """
    signals: list[Signal] = []
    now_str = datetime.utcnow().isoformat()

    if mandi_price is None:
        # Fallback: tarihsel ortalama + Düşük güven
        mandi_price = MASOOR_HIST_AVG
        z = 0.0
        note = (
            f"Hindistan Mandi fiyatı alınamadı — tarihsel ort. kullanılıyor "
            f"({MASOOR_HIST_AVG:.0f} USD/MT). Güven düşük."
        )
        source_url = "https://agmarknet.gov.in"
    else:
        delta = mandi_price - INDIA_MSP_USD_PER_MT
        z = -delta / MASOOR_HIST_STD  # Mandi < MSP → pozitif z (risk)
        pct = delta / INDIA_MSP_USD_PER_MT * 100
        swing_risk = "YÜK" if delta < 0 else "DÜŞÜK"
        note = (
            f"Hindistan masoor Mandi: {mandi_price:.0f} USD/MT vs MSP {INDIA_MSP_USD_PER_MT:.0f} "
            f"(delta {pct:+.1f}%). Swing buyer riski: {swing_risk}. "
            f"{'Hindistan ihracat yapmıyor → CA/KZ talep artabilir.' if delta < 0 else 'MSP üstü → ihracat baskısı yok.'}"
        )
        source_url = "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070"

    # Swing buyer riski CA ve KZ'yi etkiler (Hindistan kayıptan CA/KZ kazanır)
    for origin in ("CA", "KZ"):
        signals.append(Signal(
            origin=origin,
            category="market",
            value=round(min(max(mandi_price / (INDIA_MSP_USD_PER_MT * 2), 0), 1), 4),
            anomaly_z=round(z, 3),
            source_url=source_url,
            source_label="Agmarknet / data.gov.in",
            horizon_weights={"4w": 0.8, "8w": 1.0, "12w": 0.9},
            note=note,
            ts=now_str,
        ))

    # IN sinyali de üret (kendisi için farklı anlam: iç fiyat baskısı)
    signals.append(Signal(
        origin="IN",
        category="market",
        value=round(min(max(mandi_price / (INDIA_MSP_USD_PER_MT * 2), 0), 1), 4),
        anomaly_z=round(-z * 0.5, 3),  # IN için ters yön
        source_url=source_url,
        source_label="Agmarknet / data.gov.in",
        horizon_weights={"4w": 0.7, "8w": 0.8, "12w": 0.7},
        note=note,
        ts=now_str,
    ))

    return signals


# ---------------------------------------------------------------------------
# 2. Sarı bezelye fiyatı (yellow pea) — ikame tavanı
# ---------------------------------------------------------------------------

def _fetch_yellow_pea_price() -> Optional[float]:
    """
    WB Pink Sheet'ten sarı bezelye fiyatını çek (USD/MT).
    Başarısız olursa None döner.
    """
    cached = _load_cache("yellow_pea")
    if cached:
        log.info("Yellow pea: cache hit")
        return cached.get("price")

    try:
        import pandas as pd
        if WB_CACHE_PATH.exists():
            age = (datetime.now() - datetime.fromtimestamp(WB_CACHE_PATH.stat().st_mtime)).total_seconds()
            if age < 86400:
                wb = pd.read_excel(WB_CACHE_PATH, sheet_name="Monthly Prices", header=4)
            else:
                raise FileNotFoundError("cache eski")
        else:
            raise FileNotFoundError("cache yok")

        # Sarı bezelye veya buğday proxy kolonu
        for kw in ("pea", "wheat", "barley"):
            cols = [c for c in wb.columns if isinstance(c, str) and kw in c.lower()]
            if cols:
                series = pd.to_numeric(wb[cols[0]], errors="coerce").dropna()
                if not series.empty:
                    price = float(series.iloc[-1])
                    # Sarı bezelye yaklaşık buğday fiyatının 1.1x'i
                    if kw != "pea":
                        price = price * 1.1
                    _save_cache("yellow_pea", {"price": price})
                    log.info("Yellow pea proxy (%s): %.1f USD/MT", cols[0], price)
                    return price

        log.warning("WB: sarı bezelye proxy kolonu bulunamadı.")
        return None

    except Exception:
        # WB yoksa data.gov.in ya da farklı kaynak dene
        try:
            resp = requests.get(WB_PINK_SHEET_URL, timeout=30)
            resp.raise_for_status()
            WB_CACHE_PATH.parent.mkdir(exist_ok=True)
            with open(WB_CACHE_PATH, "wb") as f:
                f.write(resp.content)
            return _fetch_yellow_pea_price()  # recursion (bir kere)
        except Exception as e:
            log.warning("Yellow pea fiyatı alınamadı: %s", e)
            return None


def _yellow_pea_signal(yp_price: Optional[float]) -> list[Signal]:
    """
    Sarı bezelye fiyatı → kırmızı mercimek talep tavanı sinyali.
    Sarı bezelye pahalanırsa → alıcılar kırmızı mercimeğe döner → talep artar → fiyat baskısı.
    """
    signals: list[Signal] = []
    now_str = datetime.utcnow().isoformat()

    if yp_price is None:
        yp_price = YELLOW_PEA_HIST_AVG
        z = 0.0
        note = (
            f"Sarı bezelye fiyatı alınamadı — tarihsel ort. {YELLOW_PEA_HIST_AVG:.0f} USD/MT kullanılıyor."
        )
        source_url = WB_PINK_SHEET_URL
    else:
        z = (yp_price - YELLOW_PEA_HIST_AVG) / YELLOW_PEA_HIST_STD
        ratio = yp_price / YELLOW_PEA_HIST_AVG
        note = (
            f"Sarı bezelye: {yp_price:.0f} USD/MT (tarihsel ort. {YELLOW_PEA_HIST_AVG:.0f}, "
            f"z={z:+.2f}). "
            f"{'Kırmızı mercimek talebi artabilir (ikame etkisi).' if z > 0.5 else 'Normal seviye.'}"
        )
        source_url = WB_PINK_SHEET_URL

    # Sarı bezelye yüksek → CA ve AU origin'leri etkiler (üretici)
    for origin in ("CA", "AU"):
        signals.append(Signal(
            origin=origin,
            category="market",
            value=round(min(yp_price / (YELLOW_PEA_HIST_AVG * 2), 1.0), 4),
            anomaly_z=round(z * 0.7, 3),  # ikame etkisi dolaylı
            source_url=source_url,
            source_label="World Bank Pink Sheet — Yellow Pea",
            horizon_weights={"4w": 0.5, "8w": 0.8, "12w": 1.0},
            note=note,
            ts=now_str,
        ))

    return signals


# ---------------------------------------------------------------------------
# 3. WFP ihale takibi
# ---------------------------------------------------------------------------

def _fetch_wfp_tenders() -> list[dict]:
    """WFP gıda ihalelerini çek — kırmızı mercimek içerenleri filtrele."""
    cached = _load_cache("wfp")
    if cached:
        log.info("WFP: cache hit")
        return cached.get("tenders", [])

    lentil_keywords = ["lentil", "masoor", "red lentil", "mercimek", "pulse"]
    tenders = []

    try:
        resp = requests.get(WFP_TENDER_URL, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.iter("item"):
            title = item.findtext("title", "") or ""
            desc = item.findtext("description", "") or ""
            link = item.findtext("link", "") or ""
            pub = item.findtext("pubDate", "") or ""
            combined = (title + " " + desc).lower()
            if any(kw in combined for kw in lentil_keywords):
                # Miktarı parse etmeye çalış
                qty_mt = _parse_tender_quantity(title + " " + desc)
                tenders.append({
                    "title": title,
                    "url": link or "https://www.wfp.org/procurement",
                    "publishedAt": pub,
                    "qty_mt": qty_mt,
                })
    except Exception as e:
        log.warning("WFP RSS hatası: %s", e)

    _save_cache("wfp", {"tenders": tenders})
    log.info("WFP: %d kırmızı mercimek ihalesi.", len(tenders))
    return tenders


def _parse_tender_quantity(text: str) -> Optional[float]:
    """İhale metinden miktar (MT) çıkarmaya çalış."""
    patterns = [
        r"(\d[\d,\.]+)\s*(?:MT|metric ton)",
        r"(\d[\d,\.]+)\s*(?:tonnes|tons)",
        r"(\d[\d,\.]+)\s*(?:kg)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            qty_str = m.group(1).replace(",", "")
            try:
                qty = float(qty_str)
                if "kg" in pat.lower():
                    qty /= 1000
                return qty
            except ValueError:
                continue
    return None


def _wfp_signals(tenders: list[dict]) -> list[Signal]:
    """WFP ihalelerinden talep patlaması sinyali üret."""
    signals: list[Signal] = []
    now_str = datetime.utcnow().isoformat()

    if not tenders:
        return signals

    total_qty = sum(t.get("qty_mt") or 0 for t in tenders)
    n = len(tenders)

    # Büyük ihale = ani talep = fiyat baskısı
    # Tarihsel WFP kırmızı mercimek alımı ~50-200 MT/ihale → normalizasyon
    TYPICAL_QTY = 100.0
    z = (total_qty / max(n, 1) - TYPICAL_QTY) / TYPICAL_QTY if total_qty > 0 else float(n - 1) * 0.5

    note = (
        f"WFP: {n} kırmızı mercimek ihalesi aktif"
        + (f", toplam ~{total_qty:.0f} MT" if total_qty > 0 else "")
        + ". Ani talep baskısı riski."
    )

    # Küresel talep → tüm büyük ihracat originlerini etkiler
    for origin in ("CA", "KZ", "AU"):
        signals.append(Signal(
            origin=origin,
            category="market",
            value=min(z / 3.0, 1.0) if z > 0 else 0.0,
            anomaly_z=round(min(z, 3.0), 3),
            source_url=tenders[0]["url"] if tenders else "https://www.wfp.org/procurement",
            source_label="WFP Food Tenders",
            horizon_weights={"4w": 1.0, "8w": 0.7, "12w": 0.4},
            note=note,
            ts=now_str,
        ))

    return signals


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------

def fetch() -> list[Signal]:
    """
    Agent 4 ana giriş noktası.
    Döndürür: list[Signal] (category="market")
    """
    signals: list[Signal] = []

    # 1) Hindistan Mandi vs MSP
    mandi_price = _fetch_mandi_price()
    signals.extend(_mandi_signal(mandi_price))

    # 2) Sarı bezelye ikame tavanı
    yp_price = _fetch_yellow_pea_price()
    signals.extend(_yellow_pea_signal(yp_price))

    # 3) WFP ihale takibi
    tenders = _fetch_wfp_tenders()
    signals.extend(_wfp_signals(tenders))

    log.info("Agent 4 tamamlandı: %d sinyal.", len(signals))
    return signals


# ---------------------------------------------------------------------------
# Hızlı test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = fetch()
    print(f"\n=== Agent 4 — {len(results)} sinyal ===\n")
    for s in results:
        print(
            f"  [{s.origin:10s}] {s.category:12s} "
            f"z={s.anomaly_z:+.2f}  val={s.value:.3f}  "
            f"| {s.note[:90]}"
        )
