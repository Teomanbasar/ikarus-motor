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


def icerden_yokla():
    """22 Kas: 'Pay Alim Satim Bildirimi' satirlari ve detay sayfasi bicimi (alim/satim ayrimi yapilabilir mi?)."""
    s = requests.Session()
    s.get("https://www.kap.org.tr/tr/", headers={"User-Agent": BASLIK["User-Agent"]}, timeout=60)
    rows = _cek(s, "2026-11-17", "2026-11-20") or []
    pas = [r for r in rows if "Pay Alım Satım" in str((r.get("basic", r) if isinstance(r, dict) else {}).get("subject"))]
    out = [f"toplam {len(rows)}, pay alim satim {len(pas)}"]
    for r in pas[:3]:
        out.append("HAM: " + str(r)[:1500])
    import re
    for r in pas[:4]:
        b_ = r.get("basic", r)
        idx = b_.get("disclosureIndex")
        for u in (f"https://www.kap.org.tr/tr/Bildirim/{idx}", f"https://www.kap.org.tr/tr/api/notification/attachment-detail/{idx}",
                  f"https://www.kap.org.tr/tr/api/BildirimPdf/{idx}"):
            try:
                h = s.get(u, headers={k: v for k, v in BASLIK.items() if k != "Content-Type"}, timeout=60)
                txt = h.text
                if "html" in h.headers.get("content-type", ""):
                    m = re.sub(r"<script.*?</script>|<style.*?</style>", " ", txt, flags=re.S)
                    m = re.sub(r"<[^>]+>", " ", m); m = re.sub(r"\s+", " ", m)
                    # Next.js verisi script icinde olabilir
                    j = [x[:600] for x in re.findall(r"(?:Alım|Satım|ALIM|SATIM|İşlem)[^<]{0,300}", txt)][:8]
                    out.append(f"== {u} {h.status_code} html metin: {m[:1500]}\n   eslesme: {j}")
                else:
                    out.append(f"== {u} {h.status_code} {h.headers.get('content-type')} {txt[:800]}")
            except Exception as e:
                out.append(f"== {u} HATA {e}")
    (DATA.parent / "temel" / "icerden_yokla.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)[:5000])


def pas_topla(bas: str = "2021-01-01", gun: int = 3, butce_dk: float = 110):
    """22 Kas: 'Pay Alim Satim Bildirimi' (iceriden / ortak / sirket pay alim-satimlari) -> data/kap_pas.csv."""
    f = DATA / "kap_pas.csv"
    eski = pd.read_csv(f, dtype=str) if f.exists() else pd.DataFrame()
    t0 = time.time()
    s = requests.Session()
    s.get("https://www.kap.org.tr/tr/", headers={"User-Agent": BASLIK["User-Agent"]}, timeout=60)
    a = pd.Timestamp(bas) if eski.empty else pd.to_datetime(eski["tarih"].str[:10], format="%d.%m.%Y").max() - pd.Timedelta(days=3)
    son = pd.Timestamp.today().normalize()
    satir = []
    while a <= son and time.time() - t0 < butce_dk * 60:
        b = min(a + pd.Timedelta(days=gun - 1), son)
        rows = _cek(s, a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d"))
        if rows is not None and len(rows) >= 2000 and b > a:
            rows = []
            for g in pd.date_range(a, b):
                rows += _cek(s, g.strftime("%Y-%m-%d"), g.strftime("%Y-%m-%d")) or []
                time.sleep(0.4)
        for r in rows or []:
            if "Pay Alım Satım" in str(r.get("subject")):
                satir.append({"tarih": str(r.get("publishDate") or ""), "gonderen": str(r.get("stockCodes") or ""),
                              "ilgili": str(r.get("relatedStocks") or ""), "sinif": str(r.get("disclosureClass") or ""),
                              "unvan": str(r.get("kapTitle") or ""), "ozet": str(r.get("summary") or "").replace("\n", " ")[:300],
                              "index": str(r.get("disclosureIndex") or "")})
        a = b + pd.Timedelta(days=1)
        time.sleep(0.5)
    yeni = pd.DataFrame(satir)
    tum = pd.concat([eski, yeni]).drop_duplicates(subset=["index"]) if len(yeni) else eski
    tum.to_csv(f, index=False)
    print(f"KAP pay alim satim: {len(yeni)} yeni, dosyada {len(tum)}; son {a:%Y-%m-%d}")
    return tum


def detay_metin(s, idx: str) -> str:
    """Bildirim sayfasinin duz metni (Next.js sayfasindaki kacisli HTML dahil)."""
    import html as _h
    import re
    h = s.get(f"https://www.kap.org.tr/tr/Bildirim/{idx}", headers={k: v for k, v in BASLIK.items() if k != "Content-Type"}, timeout=60).text
    h = h.replace('\\\\u003c', '<').replace('\\\\u003e', '>').replace('\\u003c', '<').replace('\\u003e', '>').replace('\\"', '"').replace('\\n', ' ')
    h = re.sub(r"<script[^>]*src=[^>]*>\\s*</script>|<style.*?</style>", " ", h, flags=re.S)
    t = re.sub(r"<[^>]+>", " ", h)
    t = _h.unescape(t)
    return re.sub(r"\\s+", " ", t)


def pas_yokla():
    import pandas as pd_
    s = requests.Session()
    s.get("https://www.kap.org.tr/tr/", headers={"User-Agent": BASLIK["User-Agent"]}, timeout=60)
    d = pd_.read_csv(DATA / "kap_pas.csv", dtype=str)
    out = []
    for sinif in ("DKB", "ODA"):
        for idx in d[d.sinif == sinif]["index"].sample(3, random_state=2).tolist() + d[d.sinif == sinif]["index"].tail(1).tolist():
            t = detay_metin(s, idx)
            i = max(t.find("Alım"), 0)
            k = [m for m in ("İşlem Tür", "Alım", "Satım", "Nominal", "Fiyat", "Oran", "Bildirim Konusu", "Adı Soyadı", "Ünvan", "Görev") if m in t]
            out.append(f"===== {sinif} {idx} uzunluk {len(t)} anahtarlar {k}\n{t[max(0, i - 2500):i + 2500]}")
    (DATA.parent / "temel" / "pas_yokla.txt").write_text("\n\n".join(out), encoding="utf-8")
    print("\n\n".join(out)[:4000])


def ek_metin(s, idx: str):
    """Bildirimin ekleri (attachment-detail) ve ilk PDF ekinin metni. -> (ham_json_kisa, metin)"""
    import io
    H = {k: v for k, v in BASLIK.items() if k != "Content-Type"}
    r = s.get(f"https://www.kap.org.tr/tr/api/notification/attachment-detail/{idx}", headers=H, timeout=60)
    if r.status_code != 200:
        raise RuntimeError(f"ek-detay {r.status_code}")
    j = r.json()
    metin = ""
    for item in j or []:
        for att in item.get("attachments") or []:
            oid = att.get("objId")
            if not oid:
                continue
            f = s.get(f"https://www.kap.org.tr/tr/api/file/download/{oid}", headers=H, timeout=60)
            if f.status_code != 200:
                raise RuntimeError(f"indirme {f.status_code}")
            i = f.content.find(b"%PDF")
            if i < 0:
                raise RuntimeError(f"pdf degil {f.content[:60]!r}")
            if i >= 0:
                from pypdf import PdfReader
                metin = " ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(f.content[i:])).pages)
            else:
                metin = f.content[:3000].decode("utf-8", "ignore")
            return str(j)[:600], metin
    return str(j)[:600], metin


def pas_yokla2():
    import pandas as pd_
    s = requests.Session()
    s.get("https://www.kap.org.tr/tr/", headers={"User-Agent": BASLIK["User-Agent"]}, timeout=60)
    d = pd_.read_csv(DATA / "kap_pas.csv", dtype=str)
    out = []
    for sinif in ("DKB", "ODA"):
        for idx in d[d.sinif == sinif]["index"].sample(3, random_state=5).tolist():
            try:
                j, m = ek_metin(s, idx)
            except Exception as e:
                j, m = f"HATA {e}", ""
            out.append(f"===== {sinif} {idx}\nJSON: {j}\nMETIN: {m[:2500]}")
    (DATA.parent / "temel" / "pas_yokla.txt").write_text("\n\n".join(out), encoding="utf-8")
    print("\n\n".join(out)[:5000])


def _sayi(x: str) -> float:
    x = x.strip()
    if not x or x in ("-",):
        return 0.0
    return float(x.replace(".", "").replace(",", "."))


def pas_ayristir(metin: str) -> dict:
    """MKK 'Pay Alim Satim Bildirimi' PDF metni -> konu, kisi, gorev, toplam alim/satim nominal, oran gun basi/sonu."""
    import re
    def alan(ad):
        m = re.search(ad + r"\s+(.*?):", metin)
        return m.group(1).strip() if m else ""
    sat = re.findall(r"(\d{2}/\d{2}/\d{4})\s+(-?[\d.,]+)\s+(-?[\d.,]+)\s+(-?[\d.,]+)\s+(-?[\d.,]+)\s+(-?[\d.,]+)\s+(-?[\d.,]+)\s+(-?[\d.,]+)\s+(-?[\d.,]+)\s+(-?[\d.,]+)", metin)
    if not sat:
        return {"konu": alan("Konu"), "kisi": alan(r"Ad Soyad / Ticaret Ünvanı"), "gorev": alan("Görevi"), "satir": 0}
    al = sum(_sayi(r[1]) for r in sat); st = sum(_sayi(r[2]) for r in sat)
    return {"konu": alan("Konu"), "kisi": alan(r"Ad Soyad / Ticaret Ünvanı"), "gorev": alan("Görevi"), "satir": len(sat),
            "islem_ilk": sat[0][0], "islem_son": sat[-1][0], "alim_nom": al, "satim_nom": st, "net_nom": al - st,
            "oran_bas": _sayi(sat[0][6]), "oran_son": _sayi(sat[-1][8])}


BEKLE = 1.2  # KAP 429 (cok istek) veriyor: tek is parcacigi, istekler arasi bekleme


def pas_detay_topla(butce_dk: float = 160, isci: int = 1, en_fazla: int | None = None):
    """DKB (MKK) bildirimlerinin PDF ekini ayristirir -> data/kap_pas_detay.csv (artimli; PDF saklanmaz)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    d = pd.read_csv(DATA / "kap_pas.csv", dtype=str)
    f = DATA / "kap_pas_detay.csv"
    eski = pd.read_csv(f, dtype=str) if f.exists() else pd.DataFrame(columns=["index"])
    if "hata" in eski:  # yalniz ag hatasi (429 vb.) olanlari yeniden dene; bicimi okunamayanlar kalici
        h = eski["hata"].fillna("")
        eski = eski[(h == "") | (h == "ek yok")]
    yap = [i for i in d[d.sinif == "DKB"]["index"].tolist() if i not in set(eski["index"])]
    if en_fazla:
        yap = yap[:en_fazla]
    t0 = time.time()
    s = requests.Session()
    s.get("https://www.kap.org.tr/tr/", headers={"User-Agent": BASLIK["User-Agent"]}, timeout=60)
    def is_(idx):
        if time.time() - t0 > butce_dk * 60:
            return None
        hata = ""
        for k in range(6):
            try:
                _, m = ek_metin(s, idx)
                r = pas_ayristir(m); r["index"] = idx
                if not m:
                    r["hata"] = "ek yok"
                time.sleep(BEKLE)
                return r
            except Exception as e:
                hata = str(e)
                time.sleep(60 if "429" in hata else 3 * (k + 1))
        return {"index": idx, "hata": hata[:100]}
    yeni = []
    with ThreadPoolExecutor(isci) as ex:
        for n, fut in enumerate(as_completed([ex.submit(is_, i) for i in yap])):
            r = fut.result()
            if r is not None:
                yeni.append(r)
            if n % 500 == 0:
                print(f"pas detay {n}/{len(yap)} {time.time() - t0:.0f} sn")
                pd.concat([eski, pd.DataFrame(yeni)]).to_csv(f, index=False)
    tum = pd.concat([eski, pd.DataFrame(yeni)])
    tum.to_csv(f, index=False)
    kalan = len(yap) - len(yeni)
    Y = pd.DataFrame(yeni)
    print(f"pas detay: {len(yeni)} yeni, toplam {len(tum)}, kalan {kalan}; okunan {int((pd.to_numeric(Y.get('satir'), errors='coerce') > 0).sum()) if len(Y) else 0}")
    if "hata" in Y:
        print("hatalar:", Y["hata"].value_counts().head(8).to_dict())
    return kalan


# ---- 23 Kas: holding istirak paylari (KAP 'Sirket Genel Bilgi Formu' -> Bagli Ortakliklar tablosu) ----
def _norm(x: str) -> str:
    import re
    x = str(x).upper()
    for a, b in (("İ", "I"), ("I", "I"), ("Ş", "S"), ("Ğ", "G"), ("Ü", "U"), ("Ö", "O"), ("Ç", "C"), ("Â", "A")):
        x = x.replace(a, b)
    x = x.replace("ı".upper(), "I")
    return re.sub(r"[^A-Z0-9 ]", " ", re.sub(r"\s+", " ", x)).strip()


def genel_form_topla(hisseler, bas: str = "2024-01-01", gun: int = 4, butce_dk: float = 40):
    """Verilen hisselerin en son 'Sirket Genel Bilgi Formu' bildirimleri (index). Tarih pencereleriyle tarar."""
    hs = set(hisseler)
    t0 = time.time()
    s = requests.Session()
    s.get("https://www.kap.org.tr/tr/", headers={"User-Agent": BASLIK["User-Agent"]}, timeout=60)
    a, son = pd.Timestamp(bas), pd.Timestamp.today().normalize()
    bul = {}
    while a <= son and time.time() - t0 < butce_dk * 60:
        b = min(a + pd.Timedelta(days=gun - 1), son)
        rows = _cek(s, a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d"))
        if rows is not None and len(rows) >= 2000 and b > a:
            rows = []
            for g in pd.date_range(a, b):
                rows += _cek(s, g.strftime("%Y-%m-%d"), g.strftime("%Y-%m-%d")) or []
                time.sleep(0.4)
        for r in rows or []:
            if "Genel Bilgi Formu" not in str(r.get("subject")) + str(r.get("title")):
                continue
            kod = [k.strip() for k in str(r.get("stockCodes") or "").split(",")]
            for k in kod:
                if k in hs:
                    bul.setdefault(k, []).append({"tarih": str(r.get("publishDate") or ""), "index": str(r.get("disclosureIndex") or ""),
                                                  "ozet": str(r.get("summary") or "")[:120]})
                    if len(bul) == 1 and len(bul[k]) == 1:
                        print("ornek form satiri:", str(r)[:900])
        a = b + pd.Timedelta(days=1)
        time.sleep(0.4)
    print(f"genel bilgi formu: {len(bul)}/{len(hs)} bulundu, son tarama {a:%Y-%m-%d}, {time.time() - t0:.0f} sn")
    return s, bul


_PB = r"(?:TRY|TL|USD|EUR|GBP|CHF|HRK|RUB|AZN|KZT|CNY|JPY|PLN|RON|BGN|SEK|NOK|DKK|AED|SAR|QAR|MAD|DZD|EGP|IQD|UAH|GEL|BAM|RSD|MKD|ALL|HUF|CZK)"


def sayfa_metin(s, url: str) -> str:
    import html as _h
    import re
    h = s.get(url, headers={k: v for k, v in BASLIK.items() if k != "Content-Type"}, timeout=60).text
    h = h.replace('\\u003c', '<').replace('\\u003e', '>').replace('\u003c', '<').replace('\u003e', '>').replace('\"', '"').replace('\n', ' ')
    h = re.sub(r"<style.*?</style>", " ", h, flags=re.S)
    t = _h.unescape(re.sub(r"<[^>]+>", " ", h))
    return re.sub(r"\s+", " ", t)


def sirket_linkleri(s):
    """KAP BIST sirketler sayfasindan ticker -> permalink (or. ALARK -> 846-alarko-holding-a-s)."""
    import re
    h = s.get("https://www.kap.org.tr/tr/bist-sirketler", headers={k: v for k, v in BASLIK.items() if k != "Content-Type"}, timeout=60).text
    h2 = h.replace('\\"', '"').replace('\"', '"')
    out = {}
    for m in re.finditer(r'"permaLink"\s*:\s*"([^"]+)"[^{}]{0,400}?"stockCode"\s*:\s*"([^"]+)"', h2):
        for k in m.group(2).split(","):
            out.setdefault(k.strip(), m.group(1))
    for m in re.finditer(r'"stockCode"\s*:\s*"([^"]+)"[^{}]{0,400}?"permaLink"\s*:\s*"([^"]+)"', h2):
        for k in m.group(1).split(","):
            out.setdefault(k.strip(), m.group(2))
    for m in re.finditer(r'sirket-bilgileri/ozet/(\d+-[a-z0-9-]+)[^A-Z]{0,300}?([A-Z0-9]{4,6}(?:, ?[A-Z0-9]{4,6})*)', h2):
        for k in m.group(2).split(","):
            out.setdefault(k.strip(), m.group(1))
    if not out:
        (DATA.parent / "temel" / "kap_bist_sirketler_ornek.txt").write_text(h2[:20000], encoding="utf-8")
    print("kap sirket linkleri:", len(out))
    return out


def genel_sayfa_paylar(holdingler, bist: pd.DataFrame):
    """23 Kas: sirketin KAP 'Genel Bilgiler' sayfasindaki guncel bagli ortaklik tablosu (DOGRUDAN/DOLAYLI pay dahil)."""
    import re
    s = requests.Session()
    s.get("https://www.kap.org.tr/tr/", headers={"User-Agent": BASLIK["User-Agent"]}, timeout=60)
    link = sirket_linkleri(s)
    anah = [(t, k) for t, ad in zip(bist["ticker"], bist["ad"].fillna("")) if (k := _anahtar(ad))]
    pat = re.compile(r"(.{3,200}?)\s+([\d.]+(?:,\d+)?)\s+([\d.]+(?:,\d+)?)\s+(" + _PB + r")\s+(\d{1,3}(?:,\d+)?)\s+"
                     r"(BAĞLI ORTAKLIK|İŞTİRAK|İŞ ORTAKLIĞI|FİNANSAL YATIRIM|FİNANSAL DURAN VARLIK|DİĞER|Bağlı Ortaklık\w*|İştirak\w*|İş Ortaklı\w*|Finansal \w+|Diğer)"
                     r"\s*(\([^)]{0,120}\))?")
    sonuc, ham = {}, []
    for h in holdingler:
        if h not in link:
            ham.append(f"== {h}: KAP linki yok"); continue
        m = ""
        for dn in range(3):
            try:
                m = sayfa_metin(s, f"https://www.kap.org.tr/tr/sirket-bilgileri/genel/{link[h]}")
            except Exception as e:
                ham.append(f"== {h} HATA {e}")
            if len(m) > 3000:
                break
            time.sleep(20 * (dn + 1))
        i = m.upper().find("BAĞLI ORTAKLIKLAR, FİNANSAL DURAN")
        t = m[i:] if i >= 0 else m
        rows = []
        for r in pat.finditer(t):
            ad = re.split(r"(?:\)|BAĞLI ORTAKLIK|İŞTİRAK|Bağlı Ortaklık\w*|İştirak\w*|ORTAKLIK PAYI)", r.group(1))[-1].strip()
            par = r.group(7) or ""
            pm = re.findall(r"%\s*([\d,]+)", par)
            rows.append({"ad": ad, "oran": float(r.group(5).replace(",", ".")), "efektif": float(pm[-1].replace(",", ".")) if pm else None,
                         "pb": r.group(4), "tur": r.group(6), "not": par})
        bul_h = {}
        for r in rows:
            n = " " + _anahtar(r["ad"], kes=False) + " "
            for tk, k in anah:
                if tk != h and (f" {k} " in n if " " in k else n.strip().startswith(k + " ") or n.strip() == k):
                    bul_h[tk] = {"oran": r["oran"], "efektif": r["efektif"], "not": r["not"]}
        sonuc[h] = {"link": link[h], "satir": len(rows), "borsada": bul_h}
        ham.append(f"== {h} {link[h]} metin {len(m)} satir {len(rows)} borsada {bul_h}\n" +
                   "\n".join(f"   {r['oran']:6.2f} ef {r['efektif']} {r['pb']} {r['tur'][:14]:14s} {r['ad'][-80:]}" for r in rows[:120]))
        if not rows:
            ham.append("   METIN: " + t[:1500])
        time.sleep(1.2)
    return sonuc, ham


def bagli_ortakliklar(metin: str):
    """Genel bilgi formu metninden (unvan+faaliyet, sermaye, pay tutari, para birimi, oran %, tur) satirlari."""
    import re
    i = metin.find("Bağlı Ortaklıklar, Finansal Duran")
    t = metin[i:] if i >= 0 else metin
    pat = re.compile(r"(.{3,160}?)\s+([\d.]+(?:,\d+)?)\s+([\d.]+(?:,\d+)?)\s+(" + _PB + r")\s+(\d{1,3}(?:,\d+)?)\s+"
                     r"(Bağlı Ortaklık(?:lar)?|İştirak(?:ler)?|Finansal Duran Varlık(?:lar)?|Finansal Yatırım(?:lar)?|İş Ortaklı\w*|Diğer\w*)")
    out = []
    for m in pat.finditer(t):
        ad = m.group(1)
        ad = re.split(r"(?:Bağlı Ortaklık(?:lar)?|İştirak(?:ler)?|Finansal Duran Varlık(?:lar)?|Finansal Yatırım(?:lar)?|İş Ortaklı\w*|\bTür\b|Oranı \(%\))", ad)[-1]
        try:
            oran = float(m.group(5).replace(",", "."))
        except ValueError:
            continue
        out.append({"ad": ad.strip(), "oran": oran, "pb": m.group(4), "tur": m.group(6)})
    return out


_DOLGU = {"A", "S", "AS", "ANONIM", "SIRKETI", "SIRKET", "VE", "TIC", "SAN", "T", "INC", "LTD", "SANAYI", "TICARET", "SIRKETIN",
          "ILE", "OLAN", "ILISKININ", "NITELIGI", "FAALIYET", "KONUSU", "UNVANI"}


def _anahtar(ad, kes=True):
    w = [x for x in _norm(ad).split() if x not in _DOLGU]
    return " ".join(w[:3]) if kes else " ".join(w)


def holding_paylari(holdingler, bist: pd.DataFrame):
    """Her holding icin borsadaki istiraklerini (ticker -> pay) bulur. bist: ticker, ad.
    Form listesi temel/nad_formlar.json'da saklanir (ikinci calismada KAP taramasi atlanir)."""
    import json as _j
    fk = DATA.parent / "temel" / "nad_formlar.json"
    if fk.exists():
        bul = _j.loads(fk.read_text(encoding="utf-8"))
        s = requests.Session()
        s.get("https://www.kap.org.tr/tr/", headers={"User-Agent": BASLIK["User-Agent"]}, timeout=60)
    else:
        s, bul = genel_form_topla(holdingler)
        fk.write_text(_j.dumps(bul, ensure_ascii=False), encoding="utf-8")
    anah = [(t, k) for t, ad in zip(bist["ticker"], bist["ad"].fillna("")) if (k := _anahtar(ad))]
    sonuc, ham = {}, []
    for h, lst in bul.items():
        rows, v, denenen = [], lst[-1], 0
        for v in reversed(lst):          # en yeniden eskiye: tabloyu iceren ilk form
            if denenen >= 10:
                break
            denenen += 1
            m = ""
            for dn in range(4):
                try:
                    m = detay_metin(s, v["index"])
                except Exception as e:
                    ham.append(f"== {h} {v} HATA {e}")
                if len(m) > 2000:
                    break
                time.sleep(20 * (dn + 1))    # bos sayfa = hiz siniri
            if len(m) <= 2000:
                continue
            rows = bagli_ortakliklar(m)
            time.sleep(0.8)
            if rows:
                break
        if not rows:
            j = m.find("Bağlı Ortaklık")
            ham.append(f"== {h} {len(lst)} form, {denenen} denendi, SATIR YOK; son metin {len(m)}: " + m[max(0, j - 200):j + 1200])
        bul_h = {}
        for r in rows:
            n = " " + _anahtar(r["ad"], kes=False) + " "
            for t, k in anah:
                if t != h and (f" {k} " in n if " " in k else n.strip().startswith(k + " ") or n.strip() == k):
                    bul_h[t] = max(bul_h.get(t, 0), r["oran"])
        sonuc[h] = {"tarih": v["tarih"], "index": v["index"], "borsada": bul_h, "satir": len(rows)}
        ham.append(f"== {h} {v['tarih']} idx {v['index']} satir {len(rows)} borsada {bul_h}\n" +
                   "\n".join(f"   {r['oran']:6.2f} {r['pb']} {r['tur'][:12]:12s} {r['ad'][-90:]}" for r in rows[:80]))
    return sonuc, ham


def pas_tablo():
    """23 Kas: ayristirilmis iceriden alim-satim tablosu (portfoy_bt._icerden2_hesap ile ayni temizlik)."""
    P = pd.read_csv(DATA / "kap_pas.csv", dtype=str)
    X = pd.read_csv(DATA / "kap_pas_detay.csv", dtype=str).merge(P[["index", "tarih", "ilgili", "gonderen"]], on="index", how="left")
    for c in ("alim_nom", "satim_nom", "net_nom", "oran_bas", "oran_son", "satir"):
        X[c] = pd.to_numeric(X.get(c), errors="coerce")
    X["t"] = pd.to_datetime(X["tarih"].str[:10], format="%d.%m.%Y", errors="coerce")
    X["hisse"] = X["ilgili"].fillna(X["gonderen"]).fillna("").str.split(",").str[0].str.strip()
    konu = X["konu"].fillna("").str.lower()
    X["devir"] = konu.str.contains("devir|devri|hediye|miras|teminat|bağış|bagis|intikal|birleşme|bedelsiz", regex=True)
    g = X["gorev"].fillna("").str.lower()
    X["yonetici"] = g.str.contains("yönetim|yonetim|müdür|mudur|başkan|baskan|üye|uye|ceo|cfo|direkt", regex=True)
    return X[(X.satir > 0) & X.t.notna() & (X.hisse != "") & ~X.devir]
