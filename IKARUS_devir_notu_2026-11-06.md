# IKARUS — devir notu (6 Kasım 2026)

Bu not yeni konuşmanın başlangıç noktasıdır. Proje: claude.ai "quant". Kişi: Teoman (Türkçe konuşur, sade anlatım ister).

## 0. Çalışma kuralları (Teoman'ın kalıcı istekleri)
- Öncelik: Zippo'nun (@bist_imkb) sisteminden şaşmamak. Yalnız emin olduklarımızı ekle; tutan yerleri bozma.
- Testler ayrı test göstergesinde; Teoman'ın kayıtlı göstergesini istemeden değiştirme, "kaydetme".
- Şifre/gizli anahtar girme; Teoman kendisi girer. Zippo'nun korumalı kodunu çıkarmaya çalışma.
- Her Zippo tablosu günlük/haftalık/aylık ve normal/Heikin Ashi olabilir; paylaşıldığı saatteki fiyatla ölç.
- Geçmişe dönük ölçümde M3 o gün bilinen değer olmalı.
- TradingView'de tarayıcıyla çalıştıktan sonra grafiği eski haline getir (sembol, zaman dilimi, adj).
- Elle tarama tetiklerken Telegram'a çift mesaj gitmesin: tetik.txt içine "sessiz" yaz.
- Teoman kendi TradingView grafiğinde temettü düzeltmesi (adj) AÇIK kullanır.

## 1. Sistemler ve dosyalar
| Ne | Nerede | Durum |
|---|---|---|
| IKARUS QUANT v4.7 (Pine, en emin sürüm) | proje: claude/ikarus_quant_v4_7.pine | Teoman'ın grafiğinde ekli |
| M3 Değer Bandı (Zippo'nun sade "IKARUS" tablosu, deneme) | proje: claude/m3_deger_bandi.pine | Seviyeler çözülmedi (bkz. 5) |
| Python motoru | GitHub Teomanbasar/ikarus-motor (private) | çalışıyor |
| Uygulama (PWA) | GitHub Teomanbasar/ikarus-app (Pages) — https://teomanbasar.github.io/ikarus-app/ | çalışıyor, sw.js önbellek adı ikarus-v4 |
| Telegram botu | motor içinde ikarus/bildirim.py, telegram_dinle.py | çalışıyor |
| Temel analiz (F-skoru) | ikarus/temel.py, temel_bt.py; uygulamada hisse kartı | çalışıyor |

Yeni konuşmada depolar `add_repo` ile eklenir (owner Teomanbasar; ikarus-motor ve ikarus-app, push erişimi). Claude Actions loglarını göremez → çıktılar depoya commit edilir.

## 2. IKARUS çekirdeği (v4.7, Zippo IKARUS CORE tablosu)
- Ayrıntı: claude/m3_cozum_1026.md, makro_kurali_1101.md, bekleyenler.md, python_motor_1031.md.
- adjC = kapanış / M3 (ECONOMICS:TRM3). Dip/Tepe = 200 barın en düşük/en yüksek adjC × güncel M3. Percentile = percentrank(adjC, 200). MTF = haftalık Percentile. Stop: haftalıkta 55 hafta dip, günlükte Dip. Memory = son 15 barda Percentile ≤ 20 sayısı ×10/15.
- Makro (v4.7): M3 son 15 barda arttıysa GENİŞLEME (7), aynıysa NÖTR (5), azaldıysa DARALMA (3).
- Kesin: Percentile, Value, Dip, Tepe, Stop, MTF, Hacim, Toplam. Yakın: Recovery, Memory, Kalite, Makro. Çözülmedi: RS, Compression, sinyal/faz kuralı, 5 yıldız eşiği.
- Zippo'nun ana tablosu temettü düzeltmesi AÇIK veriyle tutuyor (16 tablonun 15'i kuruşu kuruşuna).
- Backtest (claude/backtest_1101.md): IKARUS tek başına sağlam bir üstünlük göstermedi.

