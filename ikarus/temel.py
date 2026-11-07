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


# F-skoru kural surumu. 1 = yayindaki; 2 = aday (7 Kas 2026): ROE ve nakit>kar maddeleri negatifte gecmez,
# bedelli maddesi ana ortakligin odenmis sermayesine bakar (konsolide "sermaye artirimi" bagli ortakliktan gelebilir).
SURUM = 1

KODLAR = {"1A", "1AA", "1AB", "1BL", "1Z", "2A", "2AA", "2BA", "2N", "2O", "2OA", "3C", "3D", "3DF", "3Z", "4B", "4C", "4CB", "4CBC"}


def gecmis(ceyrek: int = 28, butce_dk: float = 120, isci: int = 4):
    """Geriye donuk test icin tum BIST'in uzun ceyrek gecmisi -> temel/gecmis.json.gz (yalniz gereken kalemler)."""
    import gzip
    from concurrent.futures import ThreadPoolExecutor, as_completed
    R.mkdir(exist_ok=True)
    f = R / "gecmis.json.gz"
    G = json.loads(gzip.decompress(f.read_bytes())) if f.exists() else {}
    hisseler = [h for h in D.bist_list()["ticker"].tolist() if h not in G]
    t0 = time.time()

    def yaz():
        f.write_bytes(gzip.compress(json.dumps(G, separators=(",", ":")).encode()))

    def is_(h):
        if time.time() - t0 > butce_dk * 60:
            return h, None, None
        grup, tab = cek(h, ceyrek)
        return h, grup, tab
    n = 0
    with ThreadPoolExecutor(isci) as ex:
        for fut in as_completed([ex.submit(is_, h) for h in hisseler]):
            try:
                h, grup, tab = fut.result()
            except Exception as e:
                print("hata", e); continue
            if grup is None:
                continue
            G[h] = {"grup": grup, "tab": {f"{y}/{m}": {k: v for k, v in val.items() if k in KODLAR} for (y, m), val in tab.items()}}
            n += 1
            if n % 50 == 0:
                print(f"{n}/{len(hisseler)} {time.time() - t0:.0f} sn"); yaz()
    yaz()
    print(f"gecmis: {n} yeni, dosyada {len(G)} hisse ({time.time() - t0:.0f} sn)")


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
            time.sleep(0.3)
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


def _bilanco_donemi(tab, d):
    """Bilancosu dolu en yakin donem (d ya da oncesi, en fazla 2 ceyrek geri). Is Yatirim'da bazi
    ceyreklerin bilancosu bos gelebiliyor (ornek AKBNK 2025/9)."""
    y, m = d
    for _ in range(3):
        v = tab.get((y, m), {})
        if (v.get("1BL") or v.get("1Z") or 0) > 0:
            return (y, m)
        m -= 3
        if m <= 0:
            m += 12; y -= 1
    return d


def _bol(a, b):
    try:
        return a / b if a is not None and b not in (None, 0) else None
    except Exception:
        return None


