# TARAI — Frontend Geliştirme Brief V2 (Oyku için)
Tarih: 09 Haziran 2026 | Backend: Barış
V1'in devamıdır — yeni konular ve eksik detaylar.

---

## 1. Origin Detay Sayfası (`/origin/:code`)

Kartlara tıklayınca `/origin/CA` gibi bir URL'e gidiyor. Bu sayfayı şu API verisiyle doldur:

```
GET /risk/{origin_code}?horizon=4
```

### Response içeriği ve neyi nerede göstereceğin:

```json
{
  "code": "CA",
  "name": "Kanada",
  "flag": "🇨🇦",
  "risk_score": 28,
  "decision": "Şimdi Al",
  "confidence": "Yüksek",
  "horizon": 4,

  "price": {
    "value": 735,
    "change_pct": -5.2,
    "trend": "down",
    "source": "Armada"
  },

  "weather": {
    "risk": "Düşük",
    "detail": "Saskatchewan son 30 gün yağış 1.9 mm/gün (normal 1.8)",
    "source": "Open-Meteo — Saskatchewan"
  },

  "news": {
    "risk": "Orta",
    "detail": "Rusya'nın yeni yaptırımları tedarik zincirini...",
    "source": "NewsAPI"
  },

  "ai_reason": "Kanada kırmızı mercimek fiyatları son 60 günde düşüş eğiliminde...",

  "sources": ["Open-Meteo — Saskatchewan", "Armada XLSX", "NewsAPI"],

  "horizons": {
    "4":  { "decision": "Şimdi Al", "confidence": "Yüksek", "score": 28 },
    "8":  { "decision": "Kısmi Al", "confidence": "Orta",   "score": 34 },
    "12": { "decision": "Kısmi Al", "confidence": "Orta",   "score": 38 }
  }
}
```

### Sayfa Düzeni (öneri):

```
┌─────────────────────────────────────────────┐
│  🇨🇦 Kanada           Risk: 28   Şimdi Al   │
│  Güven: Yüksek   Son güncelleme: 09 Haz      │
├──────────────┬──────────────┬───────────────┤
│   4 hafta    │   8 hafta    │   12 hafta    │
│   28 / Şimdi │   34 / Kısmi │   38 / Kısmi  │
├──────────────┴──────────────┴───────────────┤
│  Fiyat: 735 USD/MT   ↓ -5.2%  (Armada)     │
│  Hava:  Düşük risk   Saskatchewan normal    │
│  Haber: Orta risk    ...                    │
├─────────────────────────────────────────────┤
│  🤖 AI Gerekçe                              │
│  "Kanada kırmızı mercimek fiyatları..."     │
│                                             │
│  Kaynaklar:                                 │
│  • Open-Meteo — Saskatchewan [↗]           │
│  • Armada XLSX [↗]                         │
│  • NewsAPI [↗]                             │
└─────────────────────────────────────────────┘
```

### Notlar:
- `sources` array'i `cited_sources` URL'leri içerebilir — tıklanabilir link yap
- `change_pct` negatifse yeşil (fiyat düştü = fırsat), pozitifse kırmızı
- `confidence` her zaman göster: "Düşük" gelirse sarı uyarı badge ekle
- Horizons tablosu: aktif horizon highlight edilsin

---

## 2. Güven Seviyesi (Confidence) — Her Kartda Göster

Şu an kartlarda confidence görünmüyor. **Mutlaka ekle** — özellikle AU ve IN için "Düşük" gelecek.

### Dashboard kartına eklenecek:

```
┌──────────────────────────┐
│ 🇮🇳  Hindistan           │
│                          │
│   82        Alternatif   │
│  RISK          Bak       │
│                          │
│  ● Güven: Düşük  ⚠️      │  ← BU SATIR EKSİK
│                          │
│  İhracat yasağı...       │
└──────────────────────────┘
```

### Renk kodları:
| Güven | Renk | İkon |
|---|---|---|
| Yüksek | Yeşil | ✓ |
| Orta | Sarı | ~ |
| Düşük | Turuncu | ⚠️ |

