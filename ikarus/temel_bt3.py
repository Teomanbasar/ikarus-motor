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


# ---------------------------------------------------------------------------------------------
# 16 Kas aksam: "TTKOM tongasi" testi. Ceyreklik (gecen yilin ayni ceyregi, mevsimsellik yok) + yillik (TTM).
def ceyrek_isaret(tab, m3, d):
    """Ceyreklik faaliyet isaretleri, ceyrek satisina bolunmus (negatif tabanda da calisir)."""
    out = {}
    d1 = geri(d, 12)
    m3y = T._m3_oran(m3, d, d1)
    s0, s1 = T.ceyreklik(tab, d, "3C"), T.ceyreklik(tab, d1, "3C")
    if not m3y or not s0 or s0 <= 0:
        return out
    def fq(dd):
        a, b = T.ceyreklik(tab, dd, "3DF"), T.ceyreklik(tab, dd, "4B")
        return None if a is None or b is None else a + b
    f0, f1 = fq(d), fq(d1)
    n0, n1 = T.ceyreklik(tab, d, "3Z"), T.ceyreklik(tab, d1, "3Z")
    if f0 is not None and f1 is not None:
        out["favok_q"] = (f0 - f1 * m3y) / s0
    if n0 is not None and n1 is not None:
        out["nk_q"] = (n0 - n1 * m3y) / s0
        if f0 is not None and f1 is not None:
            # faaliyet disi kalemlerin (finansman, kur, parasal kayip, vergi) degisimi: net kar - FAVOK farkinin degisimi
            out["faaliyet_disi_q"] = ((n0 - f0) - (n1 - f1) * m3y) / s0
    return out