def skor(grup, tab, m3, d=None):
    if not tab:
        return None
    if d is None:
        d = max(tab)  # son donem
    elif d not in tab:
        return None
    y, m = d
    d1 = (y - 1, m)
    if d1 not in tab:
        return {"donem": f"{y}/{m:02d}", "not": "gecen yilin ayni donemi yok"}
    T = lambda kod, dd=d: _ttm(tab, dd, kod)
    bd, bd1 = _bilanco_donemi(tab, d), _bilanco_donemi(tab, d1)
    B = lambda kod, dd=d: tab.get(bd if dd == d else bd1 if dd == d1 else dd, {}).get(kod)
    m3c = _m3_oran(m3, bd, bd1)  # bilanco kalemleri (ozkaynak) icin
    m3c_akim = _m3_oran(m3, d, d1)  # gelir kalemleri (son 4 ceyrek) icin
    out = {"donem": f"{y}/{m:02d}", "bilanco_karsilastirma": f"{bd1[0]}/{bd1[1]:02d}", "tip": "banka" if grup == "UFRS" else "sanayi", "maddeler": []}

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
        madde("Net faiz geliri M3'ten hızlı büyüdü", None if g2 is None or not m3c_akim else g2 / m3c_akim - 1, None if g2 is None or not m3c_akim or (nfg1 or 0) <= 0 else g2 > m3c_akim,
              "Bankanın ana işi olan faiz geliri M3'ten hızlı büyüdü mü? Değer reel büyüme.", "yuzde")
        madde("ROE en az %30", roe, None if roe is None else roe >= 0.30, "Yüksek faiz ortamında özkaynak kârlılığı mevduat getirisine yakın mı?", "yuzde")
        out["oranlar"] = {"roe": roe, "ozkaynak_reel_buyume": None if g is None or not m3c else g / m3c - 1,
                          "net_kar_reel_buyume": None if nk is None or nk1 in (None, 0) or not m3c_akim or nk1 <= 0 else (nk / nk1) / m3c_akim - 1}
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
        nbf = _bol(nb, favok) if (favok or 0) > 0 else None   # FAVOK negatifse oran anlamsiz
        nbf1 = _bol(nb1, favok1) if (favok1 or 0) > 0 else None
        cari, cari1 = _bol(B("1A"), B("2A")), _bol(B("1A", d1), B("2A", d1))
        bedelli = T("4CBC")
        g = _bol(oz, oz1)
        marj, marj1 = _bol(T("3D"), T("3C")), _bol(T("3D", d1), T("3C", d1))

        madde("Net kâr pozitif", nk, None if nk is None else nk > 0, "Son 4 çeyrekte şirket (ana ortaklık payı) para kazandı mı?")
        madde("Faaliyetlerden nakit pozitif", nak, None if nak is None else nak > 0, "Esas faaliyetlerden kasaya gerçekten nakit giriyor mu? (son 4 çeyrek)")
        roe_ok = None if roe is None or roe1 is None else (roe > roe1 and (SURUM < 2 or roe > 0))
        madde("Özsermaye kârlılığı (ROE) arttı", roe, roe_ok, "Net kâr / özkaynak geçen yılın aynı dönemine göre yükseldi mi?", "yuzde")
        nak_ok = None if nak is None or nk is None else (nak > nk and (SURUM < 2 or nak > 0))
        madde("Nakit kârdan büyük (kâr kalitesi)", None if nak is None or nk is None else nak - nk, nak_ok,
              "Faaliyet nakdi net kârdan büyük mü? Değilse kâr kâğıt üstünde kalıyor olabilir. Değer: nakit − kâr.")
        if (favok or 0) <= 0:
            madde("Net borç / FAVÖK azaldı", None, False, "FAVÖK (faaliyet kârı + amortisman) negatif: şirket esas faaliyetinden zarar ediyor, borcu kârla ödeyemez.", "kat")
        elif nb is not None and nb1 is not None and nb <= 0 and nb1 <= 0:
            madde("Net borç / FAVÖK azaldı", nbf, True, "Şirket net nakitte: kasasındaki para finansal borcundan fazla.", "kat")
        else:
            madde("Net borç / FAVÖK azaldı", nbf, None if nbf is None or nbf1 is None or (favok or 0) <= 0 else nbf < nbf1,
                  "Net borcun yıllık FAVÖK'e oranı geçen yıldan düşük mü? 2'nin altı rahat, 3–4 üstü riskli.", "kat")
        madde("Cari oran iyileşti", cari, None if cari is None or cari1 is None else cari > cari1, "Dönen varlıklar / kısa vadeli borçlar geçen yıldan yüksek mi? 1'in altı sıkışık.", "kat")
        if SURUM < 2:
            bed_ok = None if bedelli is None else bedelli <= 0
        else:
            s0, s1 = B("2OA"), B("2OA", d1)
            artti = None if s0 is None or s1 is None else s0 > s1 * 1.001
            onemli = (bedelli or 0) > 0.02 * (oz or 0) if oz else (bedelli or 0) > 0
            bed_ok = None if artti is None else not (artti and onemli)
        madde("Bedelli sermaye artırımı yok", bedelli, bed_ok, "Son 4 çeyrekte ortaklardan para toplanıp hisse sulandırıldı mı? (Bedelsiz sayılmaz.) Değer: toplanan para.")
        madde("Özkaynak M3'ten hızlı büyüdü", None if g is None or not m3c else g / m3c - 1, None if g is None or not m3c else g > m3c,
              "Özkaynak bir yılda para arzından (M3) hızlı büyüdü mü? Değer, M3'e göre reel büyüme.", "yuzde")
        madde("Brüt kâr marjı arttı", marj, None if marj is None or marj1 is None else marj > marj1, "Brüt kâr / satışlar geçen yıldan yüksek mi? Fiyatlama gücünün işareti.", "yuzde")
        out["oranlar"] = {"roe": roe, "net_borc_favok": nbf, "favok_negatif": (favok or 0) <= 0, "net_nakit": nb is not None and nb <= 0, "cari_oran": cari, "brut_marj": marj,
                          "ozkaynak_reel_buyume": None if g is None or not m3c else g / m3c - 1,
                          "net_kar_reel_buyume": None if nk is None or nk1 in (None, 0) or not m3c_akim or nk1 <= 0 else (nk / nk1) / m3c_akim - 1,
                          "serbest_nakit": T("4CB")}
    out["ham"] = {"net_kar": nk, "ozkaynak": oz, "sermaye": B("2OA")}
    gec = [x["gecti"] for x in out["maddeler"]]
    out["puan"] = sum(1 for x in gec if x)
    out["olculen"] = sum(1 for x in gec if x is not None)
    out["en_fazla"] = len(gec)
    return out


