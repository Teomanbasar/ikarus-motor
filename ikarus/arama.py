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
        if "alarm_test2" in q:  # varyant taramasi: mum tipi x temettu x Recovery x sinyal tanimi
            import itertools
            import yfinance as yf
            def tanim(r, ad):
                if ad == "v46":
                    return r["sinyal"].to_numpy()
                n = r["eksik"].to_numpy(); c1 = r["c1"].to_numpy(); rl = r["rec_ok"].to_numpy(); rsl = r["rs_ok"].to_numpy()
                if ad == "v44":
                    return np.where(n == 0, "ALINABILIR", np.where((rl == -2) & ((n >= 3) | (rsl == 2)), "DAGITIM", np.where(c1 & (n <= 2), "YAKIN", "BEKLE")))
                return np.where(n == 0, "ALINABILIR", np.where(c1 & (n <= 2), "YAKIN", "BEKLE"))  # basit
            ham = {}
            for t in {a[0] for a in q["alarm_test2"]}:
                try:
                    raw = yf.download(t + ".IS", start="2015-01-01", auto_adjust=False, progress=False)
                    raw.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in raw.columns]
                    ham[t] = raw[["open", "high", "low", "close", "volume"]].dropna()
                except Exception:
                    pass
            skor = {}
            detay = []
            for t, tarih, tf, bek in q["alarm_test2"]:
                day = pd.Timestamp(tarih)
                for ha_, adj, rm in itertools.product((False, True), ("adj", "ham"), ("m3", "close20")):
                    src = px.get(t) if adj == "adj" else ham.get(t)
                    if src is None or len(src) == 0:
                        continue
                    d = src[src.index <= day]
                    try:
                        r = E.compute(d, xu, m3, tf=tf, ha=ha_, rec_mod=rm)
                    except Exception:
                        continue
                    for ad in ("v46", "v44", "basit"):
                        sg = tanim(r, ad)
                        ok = len(sg) > 1 and sg[-1] == bek and sg[-2] != bek
                        k = (("HA" if ha_ else "normal"), adj, rm, ad)
                        skor.setdefault(k, [0, 0]); skor[k][1] += 1; skor[k][0] += int(ok)
                        if k == ("normal", "adj", "close20", "basit") or k == ("HA", "adj", "close20", "basit"):
                            b = r.iloc[-1]
                            detay.append(f"{k[0]:6} {t} {tf} {tarih} {bek}: {sg[-2]}->{sg[-1]} {'OK' if ok else 'XX'} pct {b['percentile']:.1f} rec {b['recovery']:.2f} top {b['toplam']:.2f} mtf {b['mtf']:.1f} hacim {b['hacim']:.2f} eksik {int(b['eksik'])}")
            out.append("=== ALARM VARYANT (mum, temettu, recovery, sinyal tanimi): tutan/toplam")
            for k, (a, b) in sorted(skor.items(), key=lambda x: -x[1][0]):
                out.append(f"{k}: {a}/{b}")
            out.extend(detay)
            continue
        if "alarm_test" in q:  # Zippo alarm listesi: [[hisse, tarih, tf, beklenen], ...] -> o bar ve onceki bar sinyali
            out.append("=== ALARM TESTI (hisse tf tarih | Zippo | bizim onceki -> o gun | eksik sart, toplam, kapanis/alarm fiyati)")
            tut = 0; top = 0
            for t, tarih, tf, bek, fy in q["alarm_test"]:
                if t not in px:
                    out.append(f"{t} {tf} {tarih} | {bek} | VERI YOK"); continue
                day = pd.Timestamp(tarih)
                d = px[t][px[t].index <= day]
                try:
                    r = E.compute(d, xu, m3, tf=tf)
                except Exception as e:
                    out.append(f"{t} {tf} {tarih} | {bek} | hata {e}"); continue
                if len(r) < 2:
                    continue
                a, b = r.iloc[-2], r.iloc[-1]
                gecis = b["sinyal"] == bek and a["sinyal"] != bek
                top += 1; tut += int(gecis)
                eks = ",".join(k for k, ok in (("Pct", b["c1"]), ("Rec", b["c2"]), ("Top", b["c3"]), ("MTF", b["c4"]), ("Hacim", b["c5"]), ("Makro", b["c6"])) if not ok)
                out.append(f"{t} {tf} {tarih} | {bek} | {a['sinyal']} -> {b['sinyal']} {'OK' if gecis else 'XX'} | eksik[{eks}] pct {b['percentile']:.1f} rec {b['recovery']:.2f} top {b['toplam']:.2f} mtf {b['mtf']:.1f} hacim {b['hacim']:.2f} | {b['close']:.2f}/{fy} ({str(r.index[-1].date())})")
            out.append(f"TUTAN GECIS: {tut}/{top}")
            continue
        if "m3_gecmis" in q:  # EVDS (TCMB) haftalik M3 tum gecmis -> arama/m3_evds_haftalik.csv
            import requests
            key = D.ayar("evds_key")
            col = D.EVDS_SERI.replace(".", "_")
            url = f"{D.EVDS_URL}series={D.EVDS_SERI}&startDate=01-01-2005&endDate=31-12-2099&type=json&frequency=3"
            try:
                it = requests.get(url, headers={"key": key}, timeout=60).json()["items"]
                rows = [(pd.to_datetime(x["Tarih"], dayfirst=True).strftime("%Y-%m-%d"), float(str(x[col]).replace(",", "")) * 1000.0)
                        for x in it if x.get(col) not in (None, "", "null")]
                pd.DataFrame(rows, columns=["hafta", "m3_tl"]).to_csv(R / "m3_evds_haftalik.csv", index=False)
                out.append(f"EVDS haftalik M3: {len(rows)} hafta, {rows[0][0]} .. {rows[-1][0]}")
            except Exception as e:
                out.append(f"EVDS hata {e}")
            continue
        if "m3_kontrol" in q:  # EVDS haftalik son degerler + TradingView TRM3
            import requests
            key = D.ayar("evds_key")
            try:
                bas = (pd.Timestamp.today() - pd.DateOffset(months=3)).strftime("01-%m-%Y")
                url = f"{D.EVDS_URL}series={D.EVDS_SERI}&startDate={bas}&endDate=31-12-2099&type=json&frequency=3"
                it = requests.get(url, headers={"key": key}, timeout=30).json()["items"]
                out.append("EVDS haftalik: " + " | ".join(f"{x['Tarih']}={x.get(D.EVDS_SERI.replace('.', '_'))}" for x in it[-8:]))
            except Exception as e:
                out.append(f"EVDS hata {e}")
            for ep in ("global", "economics", "turkey"):
                try:
                    r = requests.post(f"https://scanner.tradingview.com/{ep}/scan", timeout=30,
                                      json={"symbols": {"tickers": ["ECONOMICS:TRM3"]}, "columns": ["close", "time", "update_time"]})
                    out.append(f"TV {ep}: {r.status_code} {r.text[:300]}")
                except Exception as e:
                    out.append(f"TV {ep} hata {e}")
            continue
        if "tv_test" in q:  # TradingView tamamlama denemesi
            import io, contextlib
            b = io.StringIO()
            with contextlib.redirect_stdout(b):
                p2, x2, n = D.tv_tamamla({t: px[t] for t in q["tv_test"] if t in px}, xu)
            out.append(b.getvalue().strip())
            for t in q["tv_test"]:
                if t in p2:
                    out.append(f"{t}\n" + p2[t].tail(3).to_string())
            out.append("XU100\n" + x2.tail(3).to_string())
            continue
        if "ham_veri" in q:  # temettu duzeltmesiz (TradingView varsayilani) fiyat
            import yfinance as yf
            vd = R / "veri"
            vd.mkdir(exist_ok=True)
            for t in q["ham_veri"]:
                try:
                    raw = yf.download(t + ".IS", start="2010-01-01", auto_adjust=False, progress=False)
                    raw.columns = [c[0] if isinstance(c, tuple) else c for c in raw.columns]
                    raw.round(4).to_csv(vd / f"{t}_ham.csv")
                    out.append(f"ham veri {t}: {len(raw)} satir")
                except Exception as e:
                    out.append(f"ham veri {t} HATA {e}")
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
        if "anlik" in q:  # gun ici tablo: o saate kadarki 15dk barlarla son gunu kes, sonra hesapla
            import yfinance as yf
            t, day = q["anlik"], pd.Timestamp(q["tarih"])
            hh, mm_ = (int(x) for x in q["saat"].split(":"))
            try:
                ib = yf.download(t + ".IS", start=day.strftime("%Y-%m-%d"), end=(day + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
                                 interval="15m", auto_adjust=False, progress=False)
                ib.columns = [c[0] if isinstance(c, tuple) else c for c in ib.columns]
                ib.index = ib.index.tz_convert("Europe/Istanbul")
                kes = ib[ib.index < ib.index[0].normalize() + pd.Timedelta(hours=hh, minutes=mm_)]
                out.append(f"=== ANLIK {t} {q['tarih']} {q['saat']}  15dk bar: {len(kes)}/{len(ib)}  Zippo: {q.get('zippo', '')}")
                o, h, l, cl, vv = float(kes["Open"].iloc[0]), float(kes["High"].max()), float(kes["Low"].min()), float(kes["Close"].iloc[-1]), float(kes["Volume"].sum())
                out.append(f"  o saatte: acilis {o:.2f} yuksek {h:.2f} dusuk {l:.2f} son {cl:.2f} hacim {vv:.0f} (gun sonu kapanis {float(ib['Close'].iloc[-1]):.2f}, gun hacmi {float(ib['Volume'].sum()):.0f})")
            except Exception as e:
                out.append(f"=== ANLIK {t} hata {e}")
                continue
            d = px[t][px[t].index <= day].copy()
            if d.index[-1] == day:
                oran = float(d["close"].iloc[-1]) / float(ib["Close"].iloc[-1])  # duzeltilmis / ham gun sonu
                d.loc[day, ["open", "high", "low", "close"]] = [o * oran, h * oran, l * oran, cl * oran]
                if "volume" in d.columns:
                    d.loc[day, "volume"] = vv
            k = ["close", "percentile", "memory", "compression", "recovery", "rs", "mtf", "hacim", "toplam", "eksik", "chg1", "sinyal", "dip", "tepe", "stop"]
            for tf in q.get("tf", ["W", "D"]):
                for ha in (False, True):
                    for rm in (None, "close20"):
                        r = E.compute(d, xu[xu.index <= day], m3, tf, ha=ha, rec_mod=rm)
                        out.append(f"  -- {tf} {'HA' if ha else 'normal'} rec={rm or 'v46'}")
                        out.append(r[k].tail(3).round(3).to_string())
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
