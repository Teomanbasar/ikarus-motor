"""Tum BIST hisselerini IKARUS motoruyla tarar, uygulama icin sonuc dosyalari yazar.

Kullanim (proje klasorunde):
    python -m ikarus.scan              # tum BIST, gunluk + haftalik
    python -m ikarus.scan THYAO AKBNK  # yalniz secilen hisseler
Ciktilar: cikti/sonuclar.json (uygulama okur), cikti/sonuclar.csv (Excel icin)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import data as D
from . import engine as E

OUT = D.ROOT / "cikti"
SIG_ORDER = {"ALINABILIR": 0, "TOPLANIYOR": 1, "YAKIN": 2, "DAGITIM": 3, "BEKLE": 4}


def _temiz(x):
    """JSON'da gecersiz NaN/Infinity yerine null."""
    if isinstance(x, dict):
        return {k: _temiz(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_temiz(v) for v in x]
    if isinstance(x, (float, np.floating)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def scan_one(df: pd.DataFrame, xu: pd.Series, m3: pd.Series) -> dict | None:
    res = {}
    for tf in ("D", "W"):
        r = E.compute(df, xu, m3, tf)
        if len(r) < 2 or np.isnan(r["dip"].iloc[-1]):
            if tf == "D":
                return None  # 200 bardan kisa gecmis: degerleme yok
            res[tf] = None
            continue
        last, prev = r.iloc[-1], r.iloc[-2]
        row = E.table_row(last)
        row["tarih"] = f"{r.index[-1]:%Y-%m-%d}"
        row["onceki_sinyal"] = prev["sinyal"]
        row["yeni_sinyal"] = bool(last["sinyal"] != prev["sinyal"])
        row["kirdi"] = bool(last["d_stop"] <= -3.5)  # onceki Stop'un %3.5'ten fazla altinda
        res[tf] = row
    # faz motoru (12 Kas testi: Firsatlar'da faz alim tarafina gecis = giris zamani; DAGITIM'da satmak zararli)
    try:
        fz = {}
        for ad, kw in (("normal", {}), ("ha", {"ha": True})):
            r = E.compute(df, xu, m3, "D", sig_mod="faz", **kw)
            sg = r["sinyal"].values
            k = len(sg) - 1
            while k > 0 and sg[k - 1] == sg[-1]:
                k -= 1
            fz[ad] = {"sinyal": sg[-1], "gun": int(len(sg) - k), "alim": bool(sg[-1] in ("ALINABILIR", "TOPLANIYOR", "YAKIN"))}
        res["faz"] = fz
    except Exception:
        pass
    return res


def _temel_ekle(stocks):
    """temel/temel.json (haftalik temel analiz isi) varsa her hisseye 'temel' karti ekler.
    F/K ve PD/DD guncel fiyatla burada hesaplanir (sermaye x fiyat = piyasa degeri; BIST'te nominal 1 TL)."""
    f = D.ROOT / "temel" / "temel.json"
    if not f.exists():
        return
    try:
        T = json.loads(f.read_text(encoding="utf-8"))["hisseler"]
    except Exception as e:
        print("[uyari] temel.json okunamadi:", e)
        return
    try:   # 17 Kas: Is Yatirim'da odenmis sermayesi (2OA) olmayan sigorta/katilim bankalari icin TradingView piyasa degeri
        _lst = D.bist_list()
        MC = dict(zip(_lst["ticker"], _lst["mcap"])) if "mcap" in _lst.columns else {}
    except Exception:
        MC = {}
    for s in stocks:
        k = T.get(s["t"])
        if not k or "maddeler" not in k:
            continue
        k = dict(k)
        ham = k.pop("ham", {}) or {}
        fiyat = (s.get("D") or {}).get("fiyat")
        sermaye, nk, oz = ham.get("sermaye"), ham.get("net_kar"), ham.get("ozkaynak")
        if not sermaye and fiyat and MC.get(s["t"]) and MC[s["t"]] == MC[s["t"]]:
            sermaye = float(MC[s["t"]]) / fiyat
        if fiyat and sermaye and sermaye > 0:
            pd_ = fiyat * sermaye
            k["piyasa_degeri"] = pd_
            k["fk"] = pd_ / nk if nk and nk > 0 else None
            k["pddd"] = pd_ / oz if oz and oz > 0 else None
            k["kaz_get"] = nk / pd_ if nk is not None else None
            # 22 Kas: asil F/K = firma degeri / FAVOK (parasal kazanc, kur farki, faiz ve TMS 29 amortismani disarida)
            fav, nbr, faal = ham.get("favok"), ham.get("net_borc"), ham.get("faaliyet_kari")
            if nbr is not None:
                fd = pd_ + nbr
                k["firma_degeri"] = fd
                if fd > 0 and fav is not None:
                    k["fav_get"] = fav / fd
                    k["fd_favok"] = fd / fav if fav > 0 else None
                k["fd_fk"] = fd / faal if faal and faal > 0 and fd > 0 else None
            # 22 Kas: parasal kazancsiz F/K (bilgi; kural degil). Vergi sonrasi %75 varsayimi.
            pk = ham.get("parasal_kazanc")
            if pk is not None and nk is not None:
                nk2 = nk - 0.75 * pk
                k["parasal_kazanc"] = pk
                k["fk_parasalsiz"] = pd_ / nk2 if nk2 > 0 else None
                k["parasal_pay"] = 0.75 * pk / nk if nk > 0 else None
        s["temel"] = k
    _temel_v3(stocks)
    _temel_v3(stocks, tip="banka")   # 17 Kas: bankalar kendi icinde (finans_bt: ust 1/3 126g +19.9 / alt 1/3 +7.1); sigorta henuz test edilmedi


# 10 Kas 2026 testi (temel/bt2_sonuc.txt): bilanco yayimlandiktan sonraki 63 gunde BIST100'e gore fazla getiri,
# donemin en iyi %20'si ile en kotu %20'si arasindaki fark (kirpik ortalama) ve farkin pozitif oldugu donem orani.
V3_TEST = {"hareket": "+8.4 puan, donemlerin %86'sinda", "kalite": "+2.6 puan, %68", "deger": "+3.1 puan, %68",
           "firsat": "Temel ust %20 (esit agirlik) + kotu surpriz degil + 20 gunde endekse gore <= +%10 + 5 gunde <= +%15 + Percentile <= 20: 63g kirpik +5.7, medyan +2.3, %55 kazanma; 126g +9.8",
           "kotu": "Iki kar surprizi de en alt %20: 63g kirpik -3.8, 126g -7.7 (kaliteli+ucuz olsa bile -11.4)"}


def _temel_v3(stocks, tip="sanayi"):
    """Temel puan v3: Hareket (bilanco ivmesi), Kalite, Deger esit agirlik (12 Kas; 10 Kas-12 Kas arasi 50/25/25); hepsi sanayi hisseleri icinde siralama (0-1).
    Bankalar ayri muhasebe yapisinda oldugu icin siralamaya girmez (F-skoru karti kalir)."""
    SIGORTA = {"AGESA", "AKGRT", "ANHYT", "ANSGR", "RAYSG", "TURSG", "GUSGR"}   # 17 Kas: finans_bt yalniz bankalari dogruladi
    S = [s for s in stocks if s.get("temel") and s["temel"].get("tip") == tip and not (tip == "banka" and s["t"] in SIGORTA)]
    if len(S) < (50 if tip == "sanayi" else 8):
        return
    fin = tip == "banka"
    hcols = ["sue_nk", "satis_reel", "roe_ivme"] if fin else ["sue_nk", "sue_faal", "satis_reel", "roe_ivme"]
    def rows(s):
        k = s["temel"]; i = k.get("isaretler") or {}; o = k.get("oranlar") or {}
        return {"t": s["t"], "F": k.get("puan"), "roe": o.get("roe"), "sue_nk": i.get("sue_nk"), "sue_faal": i.get("sue_faal"),
                "satis_reel": i.get("satis_reel"), "roe_ivme": i.get("roe_ivme"), "kaz_get": k.get("kaz_get"), "fav_get": k.get("fav_get"), "pddd": k.get("pddd"),
                "favok_q": i.get("favok_q")}
    X = pd.DataFrame([rows(s) for s in S]).set_index("t").astype(float)
    r = X.rank(pct=True)
    r["pddd"] = 1 - r["pddd"]
    # 17 Kas (TTKOM): faaliyet = FAVOK + esas faaliyet + satis ceyreklik siralarinin ortalamasi (puana girmez, yalniz not)
    fcols = [c for c in (["favok_q", "satis_reel"] if fin else ["favok_q", "sue_faal", "satis_reel"]) if c in r.columns]
    faal = r[fcols].mean(axis=1).where(r[fcols].notna().sum(axis=1) >= 2).rank(pct=True)
    har = r[hcols]
    hareket = har.mean(axis=1).where(har.notna().sum(axis=1) >= 2)
    kalite = r[["F", "roe"]].mean(axis=1)
    # 22 Kas: sanayide deger = FAVOK/FD + PD/DD (temel/deger_sonuc.txt: test 5 hisse x1.87 / net kar x1.21); bankada net kar/PD
    deger = r[["kaz_get" if fin else "fav_get", "pddd"]].mean(axis=1)
    toplam = (hareket + kalite + deger) / 3   # 12 Kas: esit agirlik (50/25/25 ile ayni getiri, medyan daha iyi; Teoman: ivmeye fazla agirlik verme)
    sira = toplam.rank(pct=True)
    dilim = toplam.rank(pct=True).apply(lambda v: None if pd.isna(v) else int(max(1, np.ceil(v * 5))))
    for s in S:
        t = s["t"]; k = s["temel"]; i = k.get("isaretler") or {}
        f = lambda v: None if pd.isna(v) else round(float(v), 3)
        et = []
        if f(hareket[t]) is not None and hareket[t] >= 0.8:
            et.append("Bilanco ivmesi guclu")
        kotu = (r.at[t, "sue_nk"] <= 0.2) and (r.at[t, "satis_reel" if fin else "sue_faal"] <= 0.2)
        if kotu:
            et.append("Kotu bilanco surprizi")
        if i.get("kara_donus"):
            et.append("Zarardan kara dondu")
        # temel_bt3 tonga: faaliyet ust %40 + net kar surprizi alt %40 -> 63g +3.4 (kalite/deger iyiyse), 126g +0.9 / medyan -5.7
        if not fin and not pd.isna(faal.get(t)) and faal[t] >= 0.6 and not pd.isna(r.at[t, "sue_nk"]) and r.at[t, "sue_nk"] <= 0.4:
            et.append("Faaliyet iyi, net kar dustu")
        fv = s.get("fiyat_ivme") or {}
        hizli = (fv.get("o5") or 0) > 15 or (fv.get("o20_x") or 0) > 30
        if hizli:
            et.append("Hizli yukseldi")
        # 12 Kas (Teoman): siyasi kriz gibi piyasa geneli dususleri eleme; yalniz hisseye ozel cokus
        cokus = (fv.get("o20_x") or 0) < -25 or ((fv.get("taban10") or 0) >= 4 and (fv.get("o20_x") or 0) < -15)
        if cokus:
            et.append("Sert dusus")
        if (k.get("puan") or 0) >= (4 if fin else 6):
            et.append("Kaliteli bilanco")
        elif k.get("puan") is not None and k["puan"] <= (2 if fin else 3):
            et.append("Zayif bilanco")
        pct = (s.get("D") or {}).get("percentile")
        if kotu:
            yorum = "Dikkat: son bilanço geçen yılın aynı çeyreğine göre belirgin kötü. Testte bu grup ucuz ve kaliteli olsa bile sonraki 3-6 ayda endeksin gerisinde kaldı."
        elif cokus:
            yorum = "Dikkat: fiyat son 20 günde endeksten %25'ten fazla düştü ya da üst üste taban serisi yaptı (piyasa geneli düşüş değil, hisseye özel). Bilanço eski olabilir; şirkete özel kötü bir haber (soruşturma, işlem yasağı, yakın izleme) olup olmadığına bakın. Testte 20 günde %40+ düşen hisseler sonraki 3 ayda endeksin ortalama 18 puan gerisinde kaldı."
        elif hizli:
            yorum = "Fiyat son günlerde hızlı yükseldi; bilanço büyük ölçüde fiyatlanmış olabilir. Testte 20 günde endeksten %30+ fazla yükselen güçlü bilançolu hisseler sonraki 3 ayda ortalama endeksin 8 puan gerisinde kaldı."
        elif dilim[t] == 5 and pct is not None and pct <= 20:
            yorum = "Temel puanı en üst %20'de ve IKARUS'ta ucuz bölgede: testte en iyi sonuç veren birleşim."
        elif dilim[t] == 5:
            yorum = "Temel puanı en üst %20'de."
        elif (k.get("puan") or 0) >= (4 if fin else 6) and (hareket[t] if not pd.isna(hareket[t]) else 0) < 0.5:
            yorum = "Kaliteli ama bilanço ivmesi yok: testte bu grup bekledi (getiri endeks civarında kaldı)."
        else:
            yorum = None
        k["v3"] = {"toplam": f(toplam[t]), "sira": f(sira[t]), "dilim": None if pd.isna(dilim[t]) else int(dilim[t]), "hareket": f(hareket[t]), "kalite": f(kalite[t]), "deger": f(deger[t]),
                   "siralar": {c: f(r.at[t, c]) for c in r.columns}, "etiketler": et, "yorum": yorum, "n": int(toplam.notna().sum()),
                   "grup": "finans" if fin else "sanayi"}


def _fiyat_ivme(stocks, px, xu):
    """Son 5/20 gunluk yukselis (zaten fiyatlandi mi? 12 Kas testi)."""
    for s in stocks:
        df = px.get(s["t"])
        if df is None or len(df) < 25:
            continue
        c = df["close"]
        x = xu.reindex(c.index).ffill()
        g = c.pct_change().tail(10)
        s["fiyat_ivme"] = {"o5": round(float(100 * (c.iloc[-1] / c.iloc[-6] - 1)), 2),
                           "o20": round(float(100 * (c.iloc[-1] / c.iloc[-21] - 1)), 2),
                           "o20_x": round(float(100 * (c.iloc[-1] / c.iloc[-21] - x.iloc[-1] / x.iloc[-21])), 2),
                           "tavan10": int((g >= 0.095).sum()), "taban10": int((g <= -0.095).sum())}


TAKIP_F = D.DATA / "takip.json"
TAKIP_GUN = 126   # 12 Kas testi: en fazla ~6 ay tut


def _takip(stocks, firsat_d, xu):
    """Elde tut listesi (12 Kas firsat_bt F/HA kurali): Firsatlar'da (gunluk) ve faz motoru alim tarafinda (normal ya da HA)
    olan hisse ilk gorundugu gun 'giris' alir; listeden cikmasi onemli degil. Cikis: temel puan sirasi %60'in altina duserse,
    kotu bilanco surprizi gelirse ya da 126 islem gunu dolarsa. Kapanan islemler 10 gun daha gosterilir, sonra arsive gider."""
    try:
        K = json.loads(TAKIP_F.read_text(encoding="utf-8")) if TAKIP_F.exists() else {"acik": {}, "kapanan": []}
    except Exception:
        K = {"acik": {}, "kapanan": []}
    by = {s["t"]: s for s in stocks}
    gun = f"{xu.index[-1]:%Y-%m-%d}"
    xs = float(xu.iloc[-1])
    v3 = lambda s: ((s.get("temel") or {}).get("v3") or {})
    fz = lambda s: s.get("faz") or {}
    for t in firsat_d:
        s = by[t]
        n, h = fz(s).get("normal", {}).get("alim"), fz(s).get("ha", {}).get("alim")
        if (n or h) and t not in K["acik"]:
            K["acik"][t] = {"giris": gun, "fiyat": s["D"]["fiyat"], "xu": xs, "temel": v3(s).get("toplam"),
                            "faz": "+".join(x for x, y in (("normal", n), ("HA", h)) if y)}
    for t, p in list(K["acik"].items()):
        s = by.get(t)
        if s is None:
            continue
        g = int(np.busday_count(p["giris"], gun))
        v = v3(s)
        neden = None
        if v.get("sira") is not None and v["sira"] < 0.6:
            neden = "Temel puan sirasi %60'in altina dustu"
        elif "Kotu bilanco surprizi" in v.get("etiketler", []):
            neden = "Kotu bilanco surprizi"
        elif g >= TAKIP_GUN:
            neden = "6 ay doldu"
        f = s["D"]["fiyat"]
        p.update({"son": f, "getiri": round(100 * (f / p["fiyat"] - 1), 2),
                  "fazla": round(100 * (f / p["fiyat"] - xs / p["xu"]), 2), "gun": g, "kalan": max(0, TAKIP_GUN - g),
                  "firsatta": t in firsat_d, "temel_simdi": v.get("toplam")})
        if neden:
            p.update({"cikis": gun, "neden": neden})
            K["kapanan"].append({"t": t, **p})
            del K["acik"][t]
    K["kapanan"] = K["kapanan"][-300:]
    TAKIP_F.write_text(json.dumps(K, ensure_ascii=False, indent=1), encoding="utf-8")
    yakin = [k for k in K["kapanan"] if np.busday_count(k["cikis"], gun) <= 10]
    acik = sorted(({"t": t, **p} for t, p in K["acik"].items()), key=lambda x: x["giris"], reverse=True)
    return {"acik": acik, "kapanan": yakin, "kural": "Giris: Firsatlar + faz alim (normal ya da HA). Cikis: temel sirasi < %60, kotu bilanco surprizi ya da 126 islem gunu."}


def _bakim(m3, xu, stocks):
    """Eskiyen veri ve ayar kontrolu. Uygulama bunlari 'Bakim gerekiyor' notu olarak gosterir."""
    U = []
    bugun = pd.Timestamp.now().normalize()
    try:
        cfg = json.loads((D.DATA / "nad.json").read_text(encoding="utf-8"))
        for h, c in cfg.items():
            if h.startswith("_"):
                continue
            yas = (bugun - pd.Timestamp(c["ref_tarih"])).days
            if yas > 120:
                U.append(f"NAD {h}: istirak paylari/kalibrasyon {yas} gun once ({c['ref_tarih']}); yeni NAD tablosuyla guncellenmeli.")
    except Exception as e:
        U.append(f"NAD ayar dosyasi okunamadi: {e}")
    son_ay = m3.index.max()
    if (bugun - son_ay).days > 75:
        U.append(f"M3: son ay {son_ay:%Y-%m}; EVDS'ten yeni deger gelmiyor olabilir (evds_key?).")
    if (bugun - xu.index[-1]).days > 5:
        U.append(f"Fiyat verisi eski: son BIST100 gunu {xu.index[-1]:%Y-%m-%d}.")
    try:
        T = json.loads((D.ROOT / "temel" / "temel.json").read_text(encoding="utf-8"))
        yas = (bugun - pd.Timestamp(T.get("olusturma", "2000-01-01")[:10])).days
        if yas > 10:
            U.append(f"Temel veri {yas} gun once guncellendi; haftalik is calismiyor olabilir.")
    except Exception:
        U.append("Temel veri dosyasi okunamadi.")
    n_t = sum(1 for s in stocks if s.get("temel"))
    if len(stocks) < 450:
        U.append(f"Taramada yalniz {len(stocks)} hisse var (normalde ~600).")
    if n_t < 0.8 * max(len(stocks), 1):
        U.append(f"Temel verisi olan hisse az: {n_t}/{len(stocks)}.")
    return {"uyarilar": U, "kontrol": bugun.strftime("%Y-%m-%d")}


def _nad_ekle(stocks, px):
    """Holdinglerin NAD iskontosu (data/nad.json bilesimi, gunluk fiyatla)."""
    try:
        from . import nad as N
        cfg = json.loads((D.DATA / "nad.json").read_text(encoding="utf-8"))
    except Exception as e:
        print("[uyari] nad:", e); return
    by = {s["t"]: s for s in stocks}
    px = dict(px)
    try:
        px["USDTRY"] = N.usdtry()
    except Exception as e:
        print("[uyari] USDTRY:", e)
    ser = N.sermayeler()
    for h, c in cfg.items():
        if h.startswith("_") or c.get("test_only") or h not in px or h not in by:
            continue
        try:
            S, eksik = N.seri(h, c, px, ser)
            S = S[S.index >= "2021-01-01"].dropna()
            isk = float(S["iskonto"].iloc[-1])
            p3 = S[S.index >= S.index[-1] - pd.DateOffset(years=3)]["iskonto"]
            yuz3 = float(100 * (p3 < isk).mean())
            d20 = float(isk - S["iskonto"].iloc[-21])
            durum = ("DERIN ISKONTO, KAPANIYOR" if yuz3 <= 20 and d20 > 0.02 else "DERIN ISKONTO" if yuz3 <= 20
                     else "ISKONTO DAR" if yuz3 >= 80 else "NORMAL")
            by[h].setdefault("temel", {})["nad"] = {
                "tarih": f"{S.index[-1]:%Y-%m-%d}", "nad_mn": round(float(S["nad"].iloc[-1])), "pd_mn": round(float(S["pd"].iloc[-1])),
                "iskonto": round(isk, 4), "ort_3y": round(float(p3.mean()), 4), "yuzdelik_3y": round(yuz3, 1), "degisim_20g": round(d20, 4),
                "uzun_vade": c.get("uzun_vade_iskonto"), "durum": durum, "kaynak": c["kaynak"], "fiyatsiz": eksik}
            # 23 Kas (temel/nad_sonuc.txt havuz testi): borsadaki istirakleri NAD'in cogu olan holdinglerde (dis kaynakli
            # NAD'a kalibre: KCHOL, SAHOL, AGHOL, DOHOL) karar kutusundaki bilanco sirasi yerine NAD kullanilir.
            # Konsolide bilanco puani holdingde test edildi ve calismadi. NAD iskontosu 3y en derin %20'de -> 'iyi'
            # (126g endekse gore ort +20, t 2.9, n 27); diger durumlar ORTA (dar iskonto kotu cikmadi, UZAK DUR yok).
            v = (by[h].get("temel") or {}).get("v3")
            if c.get("karar_nad") and v is not None:
                et = v.get("etiketler") or []
                v.update({"bilanco_sira": v.get("sira"), "bilanco_dilim": v.get("dilim"), "nad_karar": True, "nad_yuzdelik": round(yuz3, 1),
                          "sira": 0.9 if yuz3 <= 20 else 0.7, "dilim": 5 if yuz3 <= 20 else 4,
                          "etiketler_bilanco": et, "etiketler": [x for x in et if x != "Kotu bilanco surprizi"]})
        except Exception as e:
            print("[uyari] nad", h, e)


def _geri_alim_ekle(stocks):
    """22 Kas: KAP pay geri alimi (temel/geri_alim_sonuc.txt: yeni dalga sonrasi 6 ay piyasa ortancasina gore +%12 ort.,
    ortanca +%5.6, t=6.8, her yil pozitif; AL icinde one almak 2025-26'da x1.33 -> x1.61 (5 hisse))."""
    try:
        from . import kap
        kap.geri_alim_topla(butce_dk=4)
    except Exception as e:
        print("[uyari] KAP geri alim guncellenemedi", e)
    f = D.DATA / "geri_alim.csv"
    if not f.exists():
        return
    g = pd.read_csv(f, dtype=str)
    g = g[g["konu"].str.contains("Geri Alınmasına", na=False)].copy()
    g["t"] = pd.to_datetime(g["tarih"].str[:10], format="%d.%m.%Y", errors="coerce")
    g["hisse"] = g["hisse"].fillna("").str.split(",").str[0].str.strip()
    g = g.dropna(subset=["t"]).sort_values("t")
    bugun = pd.Timestamp.today().normalize()
    by = {h: x["t"].tolist() for h, x in g.groupby("hisse")}
    for s in stocks:
        tl = by.get(s["t"])
        if not tl:
            continue
        son = tl[-1]
        bas = tl[-1]
        for a, b in zip(reversed(tl[:-1]), reversed(tl[1:])):  # 90 gunluk bosluga kadar geri git: dalga baslangici
            if (b - a).days > 90:
                break
            bas = a
        n30 = sum(1 for t in tl if (bugun - t).days <= 30)
        s["geri_alim"] = {"son": f"{son:%Y-%m-%d}", "dalga_bas": f"{bas:%Y-%m-%d}", "n30": n30,
                          "aktif": (bugun - son).days <= 30, "yeni_dalga": (bugun - bas).days <= 60}


def run(tickers: list[str] | None = None) -> dict:
    t0 = time.time()
    lst = D.bist_list()
    if tickers:
        tickers = [t.upper() for t in tickers]
        lst = lst[lst["ticker"].isin(tickers)]
        missing = set(tickers) - set(lst["ticker"])
        if missing:
            lst = pd.concat([lst, pd.DataFrame({"ticker": sorted(missing), "ad": sorted(missing), "sektor": ""})])
    print(f"{len(lst)} hisse. Fiyatlar indiriliyor...")
    px = D.prices(lst["ticker"].tolist())
    xu = D.xu100()
    px, xu, _ = D.tv_tamamla(px, xu)
    # TradingView'den eklenen son gun bolunmeli olabilir (or. DUNYH 13 Kas: %512 bedelsiz + %68 bedelli); tekrar duzelt
    px = {t: D.fix_splits(df) for t, df in px.items()}
    m3 = D.m3()
    print(f"{len(px)} hissenin verisi geldi ({time.time() - t0:.0f} sn). Hesaplaniyor...")

    info = lst.set_index("ticker")
    stocks = []
    for i, (t, df) in enumerate(sorted(px.items())):
        try:
            r = scan_one(df, xu, m3)
        except Exception as e:
            print(f"  [atlandi] {t}: {e}")
            continue
        if r is None:
            continue
        stocks.append({"t": t, "ad": info.at[t, "ad"] if t in info.index else t,
                       "sektor": info.at[t, "sektor"] if t in info.index else "", **r})

    _fiyat_ivme(stocks, px, xu)
    _temel_ekle(stocks)
    _nad_ekle(stocks, px)
    _geri_alim_ekle(stocks)

    # piyasa ozeti (makro etiketi BIST100'den, tum hisselerde ayni)
    m3e = E.m3_effective(m3)
    ref = next((s for s in stocks if s["t"] in ("THYAO", "AKBNK", "GARAN")), stocks[0] if stocks else None)
    piyasa = {
        "xu100": round(float(xu.iloc[-1]), 2), "xu100_tarih": f"{xu.index[-1]:%Y-%m-%d}",
        "xu100_degisim": round(float(100 * (xu.iloc[-1] / xu.iloc[-2] - 1)), 2),
        "m3": float(m3e.iloc[-1]), "m3_ay": f"{m3.index[-1]:%Y-%m}",
        "makro": ref["D"]["macro"].replace(" + UCUZ", "") if ref else None,
    }

    def lists(tf):
        S = [s for s in stocks if s.get(tf)]
        g = lambda s: s[tf]
        sinyal = sorted([s for s in S if g(s)["sinyal"] != "BEKLE"],
                        key=lambda s: (SIG_ORDER[g(s)["sinyal"]], -(g(s)["toplam"] or 0)))
        ucuz = sorted([s for s in S if g(s)["percentile"] <= 20],
                      key=lambda s: (g(s)["percentile"], -(g(s)["toplam"] or 0)))
        pahali = sorted([s for s in S if g(s)["percentile"] >= 80],
                        key=lambda s: (-g(s)["percentile"], g(s)["toplam"] or 0))
        kiran = sorted([s for s in S if g(s)["kirdi"]], key=lambda s: g(s)["d_stop"])
        yeni = [s for s in sinyal if g(s)["yeni_sinyal"]]
        T = lambda L: [s["t"] for s in L]
        v3 = lambda s: ((s.get("temel") or {}).get("v3") or {})
        temel = sorted([s for s in S if v3(s).get("toplam") is not None], key=lambda s: -v3(s)["toplam"])
        temel_ucuz = [s for s in temel if v3(s).get("dilim") == 5 and g(s)["percentile"] <= 20]
        fv = lambda s: s.get("fiyat_ivme") or {}
        firsat = [s for s in temel_ucuz if "Kotu bilanco surprizi" not in v3(s).get("etiketler", [])
                  and (fv(s).get("o20_x") or 0) <= 10 and (fv(s).get("o5") or 0) <= 15
                  and "Sert dusus" not in v3(s).get("etiketler", [])]
        fz = lambda s: s.get("faz") or {}
        guc = lambda s: int((fz(s).get("normal") or {}).get("alim", False)) + int((fz(s).get("ha") or {}).get("alim", False))
        ga = lambda s: int(bool((s.get("geri_alim") or {}).get("aktif")))
        firsat.sort(key=lambda s: (-int(guc(s) > 0), -ga(s), -guc(s), -v3(s)["toplam"]))  # 22 Kas: AL icinde geri alim yapan once
        geri = sorted([s for s in S if (s.get("geri_alim") or {}).get("aktif")],
                      key=lambda s: (-int((s.get("geri_alim") or {}).get("yeni_dalga", False)), -(v3(s).get("toplam") or 0)))
        return {"sinyal": T(sinyal), "yeni": T(yeni), "ucuz": T(ucuz), "pahali": T(pahali), "stop": T(kiran),
                "temel": T(temel), "temel_ucuz": T(temel_ucuz), "firsat": T(firsat), "geri_alim": T(geri)}

    L_D = lists("D")
    try:
        from . import defter
        defter_ozet = defter.guncelle(stocks, px, xu)
    except Exception as e:
        print("[uyari] defter", e); defter_ozet = {}
    try:
        from . import elde as _elde
        elde_iz = _elde.iz_hesap(_elde.yukle(), px)
    except Exception as e:
        print("[uyari] elde iz", e); elde_iz = {}
    result = {
        "bakim": _bakim(m3, xu, stocks),
        "olusturma": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "surum": "IKARUS QUANT v4.7 (Python)",
        "piyasa": piyasa,
        "listeler": {"D": L_D, "W": lists("W")},
        "hisseler": stocks,
        "defter": defter_ozet,
        "elde_iz": elde_iz,
        "not": "Yatirim tavsiyesi degildir. Sinyal kurali 19 Zippo tablosundan cikarilmis adaydir.",
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "sonuclar.json").write_text(json.dumps(_temiz(result), ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
    flat = []
    for s in stocks:
        for tf in ("D", "W"):
            if s.get(tf):
                x = {k: v for k, v in s[tf].items() if k != "eksik"}
                x["eksik"] = ", ".join(e["k"] for e in s[tf]["eksik"])
                flat.append({"hisse": s["t"], "ad": s["ad"], "sektor": s["sektor"], "zaman": tf, **x})
    pd.DataFrame(flat).to_csv(OUT / "sonuclar.csv", index=False, encoding="utf-8-sig", sep=";", decimal=",")
    L = result["listeler"]["D"]
    print(f"Bitti ({time.time() - t0:.0f} sn). {len(stocks)} hisse hesaplandi.")
    print(f"Gunluk: {len(L['sinyal'])} sinyal ({sum(1 for s in stocks if s['D']['sinyal']=='ALINABILIR')} ALINABILIR), "
          f"{len(L['ucuz'])} ucuz, {len(L['pahali'])} pahali, {len(L['stop'])} stop kiran.")
    print(f"Dosyalar: {OUT / 'sonuclar.json'}  ve  {OUT / 'sonuclar.csv'}")
    return result


if __name__ == "__main__":
    run(sys.argv[1:] or None)
