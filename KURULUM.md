# IKARUS – bulut kurulumu (bir kez, ~20 dakika)

Sonuç: her hafta içi 18:40'ta tarama bulutta kendiliğinden çalışır, uygulama güncellenir,
Telegram'a özet gelir. Bilgisayarın açık olması gerekmez.

İki depo (repo) var:
- **ikarus-motor** (GİZLİ): formüller ve tarama. Kimse göremez.
- **ikarus-app** (AÇIK): sadece uygulama sayfası ve günlük sonuç dosyası. Adresi: `https://Teomanbasar.github.io/ikarus-app/`

## 1. GitHub
1. github.com'da hesap aç.
2. İki boş depo oluştur: `ikarus-motor` (**Private**) ve `ikarus-app` (**Public**).
3. Dosyaları yükle (ya da GitHub'ı Claude'a bağla, yüklemeyi Claude yapar):
   `motor` klasörünün içi → ikarus-motor, `app` klasörünün içi → ikarus-app.
4. ikarus-app → Settings → Pages → Source: "Deploy from a branch", Branch: `main`, klasör `/ (root)` → Save.

## 2. Motorun uygulamaya yazabilmesi için anahtar
1. GitHub → sağ üst profil → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token.
2. Repository access: "Only select repositories" → `ikarus-app`. Permissions → Contents: **Read and write**. Süre: 1 yıl.
3. Çıkan anahtarı kopyala.

## 3. ikarus-motor ayarları (Settings → Secrets and variables → Actions)
**Secrets** (gizli):
| Ad | Değer |
|---|---|
| `APP_TOKEN` | 2. adımdaki anahtar |
| `EVDS_KEY` | evds3.tcmb.gov.tr → üye ol → profil → API anahtarı |
| `TELEGRAM_TOKEN` | Telegram'da @BotFather → /newbot → verdiği anahtar |
| `TELEGRAM_CHAT` | Aşağıdaki 4. adım |

**Variables** (açık):
| Ad | Değer |
|---|---|
| `APP_REPO` | `Teomanbasar/ikarus-app` |
| `APP_URL` | `https://Teomanbasar.github.io/ikarus-app/` |

## 4. Telegram sohbet numarası
1. Telegram'da botunu aç, "merhaba" yaz.
2. Tarayıcıda aç: `https://api.telegram.org/bot<TELEGRAM_TOKEN>/getUpdates`
3. `"chat":{"id":123456789` kısmındaki sayı → `TELEGRAM_CHAT`.

## 5. İlk deneme
ikarus-motor → Actions → "IKARUS gunluk tarama" → **Run workflow**. 3–5 dakika sonra:
- uygulama adresinde hisseler görünür,
- Telegram'a özet gelir (borsa açık günün verisiyse).

Sonrası otomatik. Telefonda uygulama adresini aç → Paylaş/menü → **Ana ekrana ekle**.
