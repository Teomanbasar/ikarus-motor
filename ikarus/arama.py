"""Isimsiz Zippo tablolarini bulmak icin: tum BIST'te verilen tarihteki Dip/Tepe'ye uyan hisseleri arar.
Girdi: arama/istek.json  [{"ad": "...", "tarih": "YYYY-MM-DD", "dip": x, "tepe": y, "pct": p}, ...]
Cikti: arama/sonuc.txt
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from . import data as D
from . import engine as E

R = D.ROOT / "arama"


def main():
    istek = json.loads((R / "istek.json").read_text(encoding="utf-8"))
    lst = D.bist_list()
    px = D.prices(lst["ticker"].tolist())
    xu = D.xu100()
    m3 = D.m3()
    out = []
    for q in istek:
        if "veri" in q:  # arastirma icin fiyat verisini depoya yaz
            vd = R / "veri"
            vd.mkdir(exist_ok=True)
            for t in q["veri"]:
                if t in px:
                    px[t].round(4).to_csv(vd / f"{t}.csv")
            xu.round(2).to_csv(vd / "XU100.csv")
            out.append(f"veri yazildi: {len(q['veri'])} hisse")
            continue
        if "aralik" in q:  # genis arama: farkli kaynak/uzunluk/M3 ile dip-tepe eslesmesi
            day = pd.Timestamp(q["tarih"])
            m3e = E.m3_effective(m3)
            rows = []
            for t, df in px.items():
                d = df[df.index <= day]
                if len(d) < 60:
                    continue
                cl = float(d["close"].iloc[-1])
                if q.get("fiyat") and abs(cl / q["fiyat"] - 1) > 0.25:
                    continue
                W = d.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
                M = d.resample("ME").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
                for tfn, X in (("D", d), ("W", W), ("M", M)):
                    mm = E.align_m3(X.index, m3e)
                    for adj in (False, True):
                        f = (mm[-1] / mm) if adj else np.ones(len(X))
                        for kay in ("c", "hl"):
                            lo_s = (X["low"] if kay == "hl" else X["close"]).values * f
                            hi_s = (X["high"] if kay == "hl" else X["close"]).values * f
                            for n in (20, 50, 52, 100, 104, 150, 200, 250, 260, 300, 500, 750, 1000, 99999):
                                if n != 99999 and len(X) < n:
                                    continue
                                lo, hi = np.nanmin(lo_s[-n:]), np.nanmax(hi_s[-n:])
                                e = abs(lo / q["dip"] - 1) + abs(hi / q["tepe"] - 1)
                                rows.append((e, t, f"{tfn}-{'M3' if adj else 'ham'}-{kay}-{n}", lo, hi, cl))
            rows.sort(key=lambda x: x[0])
            out.append(f"=== ARALIK {q['tarih']} Dip {q['dip']} Tepe {q['tepe']} fiyat~{q.get('fiyat')}")
            for e, t, k, lo, hi, cl in rows[:40]:
                out.append(f"{t:7s} {k:18s} hata {e*100:6.2f}%  dip {lo:.2f} tepe {hi:.2f} kapanis {cl:.2f} konum {100*(cl-lo)/(hi-lo):.1f}")
            vd = R / "veri"
            vd.mkdir(exist_ok=True)
            for t in dict.fromkeys(r[1] for r in rows[:40]):
                px[t].round(4).to_csv(vd / f"{t}.csv")
            out.append("")
            continue
        if "hisse" in q:  # detay: bilinen hissenin o tarihteki tablosu ve ara degerler
            t, tf, day = q["hisse"], q.get("tf", "D"), pd.Timestamp(q["tarih"])
            d = px[t][px[t].index <= day]
            r = E.compute(d, xu[xu.index <= day], m3, tf, ha=q.get("ha", False))
            k = ["close", "percentile", "memory", "compression", "recovery", "rec_pct3", "rs", "rs_pct5",
                 "mtf", "hacim", "macro_sc", "toplam", "eksik", "chg1", "d_stop", "sinyal", "dip", "tepe", "stop"]
            out.append(f"=== DETAY {t} {tf} {q['tarih']}  Zippo: {q.get('zippo', '')}")
            out.append(r[k].tail(8).round(3).to_string())
            for n in (1, 2, 3, 5):
                out.append(f"  rec-rec[{n}]={r['recovery'].iloc[-1]-r['recovery'].iloc[-1-n]:.2f}  "
                           f"rs-rs[{n}]={r['rs'].iloc[-1]-r['rs'].iloc[-1-n]:.2f}")
            out.append("")
            continue
        day = pd.Timestamp(q["tarih"])
        rows = []
        for t, df in px.items():
            d = df[df.index <= day]
            if len(d) < 60:
                continue
            c = d["close"]
            ham_lo, ham_hi = c.tail(200).min(), c.tail(200).max()
            def err(a, b):
                return abs(a / q["dip"] - 1) + abs(b / q["tepe"] - 1)
            # 1) ham kapanis (M3'suz) 200 bar
            rows.append((err(ham_lo, ham_hi), t, "ham-D", ham_lo, ham_hi, None, float(c.iloc[-1])))
            # 2) motor (M3) gunluk ve haftalik, normal ve HA
            for tf in ("D", "W"):
                for ha in (False, True):
                    try:
                        r = E.compute(d, xu[xu.index <= day], m3, tf, ha=ha)
                    except Exception:
                        continue
                    if r.empty or np.isnan(r["dip"].iloc[-1]):
                        continue
                    L = r.iloc[-1]
                    rows.append((err(L["dip"], L["tepe"]), t, f"M3-{tf}{'-HA' if ha else ''}",
                                 L["dip"], L["tepe"], L["percentile"], float(L["close"])))
        rows.sort(key=lambda x: x[0])
        out.append(f"=== {q['ad']} {q['tarih']} Dip {q['dip']} Tepe {q['tepe']} Pct {q.get('pct')}")
        for e, t, k, lo, hi, p, cl in rows[:12]:
            out.append(f"{t:7s} {k:8s} hata {e*100:6.2f}%  dip {lo:.2f} tepe {hi:.2f} pct {p if p is None else round(p,1)} kapanis {cl:.2f}")
        out.append("")
    (R / "sonuc.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
