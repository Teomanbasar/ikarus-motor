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
SURUM = 2  # 8 Kas 2026: Teoman onayi ile 2'ye gecildi (bt: temel/bt_sonuc_v1/v2.txt)

KODLAR = {"1A", "1AA", "1AB", "1BL", "1Z", "2A", "2AA", "2BA", "2N", "2O", "2OA", "3C", "3D", "3DF", "3Z", "4B", "4C", "4CB", "4CBC"}


PK_KOD = {"1AA", "1AB", "1AC", "1AD", "1AE", "1B", "1BA", "1BB", "1BC", "2A", "2B", "2AA", "2BA", "2AAGAC", "2BBBA", "2BG",
          "2AAGCA", "2BDA", "1BL", "3Z"}


def gecmis_pk(ceyrek: int = 16, butce_dk: float = 100, isci: int = 4):
    """22 Kas: net parasal pozisyon tahmini icin bilanco kalemleri (parasal varlik/yukumluluk) -> temel/gecmis_pk.json.gz."""
    import gzip
    from concurrent.futures import ThreadPoolExecutor, as_completed
    f = R / "gecmis_pk.json.gz"
    G = json.loads(gzip.decompress(f.read_bytes())) if f.exists() else {}
    hisseler = [h for h in D.bist_list()["ticker"].tolist() if h not in G]
    t0 = time.time()

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
            G[h] = {"grup": grup, "tab": {f"{y}/{m}": {k: v for k, v in val.items() if k in PK_KOD} for (y, m), val in tab.items()}}
            n += 1
            if n % 100 == 0:
                print(f"pk {n}/{len(hisseler)} {time.time() - t0:.0f} sn")
                f.write_bytes(gzip.compress(json.dumps(G, separators=(",", ":")).encode()))
    f.write_bytes(gzip.compress(json.dumps(G, separators=(",", ":")).encode()))
    print(f"gecmis_pk: {n} yeni, dosyada {len(G)} hisse ({time.time() - t0:.0f} sn)")


def gecmis_eski(butce_dk: float = 110, isci: int = 4):
    """23 Kas (Teoman: 'veriler normal bir piyasada ne kadar calisir?'). 2013/3-2019/9 ceyrekleri -> temel/gecmis_uzun.json.gz
    (gecmis.json.gz + eski ceyrekler; artimli)."""
    import gzip
    from concurrent.futures import ThreadPoolExecutor, as_completed
    fu = R / "gecmis_uzun.json.gz"
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    U = json.loads(gzip.decompress(fu.read_bytes())) if fu.exists() else {}
    donemler = [(y, m) for y in range(2013, 2020) for m in (3, 6, 9, 12)]
    yap = [h for h in G if not U.get(h, {}).get("eski_tamam")]
    t0 = time.time()
    def is_(h):
        if time.time() - t0 > butce_dk * 60:
            return h, None
        grup = G[h]["grup"]
        tab = {}
        for i in range(0, len(donemler), 4):
            dl = donemler[i:i + 4]
            for it in _cek4(h, grup, dl):
                kod = it.get("itemCode")
                if kod not in KODLAR:
                    continue
                for j, (y, m) in enumerate(dl, 1):
                    v = it.get(f"value{j}")
                    if v not in (None, ""):
                        try:
                            tab.setdefault(f"{y}/{m}", {})[kod] = float(v)
                        except (TypeError, ValueError):
                            pass
        return h, tab
    n = 0
    with ThreadPoolExecutor(isci) as ex:
        for fut in as_completed([ex.submit(is_, h) for h in yap]):
            h, tab = fut.result()
            if tab is None:
                continue
            U[h] = {"grup": G[h]["grup"], "eski": tab, "eski_tamam": True}
            n += 1
            if n % 100 == 0:
                print(f"eski {n}/{len(yap)} {time.time() - t0:.0f} sn")
                fu.write_bytes(gzip.compress(json.dumps(U, separators=(",", ":")).encode()))
    fu.write_bytes(gzip.compress(json.dumps(U, separators=(",", ":")).encode()))
    kalan = sum(1 for h in G if not U.get(h, {}).get("eski_tamam"))
    dolu = sum(1 for h in U if U[h].get("eski"))
    print(f"gecmis_eski: {n} yeni, eski verisi olan {dolu}/{len(G)}, kalan {kalan}")
    return kalan


def gecmis_birlesik():
    """gecmis.json.gz + eski ceyrekler (uzun test icin)."""
    import gzip
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    fu = R / "gecmis_uzun.json.gz"
    if fu.exists():
        U = json.loads(gzip.decompress(fu.read_bytes()))
        for h, u in U.items():
            if h in G:
                for k, v in (u.get("eski") or {}).items():
                    G[h]["tab"].setdefault(k, v)
    return G


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
        if tab and ceyrek <= 12 and yarim_yillik(tab):
            # 24 Kas: yari yillik sirketlerde 12 ceyrek = 6 bilanco; surpriz icin en az 4 gecmis fark lazim -> 8 ceyrek daha
            ek = donemler(*min(dl), 9)[1:]
            for i in range(0, len(ek), 4):
                parca = ek[i:i + 4]
                if len(parca) < 4:
                    break
                for it in _cek4(hisse, grup, parca):
                    for j, d in enumerate(parca, 1):
                        v = it.get(f"value{j}")
                        if v not in (None, ""):
                            tab.setdefault(d, {})[it["itemCode"]] = float(v)
                time.sleep(0.3)
            tab = {d: v for d, v in tab.items() if (v.get("1BL") or v.get("1Z") or 0) > 0 or (v.get("3C") or v.get("3A") or 0) != 0}
        if tab:
            return grup, tab
    return None, {}


