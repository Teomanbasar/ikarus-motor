"""Toplam skor esigiyle giris, faz mantigiyla cikis: gunluk ve haftalik, M3 gecikmeli/gecikmesiz.
Giris: Toplam >= X (bir onceki bar < X). Cikis: Toplam < X - 5, ya da stop kirildi (onceki Stop'un %3.5 alti),
ya da azami sure (gunluk 120 bar, haftalik 26 bar). Getiri: BIST100'e gore fazla getiri.
Cikti: backtest/skor_sonuc.txt
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from . import data as D
from . import engine as E

R = D.ROOT / "backtest"
BAS = "2023-07-01"


def islem(r, c, x, X, maxb):
    tot = r["toplam"].values; ds = r["d_stop"].values; idx = r.index; out = []
    i = 1
    while i < len(tot):
        if tot[i] >= X and tot[i - 1] < X and idx[i] >= pd.Timestamp(BAS):
            j = i + 1
            while j < len(tot) and j - i < maxb and tot[j] >= X - 5 and ds[j] > -3.5:
                j += 1
            if j >= len(tot):
                break
            g = 100 * (c[j] / c[i] - 1); gx = 100 * (x[j] / x[i] - 1)
            out.append((idx[i], j - i, g, g - gx, r["percentile"].values[i]))
            i = j
        i += 1
    return out


def main():
    lst = D.bist_list(); px = D.prices(lst["ticker"].tolist()); xu = D.xu100(); m3 = D.m3()
    xw = E.to_weekly(pd.DataFrame({"open": xu, "high": xu, "low": xu, "close": xu, "volume": 0.0}))["close"]
    res = {}
    for k, (t, df) in enumerate(sorted(px.items())):
        if len(df) < 400 or (df["close"] * df["volume"]).tail(250).mean() < 5e6:
            continue
        for lag in (0, 25):
            for tf in ("D", "W"):
                try:
                    r = E.compute(df, xu, m3, tf, m3_gecikme_gun=lag)
                except Exception:
                    continue
                if tf == "D":
                    c = df["close"].reindex(r.index).values; x = xu.reindex(r.index).ffill().values; maxb = 120
                else:
                    c = r["close"].values if True else None
                    c = E.to_weekly(df)["close"].reindex(r.index).values
                    x = xw.reindex(r.index).ffill().values; maxb = 26
                for X in (36, 40, 45, 50):
                    res.setdefault((lag, tf, X), []).extend(islem(r, c, x, X, maxb))
        if k % 100 == 0:
            print(k, t)
    L = ["Toplam skor esigi ile giris, faz cikisi (Toplam < X-5 ya da stop kirildi ya da azami sure). Fazla getiri = hisse - BIST100.",
         "lag 0 = TradingView gibi (ay kapaninca), lag 25 = TCMB'nin yayim gecikmesine gore +25 gun (gecmise sarinca o gun bilinen M3).", ""]
    for (lag, tf, X), T in sorted(res.items()):
        T = pd.DataFrame(T, columns=["tarih", "bar", "getiri", "fazla", "pct"])
        if not len(T):
            continue
        L.append(f"M3 gecikme {lag:2d}g | {tf} | Toplam>={X} | islem {len(T):5d} | ort sure {T.bar.mean():5.1f} bar | "
                 f"getiri ort {T.getiri.mean():+6.2f} medyan {T.getiri.median():+6.2f} | fazla ort {T.fazla.mean():+6.2f} medyan {T.fazla.median():+6.2f} | "
                 f"endeksi gecen %{100*(T.fazla>0).mean():4.1f} | kazanc/kayip {T.fazla[T.fazla>0].mean():+.1f}/{T.fazla[T.fazla<=0].mean():+.1f}")
        for lo, hi in ((0, 35), (35, 101)):
            S = T[(T.pct >= lo) & (T.pct < hi)]
            if len(S):
                L.append(f"      giriste pct {lo}-{hi}: n {len(S)} fazla ort {S.fazla.mean():+.2f} medyan {S.fazla.median():+.2f} gecen %{100*(S.fazla>0).mean():.1f}")
    txt = "\n".join(L); (R / "skor_sonuc.txt").write_text(txt, encoding="utf-8"); print(txt)


if __name__ == "__main__":
    main()
