"""Temel isaretler testi v2 (10 Kas 2026): hangi bilanco isaretleri hareketi onceden yakaliyor?

Olay = her hissenin her ceyrek bilancosunun YAYIMLANDIGI varsayilan gun (Q4 +100 gun, digerleri +75 gun;
gercek aciklama tarihlerini bilmedigimiz icin temkinli: gercekte cogu sirket daha erken aciklar,
yani olcululen getiri hareketin bir kismini kaciriyor olabilir ama gelecegi gorme hatasi yapmaz).
Giris = yayin gununden sonraki ilk islem gunu. Getiri = BIST100'e gore fazla getiri, 21/63/126 islem gunu.

Isaretler (her donemde ayni anda yayimlanan hisseler kendi aralarinda 5 dilime ayrilir):
  Kalite : F-skoru (mevcut 9 madde)
  Deger uretimi: ROE (son 4 ceyrek), ROE degisimi, ozkaynak M3'e gore buyume (1 ve 3 yil)
  Hareket: kar surprizi (ceyreklik net kar ve esas faaliyet kari, gecen yilin ayni ceyregine gore, M3 ile
           duzeltilmis, hissenin kendi oynakligiyla olceklenmis), kar ivmesi (ROE'nin bir ceyrekte degisimi),
           satis reel buyumesi, zarardan kara / nakit eksiden artiya donus
  Ucuzluk: PD/DD (kesitte ve hissenin kendi gecmisine gore), kazanc getirisi (kar / piyasa degeri),
           IKARUS Percentile (M3 bandi)
Piyasa degeri yaklasik: duzeltilmis fiyat x bugunku odenmis sermaye (1 TL nominal pay).
Cikti: temel/bt2_sonuc.txt, temel/bt2_olaylar.csv.gz
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
H = (21, 63, 126)


def yayin(y, m):
    son = pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
    return son + pd.Timedelta(days=100 if m == 12 else 75)


def onceki(d, n=1):
    y, m = d
    for _ in range(n):
        m -= 3
        if m <= 0:
            m += 12; y -= 1
    return (y, m)


def ceyreklik(tab, d, kod):
    """Yalniz o ceyregin akim degeri (tablolar yil ici kumulatif)."""
    y, m = d
    a = tab.get(d, {}).get(kod)
    if a is None:
        return None
    if m == 3:
        return a
    p = tab.get((y, m - 3), {}).get(kod)
    return None if p is None else a - p


def olaylar(G, m3):
    rows = []
    for h, g in G.items():
        tab = {tuple(map(int, k.split("/"))): v for k, v in g["tab"].items()}
        donem = sorted(tab)
        if len(donem) < 6:
            continue
        sermaye_son = None
        for d in reversed(donem):
            s = tab[d].get("2OA")
            if s and s > 0:
                sermaye_son = s; break
        for d in donem:
            alt = {k: v for k, v in tab.items() if k <= d}
            try:
                s = T.skor(g["grup"], alt, m3, d=d)
            except Exception:
                s = None
            row = {"t": h, "donem": f"{d[0]}/{d[1]:02d}", "yayin": yayin(*d), "tip": "banka" if g["grup"] == "UFRS" else "sanayi"}
            if s and "maddeler" in s and s["olculen"] >= s["en_fazla"] - 1:
                o = s.get("oranlar", {})
                row.update({"F": s["puan"], "roe": o.get("roe"), "oz_reel1": o.get("ozkaynak_reel_buyume"),
                            "nk_reel": o.get("net_kar_reel_buyume")})
            d1 = (d[0] - 1, d[1])
            row.update(T.isaretler(tab, m3, d))
            # ozkaynak 3 yillik reel buyume (yillik ortalama)
            d3 = (d[0] - 3, d[1])
            oz0 = tab.get(T._bilanco_donemi(tab, d), {}).get("2O")
            oz3 = tab.get(T._bilanco_donemi(tab, d3), {}).get("2O") if d3 in tab else None
            m3_3 = T._m3_oran(m3, d, d3)
            if oz0 and oz3 and oz3 > 0 and oz0 > 0 and m3_3:
                row["oz_reel3"] = (oz0 / oz3 / m3_3) ** (1 / 3) - 1
            row["oz"] = oz0
            row["sermaye_son"] = sermaye_son
            # 22 Kas: "asil F/K" icin faaliyet kari ve net borc (parasal kazanc/kur/faiz faaliyet karinin altinda kalir)
            b = tab.get(T._bilanco_donemi(tab, d), {})
            if any(b.get(k) is not None for k in ("2AA", "2BA", "1AA")):
                row["netborc"] = (b.get("2AA") or 0) + (b.get("2BA") or 0) - (b.get("1AA") or 0) - (b.get("1AB") or 0)
            fk = T._ttm(tab, d, "3DF"); am = T._ttm(tab, d, "4B")
            row["fk_ttm"] = fk
            row["favok_ttm"] = fk + am if fk is not None and am is not None else None
            rows.append(row)
    return pd.DataFrame(rows)


def main():
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    m3 = D.m3()
    O = olaylar(G, m3)
    print("olay", len(O), "hisse", O["t"].nunique())
    px = D.prices(sorted(O["t"].unique()))
    xu = D.xu100()
    out = []
    for i, (t, df) in enumerate(sorted(px.items())):
        ev = O[O["t"] == t]
        if ev.empty or len(df) < 300:
            continue
        try:
            r = E.compute(df, xu, m3, "D")
            pct = r["percentile"]; sig = r["sinyal"]
        except Exception:
            pct = sig = None
        idx = df.index
        c = df["close"].values
        x = xu.reindex(idx).ffill().values
        tl = (df["close"] * df["volume"]).rolling(20).mean().values
        for _, e in ev.iterrows():
            j = idx.searchsorted(e["yayin"], side="right")
            if j >= len(idx) or j < 250:
                continue
            row = e.to_dict()
            row["giris"] = idx[j]
            row["hacim_tl"] = tl[j - 1]
            # giristen onceki yukselis: "zaten fiyatlandi mi?"
            row["o5"] = 100 * (c[j - 1] / c[j - 6] - 1)
            row["o20"] = 100 * (c[j - 1] / c[j - 21] - 1)
            row["o20_x"] = row["o20"] - 100 * (x[j - 1] / x[j - 21] - 1)
            gun = c[j - 10:j] / c[j - 11:j - 1] - 1
            row["tavan10"] = int((gun >= 0.095).sum())
            mcap = c[j - 1] * (e["sermaye_son"] or np.nan)
            if e.get("oz") and e["oz"] > 0:
                row["pddd"] = mcap / e["oz"]
            if e.get("nk_ttm") is not None and mcap > 0:
                row["kaz_get"] = e["nk_ttm"] / mcap
            if pct is not None:
                k = pct.index.searchsorted(idx[j - 1], side="right") - 1
                if k >= 0:
                    row["ik_pct"] = float(pct.iloc[k]); row["ik_sinyal"] = sig.iloc[k]
            for hh in H:
                if j + hh < len(c):
                    row[f"r{hh}"] = 100 * (c[j + hh] / c[j - 1] - 1)
                    row[f"a{hh}"] = 100 * (c[j + hh] / c[j - 1] - x[j + hh] / x[j - 1])
            out.append(row)
        if i % 100 == 0:
            print(i, t, len(out))
    A = pd.DataFrame(out)
    A = A[(A["hacim_tl"] > 5e6) & (A["giris"] >= "2020-06-01")].copy()
    # PD/DD hissenin kendi gecmisine gore (yalniz o gune kadarki olaylar)
    A = A.sort_values(["t", "giris"])
    def kendi_pct(s):
        v = s.values; o = np.full(len(v), np.nan)
        for k in range(len(v)):
            g = v[:k + 1]; g = g[~np.isnan(g)]
            if len(g) >= 8 and not np.isnan(v[k]):
                o[k] = 100 * (g < v[k]).mean()
        return pd.Series(o, index=s.index)
    A["pddd_kendi"] = A.groupby("t", group_keys=False)["pddd"].apply(kendi_pct)
    A.to_csv(R / "bt2_olaylar.csv.gz", index=False, compression="gzip")
    rapor(A)


def rapor(A):
    L = []
    sn = A[A["tip"] == "sanayi"].copy()
    L.append("TEMEL ISARETLER TESTI v2 — BIST100'e gore fazla getiri (%), giris = varsayilan bilanco yayin gunu (Q4 +100, diger +75 gun)")
    L.append(f"Olay {len(A)} (sanayi {len(sn)}), hisse {A['t'].nunique()}, donem {A['donem'].min()}..{A['donem'].max()}, gunluk hacim > 5 mn TL")
    L.append("Her donemde hisseler isarete gore 5 dilime ayrildi (D1 en dusuk, D5 en yuksek). kirpik = en iyi/kotu %5 atilmis ortalama.")
    L.append("D5-D1 = ust dilim ile alt dilimin farki, donem donem; '+%' = farkin pozitif oldugu donem orani.\n")

    def dilim(X, f):
        X = X.dropna(subset=[f]).copy()
        X["q"] = X.groupby("donem")[f].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1 if len(s) >= 25 else np.nan)
        return X.dropna(subset=["q"])

    def kirp(a):
        a = a.dropna()
        if len(a) < 10:
            return np.nan
        lo, hi = a.quantile([0.05, 0.95])
        return a[(a >= lo) & (a <= hi)].mean()

    def faktor(ad, f, X=sn):
        Q = dilim(X, f)
        if Q.empty:
            L.append(f"{ad:30s} veri yok"); return
        s = [f"{ad:30s} n={len(Q):5d}"]
        for hh in (63, 126):
            parca = []
            for q in range(1, 6):
                a = Q[Q["q"] == q][f"a{hh}"]
                parca.append(f"{kirp(a):+5.1f}")
            fark = Q.groupby("donem").apply(lambda g: kirp(g[g["q"] == 5][f"a{hh}"]) - kirp(g[g["q"] == 1][f"a{hh}"])).dropna()
            s.append(f"{hh}g kirpik D1..D5: {' '.join(parca)} | D5-D1 {fark.mean():+5.1f} (+%{100 * (fark > 0).mean():3.0f}, {len(fark)} donem)")
        L.append(" | ".join(s))

    L.append("== Tek tek isaretler (sanayi/hizmet)")
    for ad, f in [("F-skoru (kalite)", "F"), ("ROE seviyesi", "roe"), ("ROE yillik degisim", "roe_deg"),
                  ("ROE ivmesi (1 ceyrek)", "roe_ivme"), ("Kar surprizi (net kar)", "sue_nk"),
                  ("Kar surprizi (esas faaliyet)", "sue_faal"), ("Satis reel buyume", "satis_reel"),
                  ("Ozkaynak reel buyume 1y", "oz_reel1"), ("Ozkaynak reel buyume 3y", "oz_reel3"),
                  ("Kazanc getirisi (kar/PD)", "kaz_get"), ("PD/DD (yuksek=pahali)", "pddd"),
                  ("PD/DD kendi gecmisine gore", "pddd_kendi"), ("IKARUS Percentile (M3 bandi)", "ik_pct")]:
        faktor(ad, f)

    def grup(ad, X):
        s = [f"{ad:46s} n={len(X):5d}"]
        for hh in (21, 63, 126):
            a = X[f"a{hh}"].dropna()
            if len(a) < 15:
                s.append(f"{hh}g -"); continue
            ay = X.dropna(subset=[f"a{hh}"]).groupby("donem")[f"a{hh}"].median()
            s.append(f"{hh}g kirpik {kirp(a):+5.1f} medyan {a.median():+5.1f} kazanma %{100 * (a > 0).mean():3.0f} "
                     f"(donem medyanlarinin %{100 * (ay > 0).mean():3.0f}'i +)")
        L.append(" | ".join(s))

    L.append("\n== Donusler")
    grup("hepsi (karsilastirma)", sn)
    grup("zarardan kara donus", sn[sn["kara_donus"] == 1])
    grup("faaliyet nakdi eksiden artiya", sn[sn["nakit_donus"] == 1])

    # birlesimler: donem ici siralamalar
    sn["r_sue"] = sn.groupby("donem")["sue_faal"].rank(pct=True)
    sn["r_suen"] = sn.groupby("donem")["sue_nk"].rank(pct=True)
    sn["r_ivme"] = sn.groupby("donem")["roe_ivme"].rank(pct=True)
    hareket = (sn["r_sue"] >= 0.8) | (sn["r_suen"] >= 0.8)
    guclu_hareket = (sn["r_sue"] >= 0.8) & (sn["r_suen"] >= 0.8)
    kalite = sn["F"] >= 6
    zayif = sn["F"] <= 3
    ucuz = (sn["pddd_kendi"] <= 30) | (sn["ik_pct"] <= 20)
    pahali = (sn["pddd_kendi"] >= 80) & (sn["ik_pct"] >= 70)
    L.append("\n== Birlesimler (sanayi). Hareket = esas faaliyet ya da net kar surprizi donemin en iyi %20'sinde")
    grup("hepsi", sn)
    grup("Hareket", sn[hareket])
    grup("Guclu hareket (iki surpriz de ust %20)", sn[guclu_hareket])
    grup("Hareket + kalite (F>=6)", sn[hareket & kalite])
    grup("Hareket + zayif (F<=3)", sn[hareket & zayif])
    grup("Hareket + ucuz", sn[hareket & ucuz])
    grup("Hareket + kalite + ucuz", sn[hareket & kalite & ucuz])
    grup("Guclu hareket + kalite + ucuz", sn[guclu_hareket & kalite & ucuz])
    grup("Hareket + pahali", sn[hareket & pahali])
    grup("Hareketsiz + kalite + ucuz (bekleyen)", sn[~hareket & kalite & ucuz])
    grup("Kotu surpriz (iki surpriz de alt %20)", sn[(sn["r_sue"] <= 0.2) & (sn["r_suen"] <= 0.2)])
    grup("Kotu surpriz + kalite + ucuz", sn[(sn["r_sue"] <= 0.2) & (sn["r_suen"] <= 0.2) & kalite & ucuz])
    L.append("\n== IKARUS sinyaliyle (giris gunu ALINABILIR/TOPLANIYOR/YAKIN)")
    al = sn["ik_sinyal"].isin(["ALINABILIR", "TOPLANIYOR", "YAKIN"])
    grup("IKARUS al-yakin hepsi", sn[al])
    grup("IKARUS al-yakin + hareket", sn[al & hareket])
    grup("IKARUS al-yakin + hareket + kalite", sn[al & hareket & kalite])
    grup("IKARUS al-yakin + kotu surpriz", sn[al & (sn["r_sue"] <= 0.2) & (sn["r_suen"] <= 0.2)])
    L.append("\n== Yillara gore: Hareket + kalite vs hepsi (63g kirpik)")
    for y in sorted(set(sn["giris"].dt.year)):
        Y = sn[sn["giris"].dt.year == y]
        L.append(f"{y}: hepsi {kirp(Y['a63']):+5.1f} (n={Y['a63'].notna().sum()}) | hareket+kalite {kirp(Y[hareket & kalite]['a63']):+5.1f} "
                 f"(n={Y[hareket & kalite]['a63'].notna().sum()}) | kotu surpriz {kirp(Y[(Y['r_sue'] <= 0.2) & (Y['r_suen'] <= 0.2)]['a63']):+5.1f}")
    # ---- 12 Kas: zaten fiyatlandi mi? Firsatlar testi, agirlik karsilastirmasi
    g = sn.groupby("donem")
    for f in ["sue_nk", "sue_faal", "satis_reel", "roe_ivme", "kaz_get", "roe", "F"]:
        sn["q_" + f] = g[f].rank(pct=True)
    sn["q_pddd"] = 1 - g["pddd"].rank(pct=True)
    H4 = sn[["q_sue_nk", "q_sue_faal", "q_satis_reel", "q_roe_ivme"]]
    sn["v_h"] = H4.mean(axis=1).where(H4.notna().sum(axis=1) >= 2)
    sn["v_k"] = sn[["q_F", "q_roe"]].mean(axis=1)
    sn["v_d"] = sn[["q_kaz_get", "q_pddd"]].mean(axis=1)
    def dil(v):
        return v.groupby(sn["donem"]).rank(pct=True)
    L.append("\n== Agirlik karsilastirmasi (ivme/kalite/deger): toplamin en ust %20'si")
    for ad, w in [("50/25/25 (su anki)", (.5, .25, .25)), ("33/33/33", (1 / 3, 1 / 3, 1 / 3)), ("25/25/50", (.25, .25, .5)),
                  ("25/50/25", (.25, .5, .25)), ("0/50/50 (ivmesiz)", (0, .5, .5))]:
        t = w[0] * sn["v_h"].fillna(0.5 if w[0] == 0 else np.nan) + w[1] * sn["v_k"] + w[2] * sn["v_d"]
        r = dil(t)
        grup(ad + " ust %20", sn[r >= 0.8])
    sn["v3"] = 0.5 * sn["v_h"] + 0.25 * sn["v_k"] + 0.25 * sn["v_d"]
    sn["v3r"] = dil(sn["v3"])
    kotu2 = (sn["r_sue"] <= 0.2) & (sn["r_suen"] <= 0.2)
    firsat = (sn["v3r"] >= 0.8) & al & ~kotu2
    L.append("\n== Firsatlar (temel ust %20 + IKARUS ALINABILIR/TOPLANIYOR/YAKIN + kotu surpriz degil)")
    grup("Firsatlar", sn[firsat])
    grup("Temel ust %20 + IKARUS DAGITIM/BEKLE", sn[(sn["v3r"] >= 0.8) & ~al & ~kotu2])
    L.append("\n== Zaten fiyatlandi mi? Giristen onceki 20 gunluk getiri (BIST100'e gore) dilimleri")
    for ad, m in [("Temel ust %20", sn["v3r"] >= 0.8), ("Ivme ust %20", sn["v_h"].groupby(sn["donem"]).rank(pct=True) >= 0.8), ("Firsatlar", firsat), ("hepsi", sn["v3r"].notna())]:
        X = sn[m]
        for a2, m2 in [("onceden dusmus (<-10)", X["o20_x"] < -10), ("yatay (-10..+10)", X["o20_x"].between(-10, 10)),
                       ("yukselmis (+10..+30)", X["o20_x"].between(10, 30, inclusive="right")), ("cok yukselmis (>+30)", X["o20_x"] > 30),
                       ("son 10 gunde 2+ tavan", X["tavan10"] >= 2)]:
            grup(f"{ad}: {a2}", X[m2])
    bk = A[A["tip"] == "banka"]
    L.append("\n== Bankalar")
    for ad, f in [("Kar surprizi (net kar)", "sue_nk"), ("ROE ivmesi", "roe_ivme"), ("PD/DD", "pddd")]:
        Q = bk.dropna(subset=[f])
        if len(Q) > 50:
            Q = Q.assign(ust=Q.groupby("donem")[f].rank(pct=True) >= 0.5)
            L.append(f"{ad:30s} ust yari 63g kirpik {kirp(Q[Q['ust']]['a63']):+5.1f} | alt yari {kirp(Q[~Q['ust']]['a63']):+5.1f} (n={len(Q)})")
    txt = "\n".join(L)
    (R / "bt2_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
