# server-scripts

Dokploy üzerinde çalışan servisler için kaynak kodlar.

## Dizin Yapısı

```
server-scripts/
├── shared/              # Ortak utilities — DB bağlantısı, logging, config
│
├── futbol/
│   ├── collector/       # Veri toplama — API, odds, istatistik
│   ├── engine/          # Poisson, ELO, form analizi, sinyal üretimi
│   └── dashboard/       # Raporlama çıktıları (opsiyonel)
│
├── kripto/
│   ├── collector/       # OHLCV, funding rate, haber toplama
│   └── engine/          # Korelasyon, hedge, sinyal üretimi
│
└── infra/               # Dokploy compose dosyaları, migration scriptleri
```

## Deployment

Her servis Dokploy'a ayrı compose servisi olarak deploy edilir.

## Notlar

- `shared/` — Tüm servislerin ortak kullandığı utility fonksiyonları
- `infra/` — Altyapı konfigürasyonları ve migration scriptleri
