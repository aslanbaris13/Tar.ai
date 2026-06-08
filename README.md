# Armada Co-Pilot

Kırmızı mercimekte tedarik/fiyat riskini fiyat piyasaya yansımadan önce gösteren karar destek sistemi.

---

## Kurulum (5 adım)

**1. Repoyu klonla**
```bash
git clone <repo-url>
cd Tar.ai
```

**2. Sanal ortam oluştur ve bağımlılıkları kur**
```bash
python3 -m venv .venv
source .venv/bin/activate      # Mac/Linux
# .venv\Scripts\activate       # Windows

pip install -r requirements.txt
```

**3. `.env` dosyasını oluştur**
```bash
cp .env.example .env
```
`.env` dosyasını aç ve key'leri doldur:
```
OPENAI_API_KEY=sk-proj-...        # platform.openai.com/api-keys
NEWS_API_KEY=...                  # newsapi.org (ücretsiz)
```

**4. Excel dosyalarını `data/` klasörüne koy**

Armada'dan iki dosya gerekiyor (repoya commit edilmez):
- `2024-2025-2026 Kırmızı Mercimek Alışları.XLSX`
- `Kırmızı Mercimek 2024-2026.xlsx`

> Not: Dosyaları repo kök dizinine koy, `data/` klasörüne gerek yok.

**5. Test et**
```bash
python3 agents/agent_1_price.py    # Fiyat ajanı
python3 agents/agent_3_news.py    # Haber ajanı
python3 agents/agent_4_market.py  # Piyasa ajanı
```

---

## Proje Yapısı

```
agents/
  core/
    models.py       — Signal dataclass (ortak veri sözleşmesi)
    scoring.py      — 0-100 risk skoru hesaplama
    reasoning.py    — GPT-4o-mini ile Türkçe gerekçe üretimi
  agent_1_price.py  — Armada Excel + World Bank fiyat sinyalleri
  agent_2_weather.py— Open-Meteo hava/tarım sinyalleri
  agent_3_news.py   — NewsAPI + Resmî Gazete haber sinyalleri
  agent_4_market.py — Mandi/MSP + sarı bezelye + WFP piyasa sinyalleri
  agent_5_decision.py— Orkestrasyon + karar üretimi

api/
  main.py           — FastAPI endpoint'leri (/scores, /cell, /scenario, /backtest)

frontend/           — Next.js 14 UI (Oyku)

docs/
  PRD.md            — Ürün gereksinimleri
```

---

## API Endpoint'leri (hazırlandıktan sonra)

```
GET  /scores                   → 7 origin × 3 ufuk skor matrisi
GET  /cell/{origin}/{horizon}  → Hücre detayı (gerekçe + kaynaklar)
POST /scenario                 → What-if analizi
GET  /backtest/{date}          → Geçmiş tarih simülasyonu
```

API çalıştırmak için:
```bash
uvicorn api.main:app --reload --port 8000
```

---