# --- Ilk gorulen degerler arsivi (15 Kas 2026) ---
# Is Yatirim bir donemin degerini o donemi iceren EN SON rapordan verir. Yeni ceyrek yayinlaninca gecen yilin
# ayni donemi enflasyona gore duzeltilmis (bugunku TL) gelir; bazi hisselerde de gelmez (birim_test: 120 hissenin
# ~%60'inda 2025/9 gelir kalemleri x1.30 degisti, digerlerinde ayni kaldi). Biz zaten M3'e boldugumuz icin
# duzeltilmis deger iki kez enflasyondan arindirilir. Cozum: her donemin ILK gorulen degerini sakla (temel/ilk.json.gz,
# tum BIST tek dosya), canli deger ile ilk deger arasindaki orani (yeniden_oran) M3 carpanindan dus.
ILK = None


def ilk_yukle():
    global ILK
    import gzip
    if ILK is None:
        f = R / "ilk.json.gz"
        if f.exists():
            ILK = json.loads(gzip.decompress(f.read_bytes()))
        else:  # ilk kurulum: 6 Kas 2026 gecmis cekimi
            g = R / "gecmis.json.gz"
            ILK = {h: v["tab"] for h, v in json.loads(gzip.decompress(g.read_bytes())).items()} if g.exists() else {}
    return ILK


def ilk_kaydet():
    import gzip
    if ILK is not None:
        (R / "ilk.json.gz").write_bytes(gzip.compress(json.dumps(ILK, separators=(",", ":")).encode()))


def yeniden_oran(h, tab, guncelle=True):
    """{(donem, 'g'|'b'): canli/ilk orani} (yalniz farkli olanlar). 'g' gelir/nakit, 'b' bilanco kalemleri.
    guncelle: arsivde olmayan donem/kalemleri ilk gorulen deger olarak ekler."""
    import numpy as np
    A = ilk_yukle().setdefault(h, {})
    out = {}
    for (y, m), val in tab.items():
        k = f"{y}/{m}"
        e = A.get(k)
        if e is not None:
            for tur in ("g", "b"):
                r = [v / e[kod] for kod, v in val.items()
                     if kod in KODLAR and (kod[0] in "34") == (tur == "g") and e.get(kod) and v and v * e[kod] > 0 and abs(e[kod]) > 1e3]
                if len(r) >= 3:
                    md = float(np.median(r))
                    if abs(md - 1) > 0.003 and np.mean([abs(x / md - 1) < 0.01 for x in r]) >= 0.6:  # kalemlerin cogu ayni oranla degismis
                        out[((y, m), tur)] = md
        if guncelle:
            hedef = A.setdefault(k, {})
            for kod, v in val.items():
                if kod in KODLAR and kod not in hedef:
                    hedef[kod] = v
    return out


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


def yarim_yillik(tab):
    """24 Kas: yalniz 6 ve 12. ay bilancosu aciklayan sirket (AYES, BALAT, ORMA, YONGA ... 12 sirket)."""
    ks = [k for k in tab if isinstance(k, tuple)]
    return bool(ks) and all(k[1] in (6, 12) for k in ks) and len(ks) >= 3


def ceyreklik(tab, d, kod):
    """Yalniz o ceyregin akim degeri (tablolar yil ici kumulatif).
    24 Kas: yari yillik aciklayan sirketlerde 'ceyrek' yerine yarim yil (H1 = 6. ay, H2 = 12. ay - 6. ay); gecen yilin
    ayni yarisiyla karsilastirilir, boylece suprizler ve satis buyumesi bu sirketlerde de hesaplanir."""
    y, m = d
    a = tab.get(d, {}).get(kod)
    if a is None:
        return None
    if m == 3:
        return a
    p = tab.get((y, m - 3), {}).get(kod)
    if p is None and m in (6, 12) and yarim_yillik(tab):
        if m == 6:
            return a
        p6 = tab.get((y, 6), {}).get(kod)
        return None if p6 is None else a - p6
    return None if p is None else a - p


