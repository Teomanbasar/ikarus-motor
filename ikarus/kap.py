"""KAP'tan pay geri alimi bildirimleri (22 Kas 2026, Teoman: 'pay geri alimi onemli bir kriter olmali').

Kaynak: KAP'in sitesinin kullandigi JSON uc noktasi POST /tr/api/disclosure/members/byCriteria
(kap-client paketindeki govde ve basliklarla). Tarih pencereleri halinde tum sirket bildirimleri cekilir,
konu/ozetinde 'geri al' gecenler data/geri_alim.csv'ye yazilir.
"""
from __future__ import annotations

import time

import pandas as pd
import requests

from .data import DATA

URL = "https://www.kap.org.tr/tr/api/disclosure/members/byCriteria"
BASLIK = {
    "Origin": "https://www.kap.org.tr", "Referer": "https://www.kap.org.tr/tr/bildirim-sorgu",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*", "Accept-Language": "tr-TR,tr;q=0.9", "Content-Type": "application/json",
}


def _govde(a, b):
    return {"fromDate": a, "toDate": b, "memberType": "", "mkkMemberOidList": [], "inactiveMkkMemberOidList": [], "disclosureClass": "",
            "subjectList": [], "isLate": "", "mainSector": "", "sector": "", "subSector": "", "marketOid": "", "index": "", "bdkReview": "",
            "bdkMemberOidList": [], "year": "", "term": "", "ruleType": "", "period": "", "fromSrc": False, "srcCategory": "", "disclosureIndexList": []}


def _cek(s, a, b, deneme=4):
    for i in range(deneme):
        try:
            r = s.post(URL, json=_govde(a, b), headers=BASLIK, timeout=60)
            if r.status_code == 200:
                return r.json()
            print("kap", a, b, r.status_code, r.text[:200])
        except Exception as e:
            print("kap hata", a, b, e)
        time.sleep(3 * (i + 1))
    return None


def geri_alim_topla(bas: str = "2021-01-01", gun: int = 7, butce_dk: float = 100):
    f = DATA / "geri_alim.csv"
    eski = pd.read_csv(f, dtype=str) if f.exists() else pd.DataFrame()
    t0 = time.time()
    s = requests.Session()
    s.get("https://www.kap.org.tr/tr/", headers={"User-Agent": BASLIK["User-Agent"]}, timeout=60)
    a = pd.Timestamp(bas) if eski.empty else pd.Timestamp(eski["tarih"].max()[:10]) - pd.Timedelta(days=3)
    son = pd.Timestamp.today().normalize()
    satir, ornek_konu, n_top = [], {}, 0
    while a <= son and time.time() - t0 < butce_dk * 60:
        b = min(a + pd.Timedelta(days=gun - 1), son)
        rows = _cek(s, a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d"))
        if rows is not None and len(rows) >= 2000 and b > a:
            rows = []  # pencere dolu: gun gun cek
            for g in pd.date_range(a, b):
                r1 = _cek(s, g.strftime("%Y-%m-%d"), g.strftime("%Y-%m-%d")) or []
                if len(r1) >= 2000:
                    print("uyari: tek gun dolu", g.date())
                rows += r1
                time.sleep(0.4)
        if rows is None:
            a = b + pd.Timedelta(days=1); continue
        n_top += len(rows)
        for r in rows:
            b_ = r.get("basic", r) if isinstance(r, dict) else {}
            konu = str(b_.get("subject") or b_.get("title") or "")
            ozet = str(b_.get("summary") or "")
            ornek_konu[konu] = ornek_konu.get(konu, 0) + 1
            if "geri al" in (konu + " " + ozet).lower().replace("İ", "i").replace("ı", "i"):
                satir.append({"tarih": str(b_.get("publishDate") or b_.get("publishDateTime") or ""), "hisse": str(b_.get("stockCodes") or b_.get("stockCode") or ""),
                              "konu": konu, "ozet": ozet[:300], "index": str(b_.get("disclosureIndex") or "")})
        a = b + pd.Timedelta(days=1)
        time.sleep(0.5)
    yeni = pd.DataFrame(satir)
    tum = pd.concat([eski, yeni]).drop_duplicates(subset=["index"]) if len(yeni) else eski
    tum.to_csv(f, index=False)
    print(f"KAP: {n_top} bildirim tarandi, {len(yeni)} geri alim satiri; dosyada {len(tum)}. Son tarih {a:%Y-%m-%d}")
    print("en sik konular:", sorted(ornek_konu.items(), key=lambda x: -x[1])[:15])
    if len(rows or []):
        print("ornek ham satir:", str(rows[0])[:800])
    return tum
