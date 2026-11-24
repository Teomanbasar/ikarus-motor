"""Bankalar icin genisletilmis analiz ve 2014-2026 testi (24 Kas 2026, Teoman: 'bankalardaki analizi genisletelim').

Is Yatirim UFRS banka sablonu (temel/kalemler.txt, AKBNK):
  1Z aktif, 1AF krediler (net), 2A mevduat, 2O ozkaynak, 3C net faiz geliri, 3CA net ucret-komisyon,
  3CC ticari kar/zarar (swap/turev dahil), 3CE faaliyet gelirleri toplami, 3CF kredi deger dusus karsiligi (-),
  3CG diger faaliyet giderleri (-), 3Z net kar. Gelir kalemleri yil ici kumulatif.
Mevcut banka puaninin olculeri: kazanc getirisi, PD/DD, ROE, reel net kar buyumesi, reel net faiz geliri buyumesi.
Yeni (bankaya ozgu) olculer, test ONCESI secildi:
  - nim: net faiz geliri / ortalama aktif; nim_deg: bir yil once ile fark (faiz dongusu)
  - maliyet_gelir: faaliyet giderleri / faaliyet gelirleri (dusuk iyi)
  - risk_maliyeti: kredi karsilik gideri / krediler (dusuk iyi)
  - komisyon_reel: net ucret-komisyon reel buyumesi
  - kredi_mevduat: krediler / mevduat (bilgi; yon test edilir)
  - ozk_aktif: ozkaynak / aktif (sermaye tamponu vekili)
  - ticari_pay: ticari kar-zarar / faaliyet gelirleri (swap maliyeti; bilgi)
Test: her bilanco yayininda (donem sonu + 75 gun, yil sonu 100) bankalar kendi icinde ucte birlere ayrilir;
sonraki 126/63 gun piyasa ortancasina gore. Donemler: 2014-17, 2018-20, 2021-24, 2025+.
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
F = R / "bankalar.json"
KOD = {"1Z", "1AF", "2A", "2O", "2OA", "3C", "3CA", "3CC", "3CE", "3CF", "3CG", "3Z"}
SIGORTA = {"AGESA", "AKGRT", "ANHYT", "ANSGR", "QUICK", "RAYSG", "TURSG"}


def bankalar():
    H = json.loads((R / "temel.json").read_text(encoding="utf-8"))["hisseler"]
    return sorted(t for t, v in H.items() if v.get("tip") == "banka" and t not in SIGORTA)


def cek():
    out = json.loads(F.read_text(encoding="utf-8")) if F.exists() else {}
    donem = [(y, m) for y in range(2026, 2012, -1) for m in (12, 9, 6, 3) if (y, m) <= (2026, 9)]
    for h in bankalar():
        tab = out.get(h, {})
        for i in range(0, len(donem) - 3, 4):
            dl = donem[i:i + 4]
            if all(f"{y}/{m}" in tab for y, m in dl) and dl[0] < (2026, 1):
                continue
            for x in T._cek4(h, "UFRS", dl):
                k = x.get("itemCode")
                if k not in KOD:
                    continue
                for j, (y, m) in enumerate(dl, 1):
                    v = x.get(f"value{j}")
                    if v is not None:
                        tab.setdefault(f"{y}/{m}", {})[k] = float(v)
            time.sleep(0.4)
        out[h] = tab
        print(h, len(tab), "donem")
    F.write_text(json.dumps(out), encoding="utf-8")
    return out


def olcular(S, px, b):
    tufe = D.tufe(update=False)

    def tf(d1, d0):
        a = tufe[tufe.index <= pd.Timestamp(d1[0], d1[1], 1)]
        c = tufe[tufe.index <= pd.Timestamp(d0[0], d0[1], 1)]
        return float(a.iloc[-1] / c.iloc[-1]) if len(a) and len(c) else None
    rows = []
    for h, t in S.items():
        if h not in px or h not in b.index:
            continue
        sm = float(b.at[h, "mcap"]) / float(px[h]["close"].iloc[-1])
        tab = {tuple(map(int, k.split("/"))): v for k, v in t.items()}
        for d in sorted(tab):
            o = (d[0] - 1, d[1])
            tt = lambda k, dd=d: T._ttm(tab, dd, k)
            g = lambda k, dd=d: (tab.get(dd) or {}).get(k)
            nk, nk1 = tt("3Z"), tt("3Z", o)
            nfg, nfg1 = tt("3C"), tt("3C", o)
            kom, kom1 = tt("3CA"), tt("3CA", o)
            fg, gid, kar, tic = tt("3CE"), tt("3CG"), tt("3CF"), tt("3CC")
            akt, akt1 = g("1Z"), g("1Z", o)
            oz, kr, mv = g("2O"), g("1AF"), g("2A")
            enf = tf(d, o)
            if nk is None or not oz or oz <= 0 or not akt:
                continue
            ort_akt = (akt + akt1) / 2 if akt1 else akt
            nim = nfg / ort_akt if nfg is not None else None
            nfg_o = tt("3C", o)
            akt_o2 = g("1Z", (d[0] - 2, d[1]))
            nim1 = nfg_o / ((akt1 + akt_o2) / 2 if akt1 and akt_o2 else akt1) if nfg_o is not None and akt1 else None
            r = {"t": h, "donem": f"{d[0]}/{d[1]:02d}", "yayin": yayin(*d), "sm": sm, "nk": nk, "oz": oz,
                 "roe": nk / oz,
                 "nk_reel": (nk / nk1) / enf - 1 if nk1 and nk1 > 0 and nk > 0 and enf else None,
                 "nfg_reel": (nfg / nfg1) / enf - 1 if nfg and nfg1 and nfg1 > 0 and enf else None,
                 "nim": nim, "nim_deg": nim - nim1 if nim is not None and nim1 is not None else None,
                 "maliyet_gelir": abs(gid) / fg if gid is not None and fg and fg > 0 else None,
                 "risk_maliyeti": abs(kar) / kr if kar is not None and kr and kr > 0 else None,
                 "komisyon_reel": (kom / kom1) / enf - 1 if kom and kom1 and kom1 > 0 and enf else None,
                 "kredi_mevduat": kr / mv if kr and mv else None,
                 "ozk_aktif": oz / akt,
                 "ticari_pay": tic / fg if tic is not None and fg and fg > 0 else None}
            rows.append(r)
    return pd.DataFrame(rows)


def test():
    S = cek()
    b = D.bist_list().set_index("ticker")
    hs = sorted(S)
    px = D.prices(hs, start="2013-01-01")
    O = olcular(S, px, b)
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    try:
        from . import temel as TT
        G2 = TT.gecmis_birlesik()
        tick = sorted(set(G) | set(G2))
    except Exception:
        tick = sorted(G)
    tum = D.prices(tick, start="2013-01-01")
    Cx = pd.DataFrame({t: df["close"] for t, df in tum.items()}).sort_index()
    Cx = Cx[Cx.index >= "2013-06-01"]
    FF = {k: (lambda r: r.sub(r.median(axis=1), axis=0))(Cx.shift(-k) / Cx - 1) for k in (63, 126)}
    gun = Cx.index
    rows = []
    for _, e in O.iterrows():
        j = gun.searchsorted(e.yayin)
        if j >= len(gun):
            continue
        g = gun[j]
        c = px[e.t]["close"]; c = c[c.index <= g]
        if not len(c):
            continue
        mcap = float(c.iloc[-1]) * e.sm
        r = e.to_dict()
        r.update({"giris": g, "kaz_get": e.nk / mcap, "pddd": mcap / e.oz,
                  "f63": FF[63].at[g, e.t] if e.t in FF[63].columns else np.nan,
                  "f126": FF[126].at[g, e.t] if e.t in FF[126].columns else np.nan})
        rows.append(r)
    A = pd.DataFrame(rows)
    A = A[(A.pddd > 0) & (A.pddd < 20)]
    A["yil"] = pd.to_datetime(A.giris).dt.year
    yon = {"pddd": -1, "maliyet_gelir": -1, "risk_maliyeti": -1}
    mevcut = ["kaz_get", "pddd", "roe", "nk_reel", "nfg_reel"]
    yeni = ["nim", "nim_deg", "maliyet_gelir", "risk_maliyeti", "komisyon_reel", "kredi_mevduat", "ozk_aktif", "ticari_pay"]
    for c in mevcut + yeni:
        A[c] = pd.to_numeric(A[c], errors="coerce")
    q = {c: (yon.get(c, 1) * A[c]).groupby(A.donem).rank(pct=True) for c in mevcut + yeni}
    A["MEVCUT"] = pd.concat([q[c] for c in mevcut], axis=1).mean(axis=1)
    A["GENIS"] = pd.concat([q[c] for c in mevcut + ["nim_deg", "maliyet_gelir", "risk_maliyeti", "komisyon_reel"]], axis=1).mean(axis=1)
    L = ["BANKALAR GENISLETILMIS ANALIZ (24 Kas 2026)",
         f"banka {A.t.nunique()} ({', '.join(sorted(A.t.unique()))}); olay {len(A)}; donem {A.donem.min()}..{A.donem.max()}; "
         f"ceyrek basina {A.groupby('donem').t.nunique().mean():.1f} banka",
         "Her ceyrek bankalar kendi icinde ucte birlere. Sonraki getiri piyasa ortancasina gore %. (maliyet/gelir, risk maliyeti, PD/DD dusuk iyi)",
         "MEVCUT = bugunku banka puaninin olculeri (kazanc getirisi, PD/DD, ROE, reel kar, reel net faiz geliri);",
         "GENIS = MEVCUT + NIM degisimi + maliyet/gelir + risk maliyeti + komisyon buyumesi (test oncesi secildi).", ""]

    def satir(v):
        v = v.dropna()
        if len(v) < 8:
            return f"n {len(v):3d}"
        v2 = v.clip(v.quantile(.05), v.quantile(.95))
        return f"n {len(v):3d} ort {100 * v2.mean():+5.1f} ort.ca {100 * v.median():+5.1f} kaz %{100 * (v > 0).mean():3.0f}"
    donemler = (("2014-17", A.yil.between(2014, 2017)), ("2018-20", A.yil.between(2018, 2020)), ("2021-24", A.yil.between(2021, 2024)), ("2025+", A.yil >= 2025))
    for c in ["MEVCUT", "GENIS"] + mevcut + yeni:
        a = A[A[c].notna()].copy()
        if len(a) < 30:
            L.append(f"  {c:14s} az veri ({len(a)})"); continue
        rk = (yon.get(c, 1) * a[c]).groupby(a.donem).rank(pct=True)
        u, l_ = a[rk >= 2 / 3]["f126"].dropna(), a[rk <= 1 / 3]["f126"].dropna()
        u2, l2 = u.clip(u.quantile(.05), u.quantile(.95)), l_.clip(l_.quantile(.05), l_.quantile(.95))
        t = (u2.mean() - l2.mean()) / np.sqrt(u2.var() / len(u2) + l2.var() / len(l2))
        L.append(f"  {c:14s} f126 iyi 1/3: {satir(a[rk >= 2 / 3]['f126'])} | kotu 1/3: {satir(a[rk <= 1 / 3]['f126'])} | t {t:+.1f}")
        per = []
        for p, m in donemler:
            u, l_ = a[m & (rk >= 2 / 3)]["f126"].dropna(), a[m & (rk <= 1 / 3)]["f126"].dropna()
            per.append(f"{p} {100 * (u.median() - l_.median()):+5.1f} (n {len(u)}/{len(l_)})" if len(u) > 3 and len(l_) > 3 else f"{p} az")
        L.append(f"  {'':14s} ortanca farki iyi-kotu: " + " | ".join(per))
        u, l_ = a[rk >= 2 / 3]["f63"].dropna(), a[rk <= 1 / 3]["f63"].dropna()
        L.append(f"  {'':14s} f63 iyi 1/3: {satir(u)} | kotu 1/3: {satir(l_)}")
    son = A.sort_values("giris").groupby("t").tail(1).copy()
    for c in ("MEVCUT", "GENIS"):
        son[c + "_r"] = A[c].groupby(A.donem).rank(pct=True).reindex(son.index)
    L.append("\nson durum (son bilanco; havuz ici sira): " + " | ".join(
        f"{r.t} {r.donem} ROE %{100 * r.roe:.0f} NIM %{100 * (r.nim or 0):.1f} NIMd {100 * (r.nim_deg or 0):+.1f} M/G %{100 * (r.maliyet_gelir or 0):.0f} "
        f"risk %{100 * (r.risk_maliyeti or 0):.1f} PD/DD {r.pddd:.2f} mevcut {r.MEVCUT_r:.2f} genis {r.GENIS_r:.2f}"
        for r in son.sort_values("GENIS_r", ascending=False).itertuples()))
    txt = "\n".join(L)
    (R / "bankalar_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    test()
