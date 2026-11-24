"""Eldekiler: Teoman'in kendi hisseleri. Liste data/elde.json'da durur (bulutta, cihazdan bagimsiz).
Telegram komutlari (telegram_dinle.py):
  ekle KCHOL 250 [12.11.2026]   -> listeye ekler (fiyat ve tarih isteğe bagli)
  cikar KCHOL                   -> listeden cikarir
  stop KCHOL 170                -> zarar stopuyla 170'ten satildi: listeden cikar, 120 gun geri giris takibi (24 Kas)
  eldekiler                     -> liste ve son karar (SAT / DIKKAT / TUT)
Karar kurali uygulamadakiyle ayni (index.html eldeKarar); 15 Kas 2026 fbt testine dayanir.
"""
from __future__ import annotations

import json
import re
from datetime import date

from . import data as D

F = D.DATA / "elde.json"
# 24 Kas (temel/stop2_sonuc.txt, 2014-2026): zarar stopu + yer tut + duzeltince geri gir. 5 hisse ortanca koşu:
# 2018-20 +84 (stopsuz +62) | 2021-24 +1827 (+1838) | 2025-26 +62 (+32); en kotu kosu 2025-26 +38 (-13).
ZARAR = 0.20      # alistan %20 asagi -> sat
GERI = 0.10       # satis fiyatinin %10 ustu -> ayni hisseye geri gir
BEKLE_GUN = 120   # yer en fazla 120 gun nakitte bekler (yerine baska hisse alma)


def yukle() -> list:
    try:
        return json.loads(F.read_text(encoding="utf-8")).get("liste", [])
    except Exception:
        return []


def stop_yukle() -> list:
    """Zarar stopuyla satilip geri giris beklenen hisseler: [{t, cikis, tarih, alis}] (120 gunu gecenler atilir)."""
    try:
        S = json.loads(F.read_text(encoding="utf-8")).get("stop", [])
    except Exception:
        return []
    bugun = date.today()
    return [x for x in S if (bugun - date.fromisoformat(x["tarih"])).days <= BEKLE_GUN]


def kaydet(L: list, S: list | None = None):
    S = stop_yukle() if S is None else S
    F.write_text(json.dumps({"guncelleme": date.today().isoformat(), "liste": L, "stop": S}, ensure_ascii=False, indent=1), encoding="utf-8")


def stop_durum(x: dict, s: dict | None) -> dict:
    """Stoplanan hisse icin geri giris durumu."""
    seviye = round(x["cikis"] * (1 + GERI), 2)
    kalan = BEKLE_GUN - (date.today() - date.fromisoformat(x["tarih"])).days
    if not s or not s.get("D"):
        return {"durum": "BEKLE", "seviye": seviye, "kalan": kalan, "neden": "taramada yok"}
    r = s["D"]; v = (s.get("temel") or {}).get("v3") or {}
    if v.get("sira") is not None and v["sira"] < 0.6:
        return {"durum": "VAZGEC", "seviye": seviye, "kalan": kalan, "neden": "temel bozuldu; yer serbest"}
    if (r.get("percentile") or 0) >= 90:
        return {"durum": "BEKLE", "seviye": seviye, "kalan": kalan, "neden": "pahali bolgede (P >= 90)"}
    if (r.get("fiyat") or 0) >= seviye:
        return {"durum": "GERI AL", "seviye": seviye, "kalan": kalan, "neden": f"fiyat {r['fiyat']:.2f} >= {seviye:.2f}"}
    return {"durum": "BEKLE", "seviye": seviye, "kalan": kalan, "neden": f"geri giris {seviye:.2f} ustunde"}


def iz_hesap(L: list, px: dict) -> dict:
    """18 Kas: Eldekiler icin takip eden stop (alistan %20 yukari ciktiktan sonra zirveden %15). Alis tarihi gerekir.
    Fiyatlar duzeltmeli kapanis; seviye bugunku fiyat cinsinden."""
    from .defter import iz_durum, _fiyat
    out = {}
    for h in L:
        t, tarih = h.get("t"), h.get("tarih")
        if not t or not tarih or t not in px:
            continue
        son = px[t]["close"].index[-1]
        ak, tepe, sev, tet = iz_durum(px, t, tarih, son, (0.20, 0.15))
        g0 = _fiyat(px, t, tarih)
        out[t] = {"aktif": ak, "tepe": round(tepe, 2) if tepe else None, "stop": round(sev, 2) if sev else None,
                  "tetik": tet, "aktiflesme": round(g0 * 1.2, 2) if g0 else None}
    return out


