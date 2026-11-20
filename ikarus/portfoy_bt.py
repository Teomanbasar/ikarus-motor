"""Portfoy simulasyonu (16 Kas 2026, Teoman: "site son haliyle islem yapilsaydi gercekten kar getirir miydi?").

Sitenin karar kutusu kurallari birebir, gercek para hesabiyla:
  - Baslangic 100.000 TL, en fazla N hisse, her yeni alima hesabin 1/N'i (nakit yetmezse kalan nakit).
  - Al: kutu AL (✓✓ once, sonra ✓; esitlikte temel sirasi yuksek olan). Sinyal gunu kapanistan sonra karar,
    ERTESI gun kapanistan islem.
  - Sat: PAHALI (Percentile >= 80, kar al) ya da bilanco bozuldu (temel sirasi < %60, kotu surpriz, 200 gunden
    yeni bilanco yok). Ertesi gun kapanistan.
  - Maliyet: her alim ve satimda %0.2 (komisyon + kayma).
  - Bostaki nakit: (a) faiz yok, (b) TCMB politika faizi kadar (mevduata yakin, yaklasik).
Karsilastirma: BIST100 (fiyat endeksi), politika faiziyle mevduat (yaklasik), M3 para arzi.
Cikti: temel/portfoy_sonuc.txt, temel/portfoy_egri.csv, temel/portfoy.png
"""
from __future__ import annotations

import gzip
import json

import numpy as np
import pandas as pd

from . import data as D
from . import engine as E
from . import temel_bt2 as B
from .firsat_bt import puanlar, AL
from .karar_bt import durumlar

R = D.ROOT / "temel"
MAL = 0.002
BAS = 100_000.0

# TCMB politika faizi (yillik %), degisim tarihleri. Mevduat icin yaklasik olcu.
FAIZ = [("2020-09-24", 10.25), ("2020-11-19", 15.0), ("2020-12-24", 17.0), ("2021-03-18", 19.0), ("2021-09-23", 18.0),
        ("2021-10-21", 16.0), ("2021-11-18", 15.0), ("2021-12-16", 14.0), ("2022-08-18", 13.0), ("2022-09-22", 12.0),
        ("2022-10-20", 10.5), ("2022-11-24", 9.0), ("2023-02-23", 8.5), ("2023-06-22", 15.0), ("2023-07-20", 17.5),
        ("2023-08-24", 25.0), ("2023-09-21", 30.0), ("2023-10-26", 35.0), ("2023-11-23", 40.0), ("2023-12-21", 42.5),
        ("2024-01-25", 45.0), ("2024-03-21", 50.0), ("2024-12-26", 47.5), ("2025-01-23", 45.0), ("2025-04-17", 46.0),
        ("2025-07-24", 43.0), ("2025-09-11", 40.5), ("2025-10-23", 39.5), ("2025-12-11", 38.0), ("2026-01-22", 37.0),
        ("2026-10-22", 36.0)]


def faiz_serisi(idx):
    s = pd.Series({pd.Timestamp(d): v for d, v in FAIZ}).sort_index()
    return s.reindex(idx.union(s.index)).ffill().reindex(idx).fillna(10.25).values / 100.0


def panel(ham: dict | None = None):
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    m3 = D.m3()
    O = B.olaylar(G, m3)
    px = D.prices(sorted(O["t"].unique()))
    xu = D.xu100()
    P = puanlar(O, px)
    idx = xu.index[xu.index >= pd.Timestamp("2020-09-01")]
    C, S, PC, VR, TK = {}, {}, {}, {}, {}
    for n_, (t, df) in enumerate(sorted(px.items())):
        ev = P[P["t"] == t].sort_values("giris")
        if ev.empty or len(df) < 300:
            continue
        try:
            rfz = E.compute(df, xu, m3, "D", sig_mod="faz")
            rha = E.compute(df, xu, m3, "D", ha=True, sig_mod="faz")
        except Exception:
            continue
        ix = rfz.index
        c = rfz["close"].values.astype(float)
        x = xu.reindex(ix).ffill().values
        pct = rfz["percentile"].values
        fz = np.isin(rfz["sinyal"].values, AL)
        ha = np.isin(rha["sinyal"].reindex(ix).values, AL)
        vol = (df["close"] * df["volume"]).reindex(ix).rolling(20).mean().values
        gv = ev["giris"].values.astype("datetime64[ns]")
        k = np.searchsorted(gv, ix.values.astype("datetime64[ns]"), side="right") - 1
        kk = np.clip(k, 0, None)
        v3r = np.where(k >= 0, ev["v3r"].values[kk].astype(float), np.nan)
        kotu = np.where(k >= 0, ev["kotu"].values[kk].astype(bool), False)
        yas = np.where(k >= 0, (ix.values.astype("datetime64[ns]") - gv[kk]) / np.timedelta64(1, "D"), 9999)
        cs, xs = pd.Series(c), pd.Series(x)
        o5 = (100 * (cs / cs.shift(5) - 1)).values
        o20x = (100 * (cs / cs.shift(20) - 1) - 100 * (xs / xs.shift(20) - 1)).values
        taban10 = (cs.pct_change() <= -0.095).rolling(10).sum().fillna(0).values
        if ham is not None:
            ham[t] = (ix, v3r, kotu, yas <= 200, pct, o5, o20x, taban10, fz, ha, vol)
        d = durumlar(v3r, kotu, yas <= 200, pct, o5, o20x, taban10, fz, ha)
        d = np.where(vol > 5e6, d, np.where(np.char.startswith(d.astype(str), "AL"), "AL likit degil", d))
        boz = (yas > 200) | np.isnan(v3r) | (v3r < 0.6) | kotu
        f = lambda a: pd.Series(a, index=ix).reindex(idx)
        C[t], S[t], PC[t] = f(c), f(d), f(pct)
        VR[t] = f(np.where(boz, -1.0, np.nan_to_num(v3r, nan=-1.0)))
        TK[t] = f(fz.astype(int) + ha.astype(int))
        if n_ % 100 == 0:
            print("panel", n_, t)
    return idx, pd.DataFrame(C), pd.DataFrame(S), pd.DataFrame(PC), pd.DataFrame(VR), pd.DataFrame(TK), xu.reindex(idx).ffill(), m3