def isaretler(tab, m3, d, yo=None):
    """Hareket isaretleri (10 Kas 2026 testinde ise yarayanlar). temel_bt2 de bunu kullanir.
    sue_nk / sue_faal: bu ceyregin net kari / esas faaliyet kari - gecen yilin ayni ceyregi x M3 buyumesi,
      hissenin onceki 8 ceyrekteki ayni farklarin oynakligina bolunmus (en az 4 gecmis fark).
    satis_reel: ceyreklik satislarin M3'e gore yillik buyumesi. roe_ivme: son 4 ceyrek ROE'sinin bir ceyrekte degisimi."""
    out = {}
    yo = yo or {}
    fark = {"3Z": [], "3DF": []}
    for dd in sorted(k for k in tab if k <= d):
        d1 = (dd[0] - 1, dd[1])
        m3y = _m3_oran(m3, dd, d1)
        if m3y:
            m3y *= yo.get((dd, "g"), 1.0) / yo.get((d1, "g"), 1.0)
        for kod, ad in (("3Z", "sue_nk"), ("3DF", "sue_faal")):
            q, q1 = ceyreklik(tab, dd, kod), ceyreklik(tab, d1, kod)
            if q is None or q1 is None or not m3y:
                continue
            f = q - q1 * m3y
            if dd == d:
                ger = fark[kod][-8:]
                if len(ger) >= 4:
                    import numpy as np
                    sd = float(np.std(ger))
                    oz = tab.get(dd, {}).get("2O") or 0
                    taban = 0.005 * abs(oz) if oz else 0
                    if sd + taban > 0:
                        out[ad] = f / (sd + taban)
            fark[kod].append(f)
    y, m = d
    d1 = (y - 1, m)
    dq = (y, m - 3) if m > 3 else (y - 1, 12)
    if dq not in tab and m in (6, 12) and yarim_yillik(tab):   # 24 Kas: yari yillik -> onceki yarim yil
        dq = (y, 6) if m == 12 else (y - 1, 12)
    m3y = _m3_oran(m3, d, d1)
    if m3y:
        m3y *= yo.get((d, "g"), 1.0) / yo.get((d1, "g"), 1.0)

    def roe(dd):
        nk = _ttm(tab, dd, "3Z")
        oz = tab.get(_bilanco_donemi(tab, dd), {}).get("2O")
        return None if nk is None or not oz or oz <= 0 else nk / oz
    r0, rq, ry = roe(d), roe(dq), roe(d1)
    if r0 is not None and rq is not None:
        out["roe_ivme"] = r0 - rq
    if r0 is not None and ry is not None:
        out["roe_deg"] = r0 - ry
    sq, sq1 = ceyreklik(tab, d, "3C"), ceyreklik(tab, d1, "3C")
    if sq and sq1 and sq1 > 0 and m3y:
        out["satis_reel"] = sq / sq1 / m3y - 1
    # 17 Kas: ceyreklik FAVOK (esas faaliyet kari + amortisman) yillik degisimi / ceyrek satisi (temel_bt3 favok_q)
    if sq and sq > 0 and m3y:
        def _fq(dd):
            a_, b_ = ceyreklik(tab, dd, "3DF"), ceyreklik(tab, dd, "4B")
            return None if a_ is None or b_ is None else a_ + b_
        f0, f1 = _fq(d), _fq(d1)
        if f0 is not None and f1 is not None:
            out["favok_q"] = (f0 - f1 * m3y) / sq
    nk0, nkq = _ttm(tab, d, "3Z"), _ttm(tab, dq, "3Z")
    if nk0 is not None and nkq is not None:
        out["kara_donus"] = int(nk0 > 0 and nkq <= 0)
    c0, cq = _ttm(tab, d, "4C"), _ttm(tab, dq, "4C")
    if c0 is not None and cq is not None:
        out["nakit_donus"] = int(c0 > 0 and cq <= 0)
    out["nk_ttm"] = nk0
    return out


_TUFE = None


def banka_olculer(tab, d):
    """24 Kas (temel/bankalar_sonuc.txt, 12 banka 2014-2026): bankaya ozgu olculer. GENIS banka puani bunlarin
    nim_deg, maliyet_gelir, risk_maliyeti, komisyon_reel kismini kullanir; digerleri bilgi icin."""
    global _TUFE
    if _TUFE is None:
        _TUFE = D.tufe(update=False)
    y, m = d
    g = lambda k, dd=d: (tab.get(dd) or {}).get(k)
    tt = lambda k, dd=d: _ttm(tab, dd, k)
    # bir yil onceki karsilastirma donemi; kaynakta bos ceyrek varsa (or. AKBNK 2025/9) bir ceyrek once/sonra
    def _kay(dd, ay):
        yy, mm = dd[0], dd[1] + ay
        while mm <= 0:
            mm += 12; yy -= 1
        while mm > 12:
            mm -= 12; yy += 1
        return (yy, mm)
    o = (y - 1, m)
    for aday in ((y - 1, m), _kay((y - 1, m), -3), _kay((y - 1, m), 3)):
        if tt("3C", aday) is not None and g("1Z", aday):
            o = aday
            break
    a1 = _TUFE[_TUFE.index <= pd.Timestamp(y, m, 1)]; a0 = _TUFE[_TUFE.index <= pd.Timestamp(o[0], o[1], 1)]
    enf = float(a1.iloc[-1] / a0.iloc[-1]) if len(a1) and len(a0) else None
    akt, akt1, akt2 = g("1Z"), g("1Z", o), g("1Z", (o[0] - 1, o[1]))
    nfg, nfg1 = tt("3C"), tt("3C", o)
    nim = nfg / ((akt + akt1) / 2 if akt and akt1 else akt) if nfg is not None and akt else None
    nim1 = nfg1 / ((akt1 + akt2) / 2 if akt1 and akt2 else akt1) if nfg1 is not None and akt1 else None
    fg, gid, kar = tt("3CE"), tt("3CG"), tt("3CF")
    kom, kom1 = tt("3CA"), tt("3CA", o)
    kr, mv, oz = g("1AF"), g("2A"), g("2O")
    return {"nim": nim, "nim_deg": nim - nim1 if nim is not None and nim1 is not None else None,
            "maliyet_gelir": abs(gid) / fg if gid is not None and fg and fg > 0 else None,
            "risk_maliyeti": abs(kar) / kr if kar is not None and kr and kr > 0 else None,
            "komisyon_reel": (kom / kom1) / enf - 1 if kom and kom1 and kom1 > 0 and enf else None,
            "kredi_mevduat": kr / mv if kr and mv else None,
            "ozk_aktif": oz / akt if oz and akt else None}


