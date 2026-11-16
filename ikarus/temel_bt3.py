"""Temel trend testi (16 Kas 2026, Teoman: "sadece gecen yilin ayni ceyregi sikinti; 3 ayda, 6 ayda, yillikta degisim de
cok onemli").

Son 4 ceyrek toplamlari (TTM) ile mevsimsellikten arinmis 3 / 6 / 12 aylik degisimler:
  satis_g{n}  : TTM satislarin n ayda M3'e gore reel buyumesi
  favok_g{n}  : TTM FAVOK'teki degisim / TTM satis (FAVOK eksiyken de calisir; M3 ile arindirilmis)
  marj{n}     : TTM FAVOK marjinin n aydaki degisimi (puan; birimsiz, enflasyondan etkilenmez)
  roe{n}      : TTM net kar / ozkaynak oraninin n aydaki degisimi (puan)
  nakit{n}    : TTM faaliyet nakdindeki degisim / TTM satis (M3 ile arindirilmis)
  oz_g{n}     : ozkaynagin n ayda M3'e gore reel buyumesi (ceyrek sonu bilancolari)
  borc{n}     : net borc / ozkaynak oraninin n aydaki degisimi (eksi = borc azaldi)
Olaylar ve getiriler temel/bt2_olaylar.csv.gz'den (giris = varsayilan yayin gunu); fiyat indirmez, yerelde calisir.
Cikti: temel/bt3_sonuc.txt
"""
from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd

from . import data as D
from . import temel as T

R = D.ROOT / "temel"


def geri(d, ay):
    y, m = d
    m -= ay
    while m <= 0:
        m += 12; y -= 1
    return (y, m)


def ttm(tab, d, kod):
    """Son 4 ceyregin toplami, ceyreklik degerlerden (yil sonu sutunu karismasin diye)."""
    t = 0.0
    for k in range(4):
        q = T.ceyreklik(tab, geri(d, 3 * k), kod)
        if q is None:
            return None
        t += q
    return t


def trendler(tab, m3, d):
    out = {}
    S, F_, N, C = {}, {}, {}, {}
    for n in (0, 3, 6, 12):
        dd = geri(d, n)
        s = ttm(tab, dd, "3C")
        fa = ttm(tab, dd, "3DF"); am = ttm(tab, dd, "4B")
        S[n] = s
        F_[n] = None if fa is None or am is None else fa + am
        N[n] = ttm(tab, dd, "3Z")
        C[n] = ttm(tab, dd, "4C")
    oz = {n: tab.get(T._bilanco_donemi(tab, geri(d, n)), {}).get("2O") for n in (0, 3, 6, 12)}

    def nb(dd):
        v = tab.get(T._bilanco_donemi(tab, dd), {})
        if not v:
            return None
        return (v.get("2AA") or 0) + (v.get("2BA") or 0) - (v.get("1AA") or 0) - (v.get("1AB") or 0)
    for n in (3, 6, 12):
        m3r = T._m3_oran(m3, d, geri(d, n))
        if not m3r:
            continue
        if S[0] and S[n] and S[0] > 0 and S[n] > 0:
            out[f"satis_g{n}"] = S[0] / S[n] / m3r - 1
            if F_[0] is not None and F_[n] is not None:
                out[f"favok_g{n}"] = (F_[0] - F_[n] * m3r) / S[0]
                out[f"marj{n}"] = F_[0] / S[0] - F_[n] / S[n]
            if C[0] is not None and C[n] is not None:
                out[f"nakit{n}"] = (C[0] - C[n] * m3r) / S[0]
        if N[0] is not None and N[n] is not None and oz[0] and oz[n] and oz[0] > 0 and oz[n] > 0:
            out[f"roe{n}"] = N[0] / oz[0] - N[n] / oz[n]
        if oz[0] and oz[n] and oz[0] > 0 and oz[n] > 0:
            out[f"oz_g{n}"] = oz[0] / oz[n] / m3r - 1
            b0, bn = nb(d), nb(geri(d, n))
            if b0 is not None and bn is not None:
                out[f"borc{n}"] = b0 / oz[0] - bn / oz[n]
    if S[0] and S[0] > 0 and F_[0] is not None:
        out["favok_marj"] = F_[0] / S[0]
    return out


