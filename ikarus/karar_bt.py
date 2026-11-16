"""Hisse karar kutusu testi (16 Kas 2026, Teoman: "Zippo gibi secilen hisse su an alinir mi, beklenir mi, satilir mi?").

Her hisse, her 5 islem gununde bir, o gun bilinen son bilanco + IKARUS + faz motoruyla tek bir duruma konur.
Sonraki 63 ve 126 islem gunundeki BIST100'e gore fazla getiri durum durum karsilastirilir.
Durumlar (oncelik sirasiyla):
  VERI YOK       : 200 gunden yeni bilanco yok
  ZAYIF          : temel sirasi < %60 ya da kotu bilanco surprizi
  SERT DUSUS     : 20 gunde endekse gore -%25 ya da 10 gunde 4+ taban
  ORTA ...       : temel %60-80 (alt kirilim: ucuz + faz alim / diger)
  (temel en ust %20 icin)
  PAHALI         : Percentile >= 80 (elindeyse kar al)
  BEKLE KACTI    : 20 gunde endeksten +%10 fazla ya da 5 gunde +%15
  BEKLE UCUZ DEGIL: Percentile 20-80
  AL ✓✓ / AL ✓   : Percentile <= 20, faz motoru (normal ve/veya HA) alim tarafinda
  BEKLE TEKNIK   : ayni sartlar, faz alim tarafinda degil
Cikti: temel/karar_sonuc.txt
"""
from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd

from . import data as D
from . import engine as E
from . import temel_bt2 as B
from .firsat_bt import puanlar, AL

R = D.ROOT / "temel"
ADIM = 5


def durumlar(v3r, kotu, guncel, pct, o5, o20x, taban10, fz, ha):
    n = len(pct)
    d = np.array(["?"] * n, dtype=object)
    for i in range(n):
        if not guncel[i] or np.isnan(v3r[i]):
            d[i] = "VERI YOK"
        elif v3r[i] < 0.6 or kotu[i]:
            d[i] = "ZAYIF"
        elif o20x[i] < -25 or (taban10[i] >= 4 and o20x[i] < -15):
            d[i] = "SERT DUSUS"
        elif v3r[i] < 0.8:
            d[i] = "ORTA ucuz+faz alim" if (pct[i] <= 20 and (fz[i] or ha[i]) and o20x[i] <= 10 and o5[i] <= 15) else "ORTA diger"
        elif pct[i] >= 80:
            d[i] = "PAHALI (kar al)"
        elif o20x[i] > 10 or o5[i] > 15:
            d[i] = "BEKLE KACTI"
        elif pct[i] > 20:
            d[i] = "BEKLE UCUZ DEGIL"
        elif fz[i] and ha[i]:
            d[i] = "AL cift tik"
        elif fz[i] or ha[i]:
            d[i] = "AL tek tik"
        else:
            d[i] = "BEKLE TEKNIK"
    return d