def parasal_kazanc_ttm(tab, d):
    """22 Kas: son 4 ceyrek tahmini net parasal pozisyon kazanci (tab birimi). Kazanc ~ ortalama net parasal yukumluluk x ceyrek TUFE.
    Kontrol (temel/parasal_sonuc.txt): TTKOM 2025 9 ay aciklanan 16.9 / tahmin 18.2; BIM 2024 28.3 / 26.4. 2023/12 oncesi 0."""
    global _TUFE
    if _TUFE is None:
        _TUFE = D.tufe(update=False)
    def oran(dd):
        v = tab.get(dd) or {}
        va = v.get("1BL")
        if not va or va <= 0 or v.get("2A") is None:
            return None
        z = lambda c: v.get(c) or 0.0
        pv = sum(z(c) for c in ("1AA", "1AB", "1AC", "1AD", "1AE", "1B", "1BA", "1BB", "1BC"))
        py = z("2A") + z("2B") - z("2AAGAC") - z("2BBBA") - z("2BG") - z("2AAGCA") - z("2BDA")
        return (py - pv) / va, va
    def pi(y, m):
        a = _TUFE.get(pd.Timestamp(y, m, 1)); y0, m0 = (y, m - 3) if m > 3 else (y - 1, m + 9)
        b = _TUFE.get(pd.Timestamp(y0, m0, 1))
        return a / b - 1 if a and b else None
    y, m = d
    if (y, m) < (2023, 12):
        return 0.0
    top = 0.0
    for i in range(4):
        yy, mm = (y, m - 3 * i) if m - 3 * i > 0 else (y - 1, m - 3 * i + 12)
        o = oran((yy, mm)); oo = oran((yy, mm - 3) if mm > 3 else (yy - 1, 12)); p = pi(yy, mm)
        if o is None or p is None:
            return None
        r = (o[0] + oo[0]) / 2 if oo else o[0]
        top += r * p * o[1]
    return top


