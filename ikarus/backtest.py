"""Backtest: tum BIST, gunluk. Degerleme cekirdegi (Percentile dilimleri) ve sinyallerin
sonraki 20/60/120 islem gunu getirisi, BIST100'e gore fazla getiri.
Cikti: backtest/sonuc.txt, backtest/olaylar.csv.gz
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import data as D
from . import engine as E

R = D.ROOT / "backtest"
H = (20, 60, 120)
BAS = "2023-07-01"   # haftalik 200 bar MTF + 200 gun degerleme icin yeterli gecmis sonrasi


def main():
    import json
    try:
        varyant = json.loads((R / "istek.txt").read_text(encoding="utf-8"))
    except Exception:
        varyant = {}
    lst = D.bist_list()
    px = D.prices(lst["ticker"].tolist())
    xu = D.xu100()
    m3 = D.m3()
    rows = []
    for i, (t, df) in enumerate(sorted(px.items())):
        if len(df) < 400:
            continue
        try:
            r = E.compute(df, xu, m3, "D", **varyant)
        except Exception as e:
            print("atlandi", t, e)
            continue
        c = df["close"].reindex(r.index).values
        x = xu.reindex(r.index).ffill().values
        out = pd.DataFrame({"t": t, "pct": r["percentile"].values, "sinyal": r["sinyal"].values,
                            "onceki": np.r_[[None], r["sinyal"].values[:-1]], "eksik": r["eksik"].values,
                            "toplam": r["toplam"].values, "hacim_tl": (df["close"] * df["volume"]).reindex(r.index).rolling(20).mean().values},
                           index=r.index)
        for h in H:
            fr = np.r_[c[h:] / c[:-h] - 1, [np.nan] * h] if len(c) > h else np.full(len(c), np.nan)
            fx = np.r_[x[h:] / x[:-h] - 1, [np.nan] * h] if len(x) > h else np.full(len(x), np.nan)
            out[f"r{h}"] = 100 * fr
            out[f"a{h}"] = 100 * (fr - fx)   # endekse gore fazla getiri
        rows.append(out[out.index >= BAS])
        if i % 100 == 0:
            print(i, t)
    A = pd.concat(rows)
    A = A[A["hacim_tl"] > 5e6]   # cok sigi hisseleri disla (gunluk ort. 5 milyon TL alti)
    R.mkdir(exist_ok=True)
    A.reset_index().to_csv(R / "olaylar.csv.gz", index=False, compression="gzip")
    L = []
    def ozet(ad, S):
        s = [ad, f"n={len(S)}"]
        for h in H:
            a = S[f"a{h}"].dropna()
            if len(a):
                s.append(f"{h}g: ort {a.mean():+6.2f} medyan {a.median():+6.2f} kazanma %{100*(a>0).mean():4.1f}")
        L.append(" | ".join(s))
    L.append(f"Varyant: {varyant or 'v4.6 aday (varsayilan)'}")
    L.append(f"Sinyal degisen gun orani: %{100*(A['sinyal'] != A['onceki']).mean():.1f}")
    L.append(f"Donem {A.index.min():%Y-%m-%d} - {A.index.max():%Y-%m-%d}, {A['t'].nunique()} hisse. Getiriler BIST100'e gore fazla getiri (%).")
    L.append("\n== Tum gunler (referans)")
    ozet("hepsi", A)
    L.append("\n== Percentile dilimleri (degerleme cekirdegi, Zippo ile birebir)")
    for lo, hi in [(0, 5), (5, 10), (10, 20), (20, 35), (35, 50), (50, 65), (65, 80), (80, 90), (90, 100.1)]:
        ozet(f"pct {lo:>3}-{hi:<5}", A[(A["pct"] >= lo) & (A["pct"] < hi)])
    L.append("\n== Sinyaller (her gun, sinyal o gun neyse)")
    for s in ["ALINABILIR", "TOPLANIYOR", "YAKIN", "DAGITIM", "BEKLE"]:
        ozet(f"{s:11s}", A[A["sinyal"] == s])
    L.append("\n== Sinyal BASLANGICLARI (bir onceki gun farkli sinyaldeydi)")
    for s in ["ALINABILIR", "TOPLANIYOR", "YAKIN", "DAGITIM"]:
        ozet(f"{s:11s}", A[(A["sinyal"] == s) & (A["onceki"] != s)])
    L.append("\n== Eksik sart sayisi (ucuz bolgede, pct<=35)")
    U = A[A["pct"] <= 35]
    for k in range(0, 7):
        ozet(f"eksik {k}", U[U["eksik"] == k])
    L.append("\n== Yillara gore: pct<20 vs hepsi (60g)")
    for y in sorted(set(A.index.year)):
        Y = A[A.index.year == y]
        a1 = Y[Y["pct"] < 20]["a60"].dropna(); a2 = Y["a60"].dropna()
        L.append(f"{y}: pct<20 ort {a1.mean():+.2f} (n={len(a1)}) | hepsi ort {a2.mean():+.2f}")
    txt = "\n".join(L)
    (R / "sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
