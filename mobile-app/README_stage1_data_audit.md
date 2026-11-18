# EpiProt — Aşama 1: Veri Denetimi

Bu aşama CHB-MIT Scalp EEG Database için:
- EDF ve özet dosyalarını özyinelemeli bulur,
- `chbXX-summary.txt` dosyalarındaki nöbet anotasyonlarını ayrıştırır,
- EDF meta verilerini (süre, örnekleme hızı, kanallar) okur,
- Anotasyonları EDF dosyalarına doğrular,
- Sorunlu dosyaları atlamaz; her atlama nedenini loglar,
- `data_audit.csv` ve `seizure_annotations.csv` üretir.