def main():
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    m3 = D.m3()
    O = B.olaylar(G, m3)
    px = D.prices(sorted(O["t"].unique()))
    xu = D.xu100()
    P = puanlar(O, px)
    rows = []
    for n_, (t, df) in enumerate(sorted(px.items())):
        ev = P[P["t"] == t].sort_values("giris")
        if ev.empty or len(df) < 300:
            continue
        try:
            rfz = E.compute(df, xu, m3, "D", sig_mod="faz")
            rha = E.compute(df, xu, m3, "D", ha=True, sig_mod="faz")
        except Exception:
            continue
        idx = rfz.index
        c = rfz["close"].values.astype(float)
        x = xu.reindex(idx).ffill().values
        pct = rfz["percentile"].values
        fz = np.isin(rfz["sinyal"].values, AL)
        ha = np.isin(rha["sinyal"].reindex(idx).values, AL)
        vol = (df["close"] * df["volume"]).reindex(idx).rolling(20).mean().values
        gv = ev["giris"].values.astype("datetime64[ns]")
        k = np.searchsorted(gv, idx.values.astype("datetime64[ns]"), side="right") - 1
        kk = np.clip(k, 0, None)
        v3r = np.where(k >= 0, ev["v3r"].values[kk].astype(float), np.nan)
        kotu = np.where(k >= 0, ev["kotu"].values[kk].astype(bool), False)
        yas = np.where(k >= 0, (idx.values.astype("datetime64[ns]") - gv[kk]) / np.timedelta64(1, "D"), 9999)
        cs, xs = pd.Series(c), pd.Series(x)
        o5 = (100 * (cs / cs.shift(5) - 1)).values
        o20x = (100 * (cs / cs.shift(20) - 1) - 100 * (xs / xs.shift(20) - 1)).values
        taban10 = (cs.pct_change() <= -0.095).rolling(10).sum().fillna(0).values
        d = durumlar(v3r, kotu, yas <= 200, pct, o5, o20x, taban10, fz, ha)
        f = {}
        for h in (21, 63, 126):
            f[h] = (100 * (cs.shift(-h) / cs - 1) - 100 * (xs.shift(-h) / xs - 1)).values
        ok = (idx >= pd.Timestamp("2020-09-01")) & (vol > 5e6)
        for i in range(0, len(idx), ADIM):
            if ok[i] and not np.isnan(f[63][i]):
                rows.append((t, idx[i], d[i], f[21][i], f[63][i], f[126][i]))
        if n_ % 100 == 0:
            print(n_, t, len(rows))
    T = pd.DataFrame(rows, columns=["t", "tarih", "durum", "f21", "f63", "f126"])
    T.to_csv(R / "karar_gozlem.csv.gz", index=False, compression="gzip")

    def kp(s):
        s = s.dropna()
        if len(s) < 10:
            return np.nan
        return s.clip(s.quantile(.05), s.quantile(.95)).mean()
    sira = ["AL cift tik", "AL tek tik", "BEKLE TEKNIK", "BEKLE UCUZ DEGIL", "BEKLE KACTI", "PAHALI (kar al)",
            "ORTA ucuz+faz alim", "ORTA diger", "ZAYIF", "SERT DUSUS", "VERI YOK"]
    L = ["HISSE KARAR KUTUSU TESTI (16 Kas 2026)",
         f"Her hisse her {ADIM} islem gununde bir, o gun bilinenlerle bir duruma konuldu (2020-09 sonrasi, gunluk islem > 5 mn TL).",
         "Sonraki 21/63/126 islem gunu BIST100'e gore fazla getiri (%). kirpik = en iyi/kotu %5 atilmis ortalama.\n",
         f"{'durum':22s} {'gozlem':>7s} {'hisse':>6s} | {'21g kirp':>8s} | {'63g kirp':>8s} {'63g med':>8s} {'63g kazanan':>11s} | {'126g kirp':>9s} {'126g med':>8s}"]
    for s_ in sira + [x for x in T.durum.unique() if x not in sira]:
        g = T[T.durum == s_]
        if g.empty:
            continue
        L.append(f"{s_:22s} {len(g):7d} {g.t.nunique():6d} | {kp(g.f21):+8.2f} | {kp(g.f63):+8.2f} {g.f63.median():+8.2f} {100 * (g.f63 > 0).mean():10.1f}% | {kp(g.f126):+9.2f} {g.f126.median():+8.2f}")
    L.append("\nYillara gore 63g kirpik (medyan):")
    yil = T.tarih.dt.year
    L.append(f"{'durum':22s} " + " ".join(f"{y:>14d}" for y in sorted(yil.unique())))
    for s_ in sira:
        g = T[T.durum == s_]
        if g.empty:
            continue
        L.append(f"{s_:22s} " + " ".join(
            (f"{kp(g[yil[g.index] == y].f63):+6.1f} ({g[yil[g.index] == y].f63.median():+5.1f})" if (yil[g.index] == y).sum() >= 10 else f"{'-':>14s}")
            for y in sorted(yil.unique())))
    txt = "\n".join(L)
    (R / "karar_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
