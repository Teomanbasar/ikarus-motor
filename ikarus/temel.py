"""Temel analiz: Is Yatirim mali tablo servisinden ceyreklik veriler, Turkiye'ye uyarlanmis F-skoru.
Bulutta (GitHub Actions) calisir; haftada bir yeterli (bilancolar ceyreklik).

Kullanim:
  python -m ikarus.temel ornek THYAO BIMAS        -> temel/ornek_<HISSE>.json (ham veri)
  python -m ikarus.temel hesapla [HISSE ...]      -> temel/temel.json (tum BIST ya da verilenler)

F-skoru (sanayi/hizmet sirketleri, 9 madde, her "evet" 1 puan; akim kalemleri son 4 ceyrek toplami):
  Karlilik : 1 net kar > 0 | 2 faaliyetlerden nakit > 0 | 3 ozsermaye karliligi (ROE) gecen yildan yuksek
             4 faaliyet nakdi > net kar (kar gercek mi)
  Borc     : 5 net borc / FAVOK gecen yildan dusuk (ya da net nakit) | 6 cari oran gecen yildan yuksek
             7 bedelli sermaye artirimi yok (son 4 ceyrek)
  Buyume   : 8 ozkaynak M3'ten hizli buyudu (reel buyume) | 9 brut kar marji gecen yildan yuksek
Bankalar (5 madde): net kar > 0 | ROE gecen yildan yuksek | ozkaynak M3'ten hizli | net faiz geliri M3'ten hizli |
  ROE >= %30 (yuksek faiz ortaminda kabaca alt sinir)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date

import pandas as pd
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


def _cek4(hisse, grup, dl):
    p = {"companyCode": hisse, "exchange": "TRY", "financialGroup": grup}
    for i, (y, m) in enumerate(dl, 1):
        p[f"year{i}"] = y; p[f"period{i}"] = m
    for deneme in range(3):
        try:
            r = requests.get(URL, params=p, headers=HDR, timeout=30)
            r.raise_for_status()
            js = r.json()
            return js.get("value") or []
        except Exception:
            time.sleep(2 + 3 * deneme)
    return []


def cek(hisse: str, ceyrek: int = 12):
    """{(yil, ay): {kod: deger}}, grup ("XI_29" sanayi / "UFRS" banka)."""
    bugun = date.today()
    son_ay = ((bugun.month - 1) // 3) * 3  # icinde bulunulan ceyrekten onceki ceyrek sonu
    son_yil = bugun.year
    if son_ay == 0:
        son_ay, son_yil = 12, son_yil - 1
    dl = donemler(son_yil, son_ay, ceyrek)
    for grup in ("XI_29", "UFRS"):
        tab = {}
        for i in range(0, len(dl), 4):
            parca = dl[i:i + 4]
            for it in _cek4(hisse, grup, parca):
                for j, d in enumerate(parca, 1):
                    v = it.get(f"value{j}")
                    if v not in (None, ""):
                        tab.setdefault(d, {})[it["itemCode"]] = float(v)
            time.sleep(0.6)
        # dolu donemler: toplam varlik/aktif > 0
        tab = {d: v for d, v in tab.items() if (v.get("1BL") or v.get("1Z") or 0) > 0 or (v.get("3C") or v.get("3A") or 0) != 0}
        if tab:
            return grup, tab
    return None, {}


def _ttm(tab, d, kod):
    """Son 4 ceyrek toplami (gelir/nakit kalemleri yil ici kumulatif gelir)."""
    y, m = d
    if m == 12:
        return tab.get(d, {}).get(kod)
    a = tab.get(d, {}).get(kod); fy = tab.get((y - 1, 12), {}).get(kod); ay = tab.get((y - 1, m), {}).get(kod)
    if None in (a, fy, ay):
        return None
    return a + fy - ay


def _m3_oran(m3, d1, d0):
    """d0'dan d1'e M3 buyume carpani (ay damgali seri)."""
    def deger(d):
        t = pd.Timestamp(d[0], d[1], 1)
        s = m3[m3.index <= t]
        return float(s.iloc[-1]) if len(s) else None
    a, b = deger(d1), deger(d0)
    return a / b if a and b else None


def _bol(a, b):
    try:
        return a / b if a is not None and b not in (None, 0) else None
    except Exception:
        return None


def skor(grup, tab, m3):
    if not tab:
        return None
    d = max(tab)  # son donem
    y, m = d
    d1 = (y - 1, m)
    if d1 not in tab:
        return {"donem": f"{y}/{m:02d}", "not": "gecen yilin ayni donemi yok"}
    T = lambda kod, dd=d: _ttm(tab, dd, kod)
    B = lambda kod, dd=d: tab.get(dd, {}).get(kod)
    m3c = _m3_oran(m3, d, d1)
    out = {"donem": f"{y}/{m:02d}", "tip": "banka" if grup == "UFRS" else "sanayi", "maddeler": []}

    def madde(ad, deger, gecti, aciklama, bicim="tl"):
        out["maddeler"].append({"ad": ad, "deger": deger, "gecti": None if gecti is None else bool(gecti), "aciklama": aciklama, "bicim": bicim})

    if grup == "UFRS":
        nk, nk1 = T("3Z"), T("3Z", d1)
        oz, oz1 = B("2O"), B("2O", d1)
        roe = _bol(nk, oz); roe1 = _bol(nk1, oz1)
        nfg, nfg1 = T("3C"), T("3C", d1)
        madde("Net kâr pozitif", nk, None if nk is None else nk > 0, "Son 4 çeyrekte banka para kazandı mı?")
        madde("Özsermaye kârlılığı (ROE) arttı", roe, None if roe is None or roe1 is None else roe > roe1, "Net kâr / özkaynak geçen yılın aynı dönemine göre yükseldi mi?", "yuzde")
        g = _bol(oz, oz1)
        madde("Özkaynak M3'ten hızlı büyüdü", None if g is None or not m3c else g / m3c - 1, None if g is None or not m3c else g > m3c,
              "Özkaynak bir yılda para arzından (M3) hızlı büyüdü mü? Değer, M3'e göre reel büyüme.", "yuzde")
        g2 = _bol(nfg, nfg1)
        madde("Net faiz geliri M3'ten hızlı büyüdü", None if g2 is None or not m3c else g2 / m3c - 1, None if g2 is None or not m3c or (nfg1 or 0) <= 0 else g2 > m3c,
              "Bankanın ana işi olan faiz geliri M3'ten hızlı büyüdü mü? Değer reel büyüme.", "yuzde")
        madde("ROE en az %30", roe, None if roe is None else roe >= 0.30, "Yüksek faiz ortamında özkaynak kârlılığı mevduat getirisine yakın mı?", "yuzde")
        out["oranlar"] = {"roe": roe, "ozkaynak_reel_buyume": None if g is None or not m3c else g / m3c - 1,
                          "net_kar_reel_buyume": None if nk is None or nk1 in (None, 0) or not m3c or nk1 <= 0 else (nk / nk1) / m3c - 1}
    else:
        nk, nk1 = T("3Z"), T("3Z", d1)
        nak, nak1 = T("4C"), T("4C", d1)
        oz, oz1 = B("2O"), B("2O", d1)
        roe = _bol(nk, oz); roe1 = _bol(nk1, oz1)
        favok = None if T("3DF") is None or T("4B") is None else T("3DF") + T("4B")
        favok1 = None if T("3DF", d1) is None or T("4B", d1) is None else T("3DF", d1) + T("4B", d1)

        def netborc(dd):
            fb = (B("2AA", dd) or 0) + (B("2BA", dd) or 0)
            return fb - (B("1AA", dd) or 0) - (B("1AB", dd) or 0)
        nb, nb1 = netborc(d), netborc(d1)
        nbf, nbf1 = _bol(nb, favok), _bol(nb1, favok1)
        cari, cari1 = _bol(B("1A"), B("2A")), _bol(B("1A", d1), B("2A", d1))
        bedelli = T("4CBC")
        g = _bol(oz, oz1)
        marj, marj1 = _bol(T("3D"), T("3C")), _bol(T("3D", d1), T("3C", d1))

        madde("Net kâr pozitif", nk, None if nk is None else nk > 0, "Son 4 çeyrekte şirket (ana ortaklık payı) para kazandı mı?")
        madde("Faaliyetlerden nakit pozitif", nak, None if nak is None else nak > 0, "Esas faaliyetlerden kasaya gerçekten nakit giriyor mu? (son 4 çeyrek)")
        madde("Özsermaye kârlılığı (ROE) arttı", roe, None if roe is None or roe1 is None else roe > roe1, "Net kâr / özkaynak geçen yılın aynı dönemine göre yükseldi mi?", "yuzde")
        madde("Nakit kârdan büyük (kâr kalitesi)", None if nak is None or nk is None else nak - nk, None if nak is None or nk is None else nak > nk,
              "Faaliyet nakdi net kârdan büyük mü? Değilse kâr kâğıt üstünde kalıyor olabilir. Değer: nakit − kâr.")
        if nb is not None and nb1 is not None and nb <= 0 and nb1 <= 0:
            madde("Net borç / FAVÖK azaldı", nbf, True, "Şirket net nakitte: kasasındaki para finansal borcundan fazla.", "kat")
        else:
            madde("Net borç / FAVÖK azaldı", nbf, None if nbf is None or nbf1 is None or (favok or 0) <= 0 else nbf < nbf1,
                  "Net borcun yıllık FAVÖK'e oranı geçen yıldan düşük mü? 2'nin altı rahat, 3–4 üstü riskli.", "kat")
        madde("Cari oran iyileşti", cari, None if cari is None or cari1 is None else cari > cari1, "Dönen varlıklar / kısa vadeli borçlar geçen yıldan yüksek mi? 1'in altı sıkışık.", "kat")
        madde("Bedelli sermaye artırımı yok", bedelli, None if bedelli is None else bedelli <= 0, "Son 4 çeyrekte ortaklardan para toplanıp hisse sulandırıldı mı? (Bedelsiz sayılmaz.) Değer: toplanan para.")
        madde("Özkaynak M3'ten hızlı büyüdü", None if g is None or not m3c else g / m3c - 1, None if g is None or not m3c else g > m3c,
              "Özkaynak bir yılda para arzından (M3) hızlı büyüdü mü? Değer, M3'e göre reel büyüme.", "yuzde")
        madde("Brüt kâr marjı arttı", marj, None if marj is None or marj1 is None else marj > marj1, "Brüt kâr / satışlar geçen yıldan yüksek mi? Fiyatlama gücünün işareti.", "yuzde")
        out["oranlar"] = {"roe": roe, "net_borc_favok": nbf, "cari_oran": cari, "brut_marj": marj,
                          "ozkaynak_reel_buyume": None if g is None or not m3c else g / m3c - 1,
                          "net_kar_reel_buyume": None if nk is None or nk1 in (None, 0) or not m3c or nk1 <= 0 else (nk / nk1) / m3c - 1,
                          "serbest_nakit": T("4CB")}
    out["ham"] = {"net_kar": nk, "ozkaynak": oz, "sermaye": B("2OA")}
    gec = [x["gecti"] for x in out["maddeler"]]
    out["puan"] = sum(1 for x in gec if x)
    out["olculen"] = sum(1 for x in gec if x is not None)
    out["en_fazla"] = len(gec)
    return out


def hesapla(hisseler=None):
    R.mkdir(exist_ok=True)
    if not hisseler:
        hisseler = D.bist_list()["ticker"].tolist()
    m3 = D.m3()
    f = R / "temel.json"
    eski = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    sonuc = dict(eski.get("hisseler", {}))
    for i, h in enumerate(hisseler):
        try:
            grup, tab = cek(h)
            s = skor(grup, tab, m3)
            if s:
                sonuc[h] = s
        except Exception as e:
            print("hata", h, e)
        if i % 50 == 0:
            print(i, h, sonuc.get(h, {}).get("puan"))
    out = {"olusturma": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "hisseler": sonuc}
    f.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=float), encoding="utf-8")
    print(f"{len(sonuc)} hisse yazildi")


def ornek(hisseler):
    R.mkdir(exist_ok=True)
    for h in hisseler:
        grup, tab = cek(h)
        print(h, grup, sorted(tab)[-1] if tab else None, len(tab))
        (R / f"ham_{h}.json").write_text(json.dumps({"grup": grup, "tab": {f"{y}/{m}": v for (y, m), v in sorted(tab.items())}},
                                                   ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    if sys.argv[1] == "ornek":
        ornek(sys.argv[2:])
    elif sys.argv[1] == "hesapla":
        hesapla(sys.argv[2:] or None)
