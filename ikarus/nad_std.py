"""Tek standart holding NAD'i: "duzeltilmis defter NAD'i" (23 Kas 2026, Teoman: 'butun holdingleri tek standarda oturtalim').

NAD_t = holdingin ana ortaklik ozkaynagi + sum_i  w_i x (istirak_i piyasa degeri_t - istirak_i ozkaynagi)
  - borsadaki istirakler piyasa degerinden, borsada olmayanlar (enflasyon duzeltmeli) defter degerinden
  - ozkaynaklar o gun BILINEN son bilancodan (yayin gecikmesi: 75 gun, yil sonu 100 gun)
  - istirak payi w: nad.json'daki araci kurum bilesimi (KCHOL/SAHOL katkilardan turetilir, AGHOL/DOHOL/LYDHO paylar),
    digerleri KAP genel bilgiler tablosu (temel/nad_genel.json) + elle duzeltmeler
  - borsada istiraki olmayan holdingde NAD = ozkaynak -> iskonto = PD/DD - 1
Test: iskontonun kendi 3y gecmisindeki yeri ve ayni gun holdingler arasindaki yeri -> sonraki 63/126 gun BIST100'e gore fazla getiri.
Gecmis seri bugunku paylarla (yaklasik). 2023 sonu TMS 29 gecisinde ozkaynaklar sicrar: donem donem ayri raporlanir.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import data as D
from . import temel as T
from .temel_bt2 import yayin

R = D.ROOT / "temel"

ELLE = {  # 23 Kas: KAP tablosunda gorunmeyen / dolayli paylar (kaynak: KAP 2026 bildirimleri)
    "ALARK": {"ALGYO": 0.5624, "ALCAR": 0.8406},
    "GLYHO": {"CONSE": 0.5099, "NTGAZ": 0.60, "GLBMD": 0.75},
    "IHLAS": {"IHYAY": 0.2396, "IHGZT": 0.0714 + 0.2396 * 0.3091, "IHLGM": 0.2107, "IHEVA": 0.2726, "IHAAS": 0.2396 * 0.4922},
    "INVES": {"VERUS": 0.6387},
    "METRO": {"MEPET": 0.4687, "VANGD": 0.031},
    "LYDHO": {"LYDYE": 0.6489, "UFUK": 0.6296},
    "TKFEN": {"AKMGY": 0.1047},
}


def _oz_serisi(tab, idx):
    """Gunluk 'o gun bilinen' ana ortaklik ozkaynagi (TL) ve sermaye (adet)."""
    pts = []
    for k, v in tab.items():
        y, m = map(int, k.split("/"))
        oz = v.get("2O")
        if oz is not None and oz == oz:
            pts.append((yayin(y, m), float(oz)))
    if not pts:
        return None
    s = pd.Series(dict(sorted(pts))).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(s.index.union(idx)).ffill().reindex(idx)


def _sermaye(tab):
    for k in sorted(tab, key=lambda x: tuple(map(int, x.split("/"))), reverse=True):
        s = tab[k].get("2OA")
        if s and s > 0:
            return float(s)
    return None


def paylar(cfg_nad, px, G):
    """holding -> {istirak: etkin pay}."""
    P = {}
    try:
        K = json.loads((R / "nad_genel.json").read_text(encoding="utf-8"))
    except Exception:
        K = {}
    for h, v in K.items():
        p = {t: (x.get("efektif") or x["oran"]) / 100 for t, x in v.get("borsada", {}).items()}
        P[h] = {t: w for t, w in p.items() if w >= 0.02}
    for h, p in ELLE.items():
        P.setdefault(h, {}).update(p)
    for h, c in cfg_nad.items():
        if h.startswith("_") or c.get("test_only"):
            continue
        if c.get("paylar"):
            P[h] = dict(c["paylar"])
        elif "halka_acik" in c:
            kt = pd.Timestamp(c.get("katki_tarih", c["ref_tarih"]))
            p = {}
            for t, katki in c["halka_acik"].items():
                if t not in px or t not in G:
                    continue
                cl = px[t]["close"].sort_index()
                cl = cl[cl.index <= kt]
                sm = _sermaye(G[t]["tab"])
                if len(cl) and sm:
                    p[t] = katki * 1e6 / (float(cl.iloc[-1]) * sm)
            P[h] = p
    return P


def seriler(holdingler, P, px, G):
    out = {}
    for h in holdingler:
        if h not in px or h not in G:
            continue
        idx = px[h]["close"].dropna().index
        ozh = _oz_serisi(G[h]["tab"], idx)
        smh = _sermaye(G[h]["tab"])
        if ozh is None or not smh:
            continue
        mch = px[h]["close"].reindex(idx) * smh
        ek = pd.Series(0.0, index=idx)
        lis = pd.Series(0.0, index=idx)
        kul = []
        for t, w in P.get(h, {}).items():
            if t not in px or t not in G:
                continue
            sm = _sermaye(G[t]["tab"]); oz = _oz_serisi(G[t]["tab"], idx)
            if not sm or oz is None:
                continue
            mc = px[t]["close"].reindex(idx).ffill() * sm
            fark = (w * (mc - oz)).where(mc.notna() & oz.notna())
            ek = ek.add(fark.fillna(0.0))
            lis = lis.add((w * mc).fillna(0.0))
            kul.append(t)
        nad = ozh + ek
        S = pd.DataFrame({"nad": nad, "pd": mch, "oz": ozh, "lis": lis}).dropna(subset=["nad", "pd"])
        S = S[(S.nad > 0) & (S.pd > 0)]
        S["iskonto"] = S.pd / S.nad - 1
        S["pddd"] = S.pd / S.oz
        out[h] = (S, kul)
    return out


def main():
    from . import portfoy_bt as PB
    cfg = json.loads((D.DATA / "nad.json").read_text(encoding="utf-8"))
    G = T.gecmis_birlesik()
    GR = PB.grup_listesi()
    hs = sorted((GR["HOLDING"] | {"BLCYT", "OSTIM", "ECZYT", "GSDHO"}) & set(G))
    try:
        K = json.loads((R / "nad_genel.json").read_text(encoding="utf-8"))
    except Exception:
        K = {}
    ist = sorted({t for v in K.values() for t in v.get("borsada", {})} | {t for p in ELLE.values() for t in p}
                 | {t for c in cfg.values() if isinstance(c, dict) for t in list(c.get("halka_acik", {})) + list(c.get("paylar", {}))})
    px = D.prices(sorted(set(hs) | set(ist)), start="2013-01-01")
    xu = PB._xu_duzelt(D.xu100(start="2013-01-01").copy())
    P = paylar(cfg, px, G)
    SER = seriler(hs, P, px, G)
    L = ["TEK STANDART HOLDING NAD'I (duzeltilmis defter NAD'i) - 23 Kas 2026",
         "NAD = ana ortaklik ozkaynagi + sum(pay x (istirak piyasa degeri - istirak ozkaynagi)); ozkaynak o gun bilinen son bilanco.", ""]
    # bugunku durum + aracı kurum karsilastirmasi
    MARBAS = {"GSDHO": 26046, "AGHOL": 260579, "NTHOL": 86592, "SAHOL": 540438, "DOHOL": 97886, "KCHOL": 723659, "OSTIM": 2487,
              "ALARK": 55655, "BLCYT": 4307, "GLYHO": 30956, "TRCAS": 11887, "RALYH": 44333, "ECZYT": 42698}
    L.append("1) BUGUN (mn TL). 'Marbas 9 Ara 2025' ile karsilastirma icin ayni gundeki bizim NAD'imiz da verildi.")
    for h, (S, kul) in sorted(SER.items(), key=lambda x: -x[1][0]["pd"].iloc[-1]):
        s = S.iloc[-1]
        m = S[S.index <= "2025-12-09"]
        mb = f" | 9 Ara 2025 bizim {m['nad'].iloc[-1] / 1e6:,.0f} / Marbas {MARBAS[h]:,}" if h in MARBAS and len(m) else ""
        L.append(f"  {h:6s} PD {s.pd / 1e6:9,.0f} NAD {s.nad / 1e6:9,.0f} iskonto %{100 * s.iskonto:6.1f} | borsadaki istirak {s.lis / max(s.nad, 1):.0%} of NAD | "
                 f"istirak {len(kul)}{mb}")
    # test
    T_ = []
    grid = xu.index[xu.index >= "2014-01-01"][::21]
    for h, (S, kul) in SER.items():
        d = S.copy()
        rp = lambda a: 100 * (a[:-1] < a[-1]).mean()
        d["y_nad"] = d["iskonto"].rolling(756, min_periods=250).apply(rp, raw=True)
        d["y_pddd"] = d["pddd"].rolling(756, min_periods=250).apply(rp, raw=True)
        c = px[h]["close"].reindex(d.index)
        x = xu.reindex(d.index).ffill()
        d["y_fiyat"] = (c / x).rolling(756, min_periods=250).apply(rp, raw=True)
        for k in (63, 126):
            d[f"f{k}"] = 100 * (c.shift(-k) / c - x.shift(-k) / x)
        d["lis_pay"] = d["lis"] / d["nad"]
        d["h"] = h
        T_.append(d[d.index.isin(grid)])
    A = pd.concat(T_).dropna(subset=["y_nad"])
    A["kesit"] = A.groupby(level=0)["iskonto"].rank(pct=True) * 100   # ayni gun holdingler arasinda (dusuk = en derin iskonto)
    A["yil"] = A.index.year
    A["donem"] = pd.cut(A.yil, [2013, 2017, 2020, 2023, 2030], labels=["2014-17", "2018-20", "2021-23", "2024+"])
    L.append(f"\n2) TEST: {A.h.nunique()} holding, 21 gunde bir gozlem ({A.index.min():%Y-%m}..{A.index.max():%Y-%m}). Sonraki getiri BIST100'e gore, kirpik ort / ortanca / kazanma / t.")
    L.append("   Olcu: dusuk yuzdelik = en derin iskonto (ucuz). 'derin' <=20, 'dar' >=80. Gozlemler ortusur; t kaba.")

    def satir(X, k):
        v = X[k].dropna()
        if len(v) < 8:
            return f"n {len(v):4d}"
        v2 = v.clip(v.quantile(.05), v.quantile(.95))
        t = v2.mean() / (v2.std() / np.sqrt(len(v2)))
        return f"n {len(v):4d} ort {v2.mean():+6.1f} ort.ca {v.median():+6.1f} kaz %{100 * (v > 0).mean():3.0f} t {t:+.1f}"

    def blok(baslik, M):
        L.append(f"\n  -- {baslik} ({M.h.nunique()} holding)")
        for olcu in ("y_nad", "kesit", "y_pddd", "y_fiyat"):
            for k in ("f126", "f63"):
                d1, d5 = M[M[olcu] <= 20], M[M[olcu] >= 80]
                a, b = d1[k].dropna(), d5[k].dropna()
                fark = (a.clip(a.quantile(.05), a.quantile(.95)).mean() - b.clip(b.quantile(.05), b.quantile(.95)).mean()) if len(a) > 7 and len(b) > 7 else float("nan")
                L.append(f"   {olcu:7s} {k:4s} derin: {satir(d1, k)} | dar: {satir(d5, k)} | fark {fark:+.1f}")
        for per in ["2014-17", "2018-20", "2021-23", "2024+"]:
            X = M[M.donem == per]
            a, b = X[X.y_nad <= 20]["f126"].dropna(), X[X.y_nad >= 80]["f126"].dropna()
            L.append(f"   y_nad f126 {per}: derin {satir(X[X.y_nad <= 20], 'f126')} | dar {satir(X[X.y_nad >= 80], 'f126')}")
        X = M[M.y_fiyat.between(30, 70)]
        L.append(f"   fiyat ortadayken y_nad f126: derin {satir(X[X.y_nad <= 20], 'f126')} | dar {satir(X[X.y_nad >= 80], 'f126')}")

    blok("TUM HOLDINGLER", A)
    blok("borsadaki istirak NAD'in >= %30'u", A[A.lis_pay >= 0.3])
    blok("borsadaki istirak NAD'in < %30'u (NAD ~ defter)", A[A.lis_pay < 0.3])
    buyuk = A.groupby("h")["pd"].last().sort_values(ascending=False).head(15).index
    blok("en buyuk 15 holding", A[A.h.isin(buyuk)])
    L.append("\n   holding basina gozlem: " + ", ".join(f"{h} {n}" for h, n in A.h.value_counts().items()))
    L.append("   kullanilan paylar: " + "; ".join(f"{h}: " + ",".join(f"{t} {w:.2f}" for t, w in sorted(P.get(h, {}).items())) for h in sorted(SER) if P.get(h)))
    txt = "\n".join(L)
    (R / "nad_std_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()


def icinden_test():
    """23 Kas gece (Teoman: 'holdingin icinden nasil cikilir'). Iki fikir, 2014-2026:
    A) Istirak sepeti onden gider (ownership-linked firms lead-lag): son 21 gunde borsadaki istiraklerin pay agirlikli
       getirisi - holdingin kendi getirisi (= 'yakalanmamis' kisim) -> holdingin sonraki 21/63 gun BIST100'e gore getirisi.
    B) Istiraklerin temel puani: borsadaki istiraklerin v3 sirasi (son bilinen), pay x piyasa degeri agirlikli -> sonraki 126 gun.
    Holdingler: borsadaki istirak NAD'in >= %25'i olanlar (NAD = duzeltilmis defter, bkz. main)."""
    from . import portfoy_bt as PB
    from . import firsat_bt as FB
    from . import temel_bt2 as B2
    cfg = json.loads((D.DATA / "nad.json").read_text(encoding="utf-8"))
    G = T.gecmis_birlesik()
    GR = PB.grup_listesi()
    hs = sorted((GR["HOLDING"] | {"BLCYT", "OSTIM", "ECZYT", "GSDHO"}) & set(G))
    try:
        K = json.loads((R / "nad_genel.json").read_text(encoding="utf-8"))
    except Exception:
        K = {}
    ist = sorted({t for v in K.values() for t in v.get("borsada", {})} | {t for p in ELLE.values() for t in p}
                 | {t for c in cfg.values() if isinstance(c, dict) for t in list(c.get("halka_acik", {})) + list(c.get("paylar", {}))})
    px = D.prices(sorted(set(hs) | set(ist)), start="2013-01-01")
    xu = PB._xu_duzelt(D.xu100(start="2013-01-01").copy())
    P = paylar(cfg, px, G)
    SER = seriler(hs, P, px, G)
    sec = [h for h, (S, kul) in SER.items() if len(kul) and (S["lis"] / S["nad"]).iloc[-250:].median() >= 0.25]
    grid = xu.index[xu.index >= "2014-06-01"][::21]
    L = ["HOLDINGIN ICINDEN: istirak sepeti onden gider mi? istiraklerin temel puani holdingi aciklar mi? (23 Kas 2026)",
         f"holdingler (borsadaki istirak NAD'in >= %25'i): {', '.join(sec)}", ""]
    # A) lead-lag
    rows = []
    for h in sec:
        S, kul = SER[h]
        idx = S.index
        ch = px[h]["close"].reindex(idx)
        x = xu.reindex(idx).ffill()
        smv = {t: _sermaye(G[t]["tab"]) for t in kul}
        val = pd.DataFrame({t: P[h][t] * px[t]["close"].reindex(idx).ffill() * smv[t] for t in kul})
        ret21 = {t: px[t]["close"].reindex(idx).ffill().pct_change(21) for t in kul}
        w = val.shift(21).div(val.shift(21).sum(axis=1), axis=0)
        sep = sum(w[t] * ret21[t] for t in kul)
        own = ch.pct_change(21)
        d = pd.DataFrame({"sepet21": 100 * sep, "kendi21": 100 * own, "x21": 100 * x.pct_change(21),
                          "f21": 100 * (ch.shift(-21) / ch - x.shift(-21) / x), "f63": 100 * (ch.shift(-63) / ch - x.shift(-63) / x),
                          "lis_pay": S["lis"] / S["nad"]})
        d["acik"] = d.sepet21 - d.kendi21
        d["h"] = h
        rows.append(d[d.index.isin(grid)])
    A = pd.concat(rows).dropna(subset=["acik"])
    A["yil"] = A.index.year

    def ozet(X, k):
        v = X[k].dropna()
        if len(v) < 10:
            return f"n {len(v):3d}"
        v2 = v.clip(v.quantile(.05), v.quantile(.95))
        return f"n {len(v):4d} ort {v2.mean():+5.1f} ort.ca {v.median():+5.1f} kaz %{100 * (v > 0).mean():3.0f} t {v2.mean() / (v2.std() / np.sqrt(len(v2))):+.1f}"
    L.append("A) ACIK = son 21 gunde istirak sepeti getirisi - holdingin kendi getirisi (puan). Pozitif: istirakler yukseldi, holding yakalamadi.")
    A["q"] = A.groupby(level=0)["acik"].rank(pct=True)
    for k in ("f21", "f63"):
        L.append(f"  {k}: acik en yuksek 1/3 (kesit): {ozet(A[A.q >= 2 / 3], k)}")
        L.append(f"  {k}: acik en dusuk 1/3 (kesit) : {ozet(A[A.q <= 1 / 3], k)}")
        L.append(f"  {k}: acik >= +5 puan (mutlak)  : {ozet(A[A.acik >= 5], k)}")
        L.append(f"  {k}: acik <= -5 puan (mutlak)  : {ozet(A[A.acik <= -5], k)}")
    for per, m in (("2014-17", A.yil <= 2017), ("2018-20", A.yil.between(2018, 2020)), ("2021-23", A.yil.between(2021, 2023)), ("2024+", A.yil >= 2024)):
        X = A[m]
        L.append(f"  f21 {per}: acik>=+5 {ozet(X[X.acik >= 5], 'f21')} | acik<=-5 {ozet(X[X.acik <= -5], 'f21')}")
    L.append("  holding basina gozlem: " + ", ".join(f"{h} {n}" for h, n in A.h.value_counts().items()))
    # B) istiraklerin temel puani
    O = B2.olaylar(G, D.m3())
    pxa = D.prices(sorted(O["t"].unique()), start="2013-01-01")
    FB.HAM_DONDUR = True
    E = FB.puanlar(O, pxa)
    FB.HAM_DONDUR = False
    E = E.dropna(subset=["v3r"]).sort_values("giris")
    V = E.pivot_table(index="giris", columns="t", values="v3r", aggfunc="last").sort_index()
    rows = []
    for h in sec:
        S, kul = SER[h]
        idx = S.index[S.index.isin(grid)]
        if not len(idx):
            continue
        kul2 = [t for t in kul if t in V.columns]
        if not kul2:
            continue
        Vh = V[kul2].reindex(V.index.union(idx)).ffill().reindex(idx)
        # en fazla ~1 yil eski puan kullan
        son = E[E.t.isin(kul2)].pivot_table(index="giris", columns="t", values="v3r", aggfunc="last").notna()
        smv = {t: _sermaye(G[t]["tab"]) for t in kul2}
        val = pd.DataFrame({t: P[h][t] * px[t]["close"].reindex(idx).ffill() * smv[t] for t in kul2 if t in px})
        w = val.div(val.sum(axis=1), axis=0)
        sk = (Vh[val.columns] * w).sum(axis=1) / (w.where(Vh[val.columns].notna()).sum(axis=1))
        kap = w.where(Vh[val.columns].notna()).sum(axis=1)
        ch = px[h]["close"].reindex(S.index)
        x = xu.reindex(S.index).ffill()
        f126 = (100 * (ch.shift(-126) / ch - x.shift(-126) / x)).reindex(idx)
        f63 = (100 * (ch.shift(-63) / ch - x.shift(-63) / x)).reindex(idx)
        own = V[h].reindex(V.index.union(idx)).ffill().reindex(idx) if h in V.columns else pd.Series(np.nan, index=idx)
        rows.append(pd.DataFrame({"sk": sk, "kap": kap, "f126": f126, "f63": f63, "kendi_v3": own, "h": h}, index=idx))
    Bt = pd.concat(rows).dropna(subset=["sk"])
    Bt = Bt[Bt.kap >= 0.5]
    Bt["yil"] = Bt.index.year
    Bt["q"] = Bt.groupby(level=0)["sk"].rank(pct=True)
    L.append("\nB) ISTIRAK PUANI = borsadaki istiraklerin v3 sirasi (0-1, piyasa geneli), pay x piyasa degeri agirlikli. (istirak puani olan agirlik >= %50)")
    for k in ("f126", "f63"):
        L.append(f"  {k}: istirak puani >= 0.7 (mutlak): {ozet(Bt[Bt.sk >= 0.7], k)}")
        L.append(f"  {k}: istirak puani 0.4-0.7        : {ozet(Bt[Bt.sk.between(0.4, 0.7)], k)}")
        L.append(f"  {k}: istirak puani <= 0.4         : {ozet(Bt[Bt.sk <= 0.4], k)}")
        L.append(f"  {k}: ayni gun holdingler arasi en iyi 1/3: {ozet(Bt[Bt.q >= 2 / 3], k)} | en kotu 1/3: {ozet(Bt[Bt.q <= 1 / 3], k)}")
    for per, m in (("2014-17", Bt.yil <= 2017), ("2018-20", Bt.yil.between(2018, 2020)), ("2021-23", Bt.yil.between(2021, 2023)), ("2024+", Bt.yil >= 2024)):
        X = Bt[m]
        L.append(f"  f126 {per}: >=0.7 {ozet(X[X.sk >= 0.7], 'f126')} | <=0.4 {ozet(X[X.sk <= 0.4], 'f126')}")
    X = Bt.dropna(subset=["kendi_v3"])
    L.append(f"  karsilastirma, holdingin KENDI v3'u: >=0.7 {ozet(X[X.kendi_v3 >= 0.7], 'f126')} | <=0.4 {ozet(X[X.kendi_v3 <= 0.4], 'f126')}")
    L.append("  holding basina gozlem: " + ", ".join(f"{h} {n}" for h, n in Bt.h.value_counts().items()))
    son = Bt.groupby("h").tail(1)
    L.append("  son durum: " + ", ".join(f"{h} {r.sk:.2f}" for h, r in son.set_index("h").iterrows()))
    txt = "\n".join(L)
    (R / "icinden_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)
