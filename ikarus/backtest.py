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


def islemler(t, r, c, x, maxb=120, cikis="faz"):
    """Alim fazina giriste al (ALINABILIR/TOPLANIYOR). Cikis "faz": faz bitince (BEKLE/DAGITIM);
    "adil": fiyat Dip-Tepe ortasina ulasinca ya da stop kirilinca (onceki Stop'un %3.5 alti); her ikisinde azami maxb bar."""
    sig = r["sinyal"].values; idx = r.index; out = []
    adil = ((r["dip"] + r["tepe"]) / 2).values; ds = r["d_stop"].values
    alim = np.isin(sig, ["ALINABILIR", "TOPLANIYOR"])
    i = 1
    while i < len(sig):
        if alim[i] and not alim[i - 1] and idx[i] >= pd.Timestamp(BAS):
            j = i + 1
            if cikis == "adil":
                while j < len(sig) and j - i < maxb and c[j] < adil[i] and ds[j] > -3.5:
                    j += 1
            else:
                while j < len(sig) and j - i < maxb and sig[j] not in ("BEKLE", "DAGITIM"):
                    j += 1
            if j >= len(sig):
                break
            g = 100 * (c[j] / c[i] - 1); gx = 100 * (x[j] / x[i] - 1)
            if cikis == "adil":
                neden = "azami" if j - i >= maxb else ("adil" if c[j] >= adil[i] else "stop")
            else:
                neden = "azami" if j - i >= maxb else ("stop/ucuz-disi" if sig[j] == "BEKLE" else "DAGITIM")
            out.append((t, idx[i], sig[i], j - i, g, g - gx, neden))
            i = j
        i += 1
    return out


def main():
    import json
    try:
        varyant = json.loads((R / "istek.txt").read_text(encoding="utf-8"))
    except Exception:
        varyant = {}
    etiket = varyant.pop("etiket", "v46")
    tf = varyant.pop("tf", "D"); ha = varyant.pop("ha", False); cikis = varyant.pop("cikis", "faz")
    global H
    if tf == "W":
        H = (4, 12, 26)
    lst = D.bist_list()
    px = D.prices(lst["ticker"].tolist())
    xu = D.xu100()
    m3 = D.m3()
    xw = E.to_weekly(pd.DataFrame({"open": xu, "high": xu, "low": xu, "close": xu, "volume": 0.0}))["close"]
    rows = []; ISL = []; MAK = []
    for i, (t, df) in enumerate(sorted(px.items())):
        if len(df) < 400:
            continue
        try:
            r = E.compute(df, xu, m3, tf, ha=ha, **varyant)
        except Exception as e:
            print("atlandi", t, e)
            continue
        if tf == "W":
            c = E.to_weekly(df)["close"].reindex(r.index).values
            x = xw.reindex(r.index).ffill().values
        else:
            c = df["close"].reindex(r.index).values
            x = xu.reindex(r.index).ffill().values
        if (df["close"] * df["volume"]).tail(250).mean() > 5e6:
            ISL.extend(islemler(t, r, c, x, 26 if tf == "W" else 120, cikis))
        MAK.extend(r["macro_base"].values[r.index >= BAS][::5].tolist())
        out = pd.DataFrame({"t": t, "pct": r["percentile"].values, "sinyal": r["sinyal"].values,
                            "onceki": np.r_[[None], r["sinyal"].values[:-1]], "eksik": r["eksik"].values,
                            "toplam": r["toplam"].values, "hacim_tl": ((df["close"] * df["volume"]).rolling(20).mean().reindex(r.index, method="ffill").values)},
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
    L.append(f"Varyant: {varyant or 'v4.6 aday (varsayilan)'} | tf {tf} | HA {ha} | cikis {cikis}")
    L.append(f"Makro etiket dagilimi: {pd.Series(MAK).value_counts(normalize=True).round(3).to_dict() if MAK else '-'}")
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
        a1 = Y[Y["pct"] < 20][f"a{H[1]}"].dropna(); a2 = Y[f"a{H[1]}"].dropna()
        L.append(f"{y}: pct<20 ort {a1.mean():+.2f} (n={len(a1)}) | hepsi ort {a2.mean():+.2f}")
    T = pd.DataFrame(ISL, columns=["t", "tarih", "giris", "gun", "getiri", "fazla", "cikis"])
    L.append("\n== ISLEM SIMULASYONU: alim fazina girince al, faz bitince (BEKLE/DAGITIM) ya da 120 gunde sat")
    if len(T):
        L.append(f"islem {len(T)} | ort sure {T.gun.mean():.1f} gun | getiri ort {T.getiri.mean():+.2f} medyan {T.getiri.median():+.2f} | "
                 f"endekse gore fazla ort {T.fazla.mean():+.2f} medyan {T.fazla.median():+.2f} | kazanan (fazla>0) %{100*(T.fazla>0).mean():.1f} | "
                 f"mutlak kazanan %{100*(T.getiri>0).mean():.1f}")
        for g, G in T.groupby("giris"):
            L.append(f"  giris {g:11s} n={len(G)} sure {G.gun.mean():.1f} fazla ort {G.fazla.mean():+.2f} medyan {G.fazla.median():+.2f} kazanan %{100*(G.fazla>0).mean():.1f}")
        for g, G in T.groupby("cikis"):
            L.append(f"  cikis {g:15s} n={len(G)} sure {G.gun.mean():.1f} fazla ort {G.fazla.mean():+.2f} kazanan %{100*(G.fazla>0).mean():.1f}")
        kz = T.fazla[T.fazla > 0].mean(); ky = T.fazla[T.fazla <= 0].mean()
        L.append(f"  ort kazanc {kz:+.2f} / ort kayip {ky:+.2f}")
        T.to_csv(R / f"islemler_{etiket}.csv", index=False)
        # hisse bazli gecmis basari filtresi (yuruyen: sadece o tarihe kadar KAPANMIS islemler)
        T = T.sort_values("tarih").reset_index(drop=True)
        T["bitis"] = T["tarih"] + pd.to_timedelta(T["gun"] * (7 if tf == "W" else 1.45), unit="D")
        for nmin, esik in ((3, 0.5), (5, 0.5), (3, 0.6)):
            sec = []
            for k2, row in T.iterrows():
                G = T[(T.t == row.t) & (T.bitis < row.tarih)]
                if len(G) >= nmin and (G.fazla > 0).mean() >= esik:
                    sec.append(k2)
            S = T.loc[sec]
            if len(S):
                L.append(f"  HISSE GECMIS BASARI FILTRESI (en az {nmin} eski islem, basari >= %{int(esik*100)}): n={len(S)} fazla ort {S.fazla.mean():+.2f} medyan {S.fazla.median():+.2f} kazanan %{100*(S.fazla>0).mean():.1f} | en iyi %5 haric ort {S.fazla[S.fazla <= S.fazla.quantile(.95)].mean():+.2f}")
        L.append(f"  TUM ISLEMLER en iyi %5 haric ort {T.fazla[T.fazla <= T.fazla.quantile(.95)].mean():+.2f}")
    txt = "\n".join(L)
    (R / f"sonuc_{etiket}.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
