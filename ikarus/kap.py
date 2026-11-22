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
    j = r.json() if r.status_code == 200 else []
    metin = ""
    for item in j or []:
        for att in item.get("attachments") or []:
            oid = att.get("objId")
            if not oid:
                continue
            f = s.get(f"https://www.kap.org.tr/tr/api/file/download/{oid}", headers=H, timeout=60)
            if f.content[:4] == b"%PDF":
                from pypdf import PdfReader
                metin = " ".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(f.content)).pages)
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
