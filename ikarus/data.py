"""Veri katmani: BIST hisse listesi, fiyatlar (Yahoo Finance), BIST100 ve M3.

Bu modul kullanicinin bilgisayarinda calisir (internet gerekir).
  - Hisse listesi: TradingView tarayici API'si (scanner.tradingview.com), olmazsa data/bist_listesi.txt
  - Fiyatlar: yfinance, "THYAO.IS" bicimi, temettu ve bolunme duzeltmeli (auto_adjust=True)
  - BIST100: "XU100.IS"
  - M3: data/m3.csv (TradingView ECONOMICS:TRM3 ile ayni seri). Istege bagli EVDS'ten guncelleme.
"""
from __future__ import annotations

import os
import pickle
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
START = "2019-06-01"  # haftalik 200 + makro 250 hafta icin yeterli gecmis


# ------------------------------------------------------------------ hisse listesi

def bist_list(use_cache_hours: float = 24.0) -> pd.DataFrame:
    """BIST'te islem goren hisseler: kolonlar ticker, ad, sektor."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cf = CACHE / "bist_list.pkl"
    if cf.exists() and time.time() - cf.stat().st_mtime < use_cache_hours * 3600:
        return pd.read_pickle(cf)
    try:
        import requests
        body = {
            "filter": [{"left": "type", "operation": "equal", "right": "stock"},
                       {"left": "exchange", "operation": "equal", "right": "BIST"}],
            "columns": ["name", "description", "sector", "typespecs"],
            "range": [0, 2000],
        }
        r = requests.post("https://scanner.tradingview.com/turkey/scan", json=body, timeout=30)
        r.raise_for_status()
        rows = []
        for it in r.json()["data"]:
            name, desc, sector, specs = it["d"]
            if specs and any(s in ("preferred", "etf", "fund") for s in specs):
                continue
            rows.append({"ticker": name, "ad": desc, "sektor": sector})
        df = pd.DataFrame(rows).drop_duplicates("ticker").sort_values("ticker").reset_index(drop=True)
        df.to_pickle(cf)
        return df
    except Exception as e:  # internet/servis sorunu: yerel liste
        f = DATA / "bist_listesi.txt"
        if not f.exists():
            raise RuntimeError(f"Hisse listesi alinamadi ({e}) ve {f} yok.") from e
        t = [x.strip().upper() for x in f.read_text(encoding="utf-8").split() if x.strip()]
        return pd.DataFrame({"ticker": t, "ad": t, "sektor": ""})


# ------------------------------------------------------------------ fiyatlar

def _norm(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(1, axis=1)
    df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].copy()
    df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
    df.index.name = "date"
    return df.dropna(subset=["close"])


def prices(tickers: list[str], start: str = START, chunk: int = 80, refresh: bool = True) -> dict[str, pd.DataFrame]:
    """Gunluk OHLCV (temettu duzeltmeli). Donus: {ticker: DataFrame}."""
    import yfinance as yf

    CACHE.mkdir(parents=True, exist_ok=True)
    cf = CACHE / "prices.pkl"
    if not refresh and cf.exists():
        with open(cf, "rb") as f:
            return pickle.load(f)
    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i + chunk]
        sy = [t + ".IS" for t in part]
        raw = yf.download(sy, start=start, auto_adjust=True, group_by="ticker",
                          threads=True, progress=False)
        for t, s in zip(part, sy):
            try:
                df = raw[s] if len(sy) > 1 else raw
                df = _norm(df)
                if len(df) > 50:
                    out[t] = df
            except Exception:
                pass
    eksik = [t for t in tickers if t not in out]
    if eksik and len(eksik) < len(tickers):  # Yahoo bazen bir kismini vermiyor: bir kez daha dene
        time.sleep(5)
        for i in range(0, len(eksik), 20):
            part = eksik[i:i + 20]
            raw = yf.download([t + ".IS" for t in part], start=start, auto_adjust=True,
                              group_by="ticker", threads=False, progress=False)
            for t in part:
                try:
                    df = _norm(raw[t + ".IS"] if len(part) > 1 else raw)
                    if len(df) > 50:
                        out[t] = df
                except Exception:
                    pass
    with open(cf, "wb") as f:
        pickle.dump(out, f)
    return out


def xu100(start: str = START) -> pd.Series:
    import yfinance as yf
    raw = yf.download("XU100.IS", start=start, auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.droplevel(1, axis=1)
    return _norm(raw)["close"]


# ------------------------------------------------------------------ ayarlar

def ayar(ad: str, varsayilan: str | None = None) -> str | None:
    """Once ortam degiskeni (IKARUS_<AD>), sonra ayarlar.txt (ad=deger satirlari)."""
    v = os.environ.get("IKARUS_" + ad.upper())
    if v:
        return v.strip()
    f = ROOT / "ayarlar.txt"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, val = line.split("=", 1)
                if k.strip().lower() == ad.lower() and val.strip():
                    return val.strip()
    return varsayilan


# ------------------------------------------------------------------ M3

# EVDS (TCMB) haftalik M3: "Haftalik Para ve Banka Istatistikleri - 3.M3" (bin TL, her cuma).
# Ayin son cuma degeri TradingView ECONOMICS:TRM3'un o ayki degeriyle ayni seri
# (Agustos 2026 birebir; diger aylarda revizyon farki %0.01-0.06).
EVDS_URL = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"
EVDS_SERI = "TP.HPBITABLO1.18"


def m3(update: bool = True) -> pd.Series:
    """Aylik M3 (TL). index = TradingView ay damgasi (ayin 1'i).
    data/m3.csv TradingView'den alinmis gecmisi tutar; sonraki aylar her calismada EVDS'ten eklenir
    (yalniz ayin son cuma verisi yayimlanmissa, TradingView de o zaman alir)."""
    f = DATA / "m3.csv"
    s = pd.read_csv(f, comment="#", parse_dates=["tarih"]).set_index("tarih")["m3"].astype(float)
    key = ayar("evds_key")
    if update and key:
        try:
            s2 = _evds_m3(key)
            yeni = s2[s2.index > s.index.max()]
            if len(yeni):
                s = pd.concat([s, yeni])
                print(f"M3 (EVDS): {', '.join(f'{d:%Y-%m}' for d in yeni.index)} eklendi")
        except Exception as e:
            print(f"[uyari] EVDS'ten M3 alinamadi, son bilinen deger kullaniliyor: {e}")
    elif update:
        print("[uyari] EVDS anahtari yok (ayarlar.txt > evds_key); M3 yalniz data/m3.csv'den.")
    return s.sort_index()


def _evds_m3(key: str) -> pd.Series:
    """EVDS haftalik M3'ten aylik seri: her ayin son cuma degeri (TL).
    Ayin son cumasi henuz yayimlanmadiysa o ay alinmaz."""
    import requests
    bas = (pd.Timestamp.today() - pd.DateOffset(months=14)).strftime("01-%m-%Y")
    url = f"{EVDS_URL}series={EVDS_SERI}&startDate={bas}&endDate=31-12-2099&type=json&frequency=3"
    r = requests.get(url, headers={"key": key}, timeout=30)
    r.raise_for_status()
    col = EVDS_SERI.replace(".", "_")
    w = {}
    for it in r.json()["items"]:
        v = it.get(col)
        if v in (None, "", "null"):
            continue
        w[pd.to_datetime(str(it["Tarih"]), dayfirst=True)] = float(str(v).replace(",", "")) * 1000.0
    w = pd.Series(w, dtype=float).sort_index()
    if w.empty:
        return w
    son = w.index.max()
    out = {}
    for ay, g in w.groupby(w.index.to_period("M")):
        ay_sonu = ay.to_timestamp(how="end").normalize()
        son_cuma = ay_sonu - pd.Timedelta(days=(ay_sonu.weekday() - 4) % 7)
        if son >= son_cuma:  # ayin son cumasi yayimlanmis
            out[ay.to_timestamp()] = g.iloc[-1]
    return pd.Series(out, dtype=float).sort_index()