## 3. M3 verisi (önemli, 4-6 Kas'ta değişti)
- Kaynak: data/m3.csv (TradingView geçmişi) + EVDS haftalık "3.M3". EVDS anahtarı GitHub secret EVDS_KEY.
- DÜZELTME (4 Kas): TradingView TRM3 ay damgasına o ayın YAYIMLANMIŞ EN SON haftasını yazıyor (ayın son cumasını beklemiyor). Motor artık böyle (data._evds_m3). Önceden Ekim değeri eksik kaldığı için makro NÖTR çıkıyor ve sinyaller TradingView'den farklı oluyordu (GARAN).
- m3() son 3 ayı EVDS'ten yeniler. data/m3.csv Eylül = 32.632037 trilyon (TradingView ile aynı).
- TradingView M3 geçmişini sonradan revize ediyor (Ara 2025 −%0.24; Ekim 33.109 → 33.044). Ay damgası X, X+1'in başından itibaren geçerli.

## 4. Bulut ve otomasyon (ikarus-motor/.github/workflows)
- tarama.yml: hafta içi 18:43 + yedekler 19:17/20:11/21:37 TR; push(tetik.txt), workflow_dispatch. Adımlar: tarama → sonuclar.json ikarus-app'e push → Telegram → data/son_bildirim.log commit.
- GitHub zamanlayıcısı saatlerce gecikebiliyor (3-6 Kas gece 00-03'te çalıştı). Bu yüzden:
  - bildirim.py: "bugün mü" yerine veri günü daha önce bildirildi mi (data/son_bildirilen.txt). Aynı gün iki kez göndermez; elle tetikte (--zorla) her zaman gönderir.
  - data.tv_tamamla: Yahoo son seansı vermezse TradingView tarayıcısından ekler (seans içinde yapmaz).
- telegram.yml: hafta içi 18:00-23:45 TR 15 dakikada bir; bota "güncelle"/"tara" yazılınca tarama.yml'yi workflow_dispatch ile başlatır (Actions dakika kotası için akşamla sınırlı).
- temel.yml: cumartesi 06:23 TR tüm BIST temel veri; temel/istek.txt push'uyla elle ("hesapla", "gecmis", "bt", "ornek H...").
- arama.yml: arama/istek.json push'uyla tablo arama/veri çıkarma ("aralik", "ham_veri", "m3_kontrol", "tv_test", "veri").
- Secrets: APP_TOKEN, EVDS_KEY, TELEGRAM_TOKEN (TELEGRAM_CHAT gerekmiyor, sohbet dosyadan). Variables: APP_REPO, APP_URL. Telegram sohbet: data/telegram_chat.txt.
- Elle tarama: tetik.txt'yi değiştirip push ("sessiz" yazılırsa Telegram atlanır).

## 5. M3 Değer Bandı / Zippo'nun sade "IKARUS" tablosu (açık iş)
Ayrıntı: claude/ikarus_sade_tablo_1103.md.
- Örnekler: EREGL (3 Kas 17:35): Pahalı 99.00 / Adil 64.01 / Ucuzluk 29.02 / puan 1.9 / AL 3/3. SISE (5 Kas 19:22, "1A" aylık grafik): 189.64 / 110.68 / 31.72 / 1.4 / AL 3/3.
- KESİN: Adil = (Pahalı + Ucuzluk)/2. Puan = (fiyat − Ucuzluk)/(Pahalı − Ucuzluk)×100. Tablo fiyatı = AYLIK Heikin Ashi kapanışı = ayın (açılış+yüksek+düşük+kapanış)/4 (SISE 33.885 → +460/+227/−6 birebir). Veri temettü düzeltmesiz.
- ÇÖZÜLMEDİ: Ucuzluk ve Pahalı. EREGL'de günlük kapanış/M3 tüm geçmiş dibi 29.0214 tuttu ama SISE'de aynı formül 29.4 veriyor → büyük ihtimalle tesadüf. Günlük/haftalık/aylık, normal/HA, kapanış/fitil, M3 gecikme 0/1/2, 60-300 ay ve tüm geçmiş pencereleri, yüzdelikler, ortalama±σ, Fibonacci, defter değeri denendi: iki hisseyi birlikte tutan formül yok. SISE'de en yakın: aylık fitil dip/tepe, ikisi de %0.12 eksik (M3 sürüm farkı olabilir) ama EREGL'de tutmuyor.
- Sonraki adım: yeni sade tablo gelince AYNI GÜN TradingView'in TRM3 değerini kaydet; pahalı bölgede ya da kısa geçmişli hisse en öğretici olur. Kademe eşikleri tahmin.
- Gösterge: günlük grafikte kullanılmalı (aylıkta tüm geçmiş uçları 1990'lardan geliyor; SISE'de Pahalı 745 çıktı). Son sürüm (6 Kas) TradingView'de henüz derlenmedi.
- TradingView verisini çekme yöntemi (Claude tarayıcısı, Teoman'ın oturumu): `TradingViewApi.activeChart()`, `setSymbol`, `setResolution`, `chartModel().mainSeries().requestMoreData()`, `bars().each`, adj = `mainSeries().properties().childs().dividendsAdjustment`. Sonra eski haline döndür.

## 6. Temel analiz (F-skoru)
Ayrıntı: claude/temel_analiz_1102.md (sonuçlar dahil).
- Kaynak: İş Yatırım MaliTablo (yalnız GitHub Actions'tan). Sanayi 9 madde (Piotroski uyarlaması, M3'e göre reel), banka 5 madde.
- Backtest (2021-2026, 565 hisse): F-skoru kaybedeni eliyor. Ucuz + F≥7 medyan −6.9 / ucuz + F≤4 −9.7 (6 yılın 6'sında). En güçlü kalem: özkaynağın M3'ten hızlı büyümesi. Bankalarda puan işe yaramıyor. IKARUS sinyali + F≥7 umut verici ama n=74.
- Zippo'nun sözleri: "Temel analize bakmadan hisse alınmamalı… özvarlıklar, özsermaye artışı, borçlar, kârlılık artışları" (2 Kas DM). Telegram (5-6 Kas, LILAK): "Adil değerini bilmiyoruz ki" (kısa geçmiş), "Yeni bilanço… çok iyiyse, özsermaye büyümüşse alınabilir listeye".
- SISE 2026/9 bilançosu 5 Kas'ta açıklandı; kartta hâlâ 2026/06 (cumartesi otomatik güncellenecek).

## 7. Bekleyen işler (öncelik sırası önerisi)
1. Zippo'dan yeni sade tablo gelirse M3 Değer Bandı seviyelerini çöz.
2. Uygulamaya "ucuz + temeli güçlü (F≥7)" sekmesi; sinyal listesinde F≤4 uyarı işareti (Teoman onay vermedi, önerildi).
3. Canlı takip defteri: her gün sinyal/ucuz+güçlü listeleri kaydet, 1-3-6 ay sonucu yaz (önerildi, onay bekliyor). Teoman'ın planı: bir süre elle dene, temeli iyi şirketlere yatırım.
4. bekleyenler.md maddeleri: makro ok kuralı, faz motoru, 5 yıldız eşiği, Vel formülleri, TRM3 kanalı.
5. Sonra: nitel temel analiz için yapay zekâ özet botu (KAP/faaliyet raporu); Ecloud/Traffic göstergeleri.
6. Teoman temel analiz sisteminin kodunu isteyebilir (Python temel.py hazır; Pine sürümü istenirse yazılabilir).

## 8. Proje dokümanları (okuma sırası)
1. Bu not. 2. bekleyenler.md 3. temel_analiz_1102.md 4. ikarus_sade_tablo_1103.md 5. bulut_uygulama_1031.md + python_motor_1031.md 6. m3_cozum_1026.md, makro_kurali_1101.md 7. backtest_1101.md 8. zippo_tablolar.json (Zippo tabloları verisi).
