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


def panel():
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


def sim(idx, C, S, PC, VR, TK, N=10, faizli=True, sadece_cift=False, iz=None, karal=80):
    """iz=(aktif, geri): fiyat girisin aktif kadar ustune ciktiktan sonra, girişten beri gorulen en yuksek
    kapanisin 'geri' kadar altina inerse sat (takip eden stop). karal: kar al Percentile esigi."""
    r = faiz_serisi(idx)
    cash = BAS
    poz = {}   # t -> (adet, giris_fiyat, giris_tarih)
    bek_al, bek_sat = [], []
    egri, isl = [], []
    Cv = C.values; Sv = S.values; PCv = PC.values; VRv = VR.values; TKv = TK.values
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
        bos = N - len(poz) + len(bek_sat)
        if bos > 0:
            ad = []
            for t, j in col.items():
                if t in poz:
                    continue
                s_ = Sv[i, j]
                if s_ == "AL cift tik" or (s_ == "AL tek tik" and not sadece_cift):
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
