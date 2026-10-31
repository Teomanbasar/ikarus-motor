# IKARUS QUANT – tarayıcı (Python motoru)

TradingView'deki **IKARUS QUANT v4.6 aday** göstergesinin hesaplarını Python'da yapar ve
tüm BIST hisselerini kapanıştan sonra tarar. Sonuçlar uygulamanın okuyacağı `cikti/sonuclar.json`
dosyasına ve Excel'de açılabilen `cikti/sonuclar.csv` dosyasına yazılır.

Motor, TradingView'deki v4.6 göstergesiyle aynı veride **birebir aynı sonucu** veriyor
(AKBNK günlük 40 bar ve GUBRF haftalık 30 bar, 21 çıktının hepsi; fark yalnız 4. ondalıkta yuvarlama).

## Kurulum (bir kez)

1. Bu klasörü bilgisayarında bir yere çıkar (örnek: `Belgeler\ikarus_app`).
2. `kurulum_kontrol.bat` dosyasına çift tıkla. Gerekli paketleri kurar, sonra
   Yahoo verisiyle hesaplanan değerleri Zippo tablolarıyla ve TradingView'deki v4.6 ile karşılaştırır.
   Sonunda "x/y değer tuttu" yazar. Dip/Tepe'de kuruş farkı normal; Percentile ya da sinyal tutmuyorsa haber ver.

## Günlük kullanım

- `calistir.bat` → tüm BIST'i tarar (yaklaşık 1–3 dakika). Kapanıştan sonra (18:15 sonrası) çalıştır.
- Belirli hisseler için komut satırından: `python -m ikarus.scan THYAO AKBNK`
- Otomatik çalıştırmak için: Windows **Görev Zamanlayıcı** → Temel görev oluştur → her gün 18:30 →
  program olarak `calistir.bat` (görev penceresi kapanmasın istemiyorsan ortam değişkeni `IKARUS_SESSIZ=1`).

## Çıktılar

`cikti/sonuclar.json` içinde:
- `piyasa`: BIST100, M3, makro etiketi
- `listeler.D` / `listeler.W` (günlük / haftalık):
  - `sinyal`: BEKLE dışındaki sinyaller (ALINABILIR → TOPLANIYOR → YAKIN → DAGITIM, Toplam'a göre)
  - `yeni`: sinyali bugün değişenler
  - `ucuz`: Percentile ≤ 20, `pahali`: Percentile ≥ 80
  - `stop`: önceki Stop'un %3.5'ten fazla altına inenler
- `hisseler`: her hisse için IKARUS tablosunun bütün satırları (günlük ve haftalık) + eksik şartlar

## M3 (otomatik)

Hesap, TradingView'deki `ECONOMICS:TRM3` serisini (TCMB M3 para arzı) kullanır. Geçmiş `data/m3.csv`'de
(TradingView'den birebir alındı, Eylül 2026'ya kadar). Sonraki aylar her çalışmada **EVDS'ten otomatik**
eklenir: TCMB'nin haftalık M3 serisinin (`TP.HPBITABLO1.18`) her ayın son cuma değeri. Bu, TradingView'in
TRM3 değeriyle aynı seri (Ağustos 2026 birebir; diğer aylarda TCMB revizyonundan %0.01–0.06 fark).

Bunun için bir kez EVDS API anahtarı al (ücretsiz): evds3.tcmb.gov.tr → Üye ol / Giriş → profil → API anahtarı.
`ayarlar_ornek.txt` dosyasının adını `ayarlar.txt` yap ve `evds_key=` satırına anahtarı yapıştır.

Not: TradingView ay damgalı değeri ancak o ay **kapandıktan sonra** kullanır (1 Eylül damgalı değer
1 Ekim'den itibaren); motor bunu kendisi yapıyor.

## Bilinen sınırlar

- Fiyatlar Yahoo Finance'ten (temettü düzeltmeli). TradingView'in temettü düzeltmesinden küçük farklar olabilir;
  `kurulum_kontrol.bat` bunu ölçer.
- Sinyal kuralı ve RS / Compression / Makro etiketi hâlâ Zippo'nun yaklaşığı (v4.6 aday, 19 tablonun 18'i).
  Makro etiketi bu sürümde BIST100'den tek etiket (GENİŞLEME / NÖTR / DARALMA).
- Yatırım tavsiyesi değildir.

## Dosyalar

- `ikarus/engine.py` – hesap motoru (Pine v4.6'nın birebir karşılığı)
- `ikarus/data.py` – hisse listesi, fiyatlar, BIST100, M3
- `ikarus/scan.py` – tüm BIST taraması ve çıktı dosyaları
- `ikarus/kontrol.py` – kurulum kontrolü
