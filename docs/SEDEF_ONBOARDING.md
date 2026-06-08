# TARAI — Developer Onboarding (Sedef için)
Tarih: 09 Haziran 2026 | Hazırlayan: Barış

---

## Proje Nedir?

**Armada Co-Pilot** — kırmızı mercimek tedarik riskini piyasaya yansımadan önce gösteren karar destek sistemi.

6 ülkeden (Kanada, Kazakistan, Rusya, Hindistan, Avustralya, Suriye) sinyal toplar,
0–100 arası risk skoru üretir, "şimdi al / bekle / kısmi al" önerisi verir.

**Yöntem:** kural tabanlı skorlama + LLM muhakemesi. ML model yok.

---

## Kurulum (5 dakika)

### 1. Repo'yu al

```bash
git clone https://github.com/aslanbaris13/Tar.ai.git
cd Tar.ai
```

### 2. Virtual environment oluştur ve paketleri kur

```bash
python3 -m venv .venv
source .venv/bin/activate       # Mac/Linux
# .venv\Scripts\activate        # Windows

pip install -r requirements.txt
```

### 3. .env dosyası oluştur

Proje kökünde `.env` oluştur:

```env
OPENAI_API_KEY=sk-proj-...          # Zorunlu — LLM reasoning için
NEWS_API_KEY=...                    # Zorunlu — haber sinyalleri için
DATA_GOV_IN_KEY=579b464d...         # Opsiyonel — Hindistan piyasa verisi
# ARMADA_EXCEL_PATH=               # Boş bırak, otomatik bulunuyor
```

API keylerini Barış'tan al.

### 4. Excel dosyalarını kontrol et

`data/` klasöründe şu dosya olmalı:
```
data/2024-2025-2026 Kırmızı Mercimek Alışları.XLSX
```

Varsa tamam. Yoksa Barış'tan iste.

---

## Çalıştırma

### Backend API başlat

```bash
source .venv/bin/activate
uvicorn api.main:app --reload --port 8000
```

Tarayıcıda: `http://localhost:8000/docs` → Swagger UI, tüm endpoint'leri görürsün.

### İlk istek yavaş (~20-30 saniye)

İlk `/risk/all` çağrısında tüm agentlar çalışır:
- Armada XLSX okunur
- Open-Meteo'dan hava verisi çekilir
- NewsAPI'den haberler çekilir
- World Bank verisi çekilir

Sonrasında 6 saatlik cache devreye girer, ~1 saniye döner.

### Tek tek agent test

```bash
source .venv/bin/activate
cd agents

python agent_1_price.py      # Fiyat sinyalleri
python agent_2_weather.py    # Hava sinyalleri
python agent_3_news.py       # Haber sinyalleri
python agent_4_market.py     # Piyasa sinyalleri
python agent_5_decision.py   # Tam pipeline (tüm agentlar + skor + gerekçe)
python agent_5_decision.py --no-rationale   # LLM olmadan, hızlı test
```

---

## Mimari

```
Veri Kaynakları          Agentlar              Core              API
─────────────────────    ──────────────────    ──────────────    ──────────
Armada XLSX          →   agent_1_price.py  ─┐
Open-Meteo API       →   agent_2_weather.py─┤  core/
NewsAPI              →   agent_3_news.py   ─┤  ├─ models.py     api/
World Bank           →   agent_4_market.py ─┤  ├─ scoring.py →  main.py
Mandi (Hindistan)    →                      │  └─ reasoning.py  (FastAPI)
WFP RSS              →                      ┘
                         agent_5_decision.py  ← hepsini orkestre eder
```

### Veri akışı (tek yönlü, değişmez):
```
agent_N.fetch() → list[Signal] → compute_scores() → generate_rationale() → API → UI
```

### Signal dataclass (dokunma):
```python
@dataclass
class Signal:
    origin: str        # "CA"|"KZ"|"RU"|"AU"|"IN"|"TR_MERSIN"|"SY"
    category: str      # "price"|"weather"|"regulation"|"market"|"supply"
    value: float       # normalize değer
    anomaly_z: float   # z-skoru: + = normalin üstünde = yüksek risk
    source_url: str    # ZORUNLU
    horizon_weights: dict  # {"4w":1.0, "8w":0.8, "12w":0.5}
    note: str          # LLM için kısa açıklama
```

---

## Repo Yapısı

