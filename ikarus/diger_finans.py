"""'Diger finans' ortak puani (24 Kas 2026): sigorta + faktoring/leasing/finansman + varlik yonetim sirketleri tek havuzda.
Teoman: 'sigortada bir sey bulamadik' -> 6 sirketle kural kurulamiyor; havuzu buyutup ortak (net kar + ozkaynak) olculerle dene.

Is Yatirim sablonlari: sigorta 'UFRS' (sigorta sablonu), faktoring/leasing/finansman 'XI_29K', varlik yonetim 'UFRS_B'.
Ortak kodlar: 2O ana ortakliga ait ozkaynak, 3Z net donem kari (yil ici kumulatif).
Olculer (son 4 ceyrek): kazanc getirisi (1/F/K), PD/DD, ROE, reel net kar buyumesi, reel ozkaynak buyumesi.
Test: her bilanco yayininda (donem sonu + 75/100 gun) havuz icinde siralama; ust yari / alt yari ve ucte birler;
sonraki 63/126 gun piyasa ortancasina gore fazla getiri. 2020-2026.
"""
from __future__ import annotations

import gzip
import json
import time

import numpy as np
import pandas as pd

from . import data as D
from . import temel as T
from .temel_bt2 import yayin

R = D.ROOT / "temel"
F = R / "diger_finans.json"
KOD = {"2O", "2OA", "3Z", "2N"}


def sirketler():
    from . import portfoy_bt as PB
    GR = PB.grup_listesi()
    b = D.bist_list()
    ad = dict(zip(b.ticker, b.ad.fillna("").str.upper()))
    vy = {t for t, a in ad.items() if "VARLIK YONETIM" in a.replace("İ", "I").replace("Ö", "O")}
    return {**{t: "UFRS" for t in GR["SIGORTA"]}, **{t: "XI_29K" for t in GR["FAKTORING/LEASING"]}, **{t: "UFRS_B" for t in vy}}


def cek():
    S = sirketler()
    out = json.loads(F.read_text(encoding="utf-8")) if F.exists() else {}
    donem = [(y, m) for y in range(2026, 2017, -1) for m in (12, 9, 6, 3) if (y, m) <= (2026, 9)]
    for h, g in S.items():
        tab = out.get(h, {}).get("tab", {})
        for i in range(0, len(donem) - 3, 4):
            dl = donem[i:i + 4]
            if all(f"{y}/{m}" in tab for y, m in dl) and dl[0] < (2026, 1):
                continue
            v = T._cek4(h, g, dl)
            for x in v:
                k = x.get("itemCode")
                if k not in KOD:
                    continue
                for j, (y, m) in enumerate(dl, 1):
                    val = x.get(f"value{j}")
                    if val is not None:
                        tab.setdefault(f"{y}/{m}", {})[k] = float(val)
            time.sleep(0.4)
        out[h] = {"grup": g, "tab": tab}
        print(h, g, len(tab), "donem")
    F.write_text(json.dumps(out), encoding="utf-8")
    return out


