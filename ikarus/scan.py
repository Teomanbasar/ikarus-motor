"""Tum BIST hisselerini IKARUS motoruyla tarar, uygulama icin sonuc dosyalari yazar.

Kullanim (proje klasorunde):
    python -m ikarus.scan              # tum BIST, gunluk + haftalik
    python -m ikarus.scan THYAO AKBNK  # yalniz secilen hisseler
Ciktilar: cikti/sonuclar.json (uygulama okur), cikti/sonuclar.csv (Excel icin)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import data as D
from . import engine as E

OUT = D.ROOT / "cikti"
SIG_ORDER = {"ALINABILIR": 0, "TOPLANIYOR": 1, "YAKIN": 2, "DAGITIM": 3, "BEKLE": 4}


def _temiz(x):
    """JSON'da gecersiz NaN/Infinity yerine null."""
    if isinstance(x, dict):
        return {k: _temiz(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_temiz(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def scan_one(df: pd.DataFrame, xu: pd.Series, m3: pd.Series) -> dict | None:
    res = {}
    for tf in ("D", "W"):
        r = E.compute(df, xu, m3, tf)
        if len(r) < 2 or np.isnan(r["dip"].iloc[-1]):
            if tf == "D":
                return None  # 200 bardan kisa gecmis: degerleme yok
            res[tf] = None
            continue
        last, prev = r.iloc[-1], r.iloc[-2]
        row = E.table_row(last)
        row["tarih"] = f"{r.index[-1]:%Y-%m-%d}"
        row["onceki_sinyal"] = prev["sinyal"]
        row["yeni_sinyal"] = bool(last["sinyal"] != prev["sinyal"])
        row["kirdi"] = bool(last["d_stop"] <= -3.5)  # onceki Stop'un %3.5'ten fazla altinda
        res[tf] = row
    return res


def _temel_ekle(stocks):
    """temel/temel.json (haftalik temel analiz isi) varsa her hisseye 'temel' karti ekler.
    F/K ve PD/DD guncel fiyatla burada hesaplanir (sermaye x fiyat = piyasa degeri; BIST'te nominal 1 TL)."""
    f = D.ROOT / "temel" / "temel.json"
    if not f.exists():
        return
    try:
        T = json.loads(f.read_text(encoding="utf-8"))["hisseler"]
    except Exception as e:
        print("[uyari] temel.json okunamadi:", e)
        return
    for s in stocks:
        k = T.get(s["t"])
        if not k or "maddeler" not in k:
            continue
        k = dict(k)
        ham = k.pop("ham", {}) or {}
        fiyat = (s.get("D") or {}).get("fiyat")
        sermaye, nk, oz = ham.get("sermaye"), ham.get("net_kar"), ham.get("ozkaynak")
        if fiyat and sermaye and sermaye > 0:
            pd_ = fiyat * sermaye
            k["piyasa_degeri"] = pd_
            k["fk"] = pd_ / nk if nk and nk > 0 else None
            k["pddd"] = pd_ / oz if oz and oz > 0 else None
        s["temel"] = k


def run(tickers: list[str] | None = None) -> dict:
    t0 = time.time()
    lst = D.bist_list()
    if tickers:
        tickers = [t.upper() for t in tickers]
        lst = lst[lst["ticker"].isin(tickers)]
        missing = set(tickers) - set(lst["ticker"])
        if missing:
            lst = pd.concat([lst, pd.DataFrame({"ticker": sorted(missing), "ad": sorted(missing), "sektor": ""})])
    print(f"{len(lst)} hisse. Fiyatlar indiriliyor...")
    px = D.prices(lst["ticker"].tolist())
    xu = D.xu100()
    px, xu, _ = D.tv_tamamla(px, xu)
    m3 = D.m3()
    print(f"{len(px)} hissenin verisi geldi ({time.time() - t0:.0f} sn). Hesaplaniyor...")

    info = lst.set_index("ticker")
    stocks = []
    for i, (t, df) in enumerate(sorted(px.items())):
        try:
            r = scan_one(df, xu, m3)
        except Exception as e:
            print(f"  [atlandi] {t}: {e}")
            continue
        if r is None:
            continue
        stocks.append({"t": t, "ad": info.at[t, "ad"] if t in info.index else t,
                       "sektor": info.at[t, "sektor"] if t in info.index else "", **r})

    _temel_ekle(stocks)

    # piyasa ozeti (makro etiketi BIST100'den, tum hisselerde ayni)
    m3e = E.m3_effective(m3)
    ref = next((s for s in stocks if s["t"] in ("THYAO", "AKBNK", "GARAN")), stocks[0] if stocks else None)
    piyasa = {
        "xu100": round(float(xu.iloc[-1]), 2), "xu100_tarih": f"{xu.index[-1]:%Y-%m-%d}",
        "xu100_degisim": round(float(100 * (xu.iloc[-1] / xu.iloc[-2] - 1)), 2),
        "m3": float(m3e.iloc[-1]), "m3_ay": f"{m3.index[-1]:%Y-%m}",
        "makro": ref["D"]["macro"].replace(" + UCUZ", "") if ref else None,
    }

    def lists(tf):
        S = [s for s in stocks if s.get(tf)]
        g = lambda s: s[tf]
        sinyal = sorted([s for s in S if g(s)["sinyal"] != "BEKLE"],
                        key=lambda s: (SIG_ORDER[g(s)["sinyal"]], -(g(s)["toplam"] or 0)))
        ucuz = sorted([s for s in S if g(s)["percentile"] <= 20],
                      key=lambda s: (g(s)["percentile"], -(g(s)["toplam"] or 0)))
        pahali = sorted([s for s in S if g(s)["percentile"] >= 80],
                        key=lambda s: (-g(s)["percentile"], g(s)["toplam"] or 0))
        kiran = sorted([s for s in S if g(s)["kirdi"]], key=lambda s: g(s)["d_stop"])
        yeni = [s for s in sinyal if g(s)["yeni_sinyal"]]
        T = lambda L: [s["t"] for s in L]
        return {"sinyal": T(sinyal), "yeni": T(yeni), "ucuz": T(ucuz), "pahali": T(pahali), "stop": T(kiran)}

    result = {
        "olusturma": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "surum": "IKARUS QUANT v4.6 aday (Python)",
        "piyasa": piyasa,
        "listeler": {"D": lists("D"), "W": lists("W")},
        "hisseler": stocks,
        "not": "Yatirim tavsiyesi degildir. Sinyal kurali 19 Zippo tablosundan cikarilmis adaydir.",
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "sonuclar.json").write_text(json.dumps(_temiz(result), ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    flat = []
    for s in stocks:
        for tf in ("D", "W"):
            if s.get(tf):
                x = {k: v for k, v in s[tf].items() if k != "eksik"}
                x["eksik"] = ", ".join(e["k"] for e in s[tf]["eksik"])
                flat.append({"hisse": s["t"], "ad": s["ad"], "sektor": s["sektor"], "zaman": tf, **x})
    pd.DataFrame(flat).to_csv(OUT / "sonuclar.csv", index=False, encoding="utf-8-sig", sep=";", decimal=",")
    L = result["listeler"]["D"]
    print(f"Bitti ({time.time() - t0:.0f} sn). {len(stocks)} hisse hesaplandi.")
    print(f"Gunluk: {len(L['sinyal'])} sinyal ({sum(1 for s in stocks if s['D']['sinyal']=='ALINABILIR')} ALINABILIR), "
          f"{len(L['ucuz'])} ucuz, {len(L['pahali'])} pahali, {len(L['stop'])} stop kiran.")
    print(f"Dosyalar: {OUT / 'sonuclar.json'}  ve  {OUT / 'sonuclar.csv'}")
    return result


if __name__ == "__main__":
    run(sys.argv[1:] or None)
