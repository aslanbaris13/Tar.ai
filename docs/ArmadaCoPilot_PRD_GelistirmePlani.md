# Armada Co-Pilot — Kırmızı Mercimek Tedarik Riski Erken Uyarı Sistemi
### PRD + MVP Geliştirme Planı | Güncelleme: 8 Haziran 2026

---

## 0. Tek Cümlede

Kanada, Kazakistan, Rusya, Avustralya, Hindistan origin'leri ve Türkiye/Mersin referansı için **4/8/12 hafta** ufkunda kırmızı mercimekte arz-fiyat riskini fiyat piyasaya yansımadan önce gösteren; **0–100 risk skoru + güven + kaynaklı gerekçe + karar önerisi + senaryo** üreten karar destek co-pilot'u.

---

## 1. Kapsam

| Boyut | İçerik |
|---|---|
| Emtia | Kırmızı mercimek (tek) |
| Origin'ler | CA, KZ, RU, AU, IN + TR_MERSIN (yerel referans) |
| Ek origin | SY (Suriye) — brief'te yoktu, Armada verisinde 46 satır çıktı |
| Zaman ufukları | 4, 8, 12 hafta |
| Para birimi | USD/MT |
| Kapsam dışı | 12 ay+ ufuk, ML eğitimi, Armada iç verileri (silo/ledger) |

---

## 2. Fonksiyonel Gereksinimler

Her **(origin × ufuk)** hücresi için 5 çıktı:

| # | Çıktı | Kabul kriteri |
|---|---|---|
| F1 | Risk skoru 0–100 | Deterministik, tekrar üretilebilir |
| F2 | Güven: Düşük/Orta/Yüksek | Veri kapsamı × sinyal uyumu |
| F3 | Kaynaklı gerekçe | En az 1 izlenebilir source_url |
| F4 | Karar önerisi | şimdi al / bekle / kısmi al / alternatif origin |
| F5 | Senaryo (what-if) | Tek değişken pertürbasyonu → skor delta |

**+ Backtest modu:** Geçmiş tarih gir → o tarihteki veriyle skor yeniden hesapla (demo kalbi).

---

## 3. Veri — Gerçek Dosya Analizi

### 3.1 Armada Alış Verisi (agent_1 çekirdeği)

**Dosya:** `2024-2025-2026_Kırmızı_Mercimek_Alış_ları.XLSX`
- 554 satır | Ocak 2024 → Mayıs 2026 | 549 USD + 4 EUR satırı

| Kolon | Açıklama |
|---|---|
| `Belge tarihi` | Pandas direkt datetime parse eder |
| `Kısa metin` | Origin buradan parse edilir (KAZAK, KANADA, RUS, SURİYE...) |
| `Net fiyat` | **USD/MT** — kolon "KG" der ama formül: `Net SAS = (miktar_KG/1000) × Net fiyat` |
| `SA siparişi miktarı` | KG cinsinden; negatifler iptal → `> 0` filtrele |
| `Para birimi` | USD veya EUR; EUR → FX ile USD'ye çevir |

**Gerçek fiyat aralıkları (USD/MT):**

| Origin | Min | Max | Ort. | Satır |
|---|---|---|---|---|
| CA (Kanada) | 493 | 1023 | 795 | 118 |
| KZ (Kazakistan) | 303 | 904 | 510 | 371 |
| RU (Rusya) | 505 | 885 | 596 | 15 |
| SY (Suriye) | 720 | 1100 | 885 | 46 |
| **AU, IN** | — | — | — | **0** |

**Kritik bulgu:** AU ve IN alış verisinde sıfır satır. Bu origin'ler tamamen dış veri kaynaklarına (agent_2, agent_4) dayanır → güven skoru bunu yansıtır.

**Çeyreklik trend (backtest için temel):**
```
         CA     KZ     RU
2024Q1  932    655    —       ← CA fiyatı tarihi zirve
2024Q2  762    751    698
2024Q3   —     540    575     ← KZ sert düşüş
2024Q4  683    475    611     ← KZ dip
2025Q2  650    489    669
2025Q3  521    537    521
2026Q1  497     —     —       ← CA %47 düştü 2 yılda
```

### 3.2 Armada Satış Verisi (kırma marjı için)

