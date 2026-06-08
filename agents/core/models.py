"""Signal — sistemin temel veri sözleşmesi. Bu dosyaya dokunma."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Signal:
    origin: str           # "CA"|"KZ"|"RU"|"AU"|"IN"|"TR_MERSIN"|"SY"
    category: str         # "price"|"weather"|"regulation"|"market"|"supply"
    value: float          # normalize değer (genellikle 0-1 arası)
    anomaly_z: float      # z-skoru; + = normalin üstünde = yüksek risk
    source_url: str       # ZORUNLU — boş bırakma
    horizon_weights: dict = field(default_factory=lambda: {"4w": 1.0, "8w": 1.0, "12w": 1.0})
    note: str = ""        # LLM reasoning için kısa açıklama
    source_label: str = ""  # İnsan okunabilir kaynak adı
    ts: Optional[str] = None  # ISO 8601 zaman damgası


ORIGINS = ("CA", "KZ", "RU", "AU", "IN", "TR_MERSIN", "SY")
HORIZONS = ("4w", "8w", "12w")
CATEGORIES = ("price", "weather", "regulation", "market", "supply")
