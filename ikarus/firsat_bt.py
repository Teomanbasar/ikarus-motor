"""Firsatlar + faz motoru islem simulasyonu (12 Kas 2026, Teoman: "faz motoru yeni firsatlar mantigiyla kar ettirir mi?").

Her gun, her hisse icin o gun BILINEN son bilanco (yayin varsayimi: Q4 +100, digerleri +75 gun) ile:
  firsat = temel puan (esit agirlik) donem kesitinin en ust %20'si + kotu surpriz degil
           + IKARUS Percentile <= 20 + son 20 gunde endekse gore <= +%10 + son 5 gunde <= +%15
Islem: sinyal gununun ertesi kapanisinda al, cikis sinyalinin ertesi kapanisinda sat. Hisse basina ayni anda tek islem.
Maliyet: gidis-donus %0.3 dusulur. Getiri BIST100'e gore fazla getiri (%).
Cikti: temel/fbt_sonuc.txt, temel/fbt_islemler.csv.gz
"""
from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd

from . import data as D
from . import engine as E
from . import temel_bt2 as B

R = D.ROOT / "temel"
MALIYET = 0.3
AL = ("ALINABILIR", "TOPLANIYOR", "YAKIN")


# 22 Kas: deger bileseni secenekleri (test icin). "kar" = canli (net kar / PD ve PD/DD).
DEGERLER = {"kar": ["kaz_get", "pddd"], "faal": ["fv_get", "pddd"], "kar+faal": ["kaz_get", "fv_get", "pddd"],
            "favok": ["fav_get", "pddd"], "faal_tek": ["fv_get"]}
DEGER = "favok"   # 22 Kas: canli da bu
DEGERLER["favok+sna"] = ["fav_get", "sna_get", "pddd"]
KALITELER = {"canli": ["F", "roe"], "roic": ["F", "roic"], "nakit": ["F", "roe", "nakit_kal"], "roic+nakit": ["F", "roic", "nakit_kal"]}
KALITE = "canli"
HAM_DONDUR = False
DEGER_AGIRLIK = 1.0
DEGERLER.update({"kar_pk": ["kaz_pk", "pddd"], "kar_pk2": ["kaz_pk2", "pddd"], "yok": [], "pddd": ["pddd"], "favok+pk": ["fav_get", "kaz_pk", "pddd"]})


def _ok(v):
    return v is not None and not (isinstance(v, float) and np.isnan(v))