def tonga():
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    m3 = D.m3()
    rows = []
    for h, g in G.items():
        if g["grup"] != "XI_29":
            continue
        tab = {tuple(map(int, k.split("/"))): v for k, v in g["tab"].items()}
        for d in sorted(tab):
            alt = {k: v for k, v in tab.items() if k <= d}
            r = ceyrek_isaret(alt, m3, d)
            if r:
                r.update({"t": h, "donem": f"{d[0]}/{d[1]:02d}"})
                rows.append(r)
    A = pd.read_csv(R / "bt3_olaylar.csv.gz", parse_dates=["giris"]).merge(pd.DataFrame(rows), on=["t", "donem"], how="left")
    g = A.groupby("donem")
    rk = lambda f: g[f].rank(pct=True)
    for f in ["sue_nk", "sue_faal", "satis_reel", "roe_ivme", "favok_q", "nk_q", "satis_g12", "favok_g12", "roe6", "satis_g3", "favok_g3",
              "F", "roe", "kaz_get", "favok_marj"]:
        A["r_" + f] = rk(f)
    A["r_pddd"] = 1 - rk("pddd")
    L = ["TTKOM TONGASI TESTI (16 Kas 2026): net kar dusuk ama faaliyet iyi olan sirketler",
         "Ceyreklik isaretler gecen yilin ayni ceyregine gore (mevsimsellik yok), M3'e gore arindirilmis, ceyrek satisina bolunmus.",
         "Getiri: BIST100'e gore fazla (%), kirpik ortalama / medyan. Sanayi.\n"]

    def grup(ad, X):
        s = f"{ad:62s} n={len(X):5d}"
        for hh in (21, 63, 126):
            a = X[f"a{hh}"].dropna()
            s += f" | {hh}g {kirp(a):+5.1f}/{a.median():+5.1f}" if len(a) >= 15 else f" | {hh}g -"
        a = X["a63"].dropna()
        s += f" | kazanan %{100 * (a > 0).mean():3.0f}" if len(a) else ""
        L.append(s)

    L.append("== Tek tek (63g ust dilim - alt dilim)")
    for f in ["favok_q", "nk_q", "faaliyet_disi_q"]:
        X = A.dropna(subset=[f]).copy()
        X["q"] = X.groupby("donem")[f].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1 if len(s) >= 25 else np.nan)
        p = [kirp(X[X.q == q].a63) for q in range(1, 6)]
        L.append(f"{f:20s} D1..D5 63g: " + " ".join(f"{x:+5.1f}" for x in p) + f" | 21g: " + " ".join(f"{kirp(X[X.q == q].a21):+5.1f}" for q in range(1, 6)))
    op = A[["r_favok_q", "r_sue_faal", "r_satis_reel"]].mean(axis=1)
    A["r_op"] = op.groupby(A.donem).rank(pct=True)
    L.append("\n== Faaliyet (FAVOK + esas faaliyet + satis, ceyreklik) ile net kar ayri ayri")
    grup("hepsi", A)
    for a_, ma in [("faaliyet iyi (ust %40)", A.r_op >= 0.6), ("faaliyet orta", A.r_op.between(0.4, 0.6, inclusive="neither")), ("faaliyet kotu (alt %40)", A.r_op <= 0.4)]:
        for b_, mb in [("net kar iyi", A.r_sue_nk >= 0.6), ("net kar kotu", A.r_sue_nk <= 0.4)]:
            grup(f"{a_} + {b_}", A[ma & mb])
    L.append("\n== Ayni grup, kalite + deger de iyi (ikisinin ortalamasi donemin ust yarisinda)")
    kd = (A[["r_F", "r_roe"]].mean(axis=1) + A[["r_kaz_get", "r_pddd"]].mean(axis=1)) / 2
    A["r_kd"] = kd.groupby(A.donem).rank(pct=True)
    for a_, ma in [("faaliyet iyi", A.r_op >= 0.6), ("faaliyet kotu", A.r_op <= 0.4)]:
        for b_, mb in [("net kar iyi", A.r_sue_nk >= 0.6), ("net kar kotu", A.r_sue_nk <= 0.4)]:
            grup(f"{a_} + {b_} + kalite/deger iyi", A[ma & mb & (A.r_kd >= 0.5)])
    L.append("\n== Net kar faaliyet disi kalemlerden mi dustu? (faaliyet iyi + net kar kotu icinde)")
    Y = A[(A.r_op >= 0.6) & (A.r_sue_nk <= 0.4)]
    grup("faaliyet disi kayip buyuk (alt yarim)", Y[Y.faaliyet_disi_q <= Y.faaliyet_disi_q.median()])
    grup("faaliyet disi kayip kucuk", Y[Y.faaliyet_disi_q > Y.faaliyet_disi_q.median()])

    # ---- birlesik puan adaylari (hareket + kalite + deger)/3, en ust %20 -- kotu surpriz etiketi de ayri
    def puan(hcols, w=None):
        Hm = A[["r_" + c for c in hcols]]
        w = np.array(w if w else [1] * len(hcols), float)
        Wm = Hm.notna() * w
        h = (Hm.fillna(0) * w).sum(axis=1) / Wm.sum(axis=1)
        h = h.where(Hm.notna().sum(axis=1) >= 2)
        k = A[["r_F", "r_roe"]].mean(axis=1)
        dg = A[["r_kaz_get", "r_pddd"]].mean(axis=1)
        return ((h + k + dg) / 3).groupby(A.donem).rank(pct=True)
    adaylar = {
        "P0 su anki: sue_nk, sue_faal, satis_reel, roe_ivme": (["sue_nk", "sue_faal", "satis_reel", "roe_ivme"], None),
        "P1 faaliyet ceyreklik: favok_q, sue_faal, satis_reel": (["favok_q", "sue_faal", "satis_reel"], None),
        "P2 P1 + yillik: + satis_g12, favok_g12": (["favok_q", "sue_faal", "satis_reel", "satis_g12", "favok_g12"], None),
        "P3 P2 + roe6": (["favok_q", "sue_faal", "satis_reel", "satis_g12", "favok_g12", "roe6"], None),
        "P4 P3 + net kar yarim agirlik": (["favok_q", "sue_faal", "satis_reel", "satis_g12", "favok_g12", "roe6", "sue_nk"], [1, 1, 1, 1, 1, 1, .5]),
        "P5 ceyreklik+yillik+3ay: favok_q, sue_faal, satis_reel, favok_g3, satis_g3, favok_g12, satis_g12, roe6":
            (["favok_q", "sue_faal", "satis_reel", "favok_g3", "satis_g3", "favok_g12", "satis_g12", "roe6"], None),
    }
    L.append("\n== Temel puan adaylari: (hareket + kalite + deger)/3, donemin en ust %20'si")
    kotu_eski = (A.r_sue_nk <= 0.2) & (A.r_sue_faal <= 0.2)
    kotu_yeni = (A.r_op <= 0.2)
    for ad, (c, w) in adaylar.items():
        r = puan(c, w)
        X = A[r >= 0.8]
        grup(ad[:60], X)
        yl = " ".join(f"{y}:{kirp(X[X.giris.dt.year == y].a63):+.1f}" for y in range(2022, 2027))
        L.append(f"{'':62s}   yillar 63g {yl}")
        A["_p_" + ad[:2]] = r
    L.append("\n== Kotu surpriz etiketi: eski (net kar ve esas faaliyet ikisi alt %20) vs yeni (faaliyet ortalamasi alt %20)")
    grup("eski kotu surpriz", A[kotu_eski]); grup("yeni kotu surpriz", A[kotu_yeni])
    grup("eskiye gore kotu ama yeniye gore degil", A[kotu_eski & ~kotu_yeni])
    grup("yeniye gore kotu ama eskiye gore degil", A[kotu_yeni & ~kotu_eski])
    L.append("\n== Liste degisimi: P0'da ust %20 degil ama P3'te ust %20 olanlar (ve tersi)")
    grup("P3'e giren, P0'da yok", A[(A["_p_P3"] >= 0.8) & (A["_p_P0"] < 0.8)])
    grup("P0'da var, P3'ten cikan", A[(A["_p_P0"] >= 0.8) & (A["_p_P3"] < 0.8)])
    grup("faaliyet iyi + net kar kotu: P0'da ust %20", A[(A.r_op >= 0.6) & (A.r_sue_nk <= 0.4) & (A["_p_P0"] >= 0.8)])
    grup("faaliyet iyi + net kar kotu: P3'te ust %20", A[(A.r_op >= 0.6) & (A.r_sue_nk <= 0.4) & (A["_p_P3"] >= 0.8)])
    txt = "\n".join(L)
    (R / "bt3_tonga.txt").write_text(txt, encoding="utf-8")
    print(txt)
