"""Banka + sigorta temel puani testi (17 Kas 2026, Teoman: "Bankalar hala yapilmadi mi, onemli").
Sanayi v3 ile ayni yapi, finans hisseleri KENDI icinde siralanir:
  hareket = sue_nk (net kar surprizi), satis_reel (bankada 3C = net faiz geliri, reel yillik), roe_ivme
  kalite  = F (5 madde), roe          deger = kaz_get (kar getirisi = net kar / piyasa degeri), 1 - PD/DD sirasi
Getiri: ayni gun tum likit hisselerin MEDYAN getirisine gore fazla (BIST100 bankalari zaten iceriyor).
Cikti: temel/finans_sonuc.txt"""
from __future__ import annotations
import gzip, json
import numpy as np
import pandas as pd
from . import data as D
from . import temel_bt2 as B

R = D.ROOT / "temel"
H = (21, 63, 126)


def kirp(a):
    a = pd.Series(a).dropna()
    if len(a) < 8:
        return np.nan
    lo, hi = a.quantile([0.05, 0.95])
    return a[(a >= lo) & (a <= hi)].mean()


def main():
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    m3 = D.m3()
    O = B.olaylar({h: g for h, g in G.items() if g["grup"] == "UFRS"}, m3)
    lst = D.bist_list()
    px = D.prices(lst["ticker"].tolist())
    # tum likit hisselerin gunluk ileri getiri medyani
    toplam = {h: {} for h in H}
    for t, df in px.items():
        df = df[df.index >= pd.Timestamp("2019-01-01")]
        if len(df) < 200:
            continue
        cs = df["close"]; vol = (df["close"] * df["volume"]).rolling(20).mean()
        for h in H:
            f = 100 * (cs.shift(-h) / cs - 1)
            ok = (vol > 5e6) & f.notna()
            for d, v in f[ok].items():
                toplam[h].setdefault(d, []).append(v)
    med = {h: {d: float(np.median(v)) for d, v in toplam[h].items() if len(v) >= 30} for h in H}
    rows = []
    for _, e in O.iterrows():
        df = px.get(e["t"])
        if df is None:
            continue
        j = df.index.searchsorted(e["yayin"], side="right")
        if j >= len(df) or j < 1:
            continue
        p0 = float(df["close"].iloc[j - 1]); mcap = p0 * (e["sermaye_son"] or np.nan)
        r = e.to_dict(); r["giris"] = df.index[j]
        r["pddd"] = mcap / e["oz"] if e.get("oz") and e["oz"] > 0 else np.nan
        r["kaz_get"] = e["nk_ttm"] / mcap if e.get("nk_ttm") is not None and mcap > 0 else np.nan
        c = df["close"].values
        for h in H:
            k = j + h
            r[f"x{h}"] = (100 * (c[k] / c[j] - 1) - med[h].get(df.index[j], np.nan)) if k < len(c) else np.nan
        rows.append(r)
    A = pd.DataFrame(rows)
    A = A[A.giris >= pd.Timestamp("2020-06-01")]
    g = A.groupby("donem")
    q = {f: g[f].rank(pct=True) for f in ["sue_nk", "satis_reel", "roe_ivme", "kaz_get", "roe", "F"]}
    q["pddd"] = 1 - g["pddd"].rank(pct=True)
    Hm = pd.concat([q["sue_nk"], q["satis_reel"], q["roe_ivme"]], axis=1)
    A["h"] = Hm.mean(axis=1).where(Hm.notna().sum(axis=1) >= 2)
    A["k"] = pd.concat([q["F"], q["roe"]], axis=1).mean(axis=1)
    A["d"] = pd.concat([q["kaz_get"], q["pddd"]], axis=1).mean(axis=1)
    A["v3"] = (A.h + A.k + A.d) / 3
    A["v3r"] = A.groupby("donem")["v3"].rank(pct=True)
    banka = {"AKBNK", "GARAN", "ISCTR", "YKBNK", "VAKBN", "HALKB", "ALBRK", "SKBNK", "QNBTR", "ICBCT", "TSKB", "KLNMA", "ISBTR"}
    A["tur"] = np.where(A.t.isin(banka), "banka", "sigorta/diger")
    L = ["FINANS (banka + sigorta) TEMEL PUANI TESTI (17 Kas 2026)",
         f"Olay {len(A)}, hisse {A.t.nunique()} ({', '.join(sorted(A.t.unique()))}), donem {A.donem.min()}..{A.donem.max()}",
         "Getiri: ayni gun tum likit hisselerin medyanina gore fazla (%). kirpik / medyan / kazanan. Ucte bir dilimler (her donemde).\n"]

    def satir(ad, X):
        s = f"{ad:46s} n={len(X):4d}"
        for h in H:
            a = X[f"x{h}"].dropna()
            s += f" | {h}g {kirp(a):+5.1f}/{a.median():+5.1f} %{100 * (a > 0).mean():3.0f}" if len(a) >= 8 else f" | {h}g -"
        return s
    L.append(satir("tum finans olaylari", A))
    for f, ad in [("v3r", "TOPLAM puan"), ("h", "hareket"), ("k", "kalite"), ("d", "deger"),
                  ("sue_nk", "net kar surprizi"), ("satis_reel", "net faiz geliri reel buyume"), ("roe_ivme", "ROE ivmesi"), ("roe", "ROE seviye"), ("kaz_get", "kar getirisi (1/FK)")]:
        X = A.dropna(subset=[f]).copy()
        X["q"] = X.groupby("donem")[f].transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=False) + 1 if len(s) >= 6 else np.nan)
        L.append(f"== {ad}")
        for qq, nm in ((3, "ust 1/3"), (2, "orta"), (1, "alt 1/3")):
            L.append(satir(f"   {nm}", X[X.q == qq]))
    L.append("\n== Yalniz bankalar, TOPLAM puan")
    X = A[A.tur == "banka"].dropna(subset=["v3r"]).copy()
    X["q"] = X.groupby("donem")["v3r"].transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=False) + 1 if len(s) >= 6 else np.nan)
    for qq, nm in ((3, "ust 1/3"), (2, "orta"), (1, "alt 1/3")):
        L.append(satir(f"   {nm}", X[X.q == qq]))
    yl = A[A.v3r >= 2 / 3]
    L.append("\nToplam ust 1/3, yillar 63g: " + " ".join(f"{y}:{kirp(gg.x63):+.1f}/{len(gg)}" for y, gg in yl.groupby(yl.giris.dt.year)))
    yl = A[A.v3r < 1 / 3]
    L.append("Toplam alt 1/3, yillar 63g: " + " ".join(f"{y}:{kirp(gg.x63):+.1f}/{len(gg)}" for y, gg in yl.groupby(yl.giris.dt.year)))
    txt = "\n".join(L)
    (R / "finans_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
