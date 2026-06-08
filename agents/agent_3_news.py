"""
Agent 3 — Haber & Politika Ajanı
NewsAPI + Resmî Gazete RSS + DGFT ihracat politikası → Signal[category="regulation"|"supply"]

Akış:
  1. NewsAPI: origin bazında anahtar kelime araması
  2. Resmî Gazete RSS: tarife/kota/gümrük değişiklik haberleri
  3. DGFT (India): Hindistan ihracat politikası açıklamaları
  4. Tüm başlıkları Claude Haiku ile sınıflandır → risk / no-risk + origin + kategori
  5. Sonuç cache'e yaz (100 req/gün limitini aşmamak için)
"""
import hashlib
import json
import logging
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    # dotenv yoksa .env'i manuel parse et
    _env_file = Path(__file__).parent.parent / ".env"
    if _env_file.exists():
        for _line in _env_file.read_text().splitlines():
            if "=" in _line and not _line.startswith("#"):
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

import requests

sys.path.insert(0, str(Path(__file__).parent))
from core.models import Signal

logging.basicConfig(level=logging.INFO, format="%(levelname)s | agent_3 | %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

NEWS_API_URL = "https://newsapi.org/v2/everything"
RESMI_GAZETE_RSS = "https://www.resmigazete.gov.tr/rss.xml"
DGFT_RSS = "https://dgft.gov.in/rss/notifications"

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_TTL_HOURS = 6  # NewsAPI rate limit koruması

# Origin bazında arama terimleri
ORIGIN_QUERIES: dict[str, list[str]] = {
    "CA": ["Canada lentil export", "Saskatchewan lentil harvest", "Canada red lentil"],
    "KZ": ["Kazakhstan lentil", "Kazakhstan grain export ban", "Kazakh agriculture"],
    "RU": ["Russia lentil export", "Russia grain ban", "Black Sea lentil"],
    "AU": ["Australia lentil production", "Australia red lentil crop"],
    "IN": ["India lentil export ban", "India masoor dal", "DGFT lentil notification"],
    "SY": ["Syria lentil", "Syria grain trade"],
    "TR_MERSIN": ["Turkey lentil import tariff", "Türkiye mercimek tarife"],
}

# Resmî Gazete için anahtar kelimeler
RESMI_GAZETE_KEYWORDS = [
    "mercimek", "bakliyat", "ithalat tarife", "gümrük tarife", "kota",
    "lentil", "legume"
]

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_key(query: str) -> str:
    return hashlib.md5(query.encode()).hexdigest()[:12]


def _cache_path(key: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"news_{key}.json"


def _load_cache(key: str) -> Optional[list[dict]]:
    p = _cache_path(key)
    if not p.exists():
        return None
    age = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds()
    if age > CACHE_TTL_HOURS * 3600:
        return None
    with open(p) as f:
        return json.load(f)


def _save_cache(key: str, data: list[dict]) -> None:
    with open(_cache_path(key), "w") as f:
        json.dump(data, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# NewsAPI
# ---------------------------------------------------------------------------

def _fetch_newsapi(query: str, days_back: int = 30) -> list[dict]:
    """NewsAPI'den haber başlıklarını çek. Cache kullan."""
    key = _cache_key(query)
    cached = _load_cache(key)
    if cached is not None:
        log.info("NewsAPI cache hit: %s", query[:40])
        return cached

    if not NEWS_API_KEY:
        log.warning("NEWS_API_KEY yok — NewsAPI atlanıyor.")
        return []

    from_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            NEWS_API_URL,
            params={
                "q": query,
                "from": from_date,
                "language": "en",
                "sortBy": "relevancy",
                "pageSize": 10,
                "apiKey": NEWS_API_KEY,
            },
            timeout=15,
        )
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        items = [
            {
                "title": a.get("title", ""),
                "description": a.get("description", "") or "",
                "url": a.get("url", ""),
                "publishedAt": a.get("publishedAt", ""),
                "source": a.get("source", {}).get("name", ""),
            }
            for a in articles
        ]
        _save_cache(key, items)
        log.info("NewsAPI: '%s' → %d makale", query[:40], len(items))
        return items
    except Exception as e:
        log.warning("NewsAPI hatası (%s): %s", query[:30], e)
        return []


# ---------------------------------------------------------------------------
# Resmî Gazete RSS
# ---------------------------------------------------------------------------

def _fetch_resmi_gazete() -> list[dict]:
    """Resmî Gazete RSS feed'ini parse et, mercimek/tarife ile ilgili girdileri döndür."""
    key = _cache_key("resmi_gazete")
    cached = _load_cache(key)
    if cached is not None:
        log.info("Resmî Gazete: cache hit")
        return cached

    items = []
    try:
        resp = requests.get(RESMI_GAZETE_RSS, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.iter("item"):
            title = item.findtext("title", "") or ""
            desc = item.findtext("description", "") or ""
            link = item.findtext("link", "") or ""
            pub = item.findtext("pubDate", "") or ""
            combined = (title + " " + desc).lower()
            if any(kw.lower() in combined for kw in RESMI_GAZETE_KEYWORDS):
                items.append({
                    "title": title,
                    "description": desc[:300],
                    "url": link,
                    "publishedAt": pub,
                    "source": "Resmî Gazete",
                })
        _save_cache(key, items)
        log.info("Resmî Gazete: %d ilgili madde.", len(items))
    except Exception as e:
        log.warning("Resmî Gazete RSS hatası: %s", e)
    return items


# ---------------------------------------------------------------------------
# DGFT (Hindistan ihracat politikası)
# ---------------------------------------------------------------------------

def _fetch_dgft() -> list[dict]:
    """DGFT bildirimlerini çek — Hindistan kırmızı mercimek ihracat politikası."""
    key = _cache_key("dgft")
    cached = _load_cache(key)
    if cached is not None:
        log.info("DGFT: cache hit")
        return cached

    keywords = ["lentil", "masoor", "red lentil", "pulse", "export policy"]
    items = []
    try:
        resp = requests.get(DGFT_RSS, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        for item in root.iter("item"):
            title = item.findtext("title", "") or ""
            link = item.findtext("link", "") or ""
            pub = item.findtext("pubDate", "") or ""
            if any(kw.lower() in title.lower() for kw in keywords):
                items.append({
                    "title": title,
                    "description": "",
                    "url": link or "https://dgft.gov.in",
                    "publishedAt": pub,
                    "source": "DGFT India",
                })
        _save_cache(key, items)
        log.info("DGFT: %d ilgili bildirim.", len(items))
    except Exception as e:
        log.warning("DGFT RSS hatası (beklenebilir): %s", e)
    return items


# ---------------------------------------------------------------------------
# LLM Sınıflandırma
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM = """Sen kırmızı mercimek tedarik riski analistinin asistanısın.
Sana haber başlıklarının listesini ve context veriyorum.
Her başlık için şunları belirle:
- is_risk: true/false (kırmızı mercimek arzı veya fiyatı için risk mi?)
- risk_type: "regulation" | "supply" | "price" | "none"
- origin: "CA"|"KZ"|"RU"|"AU"|"IN"|"TR_MERSIN"|"SY"|"GLOBAL"
- severity: 0.0-1.0 (0=önemsiz, 1=kritik)
- note: tek cümle Türkçe özet

Çıktı: JSON array (her madde için bir nesne)
Uydurma bilgi ekleme. Emin değilsen severity=0.1, is_risk=false yap."""

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

def _classify_with_llm(articles: list[dict]) -> list[dict]:
    """Haber listesini GPT-4o-mini ile risk sınıflandır."""
    if not articles or not OPENAI_API_KEY:
        return _classify_rule_based(articles)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        batch = [
            {"index": i, "title": a["title"], "source": a.get("source", "")}
            for i, a in enumerate(articles[:20])  # max 20 madde / istek
        ]
        user_msg = f"Haberler:\n{json.dumps(batch, ensure_ascii=False)}"

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _CLASSIFY_SYSTEM + "\nJSON çıktın 'results' key'i altında array olsun."},
                {"role": "user", "content": user_msg},
            ],
        )
        data = json.loads(resp.choices[0].message.content)
        classifications = data.get("results", data) if isinstance(data, dict) else data
        log.info("LLM sınıflandırma: %d haber → %d sonuç.", len(batch), len(classifications))
        return classifications
    except Exception as e:
        log.warning("LLM sınıflandırma hatası: %s", e)
        return _classify_rule_based(articles)


def _classify_rule_based(articles: list[dict]) -> list[dict]:
    """
    LLM olmadan kural tabanlı sınıflandırma.
    ÖNCE mercimek/bakliyat alakası filtresi, SONRA risk tespiti.
    LLM yokken alakasız haberlerin sinyale dönüşmesini önler.
    """
    # Haberin mercimekle ilgili olup olmadığını anlamak için zorunlu kelimeler
    LENTIL_RELEVANCE = [
        "lentil", "masoor", "dal", "pulse", "legume",
        "mercimek", "bakliyat",
        # geniş tarım/ticaret bağlamı — sadece origin keyword'leriyle birlikte geçerliyse
        "grain", "crop", "harvest", "export", "import", "agriculture",
    ]
    # Bunlar tek başına yeterli (doğrudan mercimek haberi)
    DIRECT_LENTIL = {"lentil", "masoor", "dal", "mercimek", "bakliyat"}

    risk_keywords = {
        "export ban": ("regulation", 0.9),
        "import ban": ("regulation", 0.9),
        "ban lentil": ("regulation", 0.9),
        "ban": ("regulation", 0.7),
        "restriction": ("regulation", 0.6),
        "tariff": ("regulation", 0.6),
        "sanction": ("regulation", 0.5),
        "drought": ("supply", 0.8),
        "flood": ("supply", 0.7),
        "shortage": ("supply", 0.8),
        "crop failure": ("supply", 0.9),
        "poor harvest": ("supply", 0.8),
        "low yield": ("supply", 0.7),
        "price surge": ("price", 0.7),
        "price spike": ("price", 0.8),
        "rally": ("price", 0.5),
    }
    origin_keywords = {
        "canada": "CA", "saskatchewan": "CA", "canadian": "CA",
        "kazakhstan": "KZ", "kazakh": "KZ",
        "russia": "RU", "russian": "RU", "black sea": "RU",
        "australia": "AU", "australian": "AU",
        "india": "IN", "indian": "IN", "masoor": "IN", "dgft": "IN",
        "syria": "SY", "syrian": "SY",
        "turkey": "TR_MERSIN", "türkiye": "TR_MERSIN",
    }
    results = []
    for i, a in enumerate(articles):
        text = (a.get("title", "") + " " + a.get("description", "")).lower()

        # Mercimek alaka filtresi: doğrudan kelime yoksa düşük güvenle geç
        has_direct = any(kw in text for kw in DIRECT_LENTIL)
        has_broader = any(kw in text for kw in LENTIL_RELEVANCE)
        if not has_direct and not has_broader:
            results.append({"index": i, "is_risk": False, "risk_type": "none",
                            "origin": "GLOBAL", "severity": 0.0, "note": ""})
            continue

        risk_type = "none"
        severity = 0.0
        for kw, (rt, sv) in risk_keywords.items():
            if kw in text:
                risk_type = rt
                severity = max(severity, sv)
                break  # en güçlü eşleşme yeterli

        # Doğrudan mercimek kelimesi yoksa severity'yi yarıya indir
        if not has_direct:
            severity *= 0.5

        origin = "GLOBAL"
        for kw, orig in origin_keywords.items():
            if kw in text:
                origin = orig
                break

        results.append({
            "index": i,
            "is_risk": severity > 0.3,
            "risk_type": risk_type,
            "origin": origin,
            "severity": round(severity, 2),
            "note": a.get("title", "")[:100],
        })
    return results


# ---------------------------------------------------------------------------
# Signal üretimi
# ---------------------------------------------------------------------------

def _articles_to_signals(
    articles: list[dict],
    classifications: list[dict],
) -> list[Signal]:
    """Sınıflandırılmış haberlerden Signal listesi üret."""
    signals: list[Signal] = []
    now_str = datetime.utcnow().isoformat()

    cls_map = {c.get("index", i): c for i, c in enumerate(classifications)}

    for i, article in enumerate(articles):
        cls = cls_map.get(i, {})
        if not cls.get("is_risk", False):
            continue

        origin = cls.get("origin", "GLOBAL")
        if origin == "GLOBAL":
            # Global riski tüm originlere düşük ağırlıkla yay
            origins_to_use = ["CA", "KZ", "RU", "AU", "IN"]
        else:
            origins_to_use = [origin]

        severity = float(cls.get("severity", 0.3))
        risk_type = cls.get("risk_type", "regulation")
        category = risk_type if risk_type in ("regulation", "supply", "price") else "regulation"

        # Anomaly z: severity 0-1 → z 0-1.5 arası
        # Max 1.5 ile sınırlandırıyoruz — tek haber skoru 93'e taşımasın
        # Birden fazla haber aynı origin'i işaret ederse skor birikimiyle artar (doğru davranış)
        z = severity * 1.5

        for orig in origins_to_use:
            global_weight = 0.4 if origin == "GLOBAL" else 1.0
            signals.append(Signal(
                origin=orig,
                category=category,
                value=round(severity, 3),
                anomaly_z=round(z * global_weight, 3),
                source_url=article.get("url") or "https://newsapi.org",
                source_label=article.get("source", "News"),
                horizon_weights={
                    "4w": 1.0 if category == "regulation" else 0.8,
                    "8w": 0.8,
                    "12w": 0.6,
                },
                note=cls.get("note", article.get("title", ""))[:150],
                ts=now_str,
            ))

    return signals


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------

def fetch() -> list[Signal]:
    """
    Agent 3 ana giriş noktası.
    Döndürür: list[Signal] (category="regulation" | "supply")
    """
    all_articles: list[dict] = []

    # 1) NewsAPI — origin bazında aramalar
    seen_urls: set[str] = set()
    for origin, queries in ORIGIN_QUERIES.items():
        for q in queries[:2]:  # Her origin için max 2 sorgu (rate limit)
            for article in _fetch_newsapi(q):
                url = article.get("url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_articles.append(article)

    # 2) Resmî Gazete RSS
    all_articles.extend(_fetch_resmi_gazete())

    # 3) DGFT
    all_articles.extend(_fetch_dgft())

    if not all_articles:
        log.warning("Agent 3: hiç haber bulunamadı, boş liste dönüyor.")
        return []

    log.info("Agent 3: toplam %d haber, LLM sınıflandırmaya gönderiliyor.", len(all_articles))

    # 4) LLM sınıflandır
    classifications = _classify_with_llm(all_articles)

    # 5) Signal'e dönüştür
    signals = _articles_to_signals(all_articles, classifications)

    log.info("Agent 3 tamamlandı: %d risk sinyali / %d haber.", len(signals), len(all_articles))
    return signals


# ---------------------------------------------------------------------------
# Hızlı test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = fetch()
    print(f"\n=== Agent 3 — {len(results)} sinyal ===\n")
    for s in results:
        print(
            f"  [{s.origin:10s}] {s.category:12s} "
            f"z={s.anomaly_z:+.2f}  "
            f"| {s.note[:80]}"
        )
        print(f"    kaynak: {s.source_url[:70]}")