**Önemli:** AU ve IN'de "Düşük" güven görünce kullanıcı "bu veri az, dikkatli ol" anlasın.

---

## 3. Loading State (20-30 saniye)

API ilk çağrıldığında tüm agentlar çalışır: Armada XLSX + Open-Meteo + NewsAPI + World Bank.
Bu **20-30 saniye** sürebilir. Cache sonrası ~1-2 saniye.

### Gösterilecek UI:

```
┌──────────────────────────────────────────┐
│  ⟳  Piyasa verileri analiz ediliyor...  │
│                                          │
│  ████████░░░░░░░░  Fiyat sinyalleri ✓   │
│  ████░░░░░░░░░░░░  Hava verileri...     │
│  ██░░░░░░░░░░░░░░  Haberler...          │
│  ░░░░░░░░░░░░░░░░  Piyasa verileri...   │
└──────────────────────────────────────────┘
```

En basit çözüm: spinner + "Analizler hazırlanıyor, ~20 saniye..." yazısı.
Skeleton kartlar daha iyi UX verir (kartların outline'ı gözükür, içi shimmer).

### Teknik not:
```js
// API çağrısı sırasında isLoading = true
const [isLoading, setIsLoading] = useState(true)
// ...
setIsLoading(false) // data gelince
```

---

## 4. "Yenile" Butonu — Gerçek Cache Temizleme

Şu anki "Yenile" butonu muhtemelen sadece `window.location.reload()` yapıyor.
API'nin 6 saatlik cache'ini temizlemek için özel parametre lazım.

### Barış'ın API'ye ekleyeceği:
`GET /risk/all?horizon=4&refresh=true` → cache bypass eder, agentları yeniden çalıştırır.

### Frontend'de:
```js
// Normal yükleme (cache'den, hızlı)
fetch('/risk/all?horizon=4')

// Yenile butonu (cache'i atla, yavaş ~20-30sn)
fetch('/risk/all?horizon=4&refresh=true')
```

Yenile butonuna tıklayınca Loading State göster (yukarıdaki #3).

> **Not:** Barış bu parametreyi ekleyecek, V2 briefi okuyunca yapacak.

---

## 5. Backtest Modu (Demo'nun En Güçlü Anı)

API'de `as_of` parametresi var: geçmiş bir tarihe "o günmüş gibi" analiz yapılıyor.

```
GET /risk/all?horizon=4&as_of=2024-05-01
```

### Demo Senaryosu:
> "Mayıs 2024'te bu sistemi kullansaydınız: Kanada risk skoru 71/100, öneri 'Bekle'.
> 8 hafta sonra gerçekten -%35 fiyat düşüşü yaşandı."

### UI Önerisi — Date Picker:

```
┌─────────────────────────────────────────────────┐
│  📅 Backtest Modu        [CANLI] [GEÇMİŞ]       │
│                                                  │
│  Tarih seç: [  2024-05-01  ▼ ]  [Analizi Çalıştır] │
│                                                  │
│  ⚠️  Geçmiş analiz: 01 Mayıs 2024 verisiyle      │
└─────────────────────────────────────────────────┘
```

"CANLI" mode → normal çalışma
"GEÇMİŞ" mode → date picker açılır, tarih seçince `/risk/all?as_of=2024-05-01` çağrılır

### Öneri tarihleri (dropdown'a ekle):
| Tarih | Olay |
|---|---|
| 2024-05-01 | Kanada kuraklık başlangıcı |
| 2024-09-01 | Hindistan ihracat kısıtlamaları |
| 2025-01-01 | Rusya ambargo haberleri |

Backtest'te dashboard header'a kırmızı banner: "📅 Geçmiş Analiz: 01 Mayıs 2024"

---

## 6. Static Fallback (Demo Güvenliği)

Demo sırasında internet kesilirse ya da API kapanırsa app boş sayfa göstermemeli.

### Çözüm — Cache Dosyası:
`agents/cache/decision_result.json` → son başarılı API çalışmasının tam çıktısı.
Bu dosyayı `public/fallback_data.json` olarak kopyala.

```js
// API çağrısı başarısız olursa fallback'e düş
async function fetchRiskData(horizon) {
  try {
    const res = await fetch(`http://localhost:8000/risk/all?horizon=${horizon}`)
    if (!res.ok) throw new Error('API error')
    return await res.json()
  } catch (err) {
    console.warn('API unreachable, loading fallback data...')
    const fallback = await fetch('/fallback_data.json').then(r => r.json())
    return transformFallbackToRiskAll(fallback, horizon)
  }
}
```

Fallback aktifken banner göster:
```
⚠️  Çevrimdışı mod — son analiz: 09 Haziran 2026 01:00
```

### Demo öncesi yapılacak:
1. API'yi çalıştır, bir kez `/risk/all` çağır
2. `agents/cache/decision_result.json` dosyasını `frontend/public/fallback_data.json`'a kopyala
3. API'yi kapat — app çalışmaya devam eder

---

## 7. Renk Tutarlılığı — Origin Renkleri Sabit Olsun

Fiyat grafiğinde CA yeşil, KZ turuncu, RU kırmızı... ama kartlarda renk risk skoruna göre değişiyor.
Grafik legend'ı ile kart rengini aynı yapma — bu kafa karıştırır.

### Öneri:
- **Kartlardaki gauge rengi** → risk skoruna göre (yeşil/sarı/kırmızı) — mevcut, doğru
- **Grafikteki çizgi renkleri** → origin'e özgü sabit renk — mevcut, doğru
- **İkisini karıştırma:** kartlarda origin rengi kullanma, grafiklerde risk rengi kullanma

### Sabit Origin Renkleri (grafik için):
```js
const ORIGIN_COLORS = {
  CA: '#22c55e',   // yeşil
  KZ: '#f97316',   // turuncu
  RU: '#ef4444',   // kırmızı
  IN: '#a855f7',   // mor
  AU: '#06b6d4',   // cyan
  SY: '#eab308',   // sarı
  TR_MERSIN: '#3b82f6', // mavi
}
```

---

## 8. Senaryo Simülasyonu — Animasyon

Senaryo seçilince sadece tablo değil, kartlardaki skorlar da canlı güncellensin.

```js
// Senaryo seçilince:
// 1. /scenario POST at
// 2. response.results'taki after değerlerini kartlara yansıt
// 3. Animated counter: 28 → 47 (smooth 1 saniyelik geçiş)
// 4. delta > 10 olan kartın border'ı kırmızı pulse animasyonu yapsın
```

### Tablo DEĞİŞİM kolonu:
```
delta > 0  →  +19  (kırmızı, ↑)
delta < 0  →  -8   (yeşil, ↓)
delta == 0 →  —    (gri)

