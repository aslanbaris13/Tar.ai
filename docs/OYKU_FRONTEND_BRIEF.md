# TARAI — Frontend Geliştirme Brief (Oyku için)
Tarih: 09 Haziran 2026 | Backend: Barış

---

## API Bağlantısı

```
Base URL: http://localhost:8000
Docs:     http://localhost:8000/docs
```

Tüm endpoint'ler hazır ve çalışıyor. Aşağıdaki değişiklikler bu brief ile birlikte API'ye eklendi.

---

## 1. Düzeltmeler (Kritik)

### 1.1 Yazım Hatası
- **Fiyat Analizi grafiğindeki "şimai" → "şimdi"** olmalı

### 1.2 Senaryo Dropdown Mapping
UI'daki senaryo isimleri API key'leriyle eşleşmeli:

| UI'da gösterilen | API'ye gönderilecek `shock` değeri |
|---|---|
| Hindistan ihracat yasağı | `india_export_ban` |
| Karadeniz kapanır | `russia_embargo` |
| Saskatchewan kuraklığı | `canada_drought` |
| Kazakistan kotası *(ekle)* | `kazakhstan_quota` |

```js
// POST /scenario
const res = await fetch('/scenario', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ shock: 'canada_drought' })
})
```

### 1.3 SY ve TR_MERSIN Kartları Ekle
`GET /risk/all?horizon=4` artık 7 origin döndürüyor (CA, KZ, RU, IN, AU, **SY, TR_MERSIN**).
Bunları dashboard grid'e ekle. SY ve TR_MERSIN'in güven seviyesi "Düşük" olabilir — bu normal.

---

## 2. Yeni API Özellikleri (Bu Brief ile Eklendi)

### 2.1 Fiyat Forecast (`/prices/trend`)
Artık response'da `forecast` ve `forecast_weeks` alanları var:

```json
{
  "horizon": 4,
  "dates": ["2026-01-06", "2026-01-13", ...],
  "series": { "CA": [735.1, 728.4, ...], ... },
  "forecast": { "CA": [731.2, 729.8, 728.4, 727.1], ... },
  "forecast_weeks": 4,
  "summary": { ... }
}
```

**Kullanım:** `series` → geçmiş (solid çizgi), `forecast` → projeksiyon (dashed çizgi).
Grafik X ekseni: H1…H{n} (geçmiş) + F1…F{horizon} (forecast).
"Şimdi" marker = series'in son noktası ile forecast'ın ilk noktası arası.

### 2.2 Senaryo FOB Delta (`/scenario`)
Artık her origin için FOB fiyat tahmini de geliyor:

```json
{
  "shock_name": "Kanada kuraklık derinleşir",
  "results": [
    {
      "code": "CA",
      "name": "Kanada",
      "flag": "🇨🇦",
      "before": 28,
      "after": 47,
      "delta": 19,
      "fob_before": 735.1,
      "fob_after": 773.9,
      "fob_delta_pct": 5.2
    },
    ...
  ],
  "recommendation": "..."
}
```

**Tabloda gösterim:**
- `fob_before` → FOB (Önce) kolonu
- `fob_after` → FOB (Sonra) kolonu (bold)
- `fob_delta_pct` → Değişim kolonu (`+5.2%` veya `—` if null)
- `delta > 0` → kırmızı, `delta < 0` → yeşil renk

---

## 3. Dashboard Geliştirmeleri

### 3.1 Horizon Switcher (Ana Dashboard)
Fiyat Analizi'ndeki gibi 4/8/12 hafta switcher'ı Dashboard'a da ekle.
API çağrısı: `GET /risk/all?horizon=4` (veya 8, 12)

### 3.2 Origin Kartı — Risk Renk Eşiği
```
0–35   → yeşil  (düşük risk)
36–65  → sarı   (orta risk)
66–100 → kırmızı (yüksek risk)
```

### 3.3 Karar Renkleri
| Karar | Renk |
|---|---|
| Şimdi Al | Yeşil |
| Kısmi Al | Sarı/turuncu |
| Bekle | Kırmızı |
| Alternatif Bak | Koyu kırmızı/bordo |

---

## 4. Alerts Sayfası

`GET /alerts` response formatı:

```json
{
  "alerts": [
    {
      "time": "2026-06-09",
      "type": "Politika",
      "text": "Rusya'nın yeni yaptırımları...",
      "source": "NewsAPI",
      "origin": "RU",
      "severity": "medium",
      "score": 1.2
    }
  ]
}
```

- `time` → relative format göster ("12 dk önce" değil, "bugün" / "dün" / "3 gün önce")
- `severity` → `high`=kırmızı badge, `medium`=turuncu, `low`=sarı
- `type` map'i: `"Politika"` → POLİTİKA badge, `"Hava"` → HAVA badge vb.

---

## 5. Senaryo Simülasyonu — UX İyileştirme

Senaryo seçilince kartlardaki skorlar da animate şekilde güncellensin:
- `before` → `after` değerine smooth transition
- `delta > 0` olan originlerde kart border'ı kırmızıya dönsün
- Tablo da aynı anda güncellensin

---

## 6. Fiyat Analizi — "Armada vs Piyasa" Grafiği

`/prices/trend` endpoint'i Armada'nın gerçek alım fiyatlarını veriyor (XLSX'ten).
"Piyasa ortalaması" için tüm origin'lerin haftalık ağırlıklı ortalaması alınabilir:

```js
// Her haftada tüm originlerin ortalaması = piyasa fiyatı
const market = dates.map((d, i) =>
  Object.values(series)
    .map(vals => vals[i])
    .filter(v => v !== null)
    .reduce((a, b) => a + b, 0) / Object.keys(series).length
)
```

Armada alım fiyatı için: Armada her zaman tek bir origin'den almaz, ağırlıklı alım.
Basit gösterim için CA serisini "Armada alım" olarak gösterebilirsin (CA en çok alınan origin).

---

## 7. Stil Notları

- Dark theme default, açık tema toggle korunabilir
- Font: mevcut tasarım çok iyi, değiştirme
- Sidebar: 3 sayfa yeterli (Ana Dashboard, Senaryo, Fiyat Analizi)
- Mobile responsive zorunlu değil (B2B tool, masaüstü)
- Loading state ekle: API çağrısı sırasında skeleton veya spinner

---

## 8. API Hata Durumları

```js
// Graceful degradation: API kapalıysa mock data göster
try {
  const data = await fetch('/risk/all?horizon=4').then(r => r.json())
  // ...
} catch {
  // fallback: son cache'lenmiş data veya static mock
  console.warn('API unreachable, using cached data')
}
```

API kapalıysa app çökmemeli — statik verilerle çalışmaya devam etmeli.

---

## 9. Demo Senaryosu (10 Haziran için)

Sunum sırasında bu akışı göster:

1. **Dashboard** → "Hindistan 82 risk skoru, şimdi al" → hikaye: piyasa haberleri önümüzdeki haftalarda fiyata yansıyacak
2. **Senaryo** → "Karadeniz kapanır" seç → Rusya skoru +30 puan zıplar, FOB +%6
3. **Fiyat Analizi** → Armada vs Piyasa → "Armada piyasadan %2.6 ucuza alıyor"
4. **Alerts** → Güncel haberler → AI destekli erken uyarı

---

## Sorular için

Barış: aslanbaris870@gmail.com / WhatsApp