def puanlar(O, px):
    """Her bilanco olayina giris gunu fiyatiyla deger olcutleri, sonra donem kesitinde siralama."""
    rows = []
    for _, e in O.iterrows():
        df = px.get(e["t"])
        if df is None or e["tip"] != "sanayi":
            continue
        j = df.index.searchsorted(e["yayin"], side="right")
        if j >= len(df) or j < 1:
            continue
        mcap = float(df["close"].iloc[j - 1]) * (e["sermaye_son"] or np.nan)
        r = e.to_dict()
        r["giris"] = df.index[j]
        r["pddd"] = mcap / e["oz"] if e.get("oz") and e["oz"] > 0 else np.nan
        r["kaz_get"] = e["nk_ttm"] / mcap if e.get("nk_ttm") is not None and mcap > 0 else np.nan
        nb = e.get("netborc")
        ev = mcap + nb if nb is not None and not pd.isna(nb) else np.nan
        r["fv_get"] = e["fk_ttm"] / ev if e.get("fk_ttm") is not None and not pd.isna(e.get("fk_ttm")) and ev > 0 else np.nan
        r["fav_get"] = e["favok_ttm"] / ev if e.get("favok_ttm") is not None and not pd.isna(e.get("favok_ttm")) and ev > 0 else np.nan
        r["sna_get"] = e["sna_ttm"] / ev if _ok(e.get("sna_ttm")) and ev > 0 else np.nan
        nk_, fn_, va_ = e.get("nk_ttm"), e.get("fnakit_ttm"), e.get("varlik")
        r["nakit_kal"] = (fn_ - nk_) / va_ if _ok(nk_) and _ok(fn_) and _ok(va_) and va_ > 0 else np.nan
        ic = (e.get("oz") or np.nan) + (nb if _ok(nb) else np.nan)
        r["roic"] = e["favok_ttm"] / ic if _ok(e.get("favok_ttm")) and ic > 0 else np.nan
        for k_ in ("pk_ttm", "pk2_ttm"):
            pk = e.get(k_)
            r["kaz_" + k_[:-4]] = (e["nk_ttm"] - 0.75 * (pk if _ok(pk) else 0.0)) / mcap if _ok(e.get("nk_ttm")) and mcap > 0 else np.nan
        rows.append(r)
    A = pd.DataFrame(rows)
    g = A.groupby("donem")
    q = {}
    for f in ["sue_nk", "sue_faal", "satis_reel", "roe_ivme", "kaz_get", "roe", "F", "fv_get", "fav_get", "sna_get", "nakit_kal", "roic", "kaz_pk", "kaz_pk2"]:
        q[f] = g[f].rank(pct=True)
    q["pddd"] = 1 - g["pddd"].rank(pct=True)
    H4 = pd.concat([q["sue_nk"], q["sue_faal"], q["satis_reel"], q["roe_ivme"]], axis=1)
    h = H4.mean(axis=1).where(H4.notna().sum(axis=1) >= 2)
    k = pd.concat([q[x] for x in KALITELER[KALITE]], axis=1).mean(axis=1)
    d = pd.concat([q[k] for k in DEGERLER[DEGER]], axis=1).mean(axis=1) if DEGERLER[DEGER] else None
    A["v3"] = (h + k) / 2 if d is None or DEGER_AGIRLIK == 0 else (h + k + DEGER_AGIRLIK * d) / (2 + DEGER_AGIRLIK)
    A["v3r"] = A["v3"].groupby(A["donem"]).rank(pct=True)
    A["kotu"] = (q["sue_nk"] <= 0.2) & (q["sue_faal"] <= 0.2)
    if HAM_DONDUR:
        return A
    return A[["t", "donem", "giris", "v3r", "kotu"]]


def simule(t, idx, c, x, giris_m, cikis_f, maxb=126):
    """giris_m: bool dizi (o gun giris sinyali). cikis_f(i, j0) -> neden ya da None."""
    out = []
    i = 1
    n = len(c)
    while i < n - 1:
        if giris_m[i] and not giris_m[i - 1]:
            j0 = i + 1                      # ertesi kapanista al
            k = j0 + 1
            neden = None
            while k < n - 1:
                neden = cikis_f(k, j0)
                if neden or k - j0 >= maxb:
                    neden = neden or "sure"
                    break
                k += 1
            if k >= n - 1:
                break                         # acik islem, sayma
            s = k + 1                         # ertesi kapanista sat
            r = 100 * (c[s] / c[j0] - 1) - MALIYET
            xr = 100 * (x[s] / x[j0] - 1)
            out.append((t, idx[j0], s - j0, r, r - xr, neden))
            i = s
        i += 1
    return out


