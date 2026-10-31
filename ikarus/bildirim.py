"""Telegram bildirimi: tarama sonucundan gunluk ozet mesaji gonderir.

Ayarlar (ortam degiskeni ya da ayarlar.txt):
  telegram_token  : @BotFather'in verdigi bot anahtari
  telegram_chat   : mesajin gidecegi sohbet numarasi (python -m ikarus.bildirim --chat ile bulunur)
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
    baslik = "Günlük" if tf == "D" else "Haftalık"
    lines = [f"<b>IKARUS · {baslik} · {date.fromisoformat(p['xu100_tarih']):%d.%m.%Y}</b>",
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


def main(argv):
    token, chat = D.ayar("telegram_token"), D.ayar("telegram_chat")
    if not token:
        print("telegram_token yok, bildirim atlandi.")
        return
    if "--chat" in argv:
        r = requests.get(API.format(token, "getUpdates"), timeout=30).json()
        ids = {(u["message"]["chat"]["id"], u["message"]["chat"].get("first_name", ""))
               for u in r.get("result", []) if "message" in u}
        print("Sohbetler:", ids or "yok (once bota Telegram'dan bir mesaj yaz)")
        return
    if not chat:
        print("telegram_chat yok, bildirim atlandi.")
        return
    if "--test" in argv:
        _send(token, chat, "IKARUS bildirimleri çalışıyor ✅")
        return
    res = json.loads((D.ROOT / "cikti" / "sonuclar.json").read_text(encoding="utf-8"))
    bugun = date.today().isoformat()
    if res["piyasa"]["xu100_tarih"] != bugun and "--zorla" not in argv:
        print(f"Son veri {res['piyasa']['xu100_tarih']}, bugun {bugun}: borsa kapali ya da veri gelmedi, bildirim yok.")
        return
    _send(token, chat, mesaj(res, "D"))
    if date.today().weekday() == 4:  # cuma: haftalik ozet de
        _send(token, chat, mesaj(res, "W"))
    print("Telegram mesaji gonderildi.")


if __name__ == "__main__":
    main(sys.argv[1:])
