"""Canli kayit defteri (16 Kas 2026). Sitenin karar kutusunun her AL kararini, geriye donup duzeltilemeyecek
sekilde kaydeder ve sanal olarak takip eder. Gercek kanit budur: kural bugun sabitlendi, sonuc gelecekte olusur.

Giris (iki kural icin ortak): kutu AL (✓ ya da ✓✓) olan ve defterde acik olmayan hisse ERTESI veri gununun kapanisindan.
Cikis kurallari YAN YANA izlenir (18 Kas, Teoman: "fazla kural isi bozmasin; canli gorelim"):
  yeni : kar al Percentile >= 90, takip eden stop (girisin %20 ustune cikinca, en yuksek kapanisin %15 altinda), bilanco bozuldu
  eski : kar al Percentile >= 80, bilanco bozuldu
Getiri temettu/bolunme duzeltmeli kapanislarla; BIST100'e gore fazla getiri de tutulur. Maliyet %0.2 + %0.2.
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
KURALLAR = {"yeni": {"karal": 90, "iz": (0.20, 0.15)}, "eski": {"karal": 80, "iz": None}}


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


def _seri(px, t):
    df = px.get(t)
    return None if df is None else df["close"].sort_index()


def _fiyat(px, t, gun):
    s = _seri(px, t)
    if s is None:
        return None
    s = s[s.index <= pd.Timestamp(gun)]
    return float(s.iloc[-1]) if len(s) else None


def iz_durum(px, t, giris, gun, iz):
    """Takip eden stop: (aktif mi, tepe, stop seviyesi, tetiklendi mi) -- duzeltmeli kapanislarla, giris gunu dahil."""
    s = _seri(px, t)
    if s is None or not iz:
        return False, None, None, False
    s = s[(s.index >= pd.Timestamp(giris)) & (s.index <= pd.Timestamp(gun))]
    if not len(s):
        return False, None, None, False
    g0, tepe, son = float(s.iloc[0]), float(s.max()), float(s.iloc[-1])
    aktif = tepe >= g0 * (1 + iz[0])
    seviye = tepe * (1 - iz[1])
    return aktif, tepe, seviye, aktif and son <= seviye


def _bos_kural():
    return {"acik": {}, "kapali": [], "bekleyen_sat": {}}


def guncelle(stocks: list, px: dict, xu: pd.Series) -> dict:
    gunler = Counter((s.get("D") or {}).get("tarih") for s in stocks)
    gunler.pop(None, None)
    if not gunler:
        return {}
    V = gunler.most_common(1)[0][0]
    try:
        K = json.loads(F.read_text(encoding="utf-8"))
    except Exception:
        K = {"baslangic": BASLANGIC, "son_gun": "", "bekleyen_al": []}
    if "kural" not in K:   # 18 Kas: tek kurallik eski defterden iki kurala gecis (acik kayitlar ikisine de kopyalanir)
        eski = {"acik": K.pop("acik", {}), "kapali": K.pop("kapali", []), "bekleyen_sat": K.pop("bekleyen_sat", {})}
        K["kural"] = {"eski": eski, "yeni": json.loads(json.dumps(eski))}
    for ad in KURALLAR:
        K["kural"].setdefault(ad, _bos_kural())
    H = {s["t"]: s for s in stocks}
    xv = lambda g: float(xu[xu.index <= pd.Timestamp(g)].iloc[-1])
    simdi = pd.Timestamp.now(tz="Europe/Istanbul")
    seans_acik = V == simdi.strftime("%Y-%m-%d") and (simdi.hour, simdi.minute) < (18, 10)
    if seans_acik:
        print(f"defter: {V} seansi bitmedi, islenmedi")
    if V > K["son_gun"] and V >= K["baslangic"] and not seans_acik:
        for ad, kr in KURALLAR.items():
            Kk = K["kural"][ad]
            # 1) dunku kararlari bugunun kapanisindan uygula
            for t, neden in list(Kk["bekleyen_sat"].items()):
                a = Kk["acik"].pop(t, None)
                if a:
                    Kk["kapali"].append({**a, "cikis": V, "neden": neden})
            for t, durum in K["bekleyen_al"]:
                if t not in Kk["acik"] and _fiyat(px, t, V):
                    Kk["acik"][t] = {"t": t, "giris": V, "karar": durum}
            Kk["bekleyen_sat"] = {}
            # 2) bugunun kapanisina gore yarin icin satis karari
            for t, a in Kk["acik"].items():
                s = H.get(t)
                if not s:
                    continue
                v = (s.get("temel") or {}).get("v3") or {}
                if (s.get("D") or {}).get("percentile", 0) >= kr["karal"]:
                    Kk["bekleyen_sat"][t] = "pahali (kar al)"
                elif not v or (v.get("sira") or 0) < 0.6 or "Kotu bilanco surprizi" in (v.get("etiketler") or []):
                    Kk["bekleyen_sat"][t] = "bilanco bozuldu"
                elif iz_durum(px, t, a["giris"], V, kr["iz"])[3]:
                    Kk["bekleyen_sat"][t] = "takip eden stop"
        acik_hepsi = set().union(*[set(K["kural"][a]["acik"]) for a in KURALLAR])
        K["bekleyen_al"] = [[s["t"], kutu(s)] for s in stocks if kutu(s).startswith("AL") and s["t"] not in acik_hepsi]
        K["son_gun"] = V

    # 3) getirileri (duzeltmeli fiyatla) yeniden hesapla
    def getiri(x, bit):
        g0, g1 = _fiyat(px, x["t"], x["giris"]), _fiyat(px, x["t"], bit)
        if not g0 or not g1:
            return None, None
        r = 100 * (g1 * (1 - MAL) / (g0 * (1 + MAL)) - 1)
        return round(r, 2), round(r - 100 * (xv(bit) / xv(x["giris"]) - 1), 2)
    ozet = {"baslangic": K["baslangic"], "son_gun": K["son_gun"], "bekleyen_al": K["bekleyen_al"], "kurallar": {}}
    for ad, kr in KURALLAR.items():
        Kk = K["kural"][ad]
        for x in Kk["acik"].values():
            x["getiri"], x["fazla"] = getiri(x, K["son_gun"] or V)
            x["kutu_bugun"] = kutu(H[x["t"]]) if x["t"] in H else None
            if kr["iz"]:
                ak, tepe, sev, _ = iz_durum(px, x["t"], x["giris"], K["son_gun"] or V, kr["iz"])
                x["stop_aktif"], x["stop"] = ak, (round(sev, 2) if sev else None)
                g0 = _fiyat(px, x["t"], x["giris"])
                x["stop_aktiflesme"] = round(g0 * (1 + kr["iz"][0]), 2) if g0 else None
        for x in Kk["kapali"]:
            x["getiri"], x["fazla"] = getiri(x, x["cikis"])
        hepsi = [x for x in list(Kk["acik"].values()) + Kk["kapali"] if x.get("getiri") is not None]
        ozet["kurallar"][ad] = {
            "acik": len(Kk["acik"]), "kapali": len(Kk["kapali"]),
            "ort_getiri": round(sum(x["getiri"] for x in hepsi) / len(hepsi), 2) if hepsi else None,
            "ort_fazla": round(sum(x["fazla"] for x in hepsi) / len(hepsi), 2) if hepsi else None,
            "kazanan": round(100 * sum(x["fazla"] > 0 for x in hepsi) / len(hepsi)) if hepsi else None,
            "liste_acik": sorted(Kk["acik"].values(), key=lambda x: x["giris"]),
            "liste_kapali": Kk["kapali"][-50:], "bekleyen_sat": Kk["bekleyen_sat"]}
    F.write_text(json.dumps(K, ensure_ascii=False, indent=1), encoding="utf-8")
    # site uyumu: ust duzey alanlar = gecerli (yeni) kural
    y = ozet["kurallar"]["yeni"]
    ozet.update({k: y[k] for k in ("acik", "kapali", "ort_getiri", "ort_fazla", "kazanan", "liste_acik", "liste_kapali", "bekleyen_sat")})
    print(f"defter: {K['son_gun']} | yeni acik {y['acik']} kapali {y['kapali']} | eski acik {ozet['kurallar']['eski']['acik']} | yarin alinacak {len(K['bekleyen_al'])}")
    return ozet
