"""Telegram bildirimi: tarama sonucundan gunluk ozet mesaji gonderir.

Ayarlar (ortam degiskeni ya da ayarlar.txt):
  telegram_token  : @BotFather'in verdigi bot anahtari
  telegram_chat   : sohbet numarasi; verilmezse bota son yazan kisi otomatik bulunur ve data/telegram_chat.txt'ye kaydedilir
  app_url         : uygulamanin adresi (mesajin altina link olarak eklenir)
Kullanim:
  python -m ikarus.bildirim          # cikti/sonuclar.json'dan mesaj gonder
  python -m ikarus.bildirim --chat   # bota yazdiktan sonra sohbet numarasini goster
  python -m ikarus.bildirim --test   # deneme mesaji
"""
from __future__ import annotations

import html
import json
import sys
from datetime import date

import requests

from . import data as D

API = "https://api.telegram.org/bot{}/{}"


def _send(token: str, chat: str, text: str):
    r = requests.post(API.format(token, "sendMessage"), timeout=30,
                      json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True})
    if not r.ok:
        raise RuntimeError(f"Telegram hatasi {r.status_code}: {r.text[:300]}")


def _fmt(x, d=2):
    if x is None:
        return "-"
    s = f"{x:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def mesaj(res: dict, tf: str = "D") -> str | None:
    H = {s["t"]: s for s in res["hisseler"]}
    L = res["listeler"][tf]
    g = lambda t: H[t][tf]
    p = res["piyasa"]
    gun = p.get("veri_tarih") or p["xu100_tarih"]
    baslik = "Günlük" if tf == "D" else "Haftalık"
    lines = [f"<b>IKARUS · {baslik} · {date.fromisoformat(gun):%d.%m.%Y}</b>",
             f"BIST100 {_fmt(p['xu100'], 0)} ({'+' if p['xu100_degisim'] >= 0 else ''}{_fmt(p['xu100_degisim'])}%) · Makro {p['makro']}", ""]

    def satir(t, ek=""):
        r = g(t)
        return (f"<b>{t}</b> {_fmt(r['fiyat'])} · Pct {_fmt(r['percentile'], 1)} · "
                f"Toplam {_fmt(r['toplam'], 1)}{ek}")

    alin = [t for t in L["sinyal"] if g(t)["sinyal"] == "ALINABILIR"]
    yeni_alin = [t for t in alin if g(t)["yeni_sinyal"]]
    yeni_top = [t for t in L["yeni"] if g(t)["sinyal"] == "TOPLANIYOR"]
    yeni_yak = [t for t in L["yeni"] if g(t)["sinyal"] == "YAKIN"]
    stop = L["stop"]

    if yeni_alin:
        lines.append("🟦 <b>Yeni ALINABILIR</b>")
        lines += [satir(t) for t in yeni_alin[:15]]
        lines.append("")
    eski = [t for t in alin if t not in yeni_alin]
    if eski:
        lines.append(f"🟦 ALINABILIR devam: {', '.join(eski[:30])}")
        lines.append("")
    if yeni_top:
        lines.append("🔷 <b>Yeni TOPLANIYOR</b>")
        lines += [satir(t) for t in yeni_top[:15]]
        lines.append("")
    if yeni_yak:
        lines.append(f"🟧 Yeni YAKIN: {', '.join(yeni_yak[:30])}")
        lines.append("")
    if stop:
        lines.append("🔻 <b>Stop kıranlar</b>")
        lines += [f"<b>{t}</b> {_fmt(g(t)['fiyat'])} · önceki Stop'a {_fmt(g(t)['d_stop'], 1)}%" for t in stop[:15]]
        lines.append("")
    if len(lines) <= 3:
        lines.append("Bugün yeni sinyal yok.")
        lines.append("")
    n = {k: sum(1 for t in L["sinyal"] if g(t)["sinyal"] == k) for k in ("ALINABILIR", "TOPLANIYOR", "YAKIN", "DAGITIM")}
    lines.append(f"Toplam: {n['ALINABILIR']} ALINABILIR · {n['TOPLANIYOR']} TOPLANIYOR · {n['YAKIN']} YAKIN · "
                 f"{len(L['ucuz'])} ucuz hisse")
    url = D.ayar("app_url")
    if url:
        lines.append(f'<a href="{html.escape(url)}">Uygulamada aç</a>')
    lines.append("<i>Yatırım tavsiyesi değildir.</i>")
    return "\n".join(lines)[:4000]


def _chat_bul(token: str) -> str | None:
    """Bota en son yazan kisinin sohbet numarasi (getUpdates). Bulunursa data/telegram_chat.txt'ye yazar."""
    r = requests.get(API.format(token, "getUpdates"), timeout=30).json()
    msgs = [u["message"] for u in r.get("result", []) if "message" in u and u["message"]["chat"]["type"] == "private"]
    if not msgs:
        return None
    chat = str(msgs[-1]["chat"]["id"])
    (D.DATA / "telegram_chat.txt").write_text(chat + "\n", encoding="utf-8")
    return chat


def main(argv):
    token = D.ayar("telegram_token")
    if not token:
        print("telegram_token yok, bildirim atlandi.")
        return
    f = D.DATA / "telegram_chat.txt"
    chat = D.ayar("telegram_chat") or (f.read_text(encoding="utf-8").strip() if f.exists() else None)
    if "--chat" in argv or not chat:
        chat = _chat_bul(token)
        if not chat:
            print("Sohbet numarasi bulunamadi: Telegram'da bota bir mesaj yaz, sonra tekrar calistir.")
            return
        print(f"Sohbet numarasi bulundu ve kaydedildi: {chat}")
        _send(token, chat, "IKARUS bildirimleri bağlandı ✅ Her iş günü taramadan sonra özet buraya gelecek.")
    if "--test" in argv:
        _send(token, chat, "IKARUS bildirimleri çalışıyor ✅")
        return
    res = json.loads((D.ROOT / "cikti" / "sonuclar.json").read_text(encoding="utf-8"))
    # Verinin tarihi: hisselerin en yaygin son gunu (XU100 Yahoo'da bazen bir gun geride kaliyor)
    from collections import Counter
    gunler = Counter((s.get("D") or {}).get("tarih") for s in res["hisseler"])
    gunler.pop(None, None)
    veri_gun = gunler.most_common(1)[0][0] if gunler else res["piyasa"]["xu100_tarih"]
    # GitHub zamanlamasi saatlerce gecikebiliyor (gece yarisini gecince 'bugun' degisiyor).
    # Bu yuzden 'bugun mu' yerine: bu veri gunu daha once bildirildi mi?
    kayit = D.DATA / "son_bildirilen.txt"
    onceki = kayit.read_text(encoding="utf-8").strip() if kayit.exists() else ""
    if "--zorla" not in argv:
        if veri_gun <= onceki:
            print(f"Veri gunu {veri_gun} zaten bildirildi ({onceki}), tekrar yok.")
            return
        if (date.today() - date.fromisoformat(veri_gun)).days > 4:
            print(f"Veri cok eski ({veri_gun}), bildirim yok.")
            return
    res["piyasa"]["veri_tarih"] = veri_gun
    _send(token, chat, mesaj(res, "D"))
    if date.fromisoformat(veri_gun).weekday() == 4 or "--haftalik" in argv:
        _send(token, chat, mesaj(res, "W"))
    if veri_gun > onceki:
        kayit.write_text(veri_gun + "\n", encoding="utf-8")
    print("Telegram mesaji gonderildi.")


if __name__ == "__main__":
    main(sys.argv[1:])
