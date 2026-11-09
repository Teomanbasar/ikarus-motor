"""Holding net aktif deger (NAD) iskontosu, gunluk.

data/nad.json: her holding icin referans tarihteki istirak katkilari (mn TL) ve sabit kalemler.
Gunluk halka acik katki = referans katki x (istirak fiyati_t / fiyati_ref). Fiyatlar temettu duzeltmeli
oldugu icin oranlar temettuyu de icerir; holding fiyati icin de ayni yapildigindan etkisi buyuk olcude dengelenir.
Gecmise dogru bugunku bilesim kullanilir: pay degisikliklerinden once (or. 2026 Tupras pay satisi)
seri yaklasiktir; bu yuzden yuzdelik hesap varsayilan olarak son 3 yil.

Cikti: temel/nad.json (uygulama icin ozet), temel/nad_seri.csv (haftalik seri), temel/nad_sonuc.txt
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import data as D

R = D.ROOT / "temel"


def seri(h, cfg, px):
    ph = px[h]["close"]
    ref = pd.Timestamp(cfg["ref_tarih"])
    def oran(s):
        s = s.sort_index()
        r = s[s.index <= ref]
        return s / float(r.iloc[-1]) if len(r) else None
    idx = ph.index
    nad = pd.Series(float(sum(cfg["sabit"].values())), index=idx)
    eksik = []
    for t, k in cfg["halka_acik"].items():
        if t not in px:
            eksik.append(t); nad += k; continue   # fiyat yoksa referans degerde sabit tut
        o = oran(px[t]["close"])
        nad += k * o.reindex(idx).ffill().fillna(1.0)
    mcap = cfg["piyasa_degeri_ref"] * oran(ph)
    return pd.DataFrame({"nad": nad, "pd": mcap, "iskonto": mcap / nad - 1}), eksik


def main():
    cfg = json.loads((D.DATA / "nad.json").read_text(encoding="utf-8"))
    hs = [h for h in cfg if not h.startswith("_")]
    tick = sorted(set(hs) | {t for h in hs for t in cfg[h]["halka_acik"]})
    px = D.prices(tick)
    xu = D.xu100()
    ozet, L, tum = {}, [], []
    for h in hs:
        if h not in px:
            L.append(f"{h}: fiyat yok"); continue
        S, eksik = seri(h, cfg[h], px)
        S = S[S.index >= "2021-01-01"].dropna()
        son = S.iloc[-1]
        p3 = S[S.index >= S.index[-1] - pd.DateOffset(years=3)]["iskonto"]
        p1 = S[S.index >= S.index[-1] - pd.DateOffset(years=1)]["iskonto"]
        isk = float(son["iskonto"])
        yuz3 = float(100 * (p3 < isk).mean())     # dusuk = tarihsel olarak derin iskonto
        yuz1 = float(100 * (p1 < isk).mean())
        d20 = float(isk - S["iskonto"].iloc[-21]) if len(S) > 21 else None
        d60 = float(isk - S["iskonto"].iloc[-61]) if len(S) > 61 else None
        ort3 = float(p3.mean())
        if yuz3 <= 20 and (d20 or 0) > 0.02:
            durum = "DERIN ISKONTO, KAPANIYOR"
        elif yuz3 <= 20:
            durum = "DERIN ISKONTO"
        elif yuz3 >= 80:
            durum = "ISKONTO DAR (pahali)"
        else:
            durum = "NORMAL"
        ozet[h] = {"tarih": f"{S.index[-1]:%Y-%m-%d}", "nad_mn": round(float(son["nad"])), "piyasa_degeri_mn": round(float(son["pd"])),
                   "iskonto": round(isk, 4), "ort_3y": round(ort3, 4), "uzun_vade": cfg[h].get("uzun_vade_iskonto"),
                   "yuzdelik_3y": round(yuz3, 1), "yuzdelik_1y": round(yuz1, 1),
                   "degisim_20g": None if d20 is None else round(d20, 4), "degisim_60g": None if d60 is None else round(d60, 4),
                   "durum": durum, "kaynak": cfg[h]["kaynak"], "fiyatsiz": eksik,
                   "teorik_fiyat_ort3y": round(float(px[h]["close"].iloc[-1] * (1 + ort3) / (1 + isk)), 2)}
        L.append(f"== {h}  {S.index[-1]:%Y-%m-%d}: NAD {son['nad']:,.0f} mn TL | piyasa degeri {son['pd']:,.0f} | iskonto %{100 * isk:.1f} "
                 f"| 3y ort %{100 * ort3:.1f} | 3y yuzdelik {yuz3:.0f} | 20g degisim {100 * (d20 or 0):+.1f} puan | {durum}"
                 + (f" | fiyati olmayanlar {eksik}" if eksik else ""))
        # yaklasik test: iskonto 3y yuzdeligi -> sonraki 63 gun holding getirisi (BIST100'e gore)
        c = px[h]["close"].reindex(S.index)
        x = xu.reindex(S.index).ffill()
        f63 = 100 * (c.shift(-63) / c - x.shift(-63) / x)
        roll = S["iskonto"].rolling(756, min_periods=250).apply(lambda a: 100 * (a[:-1] < a[-1]).mean(), raw=True)
        d20s = S["iskonto"].diff(20)
        T = pd.DataFrame({"y": roll, "d20": d20s, "f63": f63}).dropna()
        if len(T) > 200:
            for ad, m in [("yuzdelik <= 20 (derin)", T["y"] <= 20), ("yuzdelik 20-80", T["y"].between(20, 80, inclusive="neither")),
                          ("yuzdelik >= 80 (dar)", T["y"] >= 80), ("derin + 20g kapaniyor (>2 puan)", (T["y"] <= 20) & (T["d20"] > 0.02)),
                          ("derin + 20g aciliyor", (T["y"] <= 20) & (T["d20"] < -0.02))]:
                X = T[m]["f63"]
                L.append(f"   {ad:34s} gun {len(X):4d} | sonraki 63g BIST100'e gore ort {X.mean():+5.1f} medyan {X.median():+5.1f} kazanma %{100 * (X > 0).mean():3.0f}")
        w = S.resample("W-FRI").last().assign(hisse=h)
        tum.append(w)
    L.append("\nNot: gecmis seri bugunku istirak paylariyla hesaplandi (yaklasik). Test gunleri birbiriyle ortusuyor (63 gunluk pencereler); "
             "bagimsiz gozlem sayisi gun sayisindan cok daha az, sonuclari kaba isaret olarak oku.")
    (R / "nad.json").write_text(json.dumps({"olusturma": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "holdingler": ozet},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
    if tum:
        pd.concat(tum).round(4).to_csv(R / "nad_seri.csv")
    txt = "\n".join(L)
    (R / "nad_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