def karar(s: dict, iz: dict | None = None, alis: float | None = None) -> dict:
    r = s.get("D") or {}
    v = (s.get("temel") or {}).get("v3") or {}
    f = s.get("faz") or {}
    sat, dikkat = [], []
    p = r.get("percentile")
    fy = r.get("fiyat")
    if alis and fy and fy <= alis * (1 - ZARAR):
        sat.append(f"Zarar stopu: alıştan {100 * (fy / alis - 1):+.0f}% (sınır −%{int(100 * ZARAR)}). Sat; yerini {BEKLE_GUN} güne kadar nakitte tut, "
                   f"başka hisse alma. Fiyat {fy * (1 + GERI):.2f} üstüne çıkarsa geri al.")
    elif alis and fy and fy <= alis * (1 - ZARAR + 0.05):
        dikkat.append(f"Zarar stopuna yakın: alıştan {100 * (fy / alis - 1):+.0f}%; stop {alis * (1 - ZARAR):.2f}")
    if p is not None and p >= 90:
        sat.append(f"Kâr al: pahalı bölgede (Percentile {p:.0f} ≥ 90)")
    elif p is not None and p >= 80:
        dikkat.append(f"Pahalı bölgeye girdi (Percentile {p:.0f}); kâr al 90'da")
    if iz and iz.get("tetik"):
        sat.append(f"Takip eden stop: zirve {iz['tepe']:.2f}, stop {iz['stop']:.2f} altına indi")
    if v.get("sira") is not None and v["sira"] < 0.6:
        sat.append(f"Temel bozuldu: temel sırası %{100 * v['sira']:.0f} (< %60)")
    if "Kotu bilanco surprizi" in (v.get("etiketler") or []):
        sat.append("Temel bozuldu: kötü bilanço sürprizi")
    if r.get("kirdi"):
        dikkat.append("Stop kırıldı")
    ys = (s.get("icerden") or {}).get("yon_satim")
    if ys:   # 23 Kas: yonetici satimi sonrasi 63g ortanca -7.1, kazanma %36 (n 318)
        dikkat.append(f"Yönetici sattı ({ys['son']}, {ys['n']} bildirim)")
    for ad, k in (("Faz", "normal"), ("HA faz", "ha")):
        x = f.get(k) or {}
        if x.get("sinyal") == "DAGITIM" and (x.get("gun") or 0) >= 10:
            dikkat.append(f"{ad} {x['gun']} gündür DAĞITIM")
    return {"karar": "SAT" if sat else ("DİKKAT" if dikkat else "TUT"), "neden": sat + dikkat,
            "fiyat": r.get("fiyat"), "percentile": p}


def ozet(res: dict, L: list | None = None) -> list[str]:
    """Telegram icin satirlar."""
    L = yukle() if L is None else L
    if not L:
        return []
    H = {s["t"]: s for s in res.get("hisseler", [])}
    out = ["💼 <b>Eldekiler</b>"]
    for h in L:
        s = H.get(h["t"])
        if not s or not s.get("D"):
            out.append(f"<b>{h['t']}</b> taramada yok"); continue
        iz = (res.get("elde_iz") or {}).get(h["t"])
        k = karar(s, iz, h.get("fiyat"))
        ik = {"SAT": "🔴", "DİKKAT": "🟠", "TUT": "🟢"}[k["karar"]]
        get = f" ({100 * (k['fiyat'] / h['fiyat'] - 1):+.1f}%)" if h.get("fiyat") and k["fiyat"] else ""
        if iz:
            st_ = f" · stop {iz['stop']:.2f}" if iz.get("aktif") else f" · stop {iz['aktiflesme']:.2f} üstünde başlar"
        else:
            st_ = " · stop için alış tarihi gerekli" if not h.get("tarih") else ""
        out.append(f"{ik} <b>{h['t']}</b> {k['karar']} · {k['fiyat']:.2f}{get} · P {k['percentile']:.0f}{st_}"
                   + (f" · {'; '.join(k['neden'])}" if k["neden"] else ""))
    S = stop_yukle()
    if S:
        out.append("⏳ <b>Stop sonrası bekleyenler</b> (yer nakitte)")
        for x in S:
            d = stop_durum(x, H.get(x["t"]))
            ik = {"GERI AL": "🟢", "VAZGEC": "⚪", "BEKLE": "⏳"}[d["durum"]]
            out.append(f"{ik} <b>{x['t']}</b> {d['durum']} · satış {x['cikis']:.2f} · geri al ≥ {d['seviye']:.2f} · {d['kalan']} gün kaldı · {d['neden']}")
    return out


