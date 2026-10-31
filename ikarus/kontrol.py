"""Kurulum kontrolu: Yahoo verisiyle hesaplanan degerleri TradingView'deki IKARUS v4.6 ve
Zippo tablolariyla karsilastirir. Fark buyukse veri kaynagi TradingView'den ayrisiyor demektir.
Kullanim: python -m ikarus.kontrol
"""
from __future__ import annotations

import pandas as pd

from . import data as D
from . import engine as E

# (hisse, zaman, tarih, kaynak, beklenen degerler)
REF = [
    ("AKBNK", "D", "2026-10-20", "Zippo", dict(percentile=5.5, dip=65.74, tepe=107.86, stop=65.74, sinyal="TOPLANIYOR")),
    ("THYAO", "D", "2026-10-20", "Zippo", dict(percentile=1.0, dip=266.0, tepe=403.3, stop=266.0, sinyal="YAKIN")),
    ("MIATK", "D", "2026-10-20", "Zippo", dict(percentile=3.5, dip=20.69, tepe=62.09, stop=20.69)),
    ("GSDHO", "D", "2026-10-19", "Zippo", dict(percentile=0.0, dip=3.99, tepe=7.28, stop=3.99, sinyal="YAKIN")),
    ("TAVHL", "D", "2026-10-21", "Zippo", dict(percentile=31.0, dip=252.94, tepe=419.79, stop=252.94, sinyal="ALINABILIR")),
    ("AKBNK", "D", "2026-10-30", "TradingView v4.6", dict(percentile=0.0, memory=10.0, compression=5.6, recovery=0.0,
                                                          rs=8.0, mtf=12.5, hacim=1.06, toplam=40.7, dip=60.9, tepe=107.86, sinyal="DAGITIM")),
    ("GUBRF", "W", "2026-10-26", "TradingView v4.6", dict(percentile=0.0, memory=1.3, compression=3.3, rs=0.0,
                                                          toplam=21.6, dip=250.25, tepe=1298.04, stop=250.25, sinyal="BEKLE")),
]


def main():
    tick = sorted({r[0] for r in REF})
    px = D.prices(tick, refresh=True)
    xu = D.xu100()
    m3 = D.m3()
    tol = {"dip": 0.02, "tepe": 0.02, "stop": 0.02}
    n_ok = n = 0
    for t, tf, tarih, kaynak, exp in REF:
        if t not in px:
            print(f"{t}: veri yok"); continue
        day = pd.Timestamp(tarih)
        end = day + pd.Timedelta(days=6) if tf == "W" else day
        df = px[t][px[t].index <= end]
        xx = xu[xu.index <= end]
        r = E.compute(df, xx, m3, tf)
        row = E.table_row(r.iloc[-1])
        out = []
        for k, v in exp.items():
            got = row[k]
            if isinstance(v, str):
                ok = got == v
            else:
                lim = max(0.051, tol.get(k, 0) * abs(v))
                ok = got is not None and abs(got - v) <= lim
            n += 1; n_ok += ok
            out.append(f"{k} {got}{'' if ok else ' (beklenen ' + str(v) + ')'}")
        print(f"{t} {tf} {tarih} [{kaynak}]: " + " | ".join(out))
    print(f"\n{n_ok}/{n} deger tuttu.")
    if n_ok < n:
        print("Tutmayan degerler varsa: Yahoo fiyat/temettu duzeltmesi TradingView'den farkli olabilir; "
              "Dip/Tepe kurus farki normaldir, Percentile farki varsa haber ver.")


if __name__ == "__main__":
    main()
