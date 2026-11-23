"""Holding net aktif deger (NAD) iskontosu, gunluk.

data/nad.json: her holding icin referans tarihteki istirak katkilari (mn TL) ve sabit kalemler.
Gunluk halka acik katki = referans katki x (istirak fiyati_t / fiyati_ref). Fiyatlar temettu duzeltmeli
oldugu icin oranlar temettuyu de icerir; holding fiyati icin de ayni yapildigindan etkisi buyuk olcude dengelenir.
Gecmise dogru bugunku bilesim kullanilir: pay degisikliklerinden once (or. 2026 Tupras pay satisi)
seri yaklasiktir; bu yuzden yuzdelik hesap varsayilan olarak son 3 yil.

Cikti: temel/nad.json (uygulama icin ozet), temel/nad_seri.csv (haftalik seri), temel/nad_sonuc.txt
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import data as D

R = D.ROOT / "temel"


def seri(h, cfg, px, sermaye=None):
    """Iki bicim: 'halka_acik' (referans katkilar, mn TL) ya da 'paylar' + 'kalibre_nad_mn'.
    px["USDTRY"] varsa ve cfg["usd"] ise borsada olmayan kisim dolar kuruyla tasinir."""
    ph = px[h]["close"]
    ref = pd.Timestamp(cfg["ref_tarih"])
    def oran(s):
        s = s.sort_index()
        r = s[s.index <= ref]
        return s / float(r.iloc[-1]) if len(r) else None
    idx = ph.index
    eksik = []
    if "paylar" in cfg:
        sermaye = sermaye or {}
        lis = pd.Series(0.0, index=idx)
        lis_ref = 0.0
        for t, w in cfg["paylar"].items():
            if t not in px or not sermaye.get(t):
                eksik.append(t); continue
            c = px[t]["close"].sort_index()
            r = c[c.index <= ref]
            lis += w * c.reindex(idx).ffill() * sermaye[t] / 1e6
            lis_ref += w * float(r.iloc[-1]) * sermaye[t] / 1e6
        sabit = (cfg.get("kalibre_nad_mn") or lis_ref) - lis_ref   # kalibre yoksa: yalniz borsadaki istirakler
        if cfg.get("usd") and "USDTRY" in px:
            sabit = sabit * oran(px["USDTRY"]["close"]).reindex(idx).ffill()
        elif cfg.get("usd"):
            eksik.append("USDTRY")
        nad = lis + sabit
    else:
        kref = pd.Timestamp(cfg.get("katki_tarih", cfg["ref_tarih"]))
        def oran_k(s):
            s = s.sort_index(); r = s[s.index <= kref]
            return s / float(r.iloc[-1]) if len(r) else None
        lis = pd.Series(0.0, index=idx)
        for t, k in cfg["halka_acik"].items():
            if t not in px:
                eksik.append(t); lis += k; continue   # fiyat yoksa referans degerde sabit tut
            o = oran_k(px[t]["close"])
            lis += k * o.reindex(idx).ffill().fillna(1.0)
        sabit = float(sum(cfg["sabit"].values()))
        if cfg.get("kalibre_nad_mn"):
            l_ref = lis[lis.index <= ref]
            sabit = cfg["kalibre_nad_mn"] - (float(l_ref.iloc[-1]) if len(l_ref) else 0.0)
        nad = lis + sabit
    mcap = cfg["piyasa_degeri_ref"] * oran(ph)
    return pd.DataFrame({"nad": nad, "pd": mcap, "iskonto": mcap / nad - 1}), eksik


def havuz_test(cfg, hs, px, ser, xu):
    """23 Kas: tum holdingler birlikte. Iskontonun kendi 3y yuzdeligi -> sonraki 63/126 gun BIST100'e gore fazla getiri.
    Ortusmeyi azaltmak icin 21 gunde bir gozlem; t = ortalama / (ss / kok n)."""
    T = []
    for h in hs:
        if h not in px:
            continue
        try:
            S, _ = seri(h, cfg[h], px, ser)
        except Exception:
            continue
        S = S[S.index >= "2021-01-01"].dropna()
        if len(S) < 400:
            continue
        c = px[h]["close"].reindex(S.index)
        x = xu.reindex(S.index).ffill()
        rp = lambda a: 100 * (a[:-1] < a[-1]).mean()
        d = pd.DataFrame({"yf": (c / x).rolling(756, min_periods=250).apply(rp, raw=True),
                          "y": S["iskonto"].rolling(756, min_periods=250).apply(lambda a: 100 * (a[:-1] < a[-1]).mean(), raw=True),
                          "f63": 100 * (c.shift(-63) / c - x.shift(-63) / x), "f126": 100 * (c.shift(-126) / c - x.shift(-126) / x)})
        d = d.iloc[::21].dropna(subset=["y"]).assign(h=h)
        T.append(d)
    if not T:
        return []
    T = pd.concat(T)
    L = [f"\n== HAVUZ ({T.h.nunique()} holding, 21 gunde bir gozlem): iskonto 3y yuzdeligi -> BIST100'e gore fazla getiri"]
    for a, b in [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]:
        X = T[(T.y >= a) & (T.y < b)]
        for k in ("f63", "f126"):
            v = X[k].dropna()
            t = v.mean() / (v.std() / np.sqrt(len(v))) if len(v) > 2 else float("nan")
            L.append(f"   yuzdelik {a:3d}-{min(b, 100):3d} {k:4s} n {len(v):4d} ort {v.mean():+6.1f} medyan {v.median():+6.1f} kazanma %{100 * (v > 0).mean():3.0f} t {t:+.1f}")
    for k in ("f63", "f126"):
        v1, v2 = T[T.y <= 30][k].dropna(), T[T.y >= 70][k].dropna()
        L.append(f"   derin(<=30) - dar(>=70) {k}: {v1.mean() - v2.mean():+.1f} puan (n {len(v1)}/{len(v2)})")
        w1, w2 = T[T.yf <= 30][k].dropna(), T[T.yf >= 70][k].dropna()
        L.append(f"   KARSILASTIRMA yalniz fiyat (endekse gore 3y yuzdelik) dusuk-yuksek {k}: {w1.mean() - w2.mean():+.1f} puan (n {len(w1)}/{len(w2)})")
        X = T[T.yf.between(30, 70)]
        u1, u2 = X[X.y <= 30][k].dropna(), X[X.y >= 70][k].dropna()
        L.append(f"   fiyat ortadayken NAD derin-dar {k}: {u1.mean() - u2.mean():+.1f} puan (n {len(u1)}/{len(u2)})")
    L.append("   holding basina gozlem: " + ", ".join(f"{h} {n}" for h, n in T.h.value_counts().items()))
    return L


def usdtry():
    """Dolar/TL gunluk kapanis (Yahoo TRY=X)."""
    import yfinance as yf
    u = yf.download("TRY=X", start="2020-01-01", auto_adjust=True, progress=False)
    u.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in u.columns]
    u.index = pd.to_datetime(u.index).tz_localize(None)
    return u[["close"]].dropna()


def sermayeler():
    try:
        T = json.loads((R / "temel.json").read_text(encoding="utf-8"))["hisseler"]
        return {t: (v.get("ham") or {}).get("sermaye") for t, v in T.items()}
    except Exception:
        return {}


def main():
    cfg = json.loads((D.DATA / "nad.json").read_text(encoding="utf-8"))
    hs = [h for h in cfg if not h.startswith("_")]
    tick = sorted(set(hs) | {t for h in hs for t in list(cfg[h].get("halka_acik", {})) + list(cfg[h].get("paylar", {}))})
    px = D.prices(tick)
    try:
        px["USDTRY"] = usdtry()
    except Exception as e:
        print("[uyari] USDTRY:", e)
    ser = sermayeler()
    xu = D.xu100()
    ozet, L, tum = {}, [], []
    for h in hs:
        if h not in px:
            L.append(f"{h}: fiyat yok"); continue
        S, eksik = seri(h, cfg[h], px, ser)
        S = S[S.index >= "2021-01-01"].dropna()
        son = S.iloc[-1]
        p3 = S[S.index >= S.index[-1] - pd.DateOffset(years=3)]["iskonto"]
        p1 = S[S.index >= S.index[-1] - pd.DateOffset(years=1)]["iskonto"]
        isk = float(son["iskonto"])
        yuz3 = float(100 * (p3 < isk).mean())     # dusuk = tarihsel olarak derin iskonto
        yuz1 = float(100 * (p1 < isk).mean())
        d20 = float(isk - S["iskonto"].iloc[-21]) if len(S) > 21 else None
        d60 = float(isk - S["iskonto"].iloc[-61]) if len(S) > 61 else None
        ort3 = float(p3.mean())
        if yuz3 <= 20 and (d20 or 0) > 0.02:
            durum = "DERIN ISKONTO, KAPANIYOR"
        elif yuz3 <= 20:
            durum = "DERIN ISKONTO"
        elif yuz3 >= 80:
            durum = "ISKONTO DAR (pahali)"
        else:
            durum = "NORMAL"
        ozet[h] = {"tarih": f"{S.index[-1]:%Y-%m-%d}", "nad_mn": round(float(son["nad"])), "piyasa_degeri_mn": round(float(son["pd"])),
                   "iskonto": round(isk, 4), "ort_3y": round(ort3, 4), "uzun_vade": cfg[h].get("uzun_vade_iskonto"),
                   "yuzdelik_3y": round(yuz3, 1), "yuzdelik_1y": round(yuz1, 1),
                   "degisim_20g": None if d20 is None else round(d20, 4), "degisim_60g": None if d60 is None else round(d60, 4),
                   "durum": durum, "kaynak": cfg[h]["kaynak"], "fiyatsiz": eksik,
                   "teorik_fiyat_ort3y": round(float(px[h]["close"].iloc[-1] * (1 + ort3) / (1 + isk)), 2)}
        L.append(f"== {h}  {S.index[-1]:%Y-%m-%d}: NAD {son['nad']:,.0f} mn TL | piyasa degeri {son['pd']:,.0f} | iskonto %{100 * isk:.1f} "
                 f"| 3y ort %{100 * ort3:.1f} | 3y yuzdelik {yuz3:.0f} | 20g degisim {100 * (d20 or 0):+.1f} puan | {durum}"
                 + (f" | fiyati olmayanlar {eksik}" if eksik else ""))
        # yaklasik test: iskonto 3y yuzdeligi -> sonraki 63 gun holding getirisi (BIST100'e gore)
        c = px[h]["close"].reindex(S.index)
        x = xu.reindex(S.index).ffill()
        f63 = 100 * (c.shift(-63) / c - x.shift(-63) / x)
        roll = S["iskonto"].rolling(756, min_periods=250).apply(lambda a: 100 * (a[:-1] < a[-1]).mean(), raw=True)
        d20s = S["iskonto"].diff(20)
        T = pd.DataFrame({"y": roll, "d20": d20s, "f63": f63}).dropna()
        if len(T) > 200:
            for ad, m in [("yuzdelik <= 20 (derin)", T["y"] <= 20), ("yuzdelik 20-80", T["y"].between(20, 80, inclusive="neither")),
                          ("yuzdelik >= 80 (dar)", T["y"] >= 80), ("derin + 20g kapaniyor (>2 puan)", (T["y"] <= 20) & (T["d20"] > 0.02)),
                          ("derin + 20g aciliyor", (T["y"] <= 20) & (T["d20"] < -0.02))]:
                X = T[m]["f63"]
                L.append(f"   {ad:34s} gun {len(X):4d} | sonraki 63g BIST100'e gore ort {X.mean():+5.1f} medyan {X.median():+5.1f} kazanma %{100 * (X > 0).mean():3.0f}")
        w = S.resample("W-FRI").last().assign(hisse=h)
        tum.append(w)
    k4 = [h for h in hs if cfg[h].get("karar_nad")]
    L += [l.replace("== HAVUZ", "== HAVUZ A: KARARDA KULLANILAN 4") for l in havuz_test(cfg, k4, px, ser, xu)]
    L += [l.replace("== HAVUZ", "== HAVUZ B: 4 + LYDHO") for l in havuz_test(cfg, k4 + ["LYDHO"], px, ser, xu)]
    tt = [h for h in hs if cfg[h].get("test_only")]
    L += [l.replace("== HAVUZ", "== HAVUZ C: TEST (Marbas NAD, cogu borsada degil: " + ",".join(tt) + ")") for l in havuz_test(cfg, tt, px, ser, xu)]
    L.append("\nNot: gecmis seri bugunku istirak paylariyla hesaplandi (yaklasik). Test gunleri birbiriyle ortusuyor (63 gunluk pencereler); "
             "bagimsiz gozlem sayisi gun sayisindan cok daha az, sonuclari kaba isaret olarak oku.")
    (R / "nad.json").write_text(json.dumps({"olusturma": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "holdingler": ozet},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
    if tum:
        pd.concat(tum).round(4).to_csv(R / "nad_seri.csv")
    txt = "\n".join(L)
    (R / "nad_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
