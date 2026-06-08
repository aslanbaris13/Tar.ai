# TARAI — Armada Co-Pilot

> Kırmızı mercimek tedarik riskini piyasaya yansımadan önce gösteren yapay zeka destekli karar destek sistemi.

---

## Problem

Kırmızı mercimek alım kararları geç kalındığında maliyetli olur. Fiyat hareketleri piyasaya yansıdığında iş işten geçmiştir — hava olayları, ihracat kısıtlamaları ve piyasa dinamikleri genellikle haftalarca önceden sinyal verir.

## Çözüm

TARAI, 6 farklı menşeden (Kanada, Kazakistan, Rusya, Hindistan, Avustralya, Suriye) eş zamanlı sinyal toplayarak **4, 8 ve 12 haftalık risk ufukları** için 0–100 arası risk skoru üretir. Her skor için AI destekli Türkçe gerekçe ve kaynaklı karar önerisi sunar.

**Sistem öneri verir; nihai kararı insan verir.**

---

## Nasıl Çalışır?

```
Veri Kaynakları                 Agentlar              Çıktı
────────────────────────────    ──────────────────    ──────────────────────
Armada alım geçmişi (XLSX)  →   Fiyat Ajanı       ─┐
Open-Meteo hava verisi      →   Hava Ajanı        ─┤  Risk Skoru (0-100)
NewsAPI + Resmî Gazete      →   Haber Ajanı       ─┤  Güven Seviyesi
World Bank + Mandi          →   Piyasa Ajanı      ─┘  Karar Önerisi
                                        ↓               AI Gerekçe
                                Karar Ajanı             Kaynaklı Analiz
                                        ↓
                                FastAPI → Next.js UI
```

**Yöntem:** Kural tabanlı z-skor anomali tespiti + GPT-4o-mini muhakemesi. ML model eğitimi yok.

---

## Özellikler

- **Risk Matrisi** — 7 menşe × 3 zaman ufku (4/8/12 hafta) = 21 hücre
- **Senaryo Simülasyonu** — "Hindistan ihracatı kapatırsa ne olur?" what-if analizi
- **Fiyat Analizi** — FOB fiyat trendi + ileriye projeksiyon + Armada vs piyasa karşılaştırması
- **Canlı Uyarılar** — AI sınıflandırmalı haber ve hava uyarıları
- **Backtest Modu** — Geçmiş tarihlerle sistemin doğruluğunu test et
- **Zarif Bozulma** — Herhangi bir veri kaynağı düşse sistem çalışmaya devam eder

---

## Tech Stack

| Katman | Teknoloji |
|---|---|
| Backend | Python 3.11, FastAPI, pandas |
| LLM | OpenAI GPT-4o-mini (birincil), Anthropic Claude Haiku (fallback) |
| Veri | Armada XLSX + Open-Meteo + NewsAPI + World Bank + Mandi |
| Frontend | Next.js 14, TypeScript, Tailwind CSS |

---

## Kurulum

**1. Repoyu klonla**
```bash
git clone https://github.com/aslanbaris13/Tar.ai.git
cd Tar.ai
```

**2. Ortam oluştur**
```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**3. `.env` dosyasını oluştur**
```bash
cp .env.example .env
# OPENAI_API_KEY ve NEWS_API_KEY alanlarını doldur
```

**4. Armada Excel dosyasını `data/` klasörüne koy**
```
data/2024-2025-2026 Kırmızı Mercimek Alışları.XLSX
```

**5. API'yi başlat**
```bash
uvicorn api.main:app --reload --port 8000
# http://localhost:8000/docs → Swagger UI
```

---

## API Endpoint'leri

| Method | Endpoint | Açıklama |
|---|---|---|
| GET | `/risk/all?horizon=4` | Tüm menşelerin risk skoru |
| GET | `/risk/{origin}` | Tek menşe detayı + AI gerekçe |
| GET | `/prices/trend` | Haftalık fiyat serisi + forecast |
| GET | `/alerts` | Aktif uyarılar |
| POST | `/scenario` | What-if senaryo analizi |

---

## Repo Yapısı

```
agents/
  core/            — Signal dataclass, scoring, LLM reasoning
  agent_1_price.py — Armada XLSX + World Bank
  agent_2_weather.py — Open-Meteo (4 üretim bölgesi)
  agent_3_news.py  — NewsAPI + Resmî Gazete RSS
  agent_4_market.py — Mandi + sarı bezelye + WFP
  agent_5_decision.py — Orkestrasyon + karar üretimi
api/
  main.py          — FastAPI (5 endpoint)
data/              — Armada ham verisi (gitignore)
docs/              — Teknik dökümanlar
```

---

## Demo

Canlı demo: [https://tarai-lens-pulse.lovable.app](https://tarai-lens-pulse.lovable.app)

Swagger UI: `http://localhost:8000/docs`
