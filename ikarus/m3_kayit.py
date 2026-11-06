"""M3 gunluk kaydi: TradingView ECONOMICS:TRM3 ve EVDS son haftalik M3 degerini data/m3_kayit.csv'ye ekler.
Neden: TradingView M3 gecmisini sonradan degistiriyor (6 Kas 2026'da Ekim 33.109 -> 33.044, eski aylar %1-7).
Zippo tablolarini kendi gunuyle karsilastirmak icin o gun TradingView'de gorunen deger lazim.
Calistirma: python -m ikarus.m3_kayit   (tarama.yml her calismada cagirir; hata tarama'yi durdurmaz)
"""
from __future__ import annotations

import pandas as pd

from . import data as D

DOSYA = D.ROOT / "data" / "m3_kayit.csv"
BASLIK = "kayit_zamani,tv_deger,tv_ay,evds_hafta,evds_deger\n"


def _tv():
    import requests
    r = requests.post("https://scanner.tradingview.com/global/scan", timeout=30,
                      json={"symbols": {"tickers": ["ECONOMICS:TRM3"]}, "columns": ["close", "time"]})
    d = r.json()["data"][0]["d"]
    return float(d[0]), pd.to_datetime(int(d[1]), unit="s").strftime("%Y-%m")


def _evds():
    import requests
    key = D.ayar("evds_key")
    if not key:
        return "", ""
    bas = (pd.Timestamp.today() - pd.DateOffset(months=2)).strftime("01-%m-%Y")
    url = f"{D.EVDS_URL}series={D.EVDS_SERI}&startDate={bas}&endDate=31-12-2099&type=json&frequency=3"
    col = D.EVDS_SERI.replace(".", "_")
    it = [x for x in requests.get(url, headers={"key": key}, timeout=30).json()["items"] if x.get(col) not in (None, "", "null")]
    son = it[-1]
    return pd.to_datetime(son["Tarih"], dayfirst=True).strftime("%Y-%m-%d"), float(str(son[col]).replace(",", "")) * 1000.0


def main():
    zaman = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")
    try:
        tv, tv_ay = _tv()
    except Exception as e:
        print(f"[uyari] TV M3 alinamadi: {e}")
        tv, tv_ay = "", ""
    try:
        eh, ed = _evds()
    except Exception as e:
        print(f"[uyari] EVDS M3 alinamadi: {e}")
        eh, ed = "", ""
    if not DOSYA.exists():
        DOSYA.write_text(BASLIK, encoding="utf-8")
    with DOSYA.open("a", encoding="utf-8") as f:
        f.write(f"{zaman},{tv},{tv_ay},{eh},{ed}\n")
    print(f"M3 kaydi: {zaman} TV={tv} ({tv_ay}) EVDS={ed} ({eh})")


if __name__ == "__main__":
    main()