def main():
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    m3 = D.m3()
    O = B.olaylar(G, m3)
    px = D.prices(sorted(O["t"].unique()))
    xu = D.xu100()
    P = puanlar(O, px)
    print("puanli olay", len(P))
    ISL = {}
    SURE = []
    for n_, (t, df) in enumerate(sorted(px.items())):
        ev = P[P["t"] == t].sort_values("giris")
        if ev.empty or len(df) < 300:
            continue
        try:
            r46 = E.compute(df, xu, m3, "D")
            rfz = E.compute(df, xu, m3, "D", sig_mod="faz")
            rha = E.compute(df, xu, m3, "D", ha=True, sig_mod="faz")
        except Exception:
            continue
        idx = r46.index
        c = r46["close"].values.astype(float)
        x = xu.reindex(idx).ffill().values
        pct = r46["percentile"].values
        s46 = r46["sinyal"].values
        sfz = rfz["sinyal"].values
        vol = (df["close"] * df["volume"]).reindex(idx).rolling(20).mean().values
        # o gun bilinen son bilanco
        gv = ev["giris"].values.astype("datetime64[ns]")
        k = np.searchsorted(gv, idx.values.astype("datetime64[ns]"), side="right") - 1
        kk = np.clip(k, 0, None)
        v3r = np.where(k >= 0, ev["v3r"].values[kk].astype(float), np.nan)
        kotu = np.where(k >= 0, ev["kotu"].values[kk].astype(bool), False)
        yas = np.where(k >= 0, (idx.values.astype("datetime64[ns]") - gv[kk]) / np.timedelta64(1, "D"), 9999)
        guncel = yas <= 200
        cs = pd.Series(c)
        o5 = (100 * (cs / cs.shift(5) - 1)).values
        o20x = (100 * (cs / cs.shift(20) - 1) - 100 * (pd.Series(x) / pd.Series(x).shift(20) - 1)).values
        temel_ok = guncel & (v3r >= 0.8) & ~kotu
        o20 = (100 * (cs / cs.shift(20) - 1)).values
        gun = cs.pct_change()
        taban10 = (gun <= -0.095).rolling(10).sum().fillna(0).values
        tarih_ok = idx >= pd.Timestamp("2020-09-01")
        kacmamis = (o20x <= 10) & (o5 <= 15)
        cokus_ok = (o20 >= -25) & (taban10 < 2)                       # canlidaki filtre (12 Kas)
        cokus_rel = (o20x >= -25) & ~((taban10 >= 4) & (o20x < -15))   # oneri: endekse gore
        baz = temel_ok & (pct <= 20) & kacmamis & (vol > 5e6) & tarih_ok
        firsat = baz & cokus_ok
        firsat_rel = baz & cokus_rel
        firsat_yok = baz
        pct_ha = rha["percentile"].reindex(idx).values
        sha = rha["sinyal"].reindex(idx).values
        firsat_ha = temel_ok & (pct_ha <= 20) & kacmamis & (vol > 5e6) & tarih_ok & cokus_rel
        ha_al = np.isin(sha, AL)
        fz_al = np.isin(sfz, AL)
        v46_al = np.isin(s46, AL)
        bozuldu = lambda i: (not guncel[i]) or v3r[i] < 0.6 or kotu[i]
        var = {
            "A Firsat, 63 gun tut": (firsat, lambda i, j0: None, 63),
            "B Firsat, temel bozulunca ya da 126 gun": (firsat, lambda i, j0: "temel" if bozuldu(i) else None, 126),
            "C Firsat, -%15 stop + temel bozulma, 126 gun": (firsat, lambda i, j0: "stop" if c[i] < c[j0] * 0.85 else ("temel" if bozuldu(i) else None), 126),
            "D Firsat, faz DAGITIM/BEKLE cikisi": (firsat, lambda i, j0: sfz[i] if sfz[i] in ("DAGITIM", "BEKLE") else None, 126),
            "D2 Firsat, yalniz faz DAGITIM cikisi": (firsat, lambda i, j0: "DAGITIM" if sfz[i] == "DAGITIM" else None, 126),
            "D3 Firsat, faz DAGITIM ya da -%15 stop": (firsat, lambda i, j0: "stop" if c[i] < c[j0] * 0.85 else ("DAGITIM" if sfz[i] == "DAGITIM" else None), 126),
            "E2 Firsat + faz alim, yalniz faz DAGITIM cikisi": (firsat & fz_al, lambda i, j0: "DAGITIM" if sfz[i] == "DAGITIM" else None, 126),
            "G2 Firsat, yalniz gunluk v46 DAGITIM cikisi": (firsat, lambda i, j0: "DAGITIM" if s46[i] == "DAGITIM" else None, 126),
            "E Firsat + faz alim, faz cikisi": (firsat & fz_al, lambda i, j0: sfz[i] if sfz[i] in ("DAGITIM", "BEKLE") else None, 126),
            "F Firsat + faz alim, temel bozulunca/126": (firsat & fz_al, lambda i, j0: "temel" if bozuldu(i) else None, 126),
            "G Firsat, gunluk v46 DAGITIM/BEKLE cikisi": (firsat, lambda i, j0: s46[i] if s46[i] in ("DAGITIM", "BEKLE") else None, 126),
            "F-rel Firsat(cokus endekse gore) + faz alim, temel/126": (firsat_rel & fz_al, lambda i, j0: "temel" if bozuldu(i) else None, 126),
            "F-yok Firsat(cokus filtresiz) + faz alim, temel/126": (firsat_yok & fz_al, lambda i, j0: "temel" if bozuldu(i) else None, 126),
            "B-rel Firsat(cokus endekse gore), temel/126": (firsat_rel, lambda i, j0: "temel" if bozuldu(i) else None, 126),
            "HA1 Firsat(HA pct) + HA faz alim, temel/126": (firsat_ha & ha_al, lambda i, j0: "temel" if bozuldu(i) else None, 126),
            "HA2 Firsat(normal) + HA faz alim, temel/126": (firsat_rel & ha_al, lambda i, j0: "temel" if bozuldu(i) else None, 126),
            "HA3 Firsat(normal) + HA faz alim + normal faz alim, temel/126": (firsat_rel & ha_al & fz_al, lambda i, j0: "temel" if bozuldu(i) else None, 126),
            "HA4 Firsat(normal) + HA faz alim, HA DAGITIM cikisi": (firsat_rel & ha_al, lambda i, j0: "DAGITIM" if sha[i] == "DAGITIM" else None, 126),
            "H Temelsiz: faz alim, faz cikisi": (fz_al & tarih_ok & (vol > 5e6), lambda i, j0: sfz[i] if sfz[i] in ("DAGITIM", "BEKLE") else None, 126),
            "I Temelsiz: Percentile<=20 + fiyat kacmamis, 63 gun": ((pct <= 20) & (o20x <= 10) & (o5 <= 15) & tarih_ok & (vol > 5e6), lambda i, j0: None, 63),
            "J Temel ust %20 (ucuzluk sartsiz), 63 gun": (temel_ok & tarih_ok & (vol > 5e6) & (o20x <= 10) & (o5 <= 15), lambda i, j0: None, 63),
        }
        # --- 15 Kas: listede kalma suresi ve teknik cikislar
        dstop = r46["d_stop"].values if "d_stop" in r46 else np.zeros(len(idx))
        def kosu(arr):
            o = np.zeros(len(arr)); c_ = 0
            for i_, v_ in enumerate(arr):
                c_ = c_ + 1 if v_ else 0; o[i_] = c_
            return o
        fz_dag = kosu(sfz == "DAGITIM"); ha_dag = kosu(sha == "DAGITIM")
        fa = np.asarray(firsat_rel & fz_al, bool)
        fr = np.asarray(firsat_rel, bool)
        # listede kesintisiz kalma suresi (gun)
        k_ = kosu(fr)
        for i_ in range(1, len(fr)):
            if fr[i_ - 1] and not fr[i_]:
                SURE.append(k_[i_ - 1])
        stop_k = lambda i: dstop[i] <= -3.5
        tem = lambda i: bozuldu(i)
        var.update({
            "K1 Firsat+faz gir, Firsatlar'dan cikinca sat": (fa, lambda i, j0: "listeden cikti" if not fr[i] else None, 252),
            "K2 Firsat gir (fazsiz), Firsatlar'dan cikinca sat": (fr, lambda i, j0: "listeden cikti" if not fr[i] else None, 252),
            "K3 Firsat+faz gir, listeden 5 gun ust uste cikinca sat": (fa, lambda i, j0: "listeden 5g" if (i >= 5 and not fr[i - 4:i + 1].any()) else None, 252),
            "T1 F + Stop kirilinca (-%3.5) ya da temel": (fa, lambda i, j0: "stop" if stop_k(i) else ("temel" if tem(i) else None), 252),
            "T2 F + pahali bolge (Percentile>=80, kar al) ya da temel": (fa, lambda i, j0: "pahali" if pct[i] >= 80 else ("temel" if tem(i) else None), 252),
            "T3 F + faz DAGITIM 10 gun surerse ya da temel": (fa, lambda i, j0: "faz10" if fz_dag[i] >= 10 else ("temel" if tem(i) else None), 252),
            "T4 F + HA faz DAGITIM 10 gun surerse ya da temel": (fa, lambda i, j0: "ha10" if ha_dag[i] >= 10 else ("temel" if tem(i) else None), 252),
            "T5 F + faz DAGITIM 20 gun ya da temel": (fa, lambda i, j0: "faz20" if fz_dag[i] >= 20 else ("temel" if tem(i) else None), 252),
            "T6 F + stop ya da pahali ya da temel": (fa, lambda i, j0: "stop" if stop_k(i) else ("pahali" if pct[i] >= 80 else ("temel" if tem(i) else None)), 252),
            "T7 F + pahali ya da faz DAGITIM 10g ya da temel": (fa, lambda i, j0: "pahali" if pct[i] >= 80 else ("faz10" if fz_dag[i] >= 10 else ("temel" if tem(i) else None)), 252),
            "T8 F + temel ya da 252 gun (6 ay yerine 1 yil)": (fa, lambda i, j0: "temel" if tem(i) else None, 252),
        })
        for ad, (m, f, mb) in var.items():
            ISL.setdefault(ad, []).extend(simule(t, idx, c, x, np.asarray(m, bool), f, mb))
        if n_ % 100 == 0:
            print(n_, t, {k_[:1]: len(v) for k_, v in ISL.items()})
    L = ["FIRSATLAR + FAZ MOTORU ISLEM SIMULASYONU (12 Kas 2026)",
         "Sinyalin ertesi kapanisinda al, cikis sinyalinin ertesi kapanisinda sat; %0.3 maliyet dusuldu; fazla = BIST100'e gore.",
         "kirpik = en iyi/kotu %5 atilmis ortalama. 'gunluk' = islem basina fazla getiri / sure (islem gunu), yaklasik hiz.\n"]
    if SURE:
        sr = pd.Series(SURE)
        L.append(f"Firsatlar listesinde kesintisiz kalma suresi (islem gunu): n={len(sr)} medyan {sr.median():.0f} ort {sr.mean():.1f} | 1 gun %{100*(sr<=1).mean():.0f} | <=5 gun %{100*(sr<=5).mean():.0f} | >20 gun %{100*(sr>20).mean():.0f}\n")
    tum = []
    XU20 = (100 * (xu / xu.shift(20) - 1))
    kriz = XU20[XU20 <= -10]
    L.append("Kriz gunleri (BIST100 20 gunde -%10+): " + ", ".join(f"{p}: {n} gun" for p, n in kriz.groupby(kriz.index.to_period("M")).size().items()) + "\n")
    for ad, I in ISL.items():
        T = pd.DataFrame(I, columns=["t", "giris", "gun", "getiri", "fazla", "cikis"])
        T["varyant"] = ad
        tum.append(T)
        if len(T) < 10:
            L.append(f"{ad}: n={len(T)}"); continue
        lo, hi = T.fazla.quantile([.05, .95])
        kp = T.fazla[(T.fazla >= lo) & (T.fazla <= hi)].mean()
        L.append(f"{ad:48s} n={len(T):5d} sure {T.gun.mean():5.1f}g | fazla ort {T.fazla.mean():+6.2f} kirpik {kp:+6.2f} medyan {T.fazla.median():+6.2f} "
                 f"| kazanan %{100 * (T.fazla > 0).mean():4.1f} | ham getiri medyan {T.getiri.median():+6.2f} | gunluk kirpik {kp / max(T.gun.mean(), 1):+.3f}")
        yl = T.groupby(T.giris.dt.year).fazla.agg(["count", "median", lambda s: s.clip(s.quantile(.05), s.quantile(.95)).mean()])
        L.append("    yillar: " + " | ".join(f"{y}: n={int(r_['count'])} kirpik {r_.iloc[2]:+.1f} med {r_['median']:+.1f}" for y, r_ in yl.iterrows()))
        xr20 = T.giris.map(XU20)
        L.append("    piyasa (giris oncesi 20g BIST100): " + " | ".join(
            f"{nm} n={len(g_)} kirpik {g_.fazla.clip(g_.fazla.quantile(.05), g_.fazla.quantile(.95)).mean():+.1f} med {g_.fazla.median():+.1f} ham med {g_.getiri.median():+.1f}"
            for nm, g_ in [("kriz <=-10%", T[xr20 <= -10]), ("dusus -10..-3", T[(xr20 > -10) & (xr20 <= -3)]), ("normal >-3", T[xr20 > -3])] if len(g_) >= 5))
        L.append("    cikis: " + " | ".join(f"{k_} n={len(g_)} ort {g_.fazla.mean():+.1f}" for k_, g_ in T.groupby("cikis")))
    pd.concat(tum).to_csv(R / "fbt_islemler.csv.gz", index=False, compression="gzip")
    txt = "\n".join(L)
    (R / "fbt_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
