# CLAUDE.md

Bu dosya, bu repo üzerinde çalışırken Claude Code'un uyması gereken kuralları içerir.
Detaylı ürün gereksinimleri için: `docs/PRD.md`.

---

## Proje

**Armada Co-Pilot** — Kırmızı mercimekte tedarik/fiyat riskini fiyat piyasaya yansımadan önce gösteren karar destek sistemi. 6 origin (CA, KZ, RU, AU, IN, TR_MERSIN) × 3 ufuk (4/8/12 hafta) için **0–100 risk skoru + güven + kaynaklı gerekçe + karar önerisi + senaryo** üretir.

Sistem **öneri** verir; nihai kararı insan (satınalma) verir. Yöntem: **kural tabanlı skorlama + LLM muhakemesi.** ML model eğitimi yok.

---

## Ekip Görev Dağılımı

| Dosya | Sahip |
|---|---|
| `agents/agent_1_price.py` | Aslan |
| `agents/agent_2_weather.py` | Barış |
| `agents/agent_3_news.py` | Aslan |
| `agents/agent_4_market.py` | Barış |
| `agents/agent_5_decision.py` | Aslan |
| `api/main.py` | Aslan |
| Frontend (Next.js) | Oyku |

**Aslan'ın öncelik sırası:** agent_1 → agent_3 → agent_5 → api/main.py → frontend entegrasyon.

---

## Tech Stack

- **Backend:** Python 3.11+, FastAPI, pandas, requests. Paket yöneticisi: `uv`.
- **Frontend:** Next.js 14 (App Router), TypeScript, Tailwind. API: `http://localhost:8000`.
- **LLM:** Anthropic Claude Haiku (birincil), OpenAI GPT-4o-mini (fallback). Temperature ≤ 0.1, JSON çıktı.
- **Veri:** Yerel XLSX + API çağrıları. MVP'de harici DB zorunlu değil.

---

## Repo Yapısı

```
agents/
  core/
    models.py       # Signal dataclass — YAZILDI, dokunma
    scoring.py      # compute_scores, ScoreResult — YAZILDI, dokunma
    reasoning.py    # generate_rationale — YAZILDI, dokunma
  agent_1_price.py  # Armada XLSX + WB Pink Sheet — YAZILDI
  agent_2_weather.py# Open-Meteo — Barış
  agent_3_news.py   # NewsAPI + Resmî Gazete RSS — YAZILDI
  agent_4_market.py # Mandi + sarı bezelye + WFP — Barış
  agent_5_decision.py # Orkestrasyon + FastAPI — YAZILMADI
api/
  main.py           # FastAPI endpoint'leri — YAZILMADI
data/
  *.XLSX            # Armada ham verisi (gitignore)
frontend/           # Oyku — Next.js 14
docs/PRD.md
.env                # API key'leri (gitignore)
CLAUDE.md
```

---

## .env (zorunlu key'ler)

```
ANTHROPIC_API_KEY=...        # LLM reasoning (zorunlu)
NEWS_API_KEY=...             # NewsAPI dev key (agent_3, ücretsiz 100 req/gün)
ARMADA_EXCEL_PATH=data/2024-2025-2026_Kırmızı_Mercimek_Alış_ları.XLSX
OPENAI_API_KEY=...           # Opsiyonel fallback
```

---

## Komutlar

```bash
cd agents && uv sync
uv run python agent_1_price.py     # test
uv run uvicorn api.main:app --reload --port 8000
uv run ruff check . && uv run ruff format .
```

---

## Mimari — DEĞİŞMEZ KURALLAR

1. **`Signal` sözleşmesi sistemin kalbidir. `core/models.py` dosyasına dokunma.**
   Her ajan `fetch() -> list[Signal]` döndürür. Scoring engine yalnızca Signal görür.

   ```
   origin: str       # "CA"|"KZ"|"RU"|"AU"|"IN"|"TR_MERSIN"|"SY"
   category: str     # "price"|"weather"|"regulation"|"market"|"supply"
   value: float      # normalize değer
   anomaly_z: float  # + = normalin üstünde = yüksek risk
   source_url: str   # ZORUNLU, boş bırakma
   horizon_weights: dict  # {"4w":..,"8w":..,"12w":..}
   note: str         # LLM reasoning için kısa not
   ```

2. **`core/scoring.py` ve `core/reasoning.py` YAZILDI. Yeniden yazma, üstüne ekle.**

3. **Akış tek yönlü:** `agent_N.fetch() → signals → compute_scores() → generate_rationale() → API → UI`

4. **Skorlama deterministik.** Aynı sinyallerle aynı skor. Ağırlıklar `core/scoring.py` içinde tablo olarak.

---

## Veri Notları (Armada XLSX — gerçek dosyadan)

- **`Net fiyat` kolonunun birimi USD/MT'dir** — kolon başlığı "KG" dese de.
  Doğrulama: `Net SAS değeri = (SA siparişi miktarı / 1000) * Net fiyat`
- Origin `Kısa metin` kolonundan parse edilir: KAZAK→KZ, KANADA/KAN→CA, RUS→RU, SURİYE→SY
- **Suriye (SY) gerçek bir origin** — challenge brief'inde yoktu ama veride 46 satır var
- **AU ve IN alış verisinde sıfır satır** — bu iki origin için güven "Düşük" olacak, bu beklenen davranış
- Negatif miktarlar = iptal/düzeltme → `miktar > 0` filtresi zorunlu
- 4 EUR satırı var → FX ile USD'ye çevir

---

## MVP Kapsam Sınırı

**VAR:** agent_1 (Armada + WB) · agent_2 (Open-Meteo) · agent_3 (NewsAPI + Resmî Gazete) · agent_4 (Mandi + sarı bezelye) · agent_5 orkestrasyon · skor matrisi · backtest modu · senaryo slider

**YOK (istenmedikçe):** Gerçek NDVI/uydu, navlun endeksleri, liman lojistiği, OFAC, gübre endeksi, ML eğitimi, auth, production DB

---

## Kritik Kurallar

- **Grounding:** LLM yalnızca verilen sinyallere dayanır. Her çıktı `cited_sources` içerir. Uydurma kaynak = bug.
- **Zarif bozulma:** Ajan düşerse boş `[]` döner, güven düşer, sistem çökmez.
- **Sırlar:** Key'ler sadece `.env`'de. Frontend'e secret sızdırma.
- **AU/IN veri yok:** Güven "Düşük" döner — bu dürüst sistem tasarımıdır, hata değil.
- Büyük değişiklikten önce kısa plan söyle, sonra uygula.
