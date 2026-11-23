"""Sigorta sirketleri icin kendi temel olculeri ve testi (24 Kas 2026, Teoman: 'Sigorta').

Is Yatirim sigortacilari 'UFRS' grubunda, sigorta sablonuyla verir (kalemler: temel/kalemler_sig.txt):
  2O ozsermaye, 3Z net kar, 3K genel teknik bolum dengesi, 3AAAA brut yazilan prim, 3AA kazanilmis prim (net),
  3BA gerceklesen hasar (net, -), 3BD faaliyet giderleri (-), 3L yatirim gelirleri. Gelir kalemleri yil ici kumulatif.
Olculer (son 4 ceyrek): ROE, F/K (kazanc getirisi), PD/DD, reel net kar buyumesi, reel brut prim buyumesi,
teknik karlilik (genel teknik denge / kazanilmis prim), bilesik oran (hayat disi: (hasar + faaliyet gideri) / kazanilmis prim).
Test: her bilanco yayininda (donem sonu + 75 gun, yil sonu 100) sigortacilar kendi icinde iki yariya bolunur;
sonraki 63/126 gun piyasa ortancasina gore fazla getiri. Sirket az (6-7): sonuc kaba isarettir.
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd

from . import data as D
from . import temel as T
from .temel_bt2 import yayin

R = D.ROOT / "temel"
F = R / "sigorta.json"
KOD = ["2O", "3Z", "3K", "3C", "3AAAA", "3AA", "3BA", "3BD", "3L", "3D", "2OA"]
HAYAT = {"AGESA", "ANHYT"}


def sirketler():
    from . import portfoy_bt as PB
    return sorted(PB.grup_listesi()["SIGORTA"])


def cek(hisseler=None):
    hs = hisseler or sirketler()
    out = json.loads(F.read_text(encoding="utf-8")) if F.exists() else {}
    donem = [(y, m) for y in range(2018, 2027) for m in (3, 6, 9, 12) if (y, m) <= (2026, 9)]
    for h in hs:
        tab = out.get(h, {})
        for i in range(0, len(donem), 4):
            dl = donem[i:i + 4]
            if all(f"{y}/{m}" in tab for y, m in dl if (y, m) < (2026, 6)):
                continue
            v = T._cek4(h, "UFRS", dl)
            for x in v:
                k = x.get("itemCode")
                if k not in KOD:
                    continue
                for j, (y, m) in enumerate(dl, 1):
                    val = x.get(f"value{j}")
                    if val is not None:
                        tab.setdefault(f"{y}/{m}", {})[k] = float(val)
            time.sleep(0.5)
        out[h] = tab
        print(h, len(tab), "donem")
    F.write_text(json.dumps(out), encoding="utf-8")
    return out


SERMAYE = {}


def _sermaye_yukle():
    try:
        H = json.loads((R / "temel.json").read_text(encoding="utf-8"))["hisseler"]
        for t, v in H.items():
            s = (v.get("ham") or {}).get("sermaye")
            if s:
                SERMAYE[t] = float(s)
    except Exception as e:
        print("[uyari] sermaye", e)
    b = D.bist_list()
    return b


def olcular(S):
    tufe = D.tufe(update=False)
    def tf(d1, d0):
        a = tufe[tufe.index <= pd.Timestamp(d1[0], d1[1], 1)]
        b = tufe[tufe.index <= pd.Timestamp(d0[0], d0[1], 1)]
        return float(a.iloc[-1] / b.iloc[-1]) if len(a) and len(b) else None
    rows = []
    for h, t in S.items():
        tab = {tuple(map(int, k.split("/"))): v for k, v in t.items()}
        for d in sorted(tab):
            ttm = lambda k, dd=d: T._ttm(tab, dd, k)
            nk, nk1 = ttm("3Z"), T._ttm(tab, (d[0] - 1, d[1]), "3Z")
            pk_ = "3D" if h in HAYAT else "3AAAA"   # hayatta: hayat teknik gelir (prim + hayat yatirim geliri)
            pr, pr1 = ttm(pk_), T._ttm(tab, (d[0] - 1, d[1]), pk_)
            kp, tk = (ttm("3D") if h in HAYAT else ttm("3AA")), ttm("3K")
            ha, fg = ttm("3BA"), ttm("3BD")
            oz = tab[d].get("2O")
            enf = tf(d, (d[0] - 1, d[1]))
            r = {"t": h, "donem": f"{d[0]}/{d[1]:02d}", "yayin": yayin(*d), "oz": oz, "nk_ttm": nk, "sermaye": SERMAYE.get(h),
                 "roe": nk / oz if nk is not None and oz else None,
                 "nk_reel": (nk / nk1) / enf - 1 if nk is not None and nk1 and nk1 > 0 and nk > 0 and enf else None,
                 "prim_reel": (pr / pr1) / enf - 1 if pr and pr1 and pr1 > 0 and enf else None,
                 "teknik": tk / kp if tk is not None and kp and kp > 0 else None,
                 "bilesik": -(ha + fg) / kp if h not in HAYAT and ha is not None and fg is not None and kp and kp > 0 else None,
                 "yatirim_pay": None}
            yg = ttm("3L")
            if yg is not None and nk and nk > 0:
                r["yatirim_pay"] = yg / (abs(tk or 0) + abs(yg))
            rows.append(r)
    return pd.DataFrame(rows)


def test():
    S = cek()
    _sermaye_yukle()
    hs0 = [h for h in S if h not in SERMAYE]
    if hs0:
        b = D.bist_list().set_index("ticker")
        pxx = D.prices(hs0)
        for h in hs0:
            if h in b.index and h in pxx:
                SERMAYE[h] = float(b.at[h, "mcap"]) / float(pxx[h]["close"].iloc[-1])
    O = olcular(S)
    hs = sorted(O.t.unique())
    px = D.prices(hs)
    tum = D.prices(sorted(json.loads(__import__("gzip").decompress((R / "gecmis.json.gz").read_bytes())).keys()))
    Cx = pd.DataFrame({t: df["close"] for t, df in tum.items()}).sort_index()
    FF = {}
    for k in (63, 126):
        r = Cx.shift(-k) / Cx - 1
        FF[k] = r.sub(r.median(axis=1), axis=0)
    gun = Cx.index
    rows = []
    for _, e in O.iterrows():
        if e.t not in px:
            continue
        j = gun.searchsorted(e.yayin)
        if j >= len(gun):
            continue
        g = gun[j]
        c = px[e.t]["close"]
        c = c[c.index <= g]
        if not len(c) or not e.sermaye:
            continue
        mcap = float(c.iloc[-1]) * e.sermaye
        r = e.to_dict()
        r["giris"] = g
        r["kaz_get"] = e.nk_ttm / mcap if e.nk_ttm is not None else None
        r["pddd"] = mcap / e.oz if e.oz and e.oz > 0 else None
        for k in FF:
            r[f"f{k}"] = FF[k].at[g, e.t] if e.t in FF[k].columns else np.nan
        rows.append(r)
    A = pd.DataFrame(rows)
    A["yil"] = pd.to_datetime(A.giris).dt.year
    yon = {"pddd": -1, "bilesik": -1}
    olc = ["kaz_get", "pddd", "roe", "nk_reel", "prim_reel", "teknik", "bilesik"]
    for c in olc:
        A[c] = pd.to_numeric(A[c], errors="coerce")
    # birlesik puan: banka modeline benzer (deger: kaz_get + pddd; kalite: roe + teknik; hareket: nk_reel + prim_reel)
    q = {c: (yon.get(c, 1) * A[c]).groupby(A.donem).rank(pct=True) for c in olc}
    A["deger"] = pd.concat([q["kaz_get"], q["pddd"]], axis=1).mean(axis=1)
    A["kalite"] = pd.concat([q["roe"], q["teknik"]], axis=1).mean(axis=1)
    A["hareket"] = pd.concat([q["nk_reel"], q["prim_reel"]], axis=1).mean(axis=1)
    A["puan"] = A[["deger", "kalite", "hareket"]].mean(axis=1)
    L = ["SIGORTA OLCU TESTI (24 Kas 2026)", f"sirketler: {', '.join(hs)} (hayat/emeklilik: {', '.join(sorted(HAYAT))})",
         f"bilanco olayi {len(A)}, donem {A.donem.min()}..{A.donem.max()}; her donem sigortacilar kendi icinde iki yariya bolunur.",
         "Sonraki getiri piyasa ortancasina gore %. ust yari = olcuye gore iyi (pddd ve bilesik oranda dusuk iyi).", ""]

    def satir(v):
        v = v.dropna()
        if len(v) < 8:
            return f"n {len(v):3d}"
        v2 = v.clip(v.quantile(.05), v.quantile(.95))
        return f"n {len(v):3d} ort {100 * v2.mean():+5.1f} ort.ca {100 * v.median():+5.1f} kaz %{100 * (v > 0).mean():3.0f}"
    for c in olc + ["deger", "kalite", "hareket", "puan"]:
        a = A[A[c].notna()].copy()
        if len(a) < 20:
            L.append(f"  {c:10s} az veri ({len(a)})"); continue
        rk = (yon.get(c, 1) * a[c]).groupby(a.donem).rank(pct=True)
        ust, alt = a[rk > 0.5], a[rk <= 0.5]
        for k in ("f126", "f63"):
            d = ust[k].dropna(); e = alt[k].dropna()
            t = (d.mean() - e.mean()) / np.sqrt(d.var() / len(d) + e.var() / len(e)) if len(d) > 5 and len(e) > 5 else float("nan")
            L.append(f"  {c:10s} {k:4s} ust yari: {satir(ust[k])} | alt yari: {satir(alt[k])} | fark t {t:+.1f}")
        per = []
        for p, m in (("2020-22", a.yil <= 2022), ("2023-24", a.yil.between(2023, 2024)), ("2025+", a.yil >= 2025)):
            u, l_ = a[m & (rk > 0.5)]["f126"].dropna(), a[m & (rk <= 0.5)]["f126"].dropna()
            per.append(f"{p} {100 * (u.median() - l_.median()):+.1f}" if len(u) > 3 and len(l_) > 3 else f"{p} az")
        L.append(f"  {'':10s} f126 ortanca farki donemlere gore: " + " | ".join(per))
    L.append("\n  grup olarak: tum sigorta olaylari f126 " + satir(A.f126) + " | f63 " + satir(A.f63))
    son = A.sort_values("giris").groupby("t").tail(1)
    L.append("\nson durum: " + " | ".join(f"{r.t} {r.donem} ROE %{100 * (r.roe or 0):.0f} PD/DD {r.pddd:.2f} teknik %{100 * (r.teknik or 0):.0f}"
                                         + (f" bilesik %{100 * r.bilesik:.0f}" if r.bilesik == r.bilesik and r.bilesik is not None else "")
                                         + f" puan {r.puan:.2f}" for r in son.itertuples()))
    txt = "\n".join(L)
    (R / "sigorta_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    test()