def skor(grup, tab, m3, d=None, yo=None):
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
    yo = yo or {}
    m3c = _m3_oran(m3, bd, bd1)  # bilanco kalemleri (ozkaynak) icin
    m3c_akim = _m3_oran(m3, d, d1)  # gelir kalemleri (son 4 ceyrek) icin
    if m3c:
        m3c *= yo.get((bd, "b"), 1.0) / yo.get((bd1, "b"), 1.0)
    if m3c_akim:
        m3c_akim *= yo.get((d, "g"), 1.0) / yo.get((d1, "g"), 1.0)
    out = {"donem": f"{y}/{m:02d}", "bilanco_karsilastirma": f"{bd1[0]}/{bd1[1]:02d}", "tip": "banka" if grup == "UFRS" else "sanayi", "maddeler": []}

    def madde(ad, deger, gecti, aciklama, bicim="tl"):
        out["maddeler"].append({"ad": ad, "deger": deger, "gecti": None if gecti is None else bool(gecti), "aciklama": aciklama, "bicim": bicim})

    if grup == "UFRS":
        nk, nk1 = T("3Z"), T("3Z", d1)
        oz, oz1 = B("2O"), B("2O", d1)
        roe = _bol(nk, oz); roe1 = _bol(nk1, oz1)
        nfg, nfg1 = T("3C"), T("3C", d1)
        madde("Net kâr pozitif", nk, None if nk is None else nk > 0, "Son 4 çeyrekte banka para kazandı mı?")
        madde("Özsermaye kârlılığı (ROE) arttı", roe, None if roe is None or roe1 is None else roe > roe1, "Net kâr / özkaynak geçen yılın aynı dönemine göre yükseldi mi? Zarardaysa geçmez.", "yuzde")
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
        madde("Özsermaye kârlılığı (ROE) arttı", roe, roe_ok, "Net kâr / özkaynak geçen yılın aynı dönemine göre yükseldi mi? Zarardaysa geçmez.", "yuzde")
        nak_ok = None if nak is None or nk is None else (nak > nk and (SURUM < 2 or nak > 0))
        madde("Nakit kârdan büyük (kâr kalitesi)", None if nak is None or nk is None else nak - nk, nak_ok,
              "Faaliyet nakdi net kârdan büyük mü? Değilse kâr kâğıt üstünde kalıyor olabilir. Faaliyet nakdi negatifse geçmez. Değer: nakit − kâr.")
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
        madde("Bedelli sermaye artırımı yok", bedelli, bed_ok, "Son 4 çeyrekte ortaklardan para toplanıp hisse sulandırıldı mı? Ana şirketin ödenmiş sermayesine bakılır; bedelsiz ve bağlı ortaklığın sermaye artırımı sayılmaz. Değer: konsolide nakit akışındaki sermaye artırımı.")
        madde("Özkaynak M3'ten hızlı büyüdü", None if g is None or not m3c else g / m3c - 1, None if g is None or not m3c else g > m3c,
              "Özkaynak bir yılda para arzından (M3) hızlı büyüdü mü? Değer, M3'e göre reel büyüme.", "yuzde")
        madde("Brüt kâr marjı arttı", marj, None if marj is None or marj1 is None else marj > marj1, "Brüt kâr / satışlar geçen yıldan yüksek mi? Fiyatlama gücünün işareti.", "yuzde")
        out["oranlar"] = {"roe": roe, "net_borc_favok": nbf, "favok_negatif": (favok or 0) <= 0, "net_nakit": nb is not None and nb <= 0, "cari_oran": cari, "brut_marj": marj,
                          "ozkaynak_reel_buyume": None if g is None or not m3c else g / m3c - 1,
                          "net_kar_reel_buyume": None if nk is None or nk1 in (None, 0) or not m3c_akim or nk1 <= 0 else (nk / nk1) / m3c_akim - 1,
                          "serbest_nakit": T("4CB")}
    # 22 Kas: "asil F/K" (FD/FAVOK) icin; bankalarda yok
    out["ham"] = {"net_kar": nk, "ozkaynak": oz, "sermaye": B("2OA"), "favok": locals().get("favok"), "net_borc": locals().get("nb"),
                  "faaliyet_kari": None if grup == "UFRS" else T("3DF"),
                  "brut_kar": None if grup == "UFRS" else T("3D"),
                  "parasal_kazanc": None if grup == "UFRS" else parasal_kazanc_ttm(tab, d)}
    if grup == "UFRS":
        try:
            out["banka"] = banka_olculer(tab, d)
        except Exception as e:
            out["banka"] = {"hata": str(e)}
    try:
        out["isaretler"] = {k: v for k, v in isaretler(tab, m3, d, yo).items() if k != "nk_ttm"}
        if yo:
            out["yeniden_duzeltme"] = {f"{p[0]}/{p[1]}{t}": round(r, 4) for (p, t), r in yo.items()}
    except Exception:
        out["isaretler"] = {}
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
    global _TUFE
    _TUFE = D.tufe()  # 22 Kas: parasal kazanc tahmini icin (TCMB'den yeni ay eklenir)
    t0 = time.time()
    bitti = 0
    import threading
    kilit = threading.Lock()
    ilk_yukle()

    def yaz():
        out = {"olusturma": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "hisseler": sonuc}
        f.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=float), encoding="utf-8")

    def is_(h):
        if time.time() - t0 > butce_dk * 60:
            return h, "atla"
        grup, tab = cek(h)
        with kilit:
            yo = yeniden_oran(h, tab) if tab else {}
        return h, skor(grup, tab, m3, yo=yo)

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
                with kilit:
                    ilk_kaydet()
    yaz()
    ilk_kaydet()
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