def sim(idx, C, S, PC, VR, TK, N=10, faizli=True, sadece_cift=False, iz=None, karal=80, iz_vol=None, agirlik=None, sert=False, sira=None, al_set=None):
    """iz=(aktif, geri): fiyat girisin aktif kadar ustune ciktiktan sonra, girişten beri gorulen en yuksek
    kapanisin 'geri' kadar altina inerse sat (takip eden stop). karal: kar al Percentile esigi."""
    r = faiz_serisi(idx)
    cash = BAS
    poz = {}   # t -> (adet, giris_fiyat, giris_tarih)
    bek_al, bek_sat = [], []
    egri, isl = [], []
    Cv = C.values; Sv = S.values; PCv = PC.values; VRv = VR.values; TKv = TK.values
    # iz_vol=(aktif, k): geri payi = k x (60 gunluk gunluk getiri oynakligi x kok 20), %8-%35 arasi
    if iz_vol:
        sig = (C.pct_change().rolling(60, min_periods=20).std() * np.sqrt(20)).values
    col = {t: j for j, t in enumerate(C.columns)}
    son_fiyat = {}
    tepe = {}
    for i, gun in enumerate(idx):
        if i > 0 and faizli:
            cash *= 1 + r[i] * (gun - idx[i - 1]).days / 365.0
        # dunku kararlari bugun kapanistan uygula
        for t, neden in bek_sat:
            p = Cv[i, col[t]]
            if t in poz and not np.isnan(p):
                a, gf, gt = poz.pop(t); tepe.pop(t, None)
                cash += a * p * (1 - MAL)
                isl.append((t, gt, gun, gf, p, 100 * (p * (1 - MAL) / (gf * (1 + MAL)) - 1), neden))
        bek_sat = []
        eq0 = cash + sum(a * son_fiyat.get(t, gf) for t, (a, gf, _) in poz.items())
        for t in bek_al:
            if len(poz) >= N or t in poz:
                continue
            p = Cv[i, col[t]]
            if np.isnan(p) or p <= 0:
                continue
            tutar = min(eq0 / N, cash)
            if tutar < 1000:
                break
            a = tutar / (p * (1 + MAL))
            cash -= a * p * (1 + MAL)
            poz[t] = (a, p, gun); tepe[t] = p
        bek_al = []
        for t, j in col.items():
            p = Cv[i, j]
            if not np.isnan(p):
                son_fiyat[t] = p
        eq = cash + sum(a * son_fiyat.get(t, gf) for t, (a, gf, _) in poz.items())
        egri.append((gun, eq, len(poz), cash))
        # bugunun kapanisina gore yarin icin karar
        for t in list(poz):
            j = col[t]
            p = Cv[i, j]
            if not np.isnan(p):
                tepe[t] = max(tepe.get(t, p), p)
            gf = poz[t][1]
            if PCv[i, j] >= karal:
                bek_sat.append((t, "pahali (kar al)"))
            elif VRv[i, j] < 0:
                bek_sat.append((t, "bilanco bozuldu"))
            elif iz and not np.isnan(p) and tepe[t] >= gf * (1 + iz[0]) and p <= tepe[t] * (1 - iz[1]):
                bek_sat.append((t, "takip eden stop"))
            elif iz_vol and not np.isnan(p) and not np.isnan(sig[i, j]) and tepe[t] >= gf * (1 + iz_vol[0]) \
                    and p <= tepe[t] * (1 - min(0.35, max(0.08, iz_vol[1] * sig[i, j]))):
                bek_sat.append((t, "takip eden stop"))
        # agirlik: o gun hisseye ayrilacak en fazla pay (borsa/mevduat kurali). sert=True ise fazlasi satilir.
        w = 1.0 if agirlik is None else float(agirlik[i])
        if sert and w < 1.0 and poz:
            hisse_deger = sum(a * son_fiyat.get(t, gf) for t, (a, gf, _) in poz.items())
            fazla = hisse_deger - w * (cash + hisse_deger)
            if fazla > 0:
                satilacak = {x for x, _ in bek_sat}
                for t in sorted(poz, key=lambda t: (PCv[i, col[t]] if not np.isnan(PCv[i, col[t]]) else 0), reverse=True):
                    if fazla <= 0:
                        break
                    if t not in satilacak:
                        bek_sat.append((t, "borsa agirligi azaldi"))
                        fazla -= poz[t][0] * son_fiyat.get(t, poz[t][1])
        bos = int(np.floor(N * w + 1e-9)) - len(poz) + len(bek_sat)
        if bos > 0:
            ad = []
            for t, j in col.items():
                if t in poz:
                    continue
                s_ = Sv[i, j]
                if (s_ in al_set) if al_set else (s_ == "AL cift tik" or (s_ == "AL tek tik" and not sadece_cift)):
                    if sira is not None:
                        k_ = sira[i, j]
                        ad.append((-(k_ if not np.isnan(k_) else -1e18), 0, t))
                    else:
                        ad.append((-TKv[i, j], -VRv[i, j], t))
            bek_al = [t for *_, t in sorted(ad)][:bos]
    E_ = pd.DataFrame(egri, columns=["tarih", "deger", "hisse", "nakit"]).set_index("tarih")
    T = pd.DataFrame(isl, columns=["t", "giris", "cikis", "gf", "cf", "getiri", "neden"])
    return E_, T, poz


def ozet(ad, E_, T, xu, faizli_ref):
    v = E_["deger"]
    yil = v.groupby(v.index.year).last()
    bas = v.groupby(v.index.year).first()
    xy = xu.groupby(xu.index.year)
    dd = (v / v.cummax() - 1).min()
    ys = (v.index[-1] - v.index[0]).days / 365.25
    L = [f"\n== {ad} ==",
         f"Toplam: 100.000 -> {v.iloc[-1]:,.0f} TL (x{v.iloc[-1] / BAS:.2f}, yillik %{100 * ((v.iloc[-1] / BAS) ** (1 / ys) - 1):.1f}) | en buyuk dusus %{100 * dd:.1f} | ortalama dolu hisse {E_['hisse'].mean():.1f}",
         f"Islem: {len(T)} kapandi, kazanan %{100 * (T.getiri > 0).mean():.0f}, medyan %{T.getiri.median():+.1f}, ortalama %{T.getiri.mean():+.1f}, ort sure {((T.cikis - T.giris).dt.days).mean():.0f} gun"
         + " | cikis: " + ", ".join(f"{k} {n}" for k, n in T.neden.value_counts().items())]
    for y in yil.index:
        g = v[v.index.year == y]
        prev = v[v.index.year == y - 1]
        b0 = prev.iloc[-1] if len(prev) else g.iloc[0]
        xg = xu[xu.index.year == y]; xp = xu[xu.index.year == y - 1]
        x0 = xp.iloc[-1] if len(xp) else xg.iloc[0]
        rf = faizli_ref[faizli_ref.index.year == y]; rp = faizli_ref[faizli_ref.index.year == y - 1]
        f0 = rp.iloc[-1] if len(rp) else rf.iloc[0]
        L.append(f"  {y}: sistem %{100 * (g.iloc[-1] / b0 - 1):+6.1f} | BIST100 %{100 * (xg.iloc[-1] / x0 - 1):+6.1f} | mevduat~ %{100 * (rf.iloc[-1] / f0 - 1):+6.1f}")
    return L