def test():
    S = cek()
    tufe = D.tufe(update=False)

    def tf(d1, d0):
        a = tufe[tufe.index <= pd.Timestamp(d1[0], d1[1], 1)]
        b = tufe[tufe.index <= pd.Timestamp(d0[0], d0[1], 1)]
        return float(a.iloc[-1] / b.iloc[-1]) if len(a) and len(b) else None
    b = D.bist_list().set_index("ticker")
    hs = sorted(S)
    px = D.prices(hs)
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    tum = D.prices(sorted(G.keys()))
    Cx = pd.DataFrame({t: df["close"] for t, df in tum.items()}).sort_index()
    FF = {k: (lambda r: r.sub(r.median(axis=1), axis=0))(Cx.shift(-k) / Cx - 1) for k in (63, 126)}
    gun = Cx.index
    rows = []
    for h in hs:
        if h not in px or h not in b.index:
            continue
        sm = float(b.at[h, "mcap"]) / float(px[h]["close"].iloc[-1])   # duzeltilmis fiyatla tutarli adet
        tab = {tuple(map(int, k.split("/"))): v for k, v in S[h]["tab"].items()}
        for d in sorted(tab):
            nk = T._ttm(tab, d, "3Z"); nk1 = T._ttm(tab, (d[0] - 1, d[1]), "3Z")
            oz = tab[d].get("2O") or tab[d].get("2N"); oz1 = (tab.get((d[0] - 1, d[1])) or {}).get("2O")
            if nk is None or not oz or oz <= 0:
                continue
            g = gun[gun.searchsorted(yayin(*d))] if gun.searchsorted(yayin(*d)) < len(gun) else None
            if g is None:
                continue
            c = px[h]["close"]; c = c[c.index <= g]
            if not len(c):
                continue
            mcap = float(c.iloc[-1]) * sm
            enf = tf(d, (d[0] - 1, d[1]))
            roe = nk / oz
            if not (-1.0 < roe < 2.5):   # birim hatasi (bin TL / TL karisik) olan satirlari at
                continue
            rows.append({"t": h, "grup": S[h]["grup"], "donem": f"{d[0]}/{d[1]:02d}", "giris": g, "roe": roe,
                         "kaz_get": nk / mcap, "pddd": mcap / oz,
                         "nk_reel": (nk / nk1) / enf - 1 if nk1 and nk1 > 0 and nk > 0 and enf else None,
                         "oz_reel": (oz / oz1) / enf - 1 if oz1 and oz1 > 0 and enf else None,
                         "f63": FF[63].at[g, h] if h in FF[63].columns else np.nan, "f126": FF[126].at[g, h] if h in FF[126].columns else np.nan})
    A = pd.DataFrame(rows)
    A = A[(A.pddd > 0) & (A.pddd < 30)]
    A["yil"] = pd.to_datetime(A.giris).dt.year
    A["ceyrek"] = A["donem"]
    yon = {"pddd": -1}
    olc = ["kaz_get", "pddd", "roe", "nk_reel", "oz_reel"]
    for c in olc:
        A[c] = pd.to_numeric(A[c], errors="coerce")
    q = {c: (yon.get(c, 1) * A[c]).groupby(A.ceyrek).rank(pct=True) for c in olc}
    A["deger"] = pd.concat([q["kaz_get"], q["pddd"]], axis=1).mean(axis=1)
    A["kalite"] = q["roe"]
    A["hareket"] = pd.concat([q["nk_reel"], q["oz_reel"]], axis=1).mean(axis=1)
    A["puan"] = A[["deger", "kalite", "hareket"]].mean(axis=1)
    L = ["DIGER FINANS HAVUZU (sigorta + faktoring/leasing/finansman + varlik yonetim) - 24 Kas 2026",
         f"sirket {A.t.nunique()} ({', '.join(sorted(A.t.unique()))}); olay {len(A)}; donem {A.donem.min()}..{A.donem.max()}; "
         f"ceyrek basina ortalama sirket {A.groupby('ceyrek').t.nunique().mean():.1f}",
         "Sonraki getiri piyasa ortancasina gore %. Her ceyrek havuz icinde siralama (PD/DD'de dusuk iyi).", ""]

    def satir(v):
        v = v.dropna()
        if len(v) < 8:
            return f"n {len(v):3d}"
        v2 = v.clip(v.quantile(.05), v.quantile(.95))
        return f"n {len(v):3d} ort {100 * v2.mean():+5.1f} ort.ca {100 * v.median():+5.1f} kaz %{100 * (v > 0).mean():3.0f}"
    for c in olc + ["deger", "kalite", "hareket", "puan"]:
        a = A[A[c].notna()].copy()
        rk = (yon.get(c, 1) * a[c]).groupby(a.ceyrek).rank(pct=True)
        for k in ("f126", "f63"):
            u, l_ = a[rk >= 2 / 3][k].dropna(), a[rk <= 1 / 3][k].dropna()
            u2, l2 = u.clip(u.quantile(.05), u.quantile(.95)), l_.clip(l_.quantile(.05), l_.quantile(.95))
            t = (u2.mean() - l2.mean()) / np.sqrt(u2.var() / len(u2) + l2.var() / len(l2)) if len(u2) > 5 and len(l2) > 5 else float("nan")
            L.append(f"  {c:8s} {k:4s} en iyi 1/3: {satir(a[rk >= 2 / 3][k])} | en kotu 1/3: {satir(a[rk <= 1 / 3][k])} | t {t:+.1f}")
        per = []
        for p, m in (("2020-22", a.yil <= 2022), ("2023-24", a.yil.between(2023, 2024)), ("2025+", a.yil >= 2025)):
            u, l_ = a[m & (rk >= 2 / 3)]["f126"].dropna(), a[m & (rk <= 1 / 3)]["f126"].dropna()
            per.append(f"{p} {100 * (u.median() - l_.median()):+.1f} (n {len(u)}/{len(l_)})" if len(u) > 3 and len(l_) > 3 else f"{p} az")
        L.append(f"  {'':8s} f126 ortanca farki (iyi-kotu 1/3): " + " | ".join(per))
    for g, ad in (("UFRS", "sigorta"), ("XI_29K", "faktoring/leasing/finansman"), ("UFRS_B", "varlik yonetim")):
        a = A[A.grup == g]
        if len(a) < 10:
            continue
        rk = a["puan"].groupby(a.ceyrek).rank(pct=True)   # havuz ici puan, grup icinde bolme
        rp = A["puan"].groupby(A.ceyrek).rank(pct=True).reindex(a.index)
        L.append(f"  [{ad}] havuz puani ust yari: {satir(a[rp > 0.5]['f126'])} | alt yari: {satir(a[rp <= 0.5]['f126'])}")
    son = A.sort_values("giris").groupby("t").tail(1)
    son = son.assign(rp=A["puan"].groupby(A.ceyrek).rank(pct=True).reindex(son.index))
    L.append("\nson durum (son bilanco, havuz ici puan sirasi): " + " | ".join(
        f"{r.t} {r.donem} ROE %{100 * r.roe:.0f} PD/DD {r.pddd:.2f} F/K {1 / r.kaz_get if r.kaz_get > 0 else float('nan'):.1f} sira {r.rp:.2f}"
        for r in son.sort_values("rp", ascending=False).itertuples()))
    txt = "\n".join(L)
    (R / "diger_finans_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    test()
