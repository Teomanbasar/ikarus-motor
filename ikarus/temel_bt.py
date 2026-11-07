"""Temel (F-skoru) geriye donuk testi: "ucuz + temeli guclu" hisseler "ucuz ama zayif"lardan iyi gitti mi?

Her ay sonu (olusum tarihi) her hisse icin:
  - o tarihte YAYIMLANMIS en son bilancoyla F-skoru (yayin gecikmesi: 4. ceyrek +100 gun, digerleri +75 gun)
  - IKARUS Percentile (o gunun M3'uyle) ve sinyal
  - sonraki 63 / 126 islem gunu getirisi, BIST100'e gore fazla getiri
Gruplar karsilastirilir. Aylik esit agirlikli ortalama da verilir (ayni aydaki kalabalik bir grubun sonucu ezmesini onler).
Cikti: temel/bt_sonuc.txt, temel/bt_olaylar.csv.gz
"""
from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd

from . import data as D
from . import engine as E
from . import temel as T

R = D.ROOT / "temel"
H = (63, 126)


def yayin(y, m):
    son = pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
    return son + pd.Timedelta(days=100 if m == 12 else 75)


def skorlar(G, m3):
    """{hisse: DataFrame(index=yayin tarihi, puan, tip, donem)}"""
    out = {}
    for h, g in G.items():
        tab = {tuple(map(int, k.split("/"))): v for k, v in g["tab"].items()}
        rows = []
        for d in sorted(tab):
            alt = {k: v for k, v in tab.items() if k <= d}
            try:
                s = T.skor(g["grup"], alt, m3, d=d)
            except Exception:
                s = None
            if not s or "maddeler" not in s or s["olculen"] < s["en_fazla"] - 1:
                continue
            o = s.get("oranlar", {})
            rows.append({"yayin": yayin(*d), "puan": s["puan"], "olculen": s["olculen"], "tip": s["tip"],
                         "donem": f"{d[0]}/{d[1]:02d}", "roe": o.get("roe"), "reel": o.get("ozkaynak_reel_buyume"),
                         "nk_poz": bool(s["maddeler"][0]["gecti"])})
        if rows:
            out[h] = pd.DataFrame(rows).set_index("yayin").sort_index()
    return out