```
Tar.ai/
├── agents/
│   ├── core/
│   │   ├── models.py       # Signal dataclass — DOKUNMA
│   │   ├── scoring.py      # Z-skor → 0-100 skor — DOKUNMA
│   │   └── reasoning.py    # OpenAI GPT-4o-mini gerekçe — DOKUNMA
│   ├── agent_1_price.py    # Armada XLSX + World Bank
│   ├── agent_2_weather.py  # Open-Meteo (4 bölge)
│   ├── agent_3_news.py     # NewsAPI + Resmî Gazete RSS
│   ├── agent_4_market.py   # Mandi + sarı bezelye + WFP
│   ├── agent_5_decision.py # Orkestrasyon + skor matrisi
│   └── cache/              # 6-12 saatlik cache dosyaları
├── api/
│   └── main.py             # FastAPI — 5 endpoint
├── data/
│   └── *.XLSX              # Armada ham verisi (gitignore)
├── docs/
│   ├── OYKU_FRONTEND_BRIEF.md
│   ├── OYKU_FRONTEND_BRIEF_V2.md
│   └── SEDEF_ONBOARDING.md  ← bu dosya
├── frontend/               # Oyku — Next.js (ayrı repo/Lovable)
├── .env                    # API keyler (gitignore)
├── .env.example            # Template
└── requirements.txt
```

---

## API Endpoint'leri

| Method | URL | Ne döner |
|---|---|---|
| GET | `/risk/all?horizon=4` | Tüm originlerin risk skoru |
| GET | `/risk/{origin}?horizon=4` | Tek origin detayı |
| GET | `/prices/trend?horizon=8` | Haftalık fiyat serisi + forecast |
| GET | `/alerts` | Aktif uyarılar |
| POST | `/scenario` | What-if senaryo analizi |
| GET | `/` | Health check |

### Örnek çağrılar:

```bash
# Tüm originlerin 4 haftalık riski
curl http://localhost:8000/risk/all?horizon=4

# Kanada detayı
curl http://localhost:8000/risk/CA?horizon=4

# Fiyat trend + forecast
curl http://localhost:8000/prices/trend?horizon=8

# Senaryo: Kanada kuraklık
curl -X POST http://localhost:8000/scenario \
  -H "Content-Type: application/json" \
  -d '{"shock": "canada_drought"}'
```

### Mevcut senaryo şokları:
| shock | Açıklama |
|---|---|
| `india_export_ban` | Hindistan ihracat yasağı |
| `canada_drought` | Saskatchewan kuraklık derinleşir |
| `russia_embargo` | Rusya ambargo / Karadeniz kapanır |
| `kazakhstan_quota` | Kazakistan ihracat kotası |

---

## Skorlama Mantığı (kısaca)

1. Her agent `list[Signal]` döndürür
2. Her signal için z-skoru var: `anomaly_z > 0` = risk yüksek
3. Kategori ağırlıkları: fiyat 4w'da %50, hava %30, regülasyon %20...
4. `sigmoid(weighted_z × 1.5) × 100` → 0-100 skor
5. Skor + sinyal kategorisi → güven seviyesi + öneri
6. OpenAI GPT-4o-mini → Türkçe gerekçe + cited_sources

---

## Cache Sistemi

| Agent | Cache dosyası | TTL |
|---|---|---|
| Agent 2 (hava) | `cache/weather_CA.json` vb. | 12 saat |
| Agent 3 (haber) | `cache/news_*.json` | 6 saat |
| Agent 4 (piyasa) | `cache/mandi.json`, `cache/wb_*.xlsx` | 24 saat |
| Agent 5 (karar) | `cache/decision_result.json` | 6 saat |

Cache'i silmek: `rm agents/cache/*.json`

---

## Backtest Modu

Geçmiş bir tarihe "o günmüş gibi" analiz:

```bash
# CLI
python agent_5_decision.py --backtest 2024-05-01 --no-rationale

# API
GET /risk/all?horizon=4&as_of=2024-05-01
```

Demo senaryosu: "Mayıs 2024'te sistem CA=71 risk gösterdi → 8 haftada -%35 fiyat"

---

## Bilinen Sınırlılıklar

| Durum | Açıklama |
|---|---|
| AU ve IN'de veri az | Armada bu ülkelerden alım yapmamış — güven "Düşük" döner, beklenen davranış |
| TR_MERSIN'de 1 satır | Çok düşük güven — 50/50 nötr skor |
| NewsAPI günde 100 istek | Ücretsiz plan — cache süresi 6 saat, sorun olmaz |
| LLM gerekçe 5-10sn | GPT-4o-mini; `--no-rationale` ile atlanabilir |
| Forecast mock değil | Linear extrapolation — kaba tahmin, ML değil |

---

## Sık Sorulan Sorular

**Q: API neden yavaş?**
İlk çalıştırmada tüm agentlar çalışır (~20-30sn). `agents/cache/` klasörü dolunca sonraki çağrılar ~1sn.

**Q: `ModuleNotFoundError` alıyorum**
Virtual environment aktif mi? `source .venv/bin/activate` yaptın mı?

**Q: `.env` dosyası yok**
`.env.example`'ı kopyala: `cp .env.example .env` → keylerini doldur.

**Q: Hangi dosyalara dokunabilirim?**
`core/` klasörüne dokunma. `agent_N.py` ve `api/main.py` güvenli.

**Q: Yeni bir origin veya senaryo eklemek?**
`api/main.py` içindeki `ORIGIN_META` ve `SHOCKS` dict'lerini genişlet.

---

## İletişim

- Barış: aslanbaris870@gmail.com
- Teslim: 10 Haziran 2026
