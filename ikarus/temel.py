"""Temel analiz verisi: Is Yatirim mali tablo servisi (ceyreklik). Bulutta (GitHub Actions) calisir.
Kullanim: python -m ikarus.temel ornek THYAO BIMAS AKBNK   -> temel/ornek_<HISSE>.json (ham)
"""
from __future__ import annotations

import json
import sys
import time

import requests

from . import data as D

URL = "https://www.isyatirim.com.tr/_layouts/15/IsYatirim.Website/Common/Data.aspx/MaliTablo"
HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
R = D.ROOT / "temel"


def donemler(son_yil: int, son_ay: int, adet: int):
    y, m = son_yil, son_ay
    out = []
    for _ in range(adet):
        out.append((y, m))
        m -= 3
        if m <= 0:
            m += 12; y -= 1
    return out


def cek(hisse: str, grup: str, dl: list[tuple[int, int]]):
    """dl: en fazla 4 donem. Donus: {kalem_kodu: {"ad":..., (yil,ay): deger}}"""
    p = {"companyCode": hisse, "exchange": "TRY", "financialGroup": grup}
    for i, (y, m) in enumerate(dl, 1):
        p[f"year{i}"] = y; p[f"period{i}"] = m
    r = requests.get(URL, params=p, headers=HDR, timeout=30)
    r.raise_for_status()
    js = r.json()
    return js


def ornek(hisseler):
    R.mkdir(exist_ok=True)
    for h in hisseler:
        res = {}
        for grup in ("XI_29", "UFRS"):
            try:
                js = cek(h, grup, donemler(2026, 6, 4))
                res[grup] = js
            except Exception as e:
                res[grup] = f"HATA {e}"
            time.sleep(1)
        (R / f"ornek_{h}.json").write_text(json.dumps(res, ensure_ascii=False, indent=0)[:400000], encoding="utf-8")
        print(h, {k: (len(v.get("value", [])) if isinstance(v, dict) else v) for k, v in res.items()})


if __name__ == "__main__":
    if sys.argv[1] == "ornek":
        ornek(sys.argv[2:])