def komut(txt: str) -> str | None:
    """Komutsa listeyi gunceller ve cevap metnini dondurur; komut degilse None."""
    t = txt.strip()
    low = t.lower().lstrip("/")
    for a, b in (("ç", "c"), ("ı", "i"), ("ş", "s"), ("ğ", "g"), ("ü", "u"), ("ö", "o")):
        low = low.replace(a, b)
    parca = t.lstrip("/").split()
    if low.startswith("ekle") and len(parca) >= 2:
        hisse = re.sub(r"[^A-Z0-9]", "", parca[1].upper())
        fiyat = tarih = None
        for x in parca[2:]:
            m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", x)
            if m:
                tarih = f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"; continue
            try:
                fiyat = float(x.replace(",", "."))
            except ValueError:
                pass
        L = [h for h in yukle() if h["t"] != hisse]
        L.append({"t": hisse, "fiyat": fiyat, "tarih": tarih})
        kaydet(L, [x for x in stop_yukle() if x["t"] != hisse])
        return f"✅ {hisse} eldekilere eklendi" + (f" (alış {fiyat})" if fiyat else "") + f". Listede {len(L)} hisse."
    if low.startswith("stop") and len(parca) >= 3:
        # 'stop KCHOL 170' -> zarar stopuyla 170'ten satildi; listeden cikar, geri giris takibine al
        hisse = re.sub(r"[^A-Z0-9]", "", parca[1].upper())
        try:
            cikis = float(parca[2].replace(",", "."))
        except ValueError:
            return "Kullanım: stop KCHOL 170 (satış fiyatı)"
        L0 = yukle(); h0 = next((h for h in L0 if h["t"] == hisse), {})
        S = [x for x in stop_yukle() if x["t"] != hisse] + [{"t": hisse, "cikis": cikis, "tarih": date.today().isoformat(), "alis": h0.get("fiyat")}]
        kaydet([h for h in L0 if h["t"] != hisse], S)
        return f"⏳ {hisse} stop listesine alındı: satış {cikis:.2f}. Yerini {BEKLE_GUN} güne kadar nakitte tut; {cikis * (1 + GERI):.2f} üstüne çıkarsa geri al uyarısı gelir."
    if (low.startswith("cikar") or low.startswith("sil")) and len(parca) >= 2:
        hisse = re.sub(r"[^A-Z0-9]", "", parca[1].upper())
        L0 = yukle(); L = [h for h in L0 if h["t"] != hisse]
        if len(L) == len(L0):
            S0 = stop_yukle(); S = [x for x in S0 if x["t"] != hisse]
            if len(S) < len(S0):
                kaydet(L0, S)
                return f"🗑 {hisse} stop takibinden çıkarıldı."
            return f"{hisse} listede yoktu."
        kaydet(L)
        return f"🗑 {hisse} çıkarıldı. Listede {len(L)} hisse. (Zarar stopuyla sattıysanız 'stop {hisse} SATIŞFİYATI' yazın; geri giriş takibi başlar.)"
    if low.startswith("elde"):
        try:
            import requests
            url = (D.ayar("app_url") or "https://teomanbasar.github.io/ikarus-app/").rstrip("/") + "/data/sonuclar.json"
            res = requests.get(url, timeout=30).json()
        except Exception:
            res = {"hisseler": []}
        s = ozet(res)
        return "\n".join(s) if s else "Eldekiler boş. Eklemek için: ekle KCHOL 250"
    return None