fob_delta_pct null değilse:
  +3.8%  →  FOB (Sonra) altında küçük yazıyla göster
```

---

## Özet — Öncelik Sırası

| # | Konu | Süre | Öncelik |
|---|---|---|---|
| 1 | Yazım hatası "şimai" → "şimdi" | 1 dk | 🔴 Kritik |
| 2 | Senaryo mapping (API key'leri) | 5 dk | 🔴 Kritik |
| 3 | SY + TR_MERSIN kartları | 15 dk | 🔴 Kritik |
| 4 | Güven seviyesi badge | 10 dk | 🟠 Önemli |
| 5 | Loading state (spinner) | 20 dk | 🟠 Önemli |
| 6 | Origin detay sayfası | 45 dk | 🟠 Önemli |
| 7 | Static fallback JSON | 30 dk | 🟡 Demo güvenliği |
| 8 | Senaryo animasyonu | 20 dk | 🟡 Demo etkisi |
| 9 | Backtest modu | 60 dk | 🟢 Nice-to-have |
| 10 | Yenile butonu (refresh param) | 10 dk | 🟢 Nice-to-have |

**Demo için minimum:** 1 + 2 + 3 + 5 + 7

---

## Barış'ın Yapacakları (API)

Oyku'nun beklemesi gereken iki şey:

1. `GET /risk/all?refresh=true` parametresi → cache bypass
2. `GET /risk/{origin}?horizon=4` detay endpoint'i → zaten çalışıyor ✅

Sorular için WhatsApp.