def kirp(a):
    a = a.dropna()
    if len(a) < 10:
        return np.nan
    lo, hi = a.quantile([0.05, 0.95])
    return a[(a >= lo) & (a <= hi)].mean()


def main():
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    m3 = D.m3()
    rows = []
    for h, g in G.items():
        if g["grup"] != "XI_29":
            continue
        tab = {tuple(map(int, k.split("/"))): v for k, v in g["tab"].items()}
        for d in sorted(tab):
            alt = {k: v for k, v in tab.items() if k <= d}
            r = trendler(alt, m3, d)
            if r:
                r.update({"t": h, "donem": f"{d[0]}/{d[1]:02d}"})
                rows.append(r)
    Tr = pd.DataFrame(rows)
    A = pd.read_csv(R / "bt2_olaylar.csv.gz", parse_dates=["giris"])
    A = A[A["tip"] == "sanayi"].merge(Tr, on=["t", "donem"], how="left")
    A.to_csv(R / "bt3_olaylar.csv.gz", index=False, compression="gzip")
    L = ["TEMEL TREND TESTI (16 Kas 2026): 3 / 6 / 12 aylik degisimler (son 4 ceyrek toplamlariyla, mevsimsellik yok)",
         f"Sanayi olay {len(A)}, hisse {A.t.nunique()}, giris {A.giris.min():%Y-%m}..{A.giris.max():%Y-%m}. Getiri: BIST100'e gore fazla (%).",
         "Her donemde 5 dilim (D1 en dusuk..D5 en yuksek). Sayilar kirpik ortalama. 'D5-D1 +%' = farkin pozitif oldugu donem orani.\n",
         f"{'isaret':34s} {'n':>5s} | {'21g D1..D5':^31s} {'D5-D1':>6s} {'+%':>4s} | {'63g D1..D5':^31s} {'D5-D1':>6s} {'+%':>4s}"]

    def dilim(f):
        X = A.dropna(subset=[f]).copy()
        X["q"] = X.groupby("donem")[f].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1 if len(s) >= 25 else np.nan)
        return X.dropna(subset=["q"])
    sonuc = {}

    def faktor(ad, f):
        Q = dilim(f)
        if Q.empty:
            return
        s = f"{ad:34s} {len(Q):5d} |"
        for hh in (21, 63):
            p = [kirp(Q[Q.q == q][f"a{hh}"]) for q in range(1, 6)]
            fark = Q.groupby("donem").apply(lambda g: kirp(g[g.q == 5][f"a{hh}"]) - kirp(g[g.q == 1][f"a{hh}"]), include_groups=False).dropna()
            s += " " + " ".join(f"{x:+5.1f}" for x in p) + f" {fark.mean():+6.1f} {100 * (fark > 0).mean():3.0f}% |"
            sonuc[(f, hh)] = (fark.mean(), (fark > 0).mean())
        L.append(s)
    L.append("== Su an kullanilanlar (gecen yilin ayni ceyregi)")
    for ad, f in [("Net kar surprizi (sue_nk)", "sue_nk"), ("Esas faaliyet surprizi (sue_faal)", "sue_faal"),
                  ("Satis reel buyume (ceyrek, yillik)", "satis_reel"), ("ROE ivmesi (3 ay)", "roe_ivme"), ("ROE degisimi (12 ay)", "roe_deg")]:
        faktor(ad, f)
    for grp, ad in [("satis_g", "Satis reel buyume (TTM)"), ("favok_g", "FAVOK degisimi / satis (TTM)"), ("marj", "FAVOK marji degisimi"),
                    ("roe", "ROE degisimi (TTM)"), ("nakit", "Faaliyet nakdi degisimi / satis"), ("oz_g", "Ozkaynak reel buyume"),
                    ("borc", "Net borc / ozkaynak degisimi (eksi iyi)")]:
        L.append(f"== {ad}")
        for n in (3, 6, 12):
            faktor(f"  {n:2d} ay", f"{grp}{n}")
    L.append("== Seviye")
    faktor("FAVOK marji (seviye)", "favok_marj")
    faktor("ROE (seviye)", "roe")
    faktor("F-skoru", "F")

    # ---- birlesik 'hareket' adaylari: donem ici siralama ortalamalari, sonra temel toplam (hareket+kalite+deger)/3 ust %20
    g = A.groupby("donem")
    rk = lambda f, ters=False: (1 - g[f].rank(pct=True)) if ters else g[f].rank(pct=True)
    A["q_kal"] = pd.concat([rk("F"), rk("roe")], axis=1).mean(axis=1)
    A["q_deg"] = pd.concat([rk("kaz_get"), rk("pddd", True)], axis=1).mean(axis=1)

    def hareket(cols):
        Hm = pd.concat([rk(c, c.startswith("borc")) for c in cols], axis=1)
        return Hm.mean(axis=1).where(Hm.notna().sum(axis=1) >= max(2, len(cols) // 2))
    adaylar = {
        "H0 su anki (sue_nk, sue_faal, satis_reel, roe_ivme)": ["sue_nk", "sue_faal", "satis_reel", "roe_ivme"],
        "H1 net karsiz (sue_faal, satis_reel, roe_ivme)": ["sue_faal", "satis_reel", "roe_ivme"],
        "H2 3 ay TTM (satis_g3, favok_g3, roe3, nakit3)": ["satis_g3", "favok_g3", "roe3", "nakit3"],
        "H3 12 ay TTM (satis_g12, favok_g12, roe12, nakit12)": ["satis_g12", "favok_g12", "roe12", "nakit12"],
        "H4 3+6+12 ay satis ve FAVOK": ["satis_g3", "satis_g6", "satis_g12", "favok_g3", "favok_g6", "favok_g12"],
        "H5 su anki + 3/12 ay TTM": ["sue_nk", "sue_faal", "satis_reel", "roe_ivme", "satis_g3", "favok_g3", "satis_g12", "favok_g12"],
        "H6 sue_faal + satis + FAVOK 3/12 + ozkaynak 12": ["sue_faal", "satis_reel", "favok_g3", "favok_g12", "satis_g12", "oz_g12"],
        "H7 H6 + borc12": ["sue_faal", "satis_reel", "favok_g3", "favok_g12", "satis_g12", "oz_g12", "borc12"],
    }
    L.append("\n== Birlesik temel puan adaylari: (hareket + kalite + deger) / 3, donemin en ust %20'si; ayrica yalniz hareketin ust %20'si")
    L.append(f"{'aday':54s} {'n':>5s} | {'21g kirp/med':>14s} | {'63g kirp/med':>14s} {'kazanan':>8s} | {'126g kirp/med':>14s} | yillar 63g kirpik")
    for ad, cols in adaylar.items():
        A["h"] = hareket(cols)
        top = (A["h"] + A["q_kal"] + A["q_deg"]) / 3
        for etk, m in [("toplam", top.groupby(A.donem).rank(pct=True) >= 0.8), ("hareket", A["h"].groupby(A.donem).rank(pct=True) >= 0.8)]:
            X = A[m]
            yil = " ".join(f"{y}:{kirp(X[X.giris.dt.year == y].a63):+.1f}" for y in range(2021, 2027))
            L.append(f"{ad[:46] + ' ' + etk:54s} {len(X):5d} | {kirp(X.a21):+6.1f}/{X.a21.median():+6.1f} | {kirp(X.a63):+6.1f}/{X.a63.median():+6.1f} "
                     f"{100 * (X.a63 > 0).mean():7.0f}% | {kirp(X.a126):+6.1f}/{X.a126.median():+6.1f} | {yil}")
    txt = "\n".join(L)
    (R / "bt3_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