def hesapla(hisseler=None, butce_dk: float = 95, isci: int = 4):
    """Paralel ceker; sure butcesi dolunca o ana kadarkini yazar. Sonraki calisma en eski guncellenenlerden devam eder."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    R.mkdir(exist_ok=True)
    f = R / "temel.json"
    eski = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    sonuc = dict(eski.get("hisseler", {}))
    if not hisseler:
        hisseler = D.bist_list()["ticker"].tolist()
        hisseler.sort(key=lambda h: sonuc.get(h, {}).get("guncelleme", ""))  # once hic/eski cekilenler
    m3 = D.m3()
    t0 = time.time()
    bitti = 0

    def yaz():
        out = {"olusturma": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "hisseler": sonuc}
        f.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=float), encoding="utf-8")

    def is_(h):
        if time.time() - t0 > butce_dk * 60:
            return h, "atla"
        grup, tab = cek(h)
        return h, skor(grup, tab, m3)

    with ThreadPoolExecutor(isci) as ex:
        for fut in as_completed([ex.submit(is_, h) for h in hisseler]):
            try:
                h, s = fut.result()
            except Exception as e:
                print("hata", e); continue
            if s == "atla":
                continue
            bitti += 1
            if s:
                s["guncelleme"] = pd.Timestamp.now().strftime("%Y-%m-%d")
                sonuc[h] = s
            if bitti % 50 == 0:
                print(f"{bitti}/{len(hisseler)} {time.time() - t0:.0f} sn"); yaz()
    yaz()
    print(f"{bitti}/{len(hisseler)} hisse islendi, dosyada {len(sonuc)} hisse ({time.time() - t0:.0f} sn)")


def ornek(hisseler):
    R.mkdir(exist_ok=True)
    for h in hisseler:
        grup, tab = cek(h)
        print(h, grup, sorted(tab)[-1] if tab else None, len(tab))
        (R / f"ham_{h}.json").write_text(json.dumps({"grup": grup, "tab": {f"{y}/{m}": v for (y, m), v in sorted(tab.items())}},
                                                   ensure_ascii=False), encoding="utf-8")


def etiket(hisseler, ceyrek: int = 8):
    """Kalem kodlari + Turkce/Ingilizce adlariyla tum tablo -> temel/etiket_<HISSE>.tsv (son N ceyrek)."""
    R.mkdir(exist_ok=True)
    bugun = date.today()
    son_ay = ((bugun.month - 1) // 3) * 3
    son_yil = bugun.year
    if son_ay == 0:
        son_ay, son_yil = 12, son_yil - 1
    dl = donemler(son_yil, son_ay, ceyrek)
    for h in hisseler:
        for grup in ("XI_29", "UFRS"):
            satir = {}
            for i in range(0, len(dl), 4):
                parca = dl[i:i + 4]
                for it in _cek4(h, grup, parca):
                    r = satir.setdefault(it["itemCode"], {"tr": it.get("itemDescTr", ""), "en": it.get("itemDescEng", "")})
                    for j, d in enumerate(parca, 1):
                        r[f"{d[0]}/{d[1]}"] = it.get(f"value{j}")
                time.sleep(0.3)
            if any(v.get(f"{d[0]}/{d[1]}") not in (None, "") for v in satir.values() for d in dl):
                kol = [f"{y}/{m}" for y, m in dl]
                out = ["kod\tad\tad_en\t" + "\t".join(kol)]
                for k, v in satir.items():
                    out.append("\t".join([k, str(v["tr"]).strip(), str(v["en"]).strip()] + [str(v.get(c) or "") for c in kol]))
                (R / f"etiket_{h}.tsv").write_text("\n".join(out), encoding="utf-8")
                print(h, grup, len(satir), "kalem")
                break


if __name__ == "__main__":
    if sys.argv[1] == "bt_karsilastir":
        from . import temel_bt
        for sv in (1, 2):
            temel_bt.main(sv)
    elif sys.argv[1] == "etiket":
        etiket(sys.argv[2:])
    elif sys.argv[1] == "ornek":
        ornek(sys.argv[2:])
    elif sys.argv[1] == "gecmis":
        gecmis()
        from . import temel_bt
        temel_bt.main()
    elif sys.argv[1] == "bt":
        from . import temel_bt
        temel_bt.main()
    elif sys.argv[1] == "hesapla":
        hesapla(sys.argv[2:] or None)