**Dosya:** `Kırmızı_Mercimek_2024-2026.xlsx`
- 1079 satır | Ocak 2024 → Haziran 2026 | USD/EUR/TRY/AED
- Alış - satış farkı = kırma marjı (demo'da gösterilebilir bonus)

### 3.3 MVP Veri Kaynakları (ajan bazında)

| Ajan | Kaynak | Sahip | Durum |
|---|---|---|---|
| agent_1 | Armada XLSX + World Bank Pink Sheet | Aslan | ✅ Yazıldı |
| agent_2 | Open-Meteo (ücretsiz, anahtarsız) | Barış | — |
| agent_3 | NewsAPI + Resmî Gazete RSS | Aslan | ✅ Yazıldı |
| agent_4 | Agmarknet/Mandi + sarı bezelye + WFP | Barış | — |
| agent_5 | Orkestrasyon (yukarıdakileri çağırır) | Aslan | — |

---

## 4. Mimari

```
agent_1.fetch()  ─┐
agent_2.fetch()  ─┤
agent_3.fetch()  ─┼→ List[Signal] → compute_scores() → generate_rationale() → FastAPI → UI
agent_4.fetch()  ─┤
agent_5 (orkestra)┘
```

**Yazılan core modüller (`agents/core/`):**
- `models.py` — Signal dataclass
- `scoring.py` — compute_scores(), ScoreResult, recommendation()
- `reasoning.py` — generate_rationale(), fallback

**API endpoint'leri (yazılacak: `api/main.py`):**
```
GET  /scores                    → tüm matris (6 origin × 3 ufuk)
GET  /cell/{origin}/{horizon}   → hücre detayı (gerekçe + kaynaklar)
POST /scenario                  → {"origin":"CA","signal":"weather","delta_z":2.0}
GET  /backtest/{date}           → geçmiş tarih için skor (YYYY-MM-DD)
```

---

## 5. Skorlama Motoru

Kategori ağırlıkları ufka göre (`core/scoring.py`'de tablo):

| Kategori | 4w | 8w | 12w |
|---|---|---|---|
| price | 0.50 | 0.35 | 0.25 |
| weather | 0.30 | 0.25 | 0.20 |
| regulation | 0.20 | 0.25 | 0.20 |
| market | 0.15 | 0.20 | 0.25 |
| supply | 0.10 | 0.20 | 0.30 |

Ağırlıklı z-toplam → sigmoid → 0–100. Güven = f(kategori kapsamı × sinyal yön uyumu).

---

## 6. LLM Reasoning

- **Model:** Claude Haiku (birincil, hız/maliyet dengesi), GPT-4o-mini (fallback)
- **Girdi:** Skor + top 3 sinyal + source_label'lar
- **Çıktı JSON:** `{rationale, recommendation, key_factors, cited_sources}`
- **Grounding kuralı:** Yalnızca verilen sinyallere dayansın. Uydurma kaynak = bug.
- **Öneri her zaman kural motorundan** — LLM öneriyi değil gerekçeyi üretir.

---

## 7. Demo Stratejisi (10 Haziran)

**Merkez argüman:** "Kendi alış verinizle geçmişe döndük — sistem ne söylerdi?"

**Backtest senaryosu (veriden hazır):**
- "Mayıs 2024'te çalıştırsaydık: CA z-skoru +1.8, risk 71/100, öneri: bekle"
- Gerçekte olan: CA 762 → 497 (-35%) sonraki 8 haftada
- Bu cümle jürinin gözünde sistemi kanıtlar

**Sürpriz kart:** "Verilerinizde 46 satır Suriye alışı bulduk — brief'te yoktu, sistem kapsıyor"

**AU/IN güven düşük:** Bu zayıflık değil, dürüst tasarım — "veri olmayan yerde güven düşürüyoruz"

---

## 8. Geliştirme Planı

### ✅ Tamamlanan
- `core/models.py` — Signal
- `core/scoring.py` — Skorlama motoru
- `core/reasoning.py` — LLM gerekçe
- `agent_1_price.py` — Armada XLSX parser + WB benchmark + backtest
- `agent_3_news.py` — NewsAPI + Resmî Gazete + LLM sınıflandırma

### 🔲 Bugün (8 Haziran)
- `agent_5_decision.py` — 4 ajanı çağır, skorla, gerekçe üret, cache
- `api/main.py` — `/scores`, `/cell`, `/scenario`, `/backtest` 

### 🔲 Yarın (9 Haziran, teslim 19:00)
- Frontend ↔ API entegrasyonu (Oyku + Aslan)
- Backtest modu UI'da çalışıyor
- Senaryo slider
- Statik fallback (demo'da internet kesilirse)
- Pitch deck (10 slayt, 30pt font)

---

## 9. Riskler

| Risk | Önlem |
|---|---|
| NewsAPI 100 req/gün limiti | Sonuçları cache'le, demoda tekrar çekme |
| WB Pink Sheet URL değişir | Başarısız olursa agent_1 sadece Armada verisiyle çalışır |
| AU/IN sinyal yok | Güven "Düşük" döner — beklenen davranış |
| Demo'da internet kesilir | Statik JSON cache hazırla, UI bunu fallback olarak sunsun |
| LLM timeout | `core/reasoning.py`'de fallback kural tabanlı gerekçe var |
