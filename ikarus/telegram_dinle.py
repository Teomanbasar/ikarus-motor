"""Telegram'dan komut dinler: bota "guncelle" (ya da /guncelle, tara, /tara) yazilinca taramayi baslatir.
GitHub Actions'ta birkac dakikada bir calisir (telegram.yml). Yalniz kayitli sohbetten gelen mesajlar dikkate alinir.
Cikis: tarama gerekiyorsa GITHUB_OUTPUT'a tara=1 yazar.
"""
from __future__ import annotations

import os
import time

import requests

from . import data as D
from .bildirim import API, _send
from . import elde

KOMUT = ("guncelle", "güncelle", "tara", "/guncelle", "/tara", "/start")


def main():
    token = D.ayar("telegram_token")
    f = D.DATA / "telegram_chat.txt"
    chat = D.ayar("telegram_chat") or (f.read_text(encoding="utf-8").strip() if f.exists() else None)
    if not token or not chat:
        print("token/chat yok"); return
    of = D.DATA / "telegram_offset.txt"
    offset = int(of.read_text().strip()) if of.exists() else 0
    r = requests.get(API.format(token, "getUpdates"), params={"offset": offset, "timeout": 0}, timeout=30).json()
    tara = False
    elde_degisti = False
    son = offset
    for u in r.get("result", []):
        son = max(son, u["update_id"] + 1)
        m = u.get("message") or {}
        if str(m.get("chat", {}).get("id")) != str(chat):
            continue
        if time.time() - m.get("date", 0) > 24 * 3600:   # cok eski mesaj (Telegram da 24 saat saklar)
            continue
        ham = (m.get("text") or "").strip()
        txt = ham.lower()
        once = elde.F.read_text(encoding="utf-8") if elde.F.exists() else ""
        cevap = elde.komut(ham)
        if cevap:
            _send(token, chat, cevap)
            elde_degisti |= (elde.F.read_text(encoding="utf-8") if elde.F.exists() else "") != once
            continue
        if any(txt.startswith(k) for k in KOMUT):
            tara = True
    if son != offset:
        of.write_text(str(son) + "\n")
    go = os.environ.get("GITHUB_OUTPUT")
    if elde_degisti and go:
        with open(go, "a") as g:
            g.write("elde=1\n")
    if tara:
        _send(token, chat, "⏳ Tarama başlatıldı, birkaç dakika içinde özet gelecek.")
        print("komut alindi: tarama")
        go = os.environ.get("GITHUB_OUTPUT")
        if go:
            with open(go, "a") as g:
                g.write("tara=1\n")
    else:
        print("komut yok")


if __name__ == "__main__":
    main()