def birim_test(adet: int = 120):
    """Is Yatirim bir donemin degerini sonraki raporlardaki duzeltilmis (enflasyon) haliyle mi veriyor?
    6 Kas gecmis.json.gz ile bugunku canli cekimi kalem kalem karsilastirir -> temel/birim_test.txt."""
    import gzip, random
    import numpy as np
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    T = json.loads((R / "temel.json").read_text(encoding="utf-8"))["hisseler"]
    aday = sorted(h for h, v in T.items() if v.get("donem") == "2026/09" and h in G and G[h]["grup"] == "XI_29")
    random.seed(1); orn = random.sample(aday, min(adet, len(aday)))
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as ex:
        canli = dict(zip(orn, ex.map(lambda h: cek(h, 12), orn)))
    sat = []
    for h, (grup, tab) in canli.items():
        g = G[h]["tab"]; L = max(g)
        for (y, m), val in tab.items():
            k = f"{y}/{m}"
            if k not in g:
                continue
            for kod, v in val.items():
                e = g[k].get(kod)
                if kod not in KODLAR or e in (None, 0) or not v:
                    continue
                tur = "gelir" if kod[0] in "34" else ("bilanco_yilsonu" if m == 12 else "bilanco_ceyrek")
                sat.append((h, k, kod, tur, v / e, L))
    df = pd.DataFrame(sat, columns=["h", "d", "kod", "tur", "oran", "L"])
    df["ayni"] = (df.oran - 1).abs() < 0.003
    out = [f"{len(canli)} hisse, {len(df)} kalem karsilastirildi (oran = bugun / 6 Kas)"]
    for (d, tur), g_ in df.groupby(["d", "tur"]):
        q = g_.oran[~g_.ayni]
        out.append(f"{d:8s} {tur:16s} n={len(g_):4d} ayni=%{100*g_.ayni.mean():5.1f}  degisenlerin medyan orani={q.median() if len(q) else float('nan'):.3f}")
    hs = df[df.d.isin(["2025/9", "2025/12"])].groupby(["h", "d", "tur"]).ayni.mean().unstack(["d", "tur"])
    out.append("\nHisse bazinda 2025/9 ve 2025/12 ayni kalma payi:")
    out.append(hs.round(2).to_string())
    (R / "birim_test.txt").write_text("\n".join(out), encoding="utf-8")
    df.to_csv(R / "birim_test.csv.gz", index=False)
    print("\n".join(out[:60]))


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
    elif sys.argv[1] == "fbt":
        from . import firsat_bt
        firsat_bt.main()
    elif sys.argv[1] == "nad":
        from . import nad
        nad.main()
    elif sys.argv[1] == "bt2":
        from . import temel_bt2
        temel_bt2.main()
    elif sys.argv[1] == "bt":
        from . import temel_bt
        temel_bt.main()
    elif sys.argv[1] == "az_hisse":
        from . import portfoy_bt
        portfoy_bt.az_hisse()
    elif sys.argv[1] == "iz2":
        from . import portfoy_bt
        portfoy_bt.iz_test2()
    elif sys.argv[1] == "iz_izgara":
        import os
        os.environ["IZ_IZGARA"] = "1"
        from . import portfoy_bt
        portfoy_bt.iz_test()
    elif sys.argv[1] == "iz":
        from . import portfoy_bt
        portfoy_bt.iz_test()
    elif sys.argv[1] == "finans":
        from . import finans_bt
        finans_bt.main()
    elif sys.argv[1] == "icinden":
        from . import nad_std
        nad_std.icinden_test()
    elif sys.argv[1] == "nad_std":
        from . import nad_std
        nad_std.main()
    elif sys.argv[1] == "gyo_kontrol":
        from . import portfoy_bt as P
        P.gyo_kontrol()
    elif sys.argv[1] == "nad_genel":
        from . import kap as K
        from . import portfoy_bt as P
        b = D.bist_list()
        hs = sorted(P.grup_listesi()["HOLDING"] | {"BLCYT", "OSTIM", "ECZYT", "GSDHO"})
        sonuc, ham = K.genel_sayfa_paylar(hs, b[["ticker", "ad"]])
        (R / "nad_genel.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1), encoding="utf-8")
        (R / "nad_genel_ham.txt").write_text("\n".join(ham), encoding="utf-8")
        for h, v in sorted(sonuc.items()):
            print(h, v["satir"], {k: (x["oran"], x["efektif"]) for k, x in v["borsada"].items()})
    elif sys.argv[1] == "nad_paylar":
        # 23 Kas: holdinglerin borsadaki istirak paylari (KAP genel bilgi formu)
        from . import kap as K
        from . import portfoy_bt as P
        b = D.bist_list()
        hs = sorted(P.grup_listesi()["HOLDING"] | {"BLCYT", "OSTIM", "ECZYT", "GSDHO"})
        sonuc, ham = K.holding_paylari(hs, b[["ticker", "ad"]])
        (R / "nad_paylar.json").write_text(json.dumps(sonuc, ensure_ascii=False, indent=1), encoding="utf-8")
        (R / "nad_paylar_ham.txt").write_text("\n".join(ham), encoding="utf-8")
        for h, v in sorted(sonuc.items()):
            print(h, v["tarih"], v["satir"], v["borsada"])
    elif sys.argv[1] == "gyo_grup":
        from . import portfoy_bt
        portfoy_bt.gyo_grup_test()
    elif sys.argv[1] == "uzun_veri":
        if gecmis_eski() > 0:
            print("KALAN eski ceyrek verisi: devam edecek")
    elif sys.argv[1] == "uzun":
        if gecmis_eski() > 0:
            print("KALAN eski ceyrek verisi: devam edecek")
        else:
            from . import portfoy_bt
            portfoy_bt.uzun_test()
    elif sys.argv[1] in ("gyo", "gyo+icerden2"):
        from . import portfoy_bt
        portfoy_bt.gyo_test()
        if sys.argv[1] == "gyo+icerden2":
            portfoy_bt.icerden2_test()
    elif sys.argv[1] == "potansiyel":
        from . import portfoy_bt
        portfoy_bt.potansiyel_test()
    elif sys.argv[1] == "pas_deneme":
        from . import kap
        kap.pas_detay_topla(butce_dk=10, isci=2, en_fazla=150)
    elif sys.argv[1] == "icerden2":
        from . import portfoy_bt
        portfoy_bt.icerden2_test()
    elif sys.argv[1] == "pas_yokla2":
        from . import kap
        kap.pas_yokla2()
    elif sys.argv[1] == "pas_yokla":
        from . import kap
        kap.pas_yokla()
    elif sys.argv[1] == "icerden":
        from . import portfoy_bt
        portfoy_bt.icerden_test()
    elif sys.argv[1] == "icerden_yokla":
        from . import kap
        kap.icerden_yokla()
    elif sys.argv[1] == "geri_alim":
        from . import portfoy_bt
        portfoy_bt.geri_alim_test()
    elif sys.argv[1] == "kapdene":
        from . import kap
        kap.geri_alim_topla(bas="2026-11-01", gun=7, butce_dk=5)
    elif sys.argv[1] == "yoklama":
        # 22 Kas: TCMB enflasyon tablosu, EVDS yeni TUFE kodu, KAP pay geri alimi erisimi
        import requests, re as _re
        H = {"User-Agent": "Mozilla/5.0"}
        out = []
        def dene(ad, f):
            try:
                r = f(); out.append(f"== {ad}: {r.status_code} {r.headers.get('content-type')}\n{r.text[:1500]}")
            except Exception as e:
                out.append(f"== {ad}: HATA {e}")
        dene("tcmb", lambda: requests.get("https://www.tcmb.gov.tr/wps/wcm/connect/TR/TCMB+TR/Main+Menu/Istatistikler/Enflasyon+Verileri/Tuketici+Fiyatlari", headers=H, timeout=30))
        key = D.ayar("evds_key")
        for u in ("serieList/type=json&code=bie_tukfiy4", "datagroups/mode=2&code=bie_tukfiy4&type=json",
                  "datagroups/mode=1&code=TP.FG&type=json", "series=TP.FE.OKTG01&startDate=01-01-2026&endDate=31-12-2026&type=json&frequency=5",
                  "series=TP.FG.J0&startDate=01-01-2026&endDate=31-12-2026&type=json&frequency=5"):
            dene("evds " + u, lambda u=u: requests.get(D.EVDS_URL + u, headers={"key": key}, timeout=30))
        dene("kap ana", lambda: requests.get("https://www.kap.org.tr/tr/", headers=H, timeout=30))
        dene("kap api disclosure", lambda: requests.post("https://www.kap.org.tr/tr/api/memberDisclosureQuery", json={"fromDate": "2026-11-01", "toDate": "2026-11-20", "subjectList": [], "memberType": "IGS"}, headers=H, timeout=30))
        dene("kap api disc2", lambda: requests.get("https://www.kap.org.tr/tr/api/disclosures?fromDate=2026-11-01&toDate=2026-11-20", headers=H, timeout=30))
        dene("kap bildirim", lambda: requests.get("https://www.kap.org.tr/tr/Bildirim/1602031", headers=H, timeout=30))
        (R / "yoklama.txt").write_text("\n\n".join(out), encoding="utf-8")
        print("\n\n".join(out)[:6000])
    elif sys.argv[1] == "parasal2":
        from . import portfoy_bt
        portfoy_bt.DENEMELER = (("asil F/K FAVOK/FD (CANLI)", "favok", 1.0), ("FAVOK/FD + parasalsiz F/K", "favok+pk", 1.0),
                                ("parasal kazanc cikmis F/K", "kar_pk", 1.0))
        portfoy_bt.parasal_test()
    elif sys.argv[1] == "parasal":
        gecmis_pk()
        from . import portfoy_bt
        portfoy_bt.parasal_test()
    elif sys.argv[1] == "denetim":
        from . import portfoy_bt
        portfoy_bt.denetim()
    elif sys.argv[1] == "nakit":
        from . import portfoy_bt
        portfoy_bt.nakit_test()
    elif sys.argv[1] == "deger":
        from . import portfoy_bt
        portfoy_bt.deger_test()
    elif sys.argv[1] == "rejim2":
        from . import portfoy_bt as P
        P.rejim2_test()
    elif sys.argv[1] == "secim3":
        from . import portfoy_bt as P
        P.secim3_test()
    elif sys.argv[1] == "secim2":
        from . import portfoy_bt as P
        P.secim2_test()
    elif sys.argv[1] == "opt":
        from . import portfoy_bt as P
        P.opt_test()
    elif sys.argv[1] == "stop2":
        from . import portfoy_bt as P
        P.stop2_test(uzun=True)
    elif sys.argv[1] == "stop":
        from . import portfoy_bt as P
        P.stop_test(uzun=False)
    elif sys.argv[1] == "stop_uzun":
        from . import portfoy_bt as P
        P.stop_test(uzun=True)
    elif sys.argv[1] == "faiz_rejim":
        from . import portfoy_bt as P
        P.faiz_rejim_test()
    elif sys.argv[1] == "otopsi":
        from . import portfoy_bt as P
        P.otopsi()
    elif sys.argv[1] == "bankalar2":
        from . import bankalar
        bankalar.test2()
    elif sys.argv[1] == "bankalar":
        from . import bankalar
        bankalar.test()
    elif sys.argv[1] == "diger_finans":
        from . import diger_finans
        diger_finans.test()
    elif sys.argv[1] == "grup_yokla":
        # 24 Kas: faktoring/leasing/finansman/varlik yonetim sirketleri hangi Is Yatirim sablonunda?
        out = []
        for h in ("ISFIN", "GARFA", "VAKFN", "BRKVY", "QNBFK", "AYES", "ORMA"):
            for g in ("XI_29", "UFRS", "UFRS_K", "UFRS_A", "UFRS_B", "UFRS_C", "UFRS_D", "UFRS_E", "UFRS_F", "XI_29K", "XI_30", "XI_31", "XI_32"):
                v = _cek4(h, g, [(2025, 12), (2025, 9), (2025, 6), (2025, 3)])
                if v:
                    out.append(f"{h} {g} {len(v)} kalem: " + " | ".join(f"{x.get('itemCode')} {str(x.get('itemDescTr')).strip()[:40]} {x.get('value1')}" for x in v[:6]))
                    break
            else:
                out.append(f"{h}: hicbir grupta veri yok")
        (R / "grup_yokla.txt").write_text("\n".join(out), encoding="utf-8")
        print("\n".join(out))
    elif sys.argv[1] == "sigorta":
        from . import sigorta
        sigorta.test()
    elif sys.argv[1] == "kalemler_sig":
        # 24 Kas: sigorta sirketlerinin Is Yatirim kalemleri (banka sablonunda geliyor; adlari gormek icin)
        out = []
        for h in ("AKGRT", "ANHYT", "TURSG"):
            v = _cek4(h, "UFRS", [(2026, 9), (2026, 6), (2025, 12), (2025, 9)])
            out.append(f"===== {h} UFRS (2026/9, 2026/6, 2025/12, 2025/9)")
            for x in v:
                out.append(f"{x.get('itemCode')}\t{x.get('itemDescTr')}\t{x.get('value1')}\t{x.get('value2')}\t{x.get('value3')}\t{x.get('value4')}")
        (R / "kalemler_sig.txt").write_text("\n".join(out), encoding="utf-8")
        print("\n".join(out[:200]))
    elif sys.argv[1] == "kalemler":
        # 22 Kas: Is Yatirim kalem kodlari ve adlari (net parasal pozisyon kalemini bulmak icin)
        out = []
        for h, g in (("TTKOM", "XI_29"), ("KCHOL", "XI_29"), ("ARCLK", "XI_29"), ("BIMAS", "XI_29"), ("AKBNK", "UFRS")):
            v = _cek4(h, g, [(2026, 9), (2025, 9), (2025, 12), (2024, 12)])
            out.append(f"===== {h} {g} (2026/9, 2025/9, 2025/12, 2024/12)")
            for x in v:
                out.append(f"{x.get('itemCode')}\t{x.get('itemDescTr')}\t{x.get('value1')}\t{x.get('value2')}\t{x.get('value3')}\t{x.get('value4')}")
        (R / "kalemler.txt").write_text("\n".join(out), encoding="utf-8")
        print("\n".join(out[:400]))
    elif sys.argv[1] == "secim":
        from . import portfoy_bt
        portfoy_bt.secim_test()
    elif sys.argv[1] == "oos2":
        from . import portfoy_bt
        portfoy_bt.oos2()
    elif sys.argv[1] == "oos":
        from . import portfoy_bt
        portfoy_bt.oos()
    elif sys.argv[1] == "zar":
        from . import portfoy_bt
        portfoy_bt.zar()
    elif sys.argv[1] == "faz_test":
        # 17 Kas: faz motoru grup kaliciligi testi. Eski ve yeni ayarla karar_bt + portfoy_bt + istikrar.
        import os, shutil, subprocess
        ozet = []
        for deger, ek in (("0", "eski"), ("1", "grup")):
            env = dict(os.environ, FAZ_GRUP=deger)
            for mod, dosyalar in (("karar_bt", ["karar_sonuc.txt"]), ("portfoy_bt", ["portfoy_sonuc.txt", "portfoy.png", "portfoy_islemler.csv", "portfoy_egri.csv"])):
                subprocess.run([sys.executable, "-m", f"ikarus.{mod}"], env=env, check=True)
                for f in dosyalar:
                    a = R / f
                    if a.exists():
                        shutil.copy(a, R / f.replace(".", f"_{ek}.", 1))
            out = subprocess.run([sys.executable, "-c", "from ikarus import faz_tani as F; F.istikrar()"], env=env, capture_output=True, text=True)
            ozet.append(out.stdout)
        (R / "faz_test_ozet.txt").write_text("\n".join(ozet), encoding="utf-8")
    elif sys.argv[1] == "faz_tani":
        from . import faz_tani
        faz_tani.main()
    elif sys.argv[1] == "m3ivme":
        from . import m3bant_bt
        m3bant_bt.ivme()
    elif sys.argv[1] == "m3bant":
        from . import m3bant_bt
        m3bant_bt.main()
    elif sys.argv[1] == "portfoy":
        from . import portfoy_bt
        portfoy_bt.main()
    elif sys.argv[1] == "karar":
        from . import karar_bt
        karar_bt.main()
    elif sys.argv[1] == "birim_test":
        birim_test()
    elif sys.argv[1] == "hesapla":
        hesapla(sys.argv[2:] or None)
