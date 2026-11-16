"""M3 bandi (Zippo'nun yeni tablosu) on denemesi (17 Kas 2026). Yalniz cozulmus kisim kullanilir:
  puan = 100 x (fiyat/M3 - en dusuk(dusuk/M3)) / (en yuksek(yuksek/M3, ~48 ay) - en dusuk(dusuk/M3))
  (DCTTR 16 Kas: 3.26 / 24.34 / 3.0 birebir). M3 o gun bilinen deger (m3_effective).
Para Girisi ve Baz/Kirilim cozulmedi; burada yalniz kisa baz / kirilim denemeleri var (Zippo'nun tanimi DEGIL).
Hicbir yere eklenmez; cikti temel/m3bant_sonuc.txt.
"""
from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd

from . import data as D
from . import engine as E
from . import temel_bt2 as B
from .firsat_bt import puanlar

R = D.ROOT / "temel"
PEN = 48 * 21   # Pahali penceresi ~48 ay (gunluk bar)


def kirp(a):
    a = pd.Series(a).dropna()
    if len(a) < 10:
        return np.nan
    lo, hi = a.quantile([0.05, 0.95])
    return a[(a >= lo) & (a <= hi)].mean()


def main():
    lst = D.bist_list()
    px = D.prices(lst["ticker"].tolist())
    xu = D.xu100()
    m3 = D.m3()
    m3e = E.m3_effective(m3)
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    O = B.olaylar(G, m3)
    P = puanlar(O, {t: px[t] for t in O["t"].unique() if t in px})
    rows, olay = [], []
    for n_, (t, df) in enumerate(sorted(px.items())):
        df = df[df.index >= pd.Timestamp("2016-01-01")]
        if len(df) < 300 or not {"high", "low", "close", "volume"} <= set(df.columns):
            continue
        ix = df.index
        mm = E.align_m3(ix, m3e)
        c = df["close"].values.astype(float)
        hi = pd.Series(df["high"].values / mm, index=ix)
        lo = pd.Series(df["low"].values / mm, index=ix)
        mn = lo.cummin().values
        mx = hi.rolling(PEN, min_periods=1).max().values
        puan = 100 * (c / mm - mn) / (mx - mn)
        x = xu.reindex(ix).ffill().values
        cs, xs = pd.Series(c), pd.Series(x)
        f = {h: (100 * (cs.shift(-h) / cs - 1) - 100 * (xs.shift(-h) / xs - 1)).values for h in (21, 63, 126)}
        vol = (df["close"] * df["volume"]).rolling(20).mean().values
        # bilanco grubu (sanayi; o gun bilinen son bilanco, 200 gunden eski degil)
        ev = P[P["t"] == t].sort_values("giris")
        bil = np.array(["yok"] * len(ix), dtype=object)
        if not ev.empty:
            gv = ev["giris"].values.astype("datetime64[ns]")
            k = np.searchsorted(gv, ix.values.astype("datetime64[ns]"), side="right") - 1
            kk = np.clip(k, 0, None)
            v3r = np.where(k >= 0, ev["v3r"].values[kk].astype(float), np.nan)
            yas = np.where(k >= 0, (ix.values.astype("datetime64[ns]") - gv[kk]) / np.timedelta64(1, "D"), 9999)
            ok = (yas <= 200) & ~np.isnan(v3r)
            bil = np.where(ok & (v3r >= 0.8), "iyi", np.where(ok & (v3r >= 0.6), "orta", np.where(ok, "zayif", "yok")))
        hh = pd.Series(df["high"].values, index=ix); ll = pd.Series(df["low"].values, index=ix)
        gecerli = (ix >= pd.Timestamp("2018-01-01")) & (vol > 5e6) & ~np.isnan(f[63])
        # 1) 5 gunde bir orneklem
        for i in range(0, len(ix), 5):
            if gecerli[i]:
                rows.append((t, ix[i], puan[i], bil[i], f[21][i], f[63][i], f[126][i]))
        # 2) olaylar: dip + kisa baz, dip + kirilim (tetiklenince 20 gun bekleme)
        for N, gen in ((10, 0.12), (15, 0.15)):
            rng = (hh.rolling(N).max() / ll.rolling(N).min() - 1).values
            ust = hh.rolling(N).max().shift(1).values
            for ad, kosul in ((f"dip(<=10) + {N}g baz (aralik <=%{int(gen * 100)})", (puan <= 10) & (rng <= gen)),
                              (f"dip(<=15) + {N}g baz kirilimi (kapanis > onceki {N}g tepe)", (pd.Series(puan).shift(1).values <= 15) & (rng <= gen * 1.5) & (c > ust))):
                son = -999
                for i in np.flatnonzero(kosul & gecerli):
                    if i - son >= 20:
                        olay.append((ad, t, ix[i], bil[i], f[21][i], f[63][i], f[126][i])); son = i
        if n_ % 100 == 0:
            print(n_, t, len(rows), len(olay))
    T = pd.DataFrame(rows, columns=["t", "tarih", "puan", "bil", "f21", "f63", "f126"])
    Ov = pd.DataFrame(olay, columns=["ad", "t", "tarih", "bil", "f21", "f63", "f126"])
    L = ["M3 BANDI ON DENEMESI (17 Kas 2026) - yalniz cozulen Ucuz<->Pahali puani; Para Girisi / Baz-Kirilim Zippo tanimi DEGIL",
         "2018+ , gunluk islem > 5 mn TL. Getiri: BIST100'e gore fazla (%), kirpik ortalama / medyan / kazanan.\n"]

    def satir(ad, X):
        s = f"{ad:62s} n={len(X):6d}"
        for h in (21, 63, 126):
            a = X[f"f{h}"].dropna()
            s += f" | {h}g {kirp(a):+5.1f}/{a.median():+5.1f}" if len(a) >= 10 else f" | {h}g -"
        a = X["f63"].dropna()
        return s + (f" | %{100 * (a > 0).mean():.0f}" if len(a) else "")
    L.append("== 1) Puan dilimleri (5 gunde bir orneklem; ayni hisse tekrar sayilir)")
    for a_, b_ in ((0, 5), (5, 10), (10, 20), (20, 40), (40, 60), (60, 80), (80, 100.1)):
        L.append(satir(f"puan {a_:>3}-{b_:<5}", T[(T.puan >= a_) & (T.puan < b_)]))
    L.append(satir("puan < 0 (Ucuzluk kirildi; tanim geregi yalniz gun ici)", T[T.puan < 0]))
    L.append("\n== 2) Dip (puan <= 10) bilanco grubuna gore")
    for b in ("iyi", "orta", "zayif", "yok"):
        L.append(satir(f"puan <= 10, bilanco {b}", T[(T.puan <= 10) & (T.bil == b)]))
        L.append(satir(f"puan 40-60, bilanco {b} (karsilastirma)", T[(T.puan.between(40, 60)) & (T.bil == b)]))
    L.append("\n== 3) Dip + kisa baz / kirilim olaylari (tetiklenince 20 gun bekleme)")
    for ad in Ov.ad.unique():
        X = Ov[Ov.ad == ad]
        L.append(satir(ad, X))
        for b in ("iyi", "zayif", "yok"):
            L.append(satir(f"   bilanco {b}", X[X.bil == b]))
    L.append("\n== Yillar (puan <= 10, 63g kirpik / n)")
    yl = T[T.puan <= 10]
    L.append("  " + " ".join(f"{y}:{kirp(g.f63):+.1f}/{len(g)}" for y, g in yl.groupby(yl.tarih.dt.year)))
    txt = "\n".join(L)
    (R / "m3bant_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()


def ivme():
    """Teoman (17 Kas): 'En ucuz kalmis, yukari ivmelenmeye baslamis hisseleri almak basli basina dogru mantik.'
    Olcum duzeltmesi: getiri BIST100 yerine ayni gun tum likit hisselerin ESIT AGIRLIKLI ortalamasina gore
    (BIST100 buyuk sirket agirlikli; tipik hisse geride kaldigi icin her sey eksi gorunuyordu)."""
    lst = D.bist_list()
    px = D.prices(lst["ticker"].tolist())
    m3e = E.m3_effective(D.m3())
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    O = B.olaylar(G, D.m3())
    P = puanlar(O, {t: px[t] for t in O["t"].unique() if t in px})
    H = (21, 63, 126)
    seri, toplam = {}, {h: {} for h in H}
    for t, df in sorted(px.items()):
        df = df[df.index >= pd.Timestamp("2016-01-01")]
        if len(df) < 300 or not {"high", "low", "close", "volume"} <= set(df.columns):
            continue
        ix = df.index
        mm = E.align_m3(ix, m3e)
        c = df["close"].values.astype(float)
        mn = pd.Series(df["low"].values / mm).cummin().values
        mx = pd.Series(df["high"].values / mm).rolling(PEN, min_periods=1).max().values
        puan = 100 * (c / mm - mn) / (mx - mn)
        cs = pd.Series(c)
        vol = (df["close"] * df["volume"]).rolling(20).mean().values
        f = {h: (100 * (cs.shift(-h) / cs - 1)).values for h in H}
        ok = (ix >= pd.Timestamp("2018-01-01")) & (vol > 5e6)
        for h in H:   # ayni gun tum likit hisselerin getirileri (medyan icin)
            for d, v in zip(ix[ok], f[h][ok]):
                if not np.isnan(v):
                    toplam[h].setdefault(d, []).append(v)
        ev = P[P["t"] == t].sort_values("giris")
        bil = np.array(["yok"] * len(ix), dtype=object)
        if not ev.empty:
            gv = ev["giris"].values.astype("datetime64[ns]")
            k = np.searchsorted(gv, ix.values.astype("datetime64[ns]"), side="right") - 1
            kk = np.clip(k, 0, None)
            v3r = np.where(k >= 0, ev["v3r"].values[kk].astype(float), np.nan)
            yas = np.where(k >= 0, (ix.values.astype("datetime64[ns]") - gv[kk]) / np.timedelta64(1, "D"), 9999)
            g = (yas <= 200) & ~np.isnan(v3r)
            bil = np.where(g & (v3r >= 0.8), "iyi", np.where(g & (v3r >= 0.6), "orta", np.where(g, "zayif", "yok")))
        seri[t] = dict(ix=ix, c=c, puan=puan, f=f, ok=ok, bil=bil,
                       taban=(cs.pct_change() <= -0.095).rolling(20).sum().fillna(0).values,
                       ma20=cs.rolling(20).mean().values, ma50=cs.rolling(50).mean().values,
                       r10=(100 * (cs / cs.shift(10) - 1)).values, r20=(100 * (cs / cs.shift(20) - 1)).values,
                       pmin20=pd.Series(puan).rolling(20).min().values)
    ort = {h: {d: float(np.median(v)) for d, v in toplam[h].items() if len(v) >= 30} for h in H}
    kurallar = {
        "I1 dip(20g icinde puan<=10) + puan<=25 + kapanis>MA20 + 10g >= +%5":
            lambda S: (S["pmin20"] <= 10) & (S["puan"] <= 25) & (S["c"] > S["ma20"]) & (S["r10"] >= 5),
        "I2 dip(20g icinde puan<=10) + puan<=30 + 20g >= +%15":
            lambda S: (S["pmin20"] <= 10) & (S["puan"] <= 30) & (S["r20"] >= 15),
        "I3 dip(20g icinde puan<=15) + puan<=30 + MA20 > MA50 (yeni)":
            lambda S: (S["pmin20"] <= 15) & (S["puan"] <= 30) & (S["ma20"] > S["ma50"]) & (pd.Series(S["ma20"]).shift(1).values <= pd.Series(S["ma50"]).shift(1).values),
        "K  karsilastirma: puan<=10, ivme sarti yok":
            lambda S: (S["puan"] <= 10),
        "Z  TABAN CIZGISI: tum hisseler (her gun aday, 20 gunde bir)":
            lambda S: np.ones(len(S["c"]), bool),
    }
    rows = []
    for ad, kos in kurallar.items():
        for t, S in seri.items():
            m = kos(S) & S["ok"]
            son = -999
            for i in np.flatnonzero(m):
                if i - son < 20:
                    continue
                son = i
                d = S["ix"][i]
                r = [S["f"][h][i] - ort[h].get(d, np.nan) for h in H]
                rows.append((ad, t, d, S["bil"][i], S["taban"][i] >= 2, *r))
    T = pd.DataFrame(rows, columns=["ad", "t", "tarih", "bil", "taban", "x21", "x63", "x126"])

    def satir(ad, X):
        s = f"{ad:66s} n={len(X):5d}"
        for h in H:
            a = X[f"x{h}"].dropna()
            s += f" | {h}g {kirp(a):+5.1f}/{a.median():+5.1f} %{100 * (a > 0).mean():3.0f}" if len(a) >= 10 else f" | {h}g -"
        return s
    L = ["DIPTEN IVMELENME TESTI (17 Kas 2026). Getiri: ayni gun tum likit hisselerin MEDYAN getirisine gore fazla (%) (tipik hisse = 0).",
         "Her hucre: kirpik ortalama / medyan / kazanan orani. Olaylar: kosul tetiklenince 20 gun bekleme. 2018+, islem > 5 mn TL.",
         "Z satiri taban cizgisi: rastgele hisse almanin ayni olcudeki sonucu. Kurallar buna gore okunmali.\n"]
    for ad in kurallar:
        X = T[T.ad == ad]
        L.append(satir(ad, X))
        L.append(satir("   taban serisi (20 gunde 2+ taban) olanlar haric", X[~X.taban]))
        for b in ("iyi", "orta", "zayif", "yok"):
            L.append(satir(f"   bilanco {b} (taban serisi haric)", X[(X.bil == b) & ~X.taban]))
        yl = X[~X.taban]
        L.append("   yillar 63g: " + " ".join(f"{y}:{kirp(g.x63):+.1f}/{len(g)}" for y, g in yl.groupby(yl.tarih.dt.year)))
        L.append("")
    txt = "\n".join(L)
    (R / "m3bant_ivme.txt").write_text(txt, encoding="utf-8")
    print(txt)
