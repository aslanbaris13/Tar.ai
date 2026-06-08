"""
Agent 1 — Fiyat Ajanı
Armada XLSX alış verisi + World Bank Pink Sheet → Signal[category="price"]

Akış:
  1. Armada XLSX'ten origin bazında fiyat serisi çıkar
  2. Her origin için rolling z-skoru hesapla (son fiyat vs tarihsel ort/std)
  3. WB Pink Sheet'ten küresel kırmızı mercimek benchmark fiyatı çek
  4. Armada vs WB delta → ek sinyal
  5. Backtest modu: belirli tarihte snapshot al
"""
import os
import sys
import json
import logging
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import pandas as pd
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

# Repo kökünden import için path ayarı
sys.path.insert(0, str(Path(__file__).parent))
from core.models import Signal

logging.basicConfig(level=logging.INFO, format="%(levelname)s | agent_1 | %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

EXCEL_PATH = os.getenv(
    "ARMADA_EXCEL_PATH",
    str(Path(__file__).parent.parent / "data" / "2024-2025-2026 Kırmızı Mercimek Alışları.XLSX"),
)

# EUR/USD sabit kur (hafif güncelleme yeterli, gerçek zamanlı gerekmez)
EUR_USD = 1.08

# World Bank Pink Sheet (commodity prices)
WB_PINK_SHEET_URL = (
    "https://thedocs.worldbank.org/en/doc/"
    "74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/CMO-Historical-Data-Monthly.xlsx"
)
WB_CACHE_PATH = Path(__file__).parent / "cache" / "wb_pink_sheet.xlsx"

# Kısa metin → origin eşlemesi
ORIGIN_MAP: dict[str, str] = {
    "KAZAK": "KZ",
    "KANADA": "CA",
    "KAN": "CA",
    "RUS": "RU",
    "SURİYE": "SY",
    "TÜRK": "TR_MERSIN",
    "TÜRKİYE": "TR_MERSIN",
    "AVUSTRALYA": "AU",
    "HİNDİSTAN": "IN",
}

# Z-skor hesabı için pencere (satır sayısı değil, gün)
ROLLING_DAYS = 180   # 6 ay
MIN_ROWS = 5         # Güvenilir z-skor için minimum satır


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------

def _parse_origin(text: str) -> Optional[str]:
    """'Kısa metin' kolonundan origin kodu çıkar."""
    if not isinstance(text, str):
        return None
    upper = text.upper()
    for keyword, code in ORIGIN_MAP.items():
        if keyword in upper:
            return code
    return None


def _load_armada(as_of: Optional[date] = None) -> pd.DataFrame:
    """
    Armada XLSX'i yükle ve temizle.
    as_of: backtest için bu tarih dahil öncesi veriyi döndür.
    """
    df = pd.read_excel(EXCEL_PATH)

    # Sütun yeniden adlandır (boşluk güvenliği)
    df.columns = [c.strip() for c in df.columns]

    # Tarih parse
    df["Belge tarihi"] = pd.to_datetime(df["Belge tarihi"], errors="coerce")

    # Negatif/sıfır miktarları at (iptal/düzeltme)
    df = df[df["SA siparişi miktarı"] > 0].copy()

    # Origin parse
    df["origin"] = df["Kısa metin"].apply(_parse_origin)
    df = df[df["origin"].notna()].copy()

    # EUR → USD çevirimi
    eur_mask = df["Para birimi"] == "EUR"
    df.loc[eur_mask, "Net fiyat"] = df.loc[eur_mask, "Net fiyat"] * EUR_USD

    # Net fiyat USD/MT
    df = df[df["Net fiyat"] > 0].copy()

    if as_of is not None:
        df = df[df["Belge tarihi"].dt.date <= as_of].copy()

    df = df.sort_values("Belge tarihi").reset_index(drop=True)
    log.info("Armada yüklendi: %d satır (as_of=%s)", len(df), as_of)
    return df


def _compute_price_signals(df: pd.DataFrame) -> list[Signal]:
    """Her origin için fiyat z-skoru sinyali üret."""
    signals: list[Signal] = []
    now_str = datetime.utcnow().isoformat()

    for origin, group in df.groupby("origin"):
        group = group.sort_values("Belge tarihi")

        if len(group) < MIN_ROWS:
            # Veri yetersiz — düşük güven sinyali
            log.warning("Origin %s: yalnızca %d satır, düşük güven sinyali.", origin, len(group))
            signals.append(Signal(
                origin=origin,
                category="price",
                value=0.5,
                anomaly_z=0.0,
                source_url=EXCEL_PATH,
                source_label="Armada Alış Verisi",
                horizon_weights={"4w": 0.3, "8w": 0.3, "12w": 0.3},
                note=f"{origin}: {len(group)} satır — veri yetersiz, güven düşük.",
                ts=now_str,
            ))
            continue

        prices = group["Net fiyat"].values
        mean = prices.mean()
        std = prices.std(ddof=1)
        last_price = prices[-1]
        last_date = group["Belge tarihi"].iloc[-1]

        z = (last_price - mean) / std if std > 0 else 0.0

        # Normalize value: son fiyat / tarihsel maksimum
        value = min(last_price / prices.max(), 1.0)

        # Trend sinyali: son 60 günlük slope
        recent = group[group["Belge tarihi"] >= group["Belge tarihi"].max() - pd.Timedelta(days=60)]
        trend_note = ""
        if len(recent) >= 3:
            recent_mean = recent["Net fiyat"].mean()
            older = group[group["Belge tarihi"] < group["Belge tarihi"].max() - pd.Timedelta(days=60)]
            older_mean = older["Net fiyat"].mean() if len(older) >= 3 else mean
            trend_pct = (recent_mean - older_mean) / older_mean * 100 if older_mean > 0 else 0
            trend_note = f" | Son 60 gün trend: {trend_pct:+.1f}%"

        note = (
            f"{origin}: son fiyat {last_price:.0f} USD/MT "
            f"(ort {mean:.0f}, std {std:.0f}, z={z:+.2f}){trend_note}. "
            f"Son alış: {last_date.strftime('%Y-%m-%d')}."
        )

        signals.append(Signal(
            origin=origin,
            category="price",
            value=round(value, 4),
            anomaly_z=round(z, 3),
            source_url=EXCEL_PATH,
            source_label="Armada Alış Verisi",
            horizon_weights={"4w": 1.0, "8w": 0.8, "12w": 0.6},
            note=note,
            ts=now_str,
        ))
        log.info("Price sinyal — %s: z=%+.2f, son_fiyat=%.0f", origin, z, last_price)

    return signals


def _fetch_wb_benchmark() -> Optional[float]:
    """
    World Bank CMO Historical Data'dan genel tarım emtia endeksi çek.
    WB'de doğrudan mercimek kolonu yok; buğday/arpa fiyatını proxy olarak kullanıyoruz.
    Başarısız olursa None döner — agent çalışmaya devam eder.
    """
    try:
        WB_CACHE_PATH.parent.mkdir(exist_ok=True)
        if WB_CACHE_PATH.exists():
            age = (datetime.now() - datetime.fromtimestamp(WB_CACHE_PATH.stat().st_mtime)).total_seconds()
            if age < 86400:  # 24 saat cache
                log.info("WB: cache'den yüklendi.")
                return _extract_grain_proxy(pd.read_excel(WB_CACHE_PATH, sheet_name="Monthly Prices", header=4))

        log.info("WB CMO Historical Data indiriliyor...")
        resp = requests.get(WB_PINK_SHEET_URL, timeout=30)
        resp.raise_for_status()
        with open(WB_CACHE_PATH, "wb") as f:
            f.write(resp.content)
        return _extract_grain_proxy(pd.read_excel(WB_CACHE_PATH, sheet_name="Monthly Prices", header=4))

    except Exception as e:
        log.warning("WB veri alınamadı: %s", e)
        return None


def _extract_grain_proxy(wb: pd.DataFrame) -> Optional[float]:
    """
    WB verisinden buğday/barley fiyatını mercimek proxy'si olarak çıkar.
    Kırmızı mercimek tarihsel olarak buğdayın ~2.5-3x fiyatına satılır.
    """
    proxy_keywords = ["wheat", "barley"]
    for kw in proxy_keywords:
        cols = [c for c in wb.columns if isinstance(c, str) and kw in c.lower()]
        if cols:
            series = pd.to_numeric(wb[cols[0]], errors="coerce").dropna()
            if not series.empty:
                grain_price = float(series.iloc[-1])
                # Mercimek ≈ buğday × 2.7 (tarihsel katsayı)
                lentil_proxy = grain_price * 2.7
                log.info("WB %s proxy: %.1f USD/MT → mercimek tahmini: %.1f USD/MT",
                         cols[0], grain_price, lentil_proxy)
                return lentil_proxy
    log.warning("WB: buğday/arpa kolonu bulunamadı.")
    return None


def _wb_signal(wb_price: float, armada_df: pd.DataFrame) -> list[Signal]:
    """Armada CA fiyatı vs WB benchmark karşılaştırması."""
    signals: list[Signal] = []
    now_str = datetime.utcnow().isoformat()

    ca_rows = armada_df[armada_df["origin"] == "CA"]
    if ca_rows.empty or wb_price is None:
        return signals

    ca_last = ca_rows.sort_values("Belge tarihi")["Net fiyat"].iloc[-1]
    delta_pct = (ca_last - wb_price) / wb_price * 100

    # Armada WB üstündeyse → piyasadan pahalı alıyoruz → risk
    z = delta_pct / 15.0  # 15% ≈ 1 z-puan

    signals.append(Signal(
        origin="CA",
        category="price",
        value=round(min(ca_last / (wb_price * 2), 1.0), 4),
        anomaly_z=round(z, 3),
        source_url=WB_PINK_SHEET_URL,
        source_label="World Bank Pink Sheet",
        horizon_weights={"4w": 0.5, "8w": 0.7, "12w": 0.9},
        note=(
            f"Armada CA alış {ca_last:.0f} USD/MT vs WB benchmark {wb_price:.0f} USD/MT "
            f"(delta {delta_pct:+.1f}%)."
        ),
        ts=now_str,
    ))
    return signals


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------

def fetch(as_of: Optional[date] = None) -> list[Signal]:
    """
    Agent 1 ana giriş noktası.
    as_of: backtest için tarih (None = bugün).
    Döndürür: list[Signal] (category="price")
    """
    signals: list[Signal] = []

    try:
        df = _load_armada(as_of)
    except Exception as e:
        log.error("Armada XLSX yüklenemedi: %s", e)
        return []

    signals.extend(_compute_price_signals(df))

    wb_price = _fetch_wb_benchmark()
    if wb_price:
        signals.extend(_wb_signal(wb_price, df))

    log.info("Agent 1 tamamlandı: %d sinyal.", len(signals))
    return signals


# ---------------------------------------------------------------------------
# Hızlı test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = fetch()
    print(f"\n=== Agent 1 — {len(results)} sinyal ===\n")
    for s in results:
        print(
            f"  [{s.origin:10s}] {s.category:12s} "
            f"z={s.anomaly_z:+.2f}  val={s.value:.3f}  "
            f"| {s.note[:80]}"
        )

    # Backtest örneği
    print("\n=== Backtest: 2024-05-01 ===\n")
    bt = fetch(as_of=date(2024, 5, 1))
    for s in bt:
        print(f"  [{s.origin}] z={s.anomaly_z:+.2f} | {s.note[:80]}")
