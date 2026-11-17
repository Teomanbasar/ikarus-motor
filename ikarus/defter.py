"""Canli kayit defteri (16 Kas 2026). Sitenin karar kutusunun her AL kararini, geriye donup duzeltilemeyecek
sekilde kaydeder ve sanal olarak takip eder. Gercek kanit budur: kural bugun sabitlendi, sonuc gelecekte olusur.

Kural (portfoy_bt ile ayni):
  - Kutu AL (✓ ya da ✓✓) olan ve defterde acik olmayan hisse, ERTESI veri gununun kapanisindan acilir.
  - Acik hisse PAHALI (Percentile >= 80) olunca ya da bilanco bozulunca (sira < %60, kotu surpriz, bilanco puani yok)
    ertesi veri gununun kapanisindan kapanir.
  - Getiri temettu/bolunme duzeltmeli kapanislarla, BIST100'e gore fazla getiri de tutulur. Maliyet %0.2 + %0.2.
Dosya: data/defter.json (motor deposu, her taramada guncellenir, git gecmisinde iz kalir).
"""
from __future__ import annotations

import json
from collections import Counter

import pandas as pd

from . import data as D

F = D.DATA / "defter.json"
MAL = 0.002
BASLANGIC = "2026-11-16"


def kutu(s: dict) -> str:
    """index.html kutu() ile ayni durum adlari."""
    r = s.get("D") or {}
    v = (s.get("temel") or {}).get("v3")
    fz = s.get("faz") or {}
    fi = s.get("fiyat_ivme") or {}
    if not v or v.get("sira") is None:
        return "BILANCO PUANI YOK"
    et = v.get("etiketler") or []
    if v.get("sira", 0) < 0.6 or "Kotu bilanco surprizi" in et or "Sert dusus" in et:
        return "UZAK DUR"
    if v["sira"] < 0.8:
        return "ORTA"
    p = r.get("percentile")
    if p is None:
        return "?"
    if p >= 80:
        return "PAHALI"
    if (fi.get("o20_x") or 0) > 10 or (fi.get("o5") or 0) > 15:
        return "BEKLE kacti"
    if p > 20:
        return "BEKLE ucuz degil"
    tik = int(bool((fz.get("normal") or {}).get("alim"))) + int(bool((fz.get("ha") or {}).get("alim")))
    return "AL ✓✓" if tik == 2 else ("AL ✓" if tik == 1 else "BEKLE teknik")


def _fiyat(px, t, gun):
    df = px.get(t)
    if df is None:
        return None
    s = df["close"]
    s = s[s.index <= pd.Timestamp(gun)]
    return float(s.iloc[-1]) if len(s) else None


def guncelle(stocks: list, px: dict, xu: pd.Series) -> dict:
    gunler = Counter((s.get("D") or {}).get("tarih") for s in stocks)
    gunler.pop(None, None)
    if not gunler:
        return {}
    V = gunler.most_common(1)[0][0]
    try:
        K = json.loads(F.read_text(encoding="utf-8"))
    except Exception:
        K = {"baslangic": BASLANGIC, "son_gun": "", "acik": {}, "kapali": [], "bekleyen_al": [], "bekleyen_sat": {}}
    H = {s["t"]: s for s in stocks}
    xv = lambda g: float(xu[xu.index <= pd.Timestamp(g)].iloc[-1])
    # Seans bitmeden (TR 18:10 oncesi) bugunun barini isleme: giris/cikis yalniz kesin kapanis fiyatiyla
    simdi = pd.Timestamp.now(tz="Europe/Istanbul")
    seans_acik = V == simdi.strftime("%Y-%m-%d") and (simdi.hour, simdi.minute) < (18, 10)
    if seans_acik:
        print(f"defter: {V} seansi bitmedi, islenmedi")
    if V > K["son_gun"] and V >= K["baslangic"] and not seans_acik:
        # 1) dunku kararlari bugunun kapanisindan uygula
        for t, neden in list(K["bekleyen_sat"].items()):
            a = K["acik"].pop(t, None)
            if a:
                K["kapali"].append({**a, "cikis": V, "neden": neden})
        for t, durum in K["bekleyen_al"]:
            if t not in K["acik"] and _fiyat(px, t, V):
                K["acik"][t] = {"t": t, "giris": V, "karar": durum}
        K["bekleyen_al"], K["bekleyen_sat"] = [], {}
        # 2) bugunun kapanisina gore yarin icin karar
        for t in K["acik"]:
            s = H.get(t)
            if not s:
                continue
            k = kutu(s)
            v = (s.get("temel") or {}).get("v3") or {}
            if (s.get("D") or {}).get("percentile", 0) >= 80:
                K["bekleyen_sat"][t] = "pahali (kar al)"
            elif not v or (v.get("sira") or 0) < 0.6 or "Kotu bilanco surprizi" in (v.get("etiketler") or []):
                K["bekleyen_sat"][t] = "bilanco bozuldu"
        for s in stocks:
            k = kutu(s)
            if k.startswith("AL") and s["t"] not in K["acik"]:
                K["bekleyen_al"].append([s["t"], k])
        K["son_gun"] = V
    # 3) getirileri (duzeltmeli fiyatla) yeniden hesapla
    def getiri(x, bit):
        g0, g1 = _fiyat(px, x["t"], x["giris"]), _fiyat(px, x["t"], bit)
        if not g0 or not g1:
            return None, None
        r = 100 * (g1 * (1 - MAL) / (g0 * (1 + MAL)) - 1)
        return round(r, 2), round(r - 100 * (xv(bit) / xv(x["giris"]) - 1), 2)
    for x in K["acik"].values():
        x["getiri"], x["fazla"] = getiri(x, V)
        x["kutu_bugun"] = kutu(H[x["t"]]) if x["t"] in H else None
    for x in K["kapali"]:
        x["getiri"], x["fazla"] = getiri(x, x["cikis"])
    F.write_text(json.dumps(K, ensure_ascii=False, indent=1), encoding="utf-8")
    hepsi = [x for x in list(K["acik"].values()) + K["kapali"] if x.get("getiri") is not None]
    ozet = {"baslangic": K["baslangic"], "son_gun": K["son_gun"], "acik": len(K["acik"]), "kapali": len(K["kapali"]),
            "ort_getiri": round(sum(x["getiri"] for x in hepsi) / len(hepsi), 2) if hepsi else None,
            "ort_fazla": round(sum(x["fazla"] for x in hepsi) / len(hepsi), 2) if hepsi else None,
            "kazanan": round(100 * sum(x["fazla"] > 0 for x in hepsi) / len(hepsi)) if hepsi else None,
            "liste_acik": sorted(K["acik"].values(), key=lambda x: x["giris"]),
            "liste_kapali": K["kapali"][-50:], "bekleyen_al": K["bekleyen_al"], "bekleyen_sat": K["bekleyen_sat"]}
    print(f"defter: {V} | acik {ozet['acik']} kapali {ozet['kapali']} | yarin alinacak {len(K['bekleyen_al'])}")
    return ozet
