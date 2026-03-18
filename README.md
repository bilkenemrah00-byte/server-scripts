# server-scripts

Dokploy uzerinde calisan servisler icin kaynak kodlar.

## Servisler (Planlanan)
- futbol-collector/ — Mac verisi ve odds toplama
- futbol-engine/ — Poisson modeli, form analizi, sinyal uretimi
- kripto-collector/ — OHLCV, funding rate toplama
- kripto-engine/ — Korelasyon, hedge sinyal uretimi
- shared/ — Ortak DB utils

## Deployment
Her servis Dokploy'a ayri compose servisi olarak deploy edilir.