def main():
    idx, C, S, PC, VR, TK, xu, m3 = panel()
    r = faiz_serisi(idx)
    mev = pd.Series(BAS * np.cumprod(np.r_[1.0, 1 + r[1:] * np.diff(idx.values).astype("timedelta64[D]").astype(float) / 365.0]), index=idx)
    xuv = BAS * xu / xu.iloc[0]
    m3s = m3.reindex(idx.union(m3.index)).ffill().reindex(idx)
    m3v = BAS * m3s / m3s.iloc[0]
    ys = (idx[-1] - idx[0]).days / 365.25
    L = ["PORTFOY SIMULASYONU: sitenin karar kutusu kurallari (16 Kas 2026)",
         f"Donem {idx[0]:%d.%m.%Y} - {idx[-1]:%d.%m.%Y} ({ys:.1f} yil). Baslangic 100.000 TL. Maliyet her islemde %0.2.",
         "Al: kutu AL (✓✓ once). Sat: Percentile >= 80 (kar al) ya da bilanco bozuldu. Sinyalin ertesi gunu kapanistan islem.",
         f"Karsilastirma (ayni donem): BIST100 x{xuv.iloc[-1] / BAS:.2f} (yillik %{100 * ((xuv.iloc[-1] / BAS) ** (1 / ys) - 1):.1f}) | "
         f"mevduat~ (politika faizi) x{mev.iloc[-1] / BAS:.2f} (yillik %{100 * ((mev.iloc[-1] / BAS) ** (1 / ys) - 1):.1f}) | "
         f"M3 x{m3v.iloc[-1] / BAS:.2f} (yillik %{100 * ((m3v.iloc[-1] / BAS) ** (1 / ys) - 1):.1f})",
         "Not: BIST100 fiyat endeksi (temettusuz); hisse fiyatlari veri kaynagina gore temettu duzeltmeli olabilir. Mevduat stopajsiz, yaklasik."]
    egriler = {"BIST100": xuv, "Mevduat~": mev, "M3": m3v}
    for ad, kw in [("A. 10 hisse, bos nakit faizde", dict(N=10, faizli=True)),
                   ("B. 10 hisse, bos nakit faizsiz", dict(N=10, faizli=False)),
                   ("C. 5 hisse, bos nakit faizde", dict(N=5, faizli=True)),
                   ("D. 10 hisse, yalniz ✓✓, nakit faizde", dict(N=10, faizli=True, sadece_cift=True)),
                   ("E. 20 hisse, bos nakit faizde", dict(N=20, faizli=True))]:
        E_, T, acik = sim(idx, C, S, PC, VR, TK, **kw)
        L += ozet(ad, E_, T, xu, mev)
        L.append(f"  su an acik: {', '.join(sorted(acik)) or '-'}")
        egriler[ad[:1] + " sistem"] = E_["deger"]
        if ad.startswith("A."):
            T.to_csv(R / "portfoy_islemler.csv", index=False)
    pd.DataFrame(egriler).to_csv(R / "portfoy_egri.csv")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(10, 5.5))
        for k_, st_ in [("A sistem", dict(lw=2.4, color="#1f5fd6", label="Sistem (10 hisse, boş nakit faizde)")),
                        ("D sistem", dict(lw=1.4, color="#7aa7f0", label="Sistem, yalnız ✓✓")),
                        ("BIST100", dict(lw=1.6, color="#444", label="BIST100")),
                        ("Mevduat~", dict(lw=1.6, color="#c28a00", ls="--", label="Mevduat (politika faizi, yaklaşık)")),
                        ("M3", dict(lw=1.2, color="#999", ls=":", label="M3 para arzı"))]:
            ax.plot(pd.DataFrame(egriler)[k_] / 1000, **st_)
        ax.set_yscale("log"); ax.set_ylabel("Bin TL (log ölçek)"); ax.grid(alpha=.25)
        ax.set_title("100.000 TL ile başlasaydı: sitenin kuralları vs BIST100 ve mevduat")
        ax.legend(loc="upper left", fontsize=9, frameon=False)
        for s_ in ("top", "right"):
            ax.spines[s_].set_visible(False)
        fig.tight_layout(); fig.savefig(R / "portfoy.png", dpi=130)
    except Exception as e:
        print("grafik hatasi", e)
    txt = "\n".join(L)
    (R / "portfoy_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()


def zar(kosu: int = 2000, seed: int = 7):
    """17 Kas (Teoman): 2025 ve 2026'ya ayri ayri 1 milyon TL ile basla; sistemin AL dediklerinden RASTGELE sec
    (kullanici her AL'i almiyor). Binlerce kosu: en kotu / en iyi / ortanca sonuc."""
    idx, C, S, PC, VR, TK, xu, m3 = panel()
    r = faiz_serisi(idx)
    Cv = C.values; Sv = S.values
    ALm = (Sv == "AL cift tik") | (Sv == "AL tek tik")
    CIFT = (Sv == "AL cift tik")
    CIK = (PC.values >= 80) | (VR.values < 0)
    rng = np.random.default_rng(seed)
    L = ["ZAR ATIMI SIMULASYONU (17 Kas 2026): sistemin AL dediklerinden rastgele secim",
         "Her yil 1.000.000 TL ile ayri baslar. Bos yer acildikca o gun AL (✓ ya da ✓✓) olan hisselerden RASTGELE secilir.",
         "Satis: Percentile >= 80 (kar al) ya da bilanco bozuldu. Islem ertesi gun kapanistan, %0.2 maliyet. Bos nakit politika faizinde.",
         "Yil sonunda acik hisseler o gunku fiyatla degerlenir.\n"]
    for yil in (2025, 2026):
        ii = np.flatnonzero((idx.year == yil))
        i0, i1 = ii[0], ii[-1]
        xu_g = 100 * (xu.iloc[i1] / xu.iloc[i0 - 1] - 1)
        mev = 1e6 * np.prod(1 + r[i0:i1 + 1] * np.diff(idx.values[i0 - 1:i1 + 1]).astype("timedelta64[D]").astype(float) / 365.0)
        L.append(f"===== {yil} ({idx[i0]:%d.%m} - {idx[i1]:%d.%m.%Y}) | BIST100 %{xu_g:+.1f} -> {1e6 * (1 + xu_g / 100):,.0f} | mevduat~ -> {mev:,.0f}")
        for N, secici, ad in ((10, 1.0, "10 hisse, her bos yere rastgele AL"), (5, 1.0, "5 hisse, her bos yere rastgele AL"),
                              (10, 0.3, "10 hisse, AL'lerin yalniz %30'una bakar (secici kullanici)"),
                              (10, 1.0, "10 hisse, yalniz ✓✓ arasindan rastgele")):
            yalniz_cift = ad.endswith("✓✓ arasindan rastgele")
            son = []
            for _ in range(kosu):
                cash, poz, bek_al, bek_sat = 1e6, {}, [], []
                for i in range(i0, i1 + 1):
                    cash *= 1 + r[i] * (idx[i] - idx[i - 1]).days / 365.0
                    for j in bek_sat:
                        p = Cv[i, j]
                        if j in poz and not np.isnan(p):
                            cash += poz.pop(j) * p * (1 - MAL)
                    eq = cash + sum(a * (Cv[i, j] if not np.isnan(Cv[i, j]) else 0) for j, a in poz.items())
                    for j in bek_al:
                        p = Cv[i, j]
                        if len(poz) >= N or j in poz or np.isnan(p) or p <= 0:
                            continue
                        tutar = min(eq / N, cash)
                        if tutar < 1000:
                            break
                        poz[j] = tutar / (p * (1 + MAL)); cash -= tutar
                    bek_sat = [j for j in poz if CIK[i, j]]
                    bos = N - len(poz) + len(bek_sat)
                    bek_al = []
                    if bos > 0 and i < i1:
                        ad_ = np.flatnonzero((CIFT[i] if yalniz_cift else ALm[i]))
                        ad_ = [j for j in ad_ if j not in poz]
                        if secici < 1.0:
                            ad_ = [j for j in ad_ if rng.random() < secici]
                        if ad_:
                            bek_al = list(rng.permutation(ad_)[:bos])
                fiyat = lambda j: Cv[i1, j] if not np.isnan(Cv[i1, j]) else np.nan
                deger = cash + sum(a * np.nan_to_num(fiyat(j), nan=0.0) for j, a in poz.items())
                son.append(deger)
            s = np.array(son)
            q = np.percentile(s, [0, 5, 25, 50, 75, 95, 100])
            L.append(f"  {ad}:")
            L.append(f"     en kotu {q[0]:,.0f} | %5 {q[1]:,.0f} | %25 {q[2]:,.0f} | ORTANCA {q[3]:,.0f} | %75 {q[4]:,.0f} | %95 {q[5]:,.0f} | en iyi {q[6]:,.0f}")
            L.append(f"     BIST100'u gecen kosu %{100 * (s > 1e6 * (1 + xu_g / 100)).mean():.0f} | mevduati gecen %{100 * (s > mev).mean():.0f} | zarar eden %{100 * (s < 1e6).mean():.0f}")
        L.append("")
    txt = "\n".join(L)
    (R / "zar_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def iz_test():
    """17 Kas (Teoman): 'Kar al olmali ama takip eden stop sistemi de sart.' Varyantlar ayni panel uzerinde."""
    idx, C, S, PC, VR, TK, xu, m3 = panel()
    r = faiz_serisi(idx)
    mev = pd.Series(BAS * np.cumprod(np.r_[1.0, 1 + r[1:] * np.diff(idx.values).astype("timedelta64[D]").astype(float) / 365.0]), index=idx)
    L = ["TAKIP EDEN STOP TESTI (17 Kas 2026). 10 hisse, bos nakit faizde, sitenin AL kurallari. Satis: kar al (Percentile esigi) / bilanco bozuldu / takip eden stop.",
         "iz=(aktif, geri): fiyat girisin 'aktif' kadar ustune ciktiktan sonra, gorulen en yuksek kapanisin 'geri' kadar altina inerse ertesi gun sat.\n"]
    import os
    if os.environ.get("IZ_IZGARA") == "1":
        var = [(f"kar al P>={ka if ka < 101 else 'yok'} | iz {iz}", iz, ka) for ka in (80, 85, 90, 95, 101)
               for iz in (None, (0.15, 0.15), (0.20, 0.15), (0.20, 0.20), (0.10, 0.20), (0.0, 0.25))]
    else:
      var = [("Mevcut (stop yok, kar al P>=80)", None, 80),
           ("Iz %0 aktif / %15 geri (klasik)", (0.0, 0.15), 80), ("Iz %0 / %20", (0.0, 0.20), 80), ("Iz %0 / %25", (0.0, 0.25), 80),
           ("Iz %10 aktif / %12 geri", (0.10, 0.12), 80), ("Iz %15 / %15", (0.15, 0.15), 80), ("Iz %20 / %15", (0.20, 0.15), 80),
           ("Iz %20 / %20", (0.20, 0.20), 80), ("Iz %30 / %20", (0.30, 0.20), 80),
           ("Iz %15 / %15 + kar al P>=90", (0.15, 0.15), 90), ("Iz %20 / %20 + kar al yok (P>=101)", (0.20, 0.20), 101)]
    cikti = "iz_izgara.txt" if os.environ.get("IZ_IZGARA") == "1" else "iz_sonuc.txt"
    for ad, iz, ka in var:
        E_, T, acik = sim(idx, C, S, PC, VR, TK, N=10, faizli=True, iz=iz, karal=ka)
        v = E_["deger"]
        dd = (v / v.cummax() - 1).min()
        def yg(y):
            g = v[v.index.year == y]; p = v[v.index.year == y - 1]
            return 100 * (g.iloc[-1] / (p.iloc[-1] if len(p) else g.iloc[0]) - 1)
        x23 = v.iloc[-1] / v[v.index >= "2023-01-01"].iloc[0]
        m23 = mev.iloc[-1] / mev[mev.index >= "2023-01-01"].iloc[0]
        cik = ", ".join(f"{k} {n}" for k, n in T.neden.value_counts().items())
        L.append(f"{ad:38s} toplam x{v.iloc[-1] / BAS:5.2f} | 2023'ten x{x23:4.2f} (mevduat x{m23:4.2f}) | en buyuk dusus %{100 * dd:5.1f} | "
                 f"2023 {yg(2023):+5.0f} 2024 {yg(2024):+5.0f} 2025 {yg(2025):+5.0f} 2026 {yg(2026):+5.0f} | islem {len(T)}, kazanan %{100 * (T.getiri > 0).mean():.0f}, medyan %{T.getiri.median():+.1f} | {cik}")
    L.append(f"\nMevduat yillari: 2023 {100 * (mev[mev.index.year == 2023].iloc[-1] / mev[mev.index.year == 2022].iloc[-1] - 1):+.0f} 2024 {100 * (mev[mev.index.year == 2024].iloc[-1] / mev[mev.index.year == 2023].iloc[-1] - 1):+.0f} "
             f"2025 {100 * (mev[mev.index.year == 2025].iloc[-1] / mev[mev.index.year == 2024].iloc[-1] - 1):+.0f} 2026 {100 * (mev.iloc[-1] / mev[mev.index.year == 2025].iloc[-1] - 1):+.0f}")
    txt = "\n".join(L)
    (R / cikti).write_text(txt, encoding="utf-8")
    print(txt)


def piyasa_kar_verimi(idx):
    """Gunluk piyasa kar verimi = toplam TTM net kar / toplam piyasa degeri (o gun bilinen son bilancolarla).
    Sanayi + banka; piyasa degeri = kapanis x son odenmis sermaye (bolunme duzeltmeli fiyatla yaklasik)."""
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    m3 = D.m3()
    O = B.olaylar(G, m3)
    px = D.prices(sorted(O["t"].unique()))
    nk = {}; mc = {}
    for t, g in O.groupby("t"):
        df = px.get(t)
        if df is None or g["sermaye_son"].isna().all() or "nk_ttm" not in g:
            continue
        g = g.dropna(subset=["nk_ttm"]).sort_values("yayin")
        if g.empty:
            continue
        s_nk = pd.Series(g["nk_ttm"].values, index=pd.DatetimeIndex(g["yayin"])).groupby(level=0).last()
        nk[t] = s_nk.reindex(idx.union(s_nk.index)).ffill().reindex(idx)
        mc[t] = df["close"].reindex(idx).ffill() * float(g["sermaye_son"].dropna().iloc[-1])
    nk = pd.DataFrame(nk); mc = pd.DataFrame(mc)
    ok = nk.notna() & mc.notna() & (mc > 0)
    ep = nk.where(ok).sum(axis=1) / mc.where(ok).sum(axis=1)
    return ep.rolling(5, min_periods=1).mean()


def iz_test2():
    """17 Kas aksam (Teoman: 'once baska ayarlar da dene') + borsa/mevduat agirlik kurali."""
    idx, C, S, PC, VR, TK, xu, m3 = panel()
    r = faiz_serisi(idx)
    mev = pd.Series(BAS * np.cumprod(np.r_[1.0, 1 + r[1:] * np.diff(idx.values).astype("timedelta64[D]").astype(float) / 365.0]), index=idx)
    m23 = mev.iloc[-1] / mev[mev.index >= "2023-01-01"].iloc[0]

    def ozet(ad, E_, T):
        v = E_["deger"]; dd = (v / v.cummax() - 1).min()
        def yg(y):
            g = v[v.index.year == y]; p = v[v.index.year == y - 1]
            return 100 * (g.iloc[-1] / (p.iloc[-1] if len(p) else g.iloc[0]) - 1)
        x23 = v.iloc[-1] / v[v.index >= "2023-01-01"].iloc[0]
        cik = ", ".join(f"{k} {n}" for k, n in T.neden.value_counts().items())
        return (f"{ad:52s} x{v.iloc[-1] / BAS:5.2f} | 2023'ten x{x23:4.2f} | dusus %{100 * dd:5.1f} | "
                f"22 {yg(2022):+4.0f} 23 {yg(2023):+4.0f} 24 {yg(2024):+4.0f} 25 {yg(2025):+4.0f} 26 {yg(2026):+4.0f} | ort.hisse {E_['hisse'].mean():.1f} | islem {len(T)} med %{T.getiri.median():+.1f} | {cik}")
    L = ["SATIS KURALI ve BORSA/MEVDUAT TESTI (17 Kas 2026 aksam). 10 hisse (aksi yazilmadikca), bos nakit faizde.",
         f"Mevduat 2023'ten x{m23:.2f}. Yillar: " + " ".join(f"{y} {100 * (mev[mev.index.year == y].iloc[-1] / mev[mev.index.year == y - 1].iloc[-1] - 1):+.0f}" for y in (2022, 2023, 2024, 2025)) + f" 2026 {100 * (mev.iloc[-1] / mev[mev.index.year == 2025].iloc[-1] - 1):+.0f}", ""]
    L.append("== A. Takip eden stop ayarlari (yuzde)")
    for ka in (90, 95):
        for iz in ((0.20, 0.15), (0.20, 0.10), (0.20, 0.12), (0.15, 0.10), (0.25, 0.15), (0.30, 0.15), (0.25, 0.20), (0.30, 0.25)):
            E_, T, _ = sim(idx, C, S, PC, VR, TK, iz=iz, karal=ka)
            L.append(ozet(f"kar al {ka} | aktif %{int(iz[0] * 100)} geri %{int(iz[1] * 100)}", E_, T))
    L.append("\n== B. Oynakliga gore takip eden stop (geri = k x 20 gunluk oynaklik, %8-%35)")
    for ka in (90, 95):
        for iv in ((0.20, 2.0), (0.20, 2.5), (0.20, 3.0), (0.15, 2.5), (0.30, 2.5)):
            E_, T, _ = sim(idx, C, S, PC, VR, TK, iz_vol=iv, karal=ka)
            L.append(ozet(f"kar al {ka} | aktif %{int(iv[0] * 100)} k={iv[1]}", E_, T))
    L.append("\n== C. Hisse sayisi (kar al 90, aktif %20 geri %15)")
    for N in (5, 8, 12, 15):
        E_, T, _ = sim(idx, C, S, PC, VR, TK, N=N, iz=(0.20, 0.15), karal=90)
        L.append(ozet(f"{N} hisse", E_, T))
    ep = piyasa_kar_verimi(idx)
    oran = ep.values / r
    yo = pd.Series(oran, index=idx)
    L.append("\n== D. Borsa/mevduat: oran = piyasa kar verimi (TTM net kar / piyasa degeri) / politika faizi")
    L.append("   yil sonlari (kar verimi / faiz = oran): " + " ".join(
        f"{y}: %{100 * ep[ep.index.year == y].iloc[-1]:.1f}/%{100 * r[np.flatnonzero(idx.year == y)[-1]]:.0f}={yo[yo.index.year == y].iloc[-1]:.2f}" for y in range(2021, 2027)))
    for ad, f in [("oran<0.5 ise %50 borsa", lambda o: np.where(o < 0.5, 0.5, 1.0)),
                  ("oran<0.5 ise %0 borsa", lambda o: np.where(o < 0.5, 0.0, 1.0)),
                  ("oran<0.35 ise %50 borsa", lambda o: np.where(o < 0.35, 0.5, 1.0)),
                  ("kademeli: borsa payi = oran (0.3-1)", lambda o: np.clip(o, 0.3, 1.0)),
                  ("kademeli: borsa payi = 1.5 x oran (0.3-1)", lambda o: np.clip(1.5 * o, 0.3, 1.0))]:
        w = f(np.nan_to_num(oran, nan=1.0))
        for sert in (False, True):
            E_, T, _ = sim(idx, C, S, PC, VR, TK, iz=(0.20, 0.15), karal=90, agirlik=w, sert=sert)
            L.append(ozet(f"{ad}{' (fazla satilir)' if sert else ' (yeni alim durur)'}", E_, T) + f" | ort. borsa payi %{100 * w[idx >= pd.Timestamp('2022-01-01')].mean():.0f}")
    E_, T, _ = sim(idx, C, S, PC, VR, TK, iz=(0.20, 0.15), karal=90)
    L.append(ozet("karsilastirma: agirlik kurali yok", E_, T))
    txt = "\n".join(L)
    (R / "iz2_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def az_hisse():
    """17 Kas aksam (Teoman: 'genelde 2-5 hisse tutuyorum; 3 yil mevduatta kalamam'). Az hisse + borsa payi kurali,
    yeni satis kuraliyla (kar al 90 + iz 20/15). Borsa payi: en az %30 -> az hissede de her zaman en az 1 hisse."""
    idx, C, S, PC, VR, TK, xu, m3 = panel()
    r = faiz_serisi(idx)
    ep = piyasa_kar_verimi(idx)
    oran = np.nan_to_num(ep.values / r, nan=1.0)
    L = ["AZ HISSE TESTI (17 Kas 2026 aksam). Satis: kar al P>=90 + iz %20/%15 (aksi yazilmadikca). Bos nakit faizde. ✓✓ once secilir.", ""]
    for N in (2, 3, 4, 5, 8):
        for ad, w, iz, ka in (("eski satis kurali (P>=80, stop yok)", None, None, 80), ("yeni satis kurali", None, (0.20, 0.15), 90),
                              ("yeni satis + borsa payi (en az %30, en az 1 hisse)", np.maximum(np.clip(oran, 0.3, 1.0), 1.0 / N), (0.20, 0.15), 90)):
            E_, T, _ = sim(idx, C, S, PC, VR, TK, N=N, iz=iz, karal=ka, agirlik=w)
            v = E_["deger"]; dd = (v / v.cummax() - 1).min()
            yg = lambda y: 100 * (v[v.index.year == y].iloc[-1] / v[v.index.year == y - 1].iloc[-1] - 1) if y > idx[0].year else np.nan
            x23 = v.iloc[-1] / v[v.index >= "2023-01-01"].iloc[0]
            L.append(f"{N} hisse | {ad:52s} 2023'ten x{x23:4.2f} | dusus %{100 * dd:5.1f} | 23 {yg(2023):+4.0f} 24 {yg(2024):+4.0f} 25 {yg(2025):+4.0f} 26 {100 * (v.iloc[-1] / v[v.index.year == 2025].iloc[-1] - 1):+4.0f} | ort.dolu {E_['hisse'].mean():.1f} | islem {len(T)}, kazanan %{100 * (T.getiri > 0).mean():.0f}")
        L.append("")
    mev = np.cumprod(np.r_[1.0, 1 + r[1:] * np.diff(idx.values).astype("timedelta64[D]").astype(float) / 365.0])
    i23 = np.flatnonzero(idx >= pd.Timestamp("2023-01-01"))[0]
    L.append(f"Mevduat 2023'ten x{mev[-1] / mev[i23]:.2f}")
    txt = "\n".join(L)
    (R / "az_hisse.txt").write_text(txt, encoding="utf-8")
    print(txt)


def _durum2(v3r, kotu, guncel, pct, o5, o20x, taban10, fz, ha, ust=0.8, ucuz=20.0):
    """karar_bt.durumlar ile ayni; yalniz 'temel ust esigi' ve 'ucuz esigi' degistirilebilir (orneklem disi test)."""
    ok = guncel & ~np.isnan(v3r) & (v3r >= max(0.6, ust)) & ~kotu & ~((o20x < -25) | ((taban10 >= 4) & (o20x < -15)))
    ok &= (pct < 80) & ~((o20x > 10) | (o5 > 15)) & (pct <= ucuz)
    d = np.full(len(pct), "X", dtype=object)
    d[ok & fz & ha] = "AL cift tik"
    d[ok & (fz ^ ha)] = "AL tek tik"
    return d


def oos():
    """18 Kas (Teoman: 'sistem hazir diyemeyiz'). ORNEKLEM DISI TEST: ayarlar yalniz 2021-2024'e bakarak secilir,
    sonra hic bakilmamis 2025-2026'da (sifirdan baslayarak) denenir. Ezber mi, gercek mi?"""
    ham = {}
    idx, C, S, PC, VR, TK, xu, m3 = panel(ham)
    egit = (idx >= "2021-01-01") & (idx <= "2024-12-31")
    test = idx >= "2025-01-01"
    r = faiz_serisi(idx)

    def mev(m):
        ii = np.flatnonzero(m)
        return float(np.prod(1 + r[ii[1:]] * np.diff(idx.values[ii]).astype("timedelta64[D]").astype(float) / 365.0))

    def kos(m, S_=S, karal=80, iz=None, N=10):
        E_, T, _ = sim(idx[m], C[m], S_[m], PC[m], VR[m], TK[m], N=N, faizli=True, iz=iz, karal=karal)
        v = E_["deger"]
        return v.iloc[-1] / BAS, (v / v.cummax() - 1).min(), len(T)

    xg = lambda m: xu[m].iloc[-1] / xu[m].iloc[0]
    L = ["ORNEKLEM DISI TEST (18 Kas 2026)",
         "Egitim: 2021-01 .. 2024-12 (ayar burada secilir). Test: 2025-01 .. bugun (hic bakilmadan, sifirdan 100.000 TL).",
         f"Egitim: mevduat x{mev(egit):.2f}, BIST100 x{xg(egit):.2f} | Test: mevduat x{mev(test):.2f}, BIST100 x{xg(test):.2f}",
         "Not: temel puanin formulu (v3) tum veriye bakilarak kuruldu; bu test onu sinamaz, yalniz esikleri ve cikis ayarlarini sinar.\n"]

    # 1) CIKIS AYARLARI
    izler = [None, (0.15, 0.15), (0.20, 0.15), (0.20, 0.20), (0.10, 0.20), (0.0, 0.25)]
    sat = []
    for ka in (80, 85, 90, 95, 101):
        for iz in izler:
            e = kos(egit, karal=ka, iz=iz); t_ = kos(test, karal=ka, iz=iz)
            sat.append((f"kar al {'P>=' + str(ka) if ka < 101 else 'yok'} | iz {iz}", ka, iz, e, t_))
            print("cikis", sat[-1][0], e[0], t_[0])
    sec = max(sat, key=lambda x: x[3][0])
    tsira = sorted(sat, key=lambda x: -x[4][0])
    L.append("1) CIKIS AYARLARI (10 hisse, giris kurallari sitedeki gibi). Egitimde en iyiye gore siralı:")
    for ad, ka, iz, e, t_ in sorted(sat, key=lambda x: -x[3][0]):
        L.append(f"  {ad:34s} egitim x{e[0]:5.2f} (dusus %{100 * e[1]:5.1f}) | TEST x{t_[0]:5.2f} (dusus %{100 * t_[1]:5.1f}, islem {t_[2]}) | test sirasi {tsira.index((ad, ka, iz, e, t_)) + 1}/{len(sat)}")
    tv = np.array([x[4][0] for x in sat])
    L.append(f"  -> Egitimde SECILEN: {sec[0]} | testte x{sec[4][0]:.2f}, sira {tsira.index(sec) + 1}/{len(sat)}; test ortancasi x{np.median(tv):.2f}; "
             f"mevduat x{mev(test):.2f} | mevduati gecen ayar {int((tv > mev(test)).sum())}/{len(sat)}\n")

    # 2) GIRIS ESIKLERI (cikis = egitimde secilen)
    def S_yap(ust, ucuz):
        out = {}
        for t, (ix, v3r, kotu, gun, pct, o5, o20x, tb, fz, ha, vol) in ham.items():
            d = _durum2(v3r, kotu, gun, pct, o5, o20x, tb, fz, ha, ust=ust, ucuz=ucuz)
            d = np.where(vol > 5e6, d, "X")
            out[t] = pd.Series(d, index=ix).reindex(idx)
        return pd.DataFrame(out)[S.columns]
    gr = []
    for ust in (0.7, 0.8, 0.9):
        for ucuz in (10.0, 20.0, 30.0):
            S2 = S_yap(ust, ucuz)
            e = kos(egit, S2, sec[1], sec[2]); t_ = kos(test, S2, sec[1], sec[2])
            gr.append((f"temel ust %{100 - 100 * ust:.0f} | Percentile <= {ucuz:.0f}", e, t_))
            print("giris", gr[-1][0], e[0], t_[0])
    gsec = max(gr, key=lambda x: x[1][0]); gts = sorted(gr, key=lambda x: -x[2][0])
    L.append(f"2) GIRIS ESIKLERI (cikis: {sec[0]}):")
    for ad, e, t_ in sorted(gr, key=lambda x: -x[1][0]):
        L.append(f"  {ad:32s} egitim x{e[0]:5.2f} (dusus %{100 * e[1]:5.1f}) | TEST x{t_[0]:5.2f} (dusus %{100 * t_[1]:5.1f}, islem {t_[2]}) | test sirasi {gts.index((ad, e, t_)) + 1}/{len(gr)}")
    gv = np.array([x[2][0] for x in gr])
    L.append(f"  -> Egitimde SECILEN: {gsec[0]} | testte x{gsec[2][0]:.2f}, sira {gts.index(gsec) + 1}/{len(gr)}; mevduati gecen {int((gv > mev(test)).sum())}/{len(gr)}\n")

    # 3) AZ HISSE (Teoman 2-5 hisse tutuyor) - secilen ayarlar, test donemi
    L.append("3) HISSE SAYISI, test donemi (secilen cikis, sitedeki giris):")
    for N in (3, 5, 8, 10):
        t_ = kos(test, karal=sec[1], iz=sec[2], N=N)
        L.append(f"  {N:2d} hisse: TEST x{t_[0]:.2f} (dusus %{100 * t_[1]:.1f}) | mevduat x{mev(test):.2f}")
    txt = "\n".join(L)
    (R / "oos_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def oos2():
    """18 Kas aksam (Teoman: 'mevduati gecemedikce anlami yok'). (A) Ucuzluk esigi canli cikis kuraliyla;
    (B) borsa payi kurali (piyasa kar verimi / faiz) orneklem disi donemde."""
    ham = {}
    idx, C, S, PC, VR, TK, xu, m3 = panel(ham)
    egit = (idx >= "2021-01-01") & (idx <= "2024-12-31")
    test = idx >= "2025-01-01"
    r = faiz_serisi(idx)

    def mev(m):
        ii = np.flatnonzero(m)
        return float(np.prod(1 + r[ii[1:]] * np.diff(idx.values[ii]).astype("timedelta64[D]").astype(float) / 365.0))

    def kos(m, S_=S, karal=90, iz=(0.20, 0.15), N=10, w=None):
        E_, T, _ = sim(idx[m], C[m], S_[m], PC[m], VR[m], TK[m], N=N, faizli=True, iz=iz, karal=karal,
                       agirlik=None if w is None else w[m])
        v = E_["deger"]
        yil = {y: 100 * (v[v.index.year == y].iloc[-1] / (v[v.index.year == y - 1].iloc[-1] if (v.index.year == y - 1).any() else BAS) - 1)
               for y in sorted(set(v.index.year))}
        return v.iloc[-1] / BAS, (v / v.cummax() - 1).min(), len(T), yil

    def S_yap(ust, ucuz):
        out = {}
        for t, (ix, v3r, kotu, gun, pct, o5, o20x, tb, fz, ha, vol) in ham.items():
            d = _durum2(v3r, kotu, gun, pct, o5, o20x, tb, fz, ha, ust=ust, ucuz=ucuz)
            out[t] = pd.Series(np.where(vol > 5e6, d, "X"), index=ix).reindex(idx)
        return pd.DataFrame(out)[S.columns]

    xg = lambda m: xu[m].iloc[-1] / xu[m].iloc[0]
    L = ["ORNEKLEM DISI TEST 2 (18 Kas 2026 aksam)",
         f"Egitim 2021-24: mevduat x{mev(egit):.2f}, BIST100 x{xg(egit):.2f} | Test 2025-bugun: mevduat x{mev(test):.2f}, BIST100 x{xg(test):.2f}",
         "Mevduat = politika faizi, gunluk bilesik, stopajsiz (gercek mevduat daha dusuk).\n",
         "A) UCUZLUK ESIGI, canli cikis kuraliyla (kar al 90 / 95 + takip eden stop %20/%15), temel ust %20:"]
    for ka in (90, 95):
        for N in (10, 5):
            for ucuz in (20.0, 25.0, 30.0, 40.0):
                S2 = S_yap(0.8, ucuz)
                e = kos(egit, S2, ka, N=N); t_ = kos(test, S2, ka, N=N)
                L.append(f"  kar al {ka} | {N:2d} hisse | Percentile <= {ucuz:.0f}: egitim x{e[0]:5.2f} (dusus %{100 * e[1]:5.1f}) | TEST x{t_[0]:4.2f} (dusus %{100 * t_[1]:5.1f}, islem {t_[2]}) | test yillar " + " ".join(f"{y} {g:+.0f}" for y, g in t_[3].items()))
                print(L[-1])
    ep = piyasa_kar_verimi(idx)
    oran = np.nan_to_num(ep.values / r, nan=1.0)
    yo = pd.Series(oran, index=idx)
    L.append("\nB) BORSA PAYI: oran = piyasa kar verimi / politika faizi. Ayar 2021-24'te degil, 17 Kas'ta secildi (yani bu da tam orneklem disi degil).")
    L.append("   oran ortalamalari: " + " ".join(f"{y} {yo[yo.index.year == y].mean():.2f}" for y in range(2021, 2027)))
    S30 = S_yap(0.8, 30.0)
    for ad, w in [("kural yok", None), ("borsa payi = oran (en az %30)", np.clip(oran, 0.3, 1.0)),
                  ("borsa payi = oran (en az %50)", np.clip(oran, 0.5, 1.0)), ("borsa payi = 2 x oran (en az %30)", np.clip(2 * oran, 0.3, 1.0))]:
        for ad2, S_ in (("P<=20", S), ("P<=30", S30)):
            for N in (10, 5):
                e = kos(egit, S_, N=N, w=w); t_ = kos(test, S_, N=N, w=w)
                L.append(f"  {ad:36s} {ad2} {N:2d} hisse: egitim x{e[0]:5.2f} (dusus %{100 * e[1]:5.1f}) | TEST x{t_[0]:4.2f} (dusus %{100 * t_[1]:5.1f}) | test yillar " + " ".join(f"{y} {g:+.0f}" for y, g in t_[3].items())
                         + ("" if w is None else f" | test ort. borsa payi %{100 * w[test].mean():.0f}"))
                print(L[-1])
    txt = "\n".join(L)
    (R / "oos2_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def secim_test():
    """20 Kas (Teoman): 'Firsatlar listesinden en yuksek hacimli / en buyuk sirketleri 3-4-5 tane alsin, guvenli liman
    olarak. Yillari ayri ayri test et.' Siralama yontemleri karsilastirmasi; cikis canli kural (kar al 90 + iz 20/15)."""
    ham = {}
    idx, C, S, PC, VR, TK, xu, m3 = panel(ham)
    r = faiz_serisi(idx)
    # piyasa degeri ~ duzeltmeli kapanis x son odenmis sermaye
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    O = B.olaylar(G, D.m3())
    ser = O.dropna(subset=["sermaye_son"]).groupby("t")["sermaye_son"].last()
    MC = C.copy() * np.nan
    for t in C.columns:
        if t in ser.index:
            MC[t] = C[t] * float(ser[t])
    VOL = pd.DataFrame({t: pd.Series(ham[t][10], index=ham[t][0]).reindex(idx) for t in C.columns if t in ham})[C.columns]
    yontem = {"site sirasi (✓✓ once, sonra temel)": None,
              "en buyuk sirket (piyasa degeri)": MC.values,
              "en yuksek hacim (20g TL)": VOL.values,
              "en yuksek temel puan": VR.values}
    yillar = [y for y in range(2021, 2027)]
    def mev(m):
        ii = np.flatnonzero(m)
        return float(np.prod(1 + r[ii[1:]] * np.diff(idx.values[ii]).astype("timedelta64[D]").astype(float) / 365.0))
    def kos(m, sira, N, al_set=None):
        si = None if sira is None else sira[m]
        E_, T, _ = sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, faizli=True, iz=(0.20, 0.15), karal=90, sira=si, al_set=al_set)
        v = E_["deger"]
        return v.iloc[-1] / BAS, (v / v.cummax() - 1).min()
    rng = np.random.default_rng(11)
    L = ["HISSE SECIM YONTEMI TESTI (20 Kas 2026). AL (✓ ya da ✓✓) listesinden hangi hisseler alinsin?",
         "Her yil 100.000 TL ile AYRI baslar (yil sonunda acik hisseler o gunku fiyatla). Cikis: kar al 90 + takip eden stop %20/%15 + bilanco bozulursa.",
         "Bos para faizde. Piyasa degeri = fiyat x son sermaye (yaklasik). Rastgele = 30 kosunun ortancasi.\n"]
    bas = "  " + f"{'':40s}" + "".join(f"{y:>8d}" for y in yillar) + "   2021-26 tek parca"
    for N in (3, 5, 10):
        L.append(f"== {N} hisse ==")
        L.append(bas)
        tum = idx >= "2021-01-01"
        L.append("  " + f"{'BIST100':40s}" + "".join(f"{100 * (xu[idx.year == y].iloc[-1] / xu[idx.year == y].iloc[0] - 1):+8.0f}" for y in yillar) + f"   x{xu[tum].iloc[-1] / xu[tum].iloc[0]:.2f}")
        L.append("  " + f"{'mevduat (stopajsiz)':40s}" + "".join(f"{100 * (mev(idx.year == y) - 1):+8.0f}" for y in yillar) + f"   x{mev(tum):.2f}")
        for ad, sira in list(yontem.items()) + [("RASTGELE (ortanca)", "rnd")]:
            satir = []
            for m in [idx.year == y for y in yillar] + [tum]:
                if isinstance(sira, str):
                    v = np.median([kos(m, rng.random(C.shape), N)[0] for _ in range(30)])
                else:
                    v = kos(m, sira, N)[0]
                satir.append(v)
            dd = "" if isinstance(sira, str) else f" (dusus %{100 * kos(tum, sira, N)[1]:.0f})"
            L.append("  " + f"{ad:40s}" + "".join(f"{100 * (v - 1):+8.0f}" for v in satir[:-1]) + f"   x{satir[-1]:.2f}{dd}")
            print(L[-1])
        # Firsatlarin tumu (teknik donmemis dahil), en buyuk sirket
        satir = [kos(m, MC.values, N, al_set={"AL cift tik", "AL tek tik", "BEKLE TEKNIK"})[0] for m in [idx.year == y for y in yillar] + [tum]]
        L.append("  " + f"{'Firsatlar TUMU (faz sartsiz), en buyuk':40s}" + "".join(f"{100 * (v - 1):+8.0f}" for v in satir[:-1]) + f"   x{satir[-1]:.2f}")
        L.append("")
    txt = "\n".join(L)
    (R / "secim_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)