def main(surum=None):
    if surum is not None:
        T.SURUM = surum
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    m3 = D.m3()
    S = skorlar(G, m3)
    print(f"skorlu hisse {len(S)}")
    px = D.prices(sorted(S))
    xu = D.xu100()
    aylar = pd.date_range("2021-01-31", pd.Timestamp.today(), freq="ME")
    rows = []
    for i, (t, df) in enumerate(sorted(px.items())):
        if t not in S or len(df) < 300:
            continue
        try:
            r = E.compute(df, xu, m3, "D")
        except Exception as e:
            print("atlandi", t, e); continue
        c = df["close"].reindex(r.index).values
        x = xu.reindex(r.index).ffill().values
        tl = (df["close"] * df["volume"]).rolling(20).mean().reindex(r.index).values
        idx = r.index
        sk = S[t]
        for a in aylar:
            j = idx.searchsorted(a, side="right") - 1   # ay sonundaki son islem gunu
            if j < 250 or idx[j] < a - pd.Timedelta(days=7):
                continue
            gec = sk[sk.index <= idx[j]]
            if gec.empty:
                continue
            k = gec.iloc[-1]
            if (idx[j] - gec.index[-1]).days > 400:   # cok eski bilanco
                continue
            row = {"tarih": idx[j], "t": t, "puan": k["puan"], "tip": k["tip"], "donem": k["donem"],
                   "roe": k["roe"], "reel": k["reel"], "nk_poz": k["nk_poz"],
                   "pct": r["percentile"].iloc[j], "sinyal": r["sinyal"].iloc[j], "toplam": r["toplam"].iloc[j], "hacim_tl": tl[j]}
            for h in H:
                if j + h < len(c):
                    row[f"r{h}"] = 100 * (c[j + h] / c[j] - 1)
                    row[f"a{h}"] = 100 * (c[j + h] / c[j] - x[j + h] / x[j])
            rows.append(row)
        if i % 100 == 0:
            print(i, t, len(rows))
    A = pd.DataFrame(rows)
    A = A[A["hacim_tl"] > 5e6]
    A.to_csv(R / "bt_olaylar.csv.gz", index=False, compression="gzip")

    L = []

    def ozet(ad, X):
        s = [f"{ad:34s}", f"n={len(X):5d}"]
        for h in H:
            a = X[f"a{h}"].dropna()
            if len(a) < 10:
                s.append(f"{h}g: -"); continue
            lo, hi = a.quantile([0.05, 0.95])
            kirp = a[(a >= lo) & (a <= hi)].mean()
            aylik = X.dropna(subset=[f"a{h}"]).groupby("tarih")[f"a{h}"].mean()
            s.append(f"{h}g: ort {a.mean():+6.1f} medyan {a.median():+6.1f} kirpik {kirp:+6.1f} "
                     f"kazanma %{100 * (a > 0).mean():4.1f} aylik-ort {aylik.mean():+6.1f} (ay {len(aylik)}, aylarin %{100 * (aylik > 0).mean():3.0f}'i +)")
        L.append(" | ".join(s))

    sn = A[A["tip"] == "sanayi"]
    bk = A[A["tip"] == "banka"]
    L.append("TEMEL (F-SKORU) GERIYE DONUK TEST — getiriler BIST100'e gore fazla getiri (%), 63g ~3 ay, 126g ~6 ay")
    L.append(f"Donem {A['tarih'].min():%Y-%m} - {A['tarih'].max():%Y-%m} | ay sonu olusum | {A['t'].nunique()} hisse | "
             f"bilanco yayin gecikmesi: Q4 +100 gun, diger +75 gun | gunluk ort. hacim > 5 mn TL")
    L.append("kirpik = en iyi/en kotu %5 atilmis ortalama (piyango hisselerin etkisini ayiklar)")
    L.append("\n== Sanayi/hizmet: F-skoru dilimleri (tum hisseler)")
    ozet("hepsi", sn)
    for lo, hi, ad in [(0, 3, "F 0-3 (zayif)"), (4, 5, "F 4-5"), (6, 6, "F 6"), (7, 7, "F 7"), (8, 9, "F 8-9 (guclu)")]:
        ozet(ad, sn[(sn["puan"] >= lo) & (sn["puan"] <= hi)])
    L.append("\n== UCUZ (IKARUS Percentile <= 20) icinde F-skoru")
    U = sn[sn["pct"] <= 20]
    ozet("ucuz hepsi", U)
    ozet("ucuz + F 0-4 (zayif)", U[U["puan"] <= 4])
    ozet("ucuz + F 5-6", U[U["puan"].between(5, 6)])
    ozet("ucuz + F >= 7 (guclu)", U[U["puan"] >= 7])
    ozet("ucuz + F >= 8", U[U["puan"] >= 8])
    ozet("ucuz + zararda", U[~U["nk_poz"].astype(bool)])
    L.append("\n== PAHALI (Percentile >= 80) icinde F-skoru")
    P = sn[sn["pct"] >= 80]
    ozet("pahali hepsi", P)
    ozet("pahali + F 0-4", P[P["puan"] <= 4])
    ozet("pahali + F >= 7", P[P["puan"] >= 7])
    L.append("\n== Tek kalemler (sanayi, tum hisseler)")
    ozet("ozkaynak M3'ten hizli (reel > 0)", sn[sn["reel"] > 0])
    ozet("ozkaynak M3'ten yavas (reel <= 0)", sn[sn["reel"] <= 0])
    ozet("ROE >= %25", sn[sn["roe"] >= 0.25])
    ozet("ROE < %5", sn[sn["roe"] < 0.05])
    ozet("zararda", sn[~sn["nk_poz"].astype(bool)])
    L.append("\n== IKARUS sinyali x temel (2023-07 sonrasi; MTF icin yeterli gecmis)")
    Z = sn[sn["tarih"] >= "2023-07-01"]
    al = Z[Z["sinyal"].isin(["ALINABILIR", "TOPLANIYOR"])]
    ozet("ALINABILIR/TOPLANIYOR hepsi", al)
    ozet("  + F >= 7", al[al["puan"] >= 7])
    ozet("  + F <= 4", al[al["puan"] <= 4])
    L.append("\n== Bankalar (5 madde)")
    ozet("banka hepsi", bk)
    ozet("banka puan >= 4", bk[bk["puan"] >= 4])
    ozet("banka puan <= 2", bk[bk["puan"] <= 2])
    L.append("\n== Yillara gore, ucuz icinde (126g fazla getiri, kirpiksiz ortalama / medyan)")
    for y in sorted(set(U["tarih"].dt.year)):
        Y = U[U["tarih"].dt.year == y]
        g, z = Y[Y["puan"] >= 7]["a126"].dropna(), Y[Y["puan"] <= 4]["a126"].dropna()
        L.append(f"{y}: F>=7 ort {g.mean():+6.1f} medyan {g.median():+6.1f} (n={len(g)}) | F<=4 ort {z.mean():+6.1f} medyan {z.median():+6.1f} (n={len(z)})")
    txt = "\n".join(L)
    (R / ("bt_sonuc.txt" if surum is None else f"bt_sonuc_v{surum}.txt")).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
