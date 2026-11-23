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
# 23 Kas: 2013-2020 yaklasik etkin TCMB fonlama faizi (2016-2018 gec likidite penceresi donemi etkin fonlama, yaklasik)
FAIZ_ESKI = [("2013-01-01", 6.0), ("2014-01-29", 10.0), ("2014-05-23", 9.5), ("2014-06-25", 8.75), ("2014-07-18", 8.25),
             ("2015-01-21", 7.75), ("2015-02-25", 7.5), ("2015-09-01", 8.8), ("2016-06-01", 8.3), ("2017-01-11", 9.5),
             ("2017-03-01", 11.0), ("2017-04-27", 12.0), ("2017-12-15", 12.75), ("2018-05-24", 16.5), ("2018-06-08", 17.75),
             ("2018-09-14", 24.0), ("2019-07-26", 19.75), ("2019-09-13", 16.5), ("2019-10-25", 14.0), ("2019-12-13", 12.0),
             ("2020-01-17", 11.25), ("2020-02-20", 10.75), ("2020-03-18", 9.75), ("2020-04-23", 8.75), ("2020-05-22", 8.25)]
FAIZ = FAIZ_ESKI + [("2020-09-24", 10.25), ("2020-11-19", 15.0), ("2020-12-24", 17.0), ("2021-03-18", 19.0), ("2021-09-23", 18.0),
        ("2021-10-21", 16.0), ("2021-11-18", 15.0), ("2021-12-16", 14.0), ("2022-08-18", 13.0), ("2022-09-22", 12.0),
        ("2022-10-20", 10.5), ("2022-11-24", 9.0), ("2023-02-23", 8.5), ("2023-06-22", 15.0), ("2023-07-20", 17.5),
        ("2023-08-24", 25.0), ("2023-09-21", 30.0), ("2023-10-26", 35.0), ("2023-11-23", 40.0), ("2023-12-21", 42.5),
        ("2024-01-25", 45.0), ("2024-03-21", 50.0), ("2024-12-26", 47.5), ("2025-01-23", 45.0), ("2025-04-17", 46.0),
        ("2025-07-24", 43.0), ("2025-09-11", 40.5), ("2025-10-23", 39.5), ("2025-12-11", 38.0), ("2026-01-22", 37.0),
        ("2026-10-22", 36.0)]


OLAY_EK = None  # 22 Kas: olaylara ek alan (parasal kazanc tahmini)


def faiz_serisi(idx):
    s = pd.Series({pd.Timestamp(d): v for d, v in FAIZ}).sort_index()
    return s.reindex(idx.union(s.index)).ffill().reindex(idx).fillna(10.25).values / 100.0


UZUN = False  # 23 Kas: 2014'ten baslayan uzun test


def _xu_duzelt(xu):
    """BIST100 27 Tem 2020'de 100'e bolundu; Yahoo serisinde kirilma varsa onceki kismi olcekle."""
    r = xu / xu.shift(1)
    k = r[r < 0.05]
    for t in k.index:
        xu.loc[xu.index < t] = xu.loc[xu.index < t] / 100.0
    return xu


def panel(ham: dict | None = None):
    if UZUN:
        from . import temel as _T
        G = _T.gecmis_birlesik()
    else:
        G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    m3 = D.m3()
    O = B.olaylar(G, m3)
    if OLAY_EK is not None:
        O = OLAY_EK(O, G)
    px = D.prices(sorted(O["t"].unique()), start="2013-01-01" if UZUN else D.START)
    xu = _xu_duzelt(D.xu100(start="2013-01-01" if UZUN else D.START))
    P = puanlar(O, px)
    idx = xu.index[xu.index >= pd.Timestamp("2014-06-01" if UZUN else "2020-09-01")]
    m3g = m3.copy(); m3g.index = m3g.index + pd.offsets.MonthBegin(1)
    m3_ref = float(m3[m3.index <= pd.Timestamp("2021-01-01")].iloc[-1])
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
        esik = 5e6 * np.minimum(1.0, m3g.reindex(ix, method="ffill").values / m3_ref) if UZUN else 5e6  # likidite esigi M3 ile (2021 oncesi)
        d = np.where(vol > esik, d, np.where(np.char.startswith(d.astype(str), "AL"), "AL likit degil", d))
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


def deger_test():
    """22 Kas (Teoman: 'net parasal pozisyon net kari bozuyor, asil F/K'). Temel puandaki deger bileseninde net kar/PD
    yerine faaliyet kari / firma degeri (FD = PD + net borc). Parasal kazanc, kur farki ve faiz faaliyet karinin altinda."""
    from . import firsat_bt as FB
    L = ["DEGER OLCUSU TESTI (22 Kas 2026): net kar mi, faaliyet kari mi?",
         "kar      = (net kar / PD) + PD/DD   [CANLI]",
         "faal     = (esas faaliyet kari / FD) + PD/DD       FD = piyasa degeri + net borc",
         "kar+faal = ucu birlikte",
         "favok    = (FAVOK / FD) + PD/DD",
         "faal_tek = yalniz faaliyet kari / FD",
         "Cikis canli kural (kar al 90 + takip eden stop %20/%15 + bilanco bozulursa). Egitim 2021-24, test 2025-bugun (sifirdan).\n"]
    for ad in ("kar", "faal", "kar+faal", "favok", "faal_tek"):
        FB.DEGER = ad
        idx, C, S, PC, VR, TK, xu, m3 = panel()
        r = faiz_serisi(idx)
        egit = (idx >= "2021-01-01") & (idx <= "2024-12-31"); test = idx >= "2025-01-01"; tum = idx >= "2021-01-01"
        def mev(m):
            ii = np.flatnonzero(m)
            return float(np.prod(1 + r[ii[1:]] * np.diff(idx.values[ii]).astype("timedelta64[D]").astype(float) / 365.0))
        if ad == "kar":
            L.append(f"mevduat: egitim x{mev(egit):.2f}, test x{mev(test):.2f}, tum x{mev(tum):.2f} | BIST100 test x{xu[test].iloc[-1] / xu[test].iloc[0]:.2f}\n")
        al_gun = ((S.values == "AL cift tik") | (S.values == "AL tek tik")).sum(axis=1)
        for N in (10, 5):
            o = []
            for m in (egit, test, tum):
                E_, T, _ = sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, iz=(0.20, 0.15), karal=90)
                v = E_["deger"]
                o.append((v.iloc[-1] / BAS, (v / v.cummax() - 1).min(), len(T), T.getiri.median() if len(T) else np.nan))
            yil = []
            for y in range(2022, 2027):
                m = idx.year == y
                E_, T, _ = sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, iz=(0.20, 0.15), karal=90)
                yil.append(100 * (E_["deger"].iloc[-1] / BAS - 1))
            L.append(f"{ad:9s} {N:2d} hisse | egitim x{o[0][0]:5.2f} (dusus %{100 * o[0][1]:4.0f}) | TEST x{o[1][0]:4.2f} (dusus %{100 * o[1][1]:4.0f}, islem {o[1][2]}, medyan %{o[1][3]:+.1f}) | "
                     f"tum x{o[2][0]:5.2f} | yillar " + " ".join(f"{y} {g:+.0f}" for y, g in zip(range(2022, 2027), yil)) + f" | gunluk ort. AL {al_gun[tum].mean():.0f}")
            print(L[-1])
    txt = "\n".join(L)
    (R / "deger_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def nakit_test():
    """22 Kas: serbest nakit verimi (SNA/FD), kar nakit kalitesi ((faaliyet nakdi - net kar) / varlik), ROIC (FAVOK / (ozkaynak + net borc))."""
    from . import firsat_bt as FB
    L = ["NAKIT / ROIC TESTI (22 Kas 2026). Taban = canli (deger: FAVOK/FD + PD/DD; kalite: F-skoru + ROE).",
         "Cikis canli kural. Egitim 2021-24, test 2025-bugun (sifirdan). 10 ve 5 hisse.\n"]
    for ad, dg, kl in (("TABAN (canli)", "favok", "canli"), ("+ serbest nakit verimi (deger)", "favok+sna", "canli"),
                       ("ROE yerine ROIC (kalite)", "favok", "roic"), ("+ nakit kalitesi (kalite)", "favok", "nakit"),
                       ("ROIC + nakit kalitesi", "favok", "roic+nakit"), ("hepsi", "favok+sna", "roic+nakit")):
        FB.DEGER, FB.KALITE = dg, kl
        idx, C, S, PC, VR, TK, xu, m3 = panel()
        r = faiz_serisi(idx)
        egit = (idx >= "2021-01-01") & (idx <= "2024-12-31"); test = idx >= "2025-01-01"; tum = idx >= "2021-01-01"
        if ad.startswith("TABAN"):
            def mev(m):
                ii = np.flatnonzero(m)
                return float(np.prod(1 + r[ii[1:]] * np.diff(idx.values[ii]).astype("timedelta64[D]").astype(float) / 365.0))
            L.append(f"mevduat: egitim x{mev(egit):.2f}, test x{mev(test):.2f} | BIST100 test x{xu[test].iloc[-1] / xu[test].iloc[0]:.2f}\n")
        for N in (10, 5):
            o = []
            for m in (egit, test, tum):
                E_, T, _ = sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, iz=(0.20, 0.15), karal=90)
                v = E_["deger"]
                o.append((v.iloc[-1] / BAS, (v / v.cummax() - 1).min(), len(T), T.getiri.median() if len(T) else np.nan))
            yil = []
            for y in range(2022, 2027):
                m = idx.year == y
                E_, T, _ = sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, iz=(0.20, 0.15), karal=90)
                yil.append(100 * (E_["deger"].iloc[-1] / BAS - 1))
            L.append(f"{ad:32s} {N:2d} hisse | egitim x{o[0][0]:5.2f} (dusus %{100 * o[0][1]:4.0f}) | TEST x{o[1][0]:4.2f} (dusus %{100 * o[1][1]:4.0f}, islem {o[1][2]}, medyan %{o[1][3]:+.1f}) | "
                     f"tum x{o[2][0]:5.2f} | yillar " + " ".join(f"{y} {g:+.0f}" for y, g in zip(range(2022, 2027), yil)))
            print(L[-1])
    FB.DEGER, FB.KALITE = "favok", "canli"
    txt = "\n".join(L)
    (R / "nakit_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def denetim():
    """22 Kas (Teoman: 'testlerde hata yapmis olabilirsin, emin ol'). Bagimsiz denetim:
    1) her olcunun kapsami ve ornek degerler (elle kontrol icin),
    2) TEK OLCU olay testi: her bilanco aciklamasindan sonra 63/126 islem gunu, piyasa ortancasina gore fazla getiri;
       olcunun donem ici dilimine (5'li) gore. Binlerce olay -> portfoy simulasyonundan cok daha az gurultulu.
    3) portfoy: AL listesinden RASTGELE secimle 25 kosu (tek bir secim sirasinin sansini ortadan kaldirir)."""
    from . import firsat_bt as FB
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    O = B.olaylar(G, D.m3())
    px = D.prices(sorted(O["t"].unique()))
    FB.HAM_DONDUR = True
    A = FB.puanlar(O, px)
    FB.HAM_DONDUR = False
    L = ["DENETIM (22 Kas 2026)\n", "1) KAPSAM (dolu oran, sanayi olaylari):"]
    olc = ["kaz_get", "fav_get", "fv_get", "sna_get", "roic", "roe", "nakit_kal", "pddd", "F"]
    A["yil"] = pd.to_datetime(A["giris"]).dt.year
    for f in olc:
        L.append(f"  {f:10s} " + " ".join(f"{y}:%{100 * A.loc[A.yil == y, f].notna().mean():.0f}" for y in sorted(A.yil.unique())))
    L.append("\n   ornek (son donem):")
    for t in ("TTKOM", "BIMAS", "ARCLK", "THYAO", "TUPRS", "ASELS"):
        x = A[A.t == t].sort_values("giris").tail(1)
        if len(x):
            x = x.iloc[0]
            L.append(f"  {t} {x['donem']} giris {str(x['giris'])[:10]} | F/K={1 / x['kaz_get'] if x['kaz_get'] else np.nan:.1f} FD/FAVOK={1 / x['fav_get'] if x['fav_get'] else np.nan:.1f} "
                     f"PD/DD={x['pddd']:.2f} ROIC={x['roic']:.2f} ROE={x['roe']:.2f} SNA/FD={x['sna_get']:.3f} nakit_kal={x['nakit_kal']:.3f} netborc={(x.get('netborc') or np.nan) / 1e9:.1f}mr")
    # 2) olay testi
    hepsi = {t: df["close"] for t, df in px.items()}
    Cx = pd.DataFrame(hepsi).sort_index()
    def ileri(h):
        r = Cx.shift(-h) / Cx - 1
        return r.sub(r.median(axis=1), axis=0)
    F63, F126 = ileri(63), ileri(126)
    def fg(F, t, g):
        try:
            return F.at[pd.Timestamp(g), t]
        except KeyError:
            return np.nan
    A["f63"] = [fg(F63, t, g) for t, g in zip(A.t, A.giris)]
    A["f126"] = [fg(F126, t, g) for t, g in zip(A.t, A.giris)]
    L.append("\n2) TEK OLCU OLAY TESTI: donem ici 5 dilim (5 = en ucuz/en iyi). Deger: 126 gun fazla getiri ortalamasi % (kirpik %5) | ortanca. Egitim <2025, test >=2025 (test 126g icin 2025 ortasina kadar olaylar).")
    yon = {"pddd": -1}
    for f in olc:
        for ad, m in (("egitim", A.yil < 2025), ("TEST", A.yil >= 2025)):
            a = A[m & A[f].notna() & A.f126.notna()].copy()
            if len(a) < 100:
                continue
            a["dl"] = (yon.get(f, 1) * a[f]).groupby(a["donem"]).rank(pct=True).mul(5).clip(upper=4.999).astype(int) + 1
            def km(v):
                v = v.clip(v.quantile(0.05), v.quantile(0.95)); return 100 * v.mean()
            st = a.groupby("dl")["f126"].agg([km, "median", "count"])
            fark = st.loc[5, "km"] - st.loc[1, "km"]
            # t istatistigi (5. dilim - 1. dilim, kirpik)
            v5, v1 = a.loc[a.dl == 5, "f126"], a.loc[a.dl == 1, "f126"]
            v5 = v5.clip(v5.quantile(.05), v5.quantile(.95)); v1 = v1.clip(v1.quantile(.05), v1.quantile(.95))
            tst = (v5.mean() - v1.mean()) / np.sqrt(v5.var() / len(v5) + v1.var() / len(v1))
            L.append(f"  {f:10s} {ad:6s} n={len(a):5d} | " + " ".join(f"D{i} {st.loc[i, 'km']:+5.1f}" for i in range(1, 6))
                     + f" | D5-D1 {fark:+5.1f} (t={tst:+.1f}) | ortanca D1 {100 * st.loc[1, 'median']:+.1f} D5 {100 * st.loc[5, 'median']:+.1f}")
        print(L[-1])
    # 3) rastgele secimli portfoy
    L.append("\n3) PORTFOY, AL listesinden RASTGELE secim, 25 kosu ortancasi (cikis canli). Test 2025-bugun, 10 ve 5 hisse:")
    rng = np.random.default_rng(5)
    for ad, dg, kl in (("kar (eski canli)", "kar", "canli"), ("favok (YENI canli)", "favok", "canli"), ("faal", "faal", "canli"),
                       ("favok+sna", "favok+sna", "canli"), ("roic", "favok", "roic"), ("nakit", "favok", "nakit")):
        FB.DEGER, FB.KALITE = dg, kl
        idx, C, S, PC, VR, TK, xu, m3 = panel()
        for per, m in (("egitim", (idx >= "2021-01-01") & (idx <= "2024-12-31")), ("TEST", idx >= "2025-01-01")):
            for N in (10, 5):
                v = []
                for _ in range(25):
                    E_, T, _ = sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, iz=(0.20, 0.15), karal=90, sira=rng.random(C[m].shape))
                    v.append(E_["deger"].iloc[-1] / BAS)
                v = np.array(v)
                L.append(f"  {ad:20s} {per:6s} {N:2d} hisse: ortanca x{np.median(v):.2f} (alt %25 x{np.quantile(v, .25):.2f}, ust %25 x{np.quantile(v, .75):.2f})")
                print(L[-1])
    FB.DEGER, FB.KALITE = "favok", "canli"
    txt = "\n".join(L)
    (R / "denetim_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def _pk_tablo():
    """Her (hisse, ceyrek) icin tahmini net parasal pozisyon kazanci / toplam varlik.
    Kazanc ~ ortalama net parasal yukumluluk x ceyrek TUFE. Net parasal yukumluluk = parasal yukumlulukler - parasal varliklar.
    pk  = tum parasal kalemler (arkadasin yontemi: net kardan tamamen cikar)
    pk2 = finansal borclar haric (dengeli: finansal borcun eriyen kismi zaten sisen faiz giderini karsiliyor)."""
    P = json.loads(gzip.decompress((R / "gecmis_pk.json.gz").read_bytes()))
    tf = D.tufe()
    def pi(y, m):
        a = tf.get(pd.Timestamp(y, m, 1)); y0, m0 = (y, m - 3) if m > 3 else (y - 1, m + 9)
        b = tf.get(pd.Timestamp(y0, m0, 1))
        return a / b - 1 if a and b else None
    out = {}
    for t, g in P.items():
        if g["grup"] != "XI_29":
            continue
        rat = {}
        for k, v in g["tab"].items():
            y, m = map(int, k.split("/"))
            z = lambda c: v.get(c) or 0.0
            va = v.get("1BL")
            if not va or va <= 0 or v.get("2A") is None:
                continue
            pv = sum(z(c) for c in ("1AA", "1AB", "1AC", "1AD", "1AE", "1B", "1BA", "1BB", "1BC"))
            py = z("2A") + z("2B") - z("2AAGAC") - z("2BBBA") - z("2BG") - z("2AAGCA") - z("2BDA")
            fb = z("2AA") + z("2BA")
            rat[(y, m)] = ((py - pv) / va, (py - fb - pv) / va, va)
        for (y, m), (r1, r2, va) in rat.items():
            onc = (y, m - 3) if m > 3 else (y - 1, 12)
            p = pi(y, m)
            if p is None:
                continue
            a1, a2 = (r1, r2) if onc not in rat else ((r1 + rat[onc][0]) / 2, (r2 + rat[onc][1]) / 2)
            out[(t, y, m)] = (a1 * p, a2 * p, va)
    return out


DENEMELER = (("klasik F/K (eski canli)", "kar", 1.0), ("parasal kazanc cikmis F/K", "kar_pk", 1.0), ("dengeli parasal F/K", "kar_pk2", 1.0),
             ("asil F/K FAVOK/FD (CANLI)", "favok", 1.0), ("deger YOK (yalniz hareket+kalite)", "yok", 0.0),
             ("deger = yalniz PD/DD", "pddd", 1.0), ("asil F/K, deger agirligi 2 kat", "favok", 2.0))


def parasal_test():
    """22 Kas (Teoman): 'parasal kazanci cikarip test edelim; F/K'ya ne kadar agirlik veriyoruz, sonucu ne kadar etkiliyor?'"""
    from . import firsat_bt as FB
    global OLAY_EK
    PK = _pk_tablo()
    L = ["PARASAL KAZANC VE DEGER AGIRLIGI TESTI (22 Kas 2026)\n",
         "1) TAHMIN KONTROLU: tahmini parasal kazanc (yil ici kumulatif, milyar TL, Is Yatirim'in o donem birimiyle) vs aciklanan:"]
    gercek = {("TTKOM", 2025, 3): 7.75, ("TTKOM", 2025, 6): 12.40, ("TTKOM", 2025, 9): 16.91, ("TTKOM", 2025, 12): 19.65,
              ("TTKOM", 2026, 3): 13.99, ("TTKOM", 2026, 9): 46.8, ("BIMAS", 2024, 12): 28.3, ("BIMAS", 2025, 12): 18.2}
    for (t, y, m), gv in gercek.items():
        tah = sum(PK[(t, y, mm)][0] * PK[(t, y, mm)][2] for mm in range(3, m + 1, 3) if (t, y, mm) in PK)
        tah2 = sum(PK[(t, y, mm)][1] * PK[(t, y, mm)][2] for mm in range(3, m + 1, 3) if (t, y, mm) in PK)
        L.append(f"  {t} {y}/{m}: aciklanan {gv:6.1f} | tahmin (tum) {tah / 1e9:6.1f} | tahmin (fin. borc haric) {tah2 / 1e9:6.1f}")
    print("\n".join(L))

    def ek(O, G):
        O = O.copy()
        p1, p2 = [], []
        for t, d in zip(O["t"], O["donem"]):
            y, m = map(int, str(d).split("/"))
            if (y, m) < (2023, 12):
                p1.append(0.0); p2.append(0.0); continue
            s1 = s2 = 0.0; ok = True
            for i in range(4):
                yy, mm = (y, m - 3 * i) if m - 3 * i > 0 else (y - 1, m - 3 * i + 12)
                x = PK.get((t, yy, mm))
                va_eski = (G.get(t, {}).get("tab", {}).get(f"{yy}/{mm}", {}) or {}).get("1BL")
                if x is None or not va_eski:
                    ok = False; break
                s1 += x[0] * va_eski; s2 += x[1] * va_eski
            p1.append(s1 if ok else np.nan); p2.append(s2 if ok else np.nan)
        O["pk_ttm"], O["pk2_ttm"] = p1, p2
        return O
    OLAY_EK = ek
    # 2) tek olcu olay testi (kar / kar_pk / kar_pk2 / favok) - yalniz 2024+ olaylari (parasal kazanc o zaman var)
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    O = ek(B.olaylar(G, D.m3()), G)
    L.append(f"\n   olaylarda parasal kazanc tahmini dolu: %{100 * O.loc[O.donem >= '2023/12', 'pk_ttm'].notna().mean():.0f} (2023/12 sonrasi)")
    sa = O[(O.donem >= "2024/03") & O.pk_ttm.notna() & O.nk_ttm.notna()]
    oran = (0.75 * sa.pk_ttm / sa.nk_ttm.abs()).clip(-5, 5)
    L.append(f"   parasal kazanc (vergi sonrasi) / |net kar| ortancasi: %{100 * oran.median():.0f}; net kari parasal kazanctan buyuk olmayan (yani kazanc cikinca zarara donen) olay orani %{100 * ((sa.nk_ttm - 0.75 * sa.pk_ttm) < 0).mean():.0f} (ham net kar < 0 orani %{100 * (sa.nk_ttm < 0).mean():.0f})")
    px = D.prices(sorted(O["t"].unique()))
    FB.HAM_DONDUR = True
    A = FB.puanlar(O, px)
    FB.HAM_DONDUR = False
    Cx = pd.DataFrame({t: df["close"] for t, df in px.items()}).sort_index()
    r = Cx.shift(-126) / Cx - 1
    F126 = r.sub(r.median(axis=1), axis=0)
    A["f126"] = [F126.at[pd.Timestamp(g), t] if pd.Timestamp(g) in F126.index and t in F126.columns else np.nan for t, g in zip(A.t, A.giris)]
    A["yil"] = pd.to_datetime(A["giris"]).dt.year
    L.append("\n2) TEK OLCU OLAY TESTI, 2024 ve sonrasi bilancolar (126 gun, piyasa ortancasina gore fazla getiri %, kirpik):")
    A["birlesik"] = pd.concat([A[c].groupby(A["donem"]).rank(pct=True) for c in ("fav_get", "kaz_pk")], axis=1).mean(axis=1)
    for f in ("kaz_get", "kaz_pk", "kaz_pk2", "fav_get", "birlesik"):
        a = A[(A.yil >= 2024) & A[f].notna() & A.f126.notna()].copy()
        a["dl"] = a[f].groupby(a["donem"]).rank(pct=True).mul(5).clip(upper=4.999).astype(int) + 1
        def km(v):
            v = v.clip(v.quantile(0.05), v.quantile(0.95)); return 100 * v.mean()
        st = a.groupby("dl")["f126"].agg(km)
        v5, v1 = a.loc[a.dl == 5, "f126"], a.loc[a.dl == 1, "f126"]
        v5 = v5.clip(v5.quantile(.05), v5.quantile(.95)); v1 = v1.clip(v1.quantile(.05), v1.quantile(.95))
        tst = (v5.mean() - v1.mean()) / np.sqrt(v5.var() / len(v5) + v1.var() / len(v1))
        ad = {"kaz_get": "net kar/PD (klasik F/K)", "kaz_pk": "parasal kazanc cikmis", "kaz_pk2": "dengeli (fin. borc haric)", "fav_get": "FAVOK/FD (asil F/K)", "birlesik": "FAVOK/FD + parasalsiz F/K"}[f]
        L.append(f"  {ad:28s} n={len(a):5d} | " + " ".join(f"D{i} {st.loc[i]:+5.1f}" for i in range(1, 6)) + f" | D5-D1 {st.loc[5] - st.loc[1]:+5.1f} (t={tst:+.1f})")
    print("\n".join(L[-5:]))
    # 3) portfoy: rastgele secim, 25 kosu; yil yil
    L.append("\n3) PORTFOY (AL listesinden rastgele secim, ortanca; cikis canli). Egitim 2021-24 / TEST 2025-bugun / yillar (her yil sifirdan, 5 hisse):")
    rng = np.random.default_rng(7)
    for ad, dg, w in DENEMELER:
        FB.DEGER, FB.DEGER_AGIRLIK = dg, w
        idx, C, S, PC, VR, TK, xu, m3 = panel()
        sat = []
        for per, m in (("egitim", (idx >= "2021-01-01") & (idx <= "2024-12-31")), ("TEST", idx >= "2025-01-01")):
            for N in (10, 5):
                v = [sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, iz=(0.20, 0.15), karal=90, sira=rng.random(C[m].shape))[0]["deger"].iloc[-1] / BAS for _ in range(25)]
                sat.append(f"{per} {N}h x{np.median(v):.2f}")
        yil = []
        for y in (2022, 2023, 2024, 2025, 2026):
            m = idx.year == y
            v = [sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=5, iz=(0.20, 0.15), karal=90, sira=rng.random(C[m].shape))[0]["deger"].iloc[-1] / BAS for _ in range(15)]
            yil.append(f"{y} {100 * (np.median(v) - 1):+.0f}")
        L.append(f"  {ad:36s} " + " | ".join(sat) + " || " + " ".join(yil))
        print(L[-1])
    FB.DEGER, FB.DEGER_AGIRLIK = "favok", 1.0
    OLAY_EK = None
    txt = "\n".join(L)
    (R / "parasal_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def geri_alim_test():
    """22 Kas (Teoman: 'pay geri alimi yapan sirket degerlenecegini dusunuyordur; onemli bir yer etmeli').
    KAP 'Paylarin Geri Alinmasina Iliskin Bildirim' (gerceklesen alimlar) 2021-bugun."""
    from . import kap
    from . import firsat_bt as FB
    g = kap.geri_alim_topla(bas="2021-01-01", gun=3, butce_dk=110)
    g = g[g["konu"].str.contains("Geri Alınmasına", na=False)].copy()
    g["t"] = pd.to_datetime(g["tarih"].str[:10], format="%d.%m.%Y", errors="coerce")
    g["hisse"] = g["hisse"].fillna("").str.split(",").str[0].str.strip()
    g = g.dropna(subset=["t"])
    g = g[g.hisse != ""]
    L = ["PAY GERI ALIMI TESTI (22 Kas 2026)", f"KAP gerceklesen geri alim bildirimi: {len(g)} adet, {g.hisse.nunique()} sirket, {g.t.min():%Y-%m} .. {g.t.max():%Y-%m}",
         "yillara gore bildirim / sirket: " + " ".join(f"{y}:{len(x)}/{x.hisse.nunique()}" for y, x in g.groupby(g.t.dt.year)), ""]
    px = D.prices(sorted(g.hisse.unique().tolist() + ["THYAO"]))
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    hep = D.prices(sorted(G.keys()))
    Cx = pd.DataFrame({t: df["close"] for t, df in hep.items()}).sort_index()
    gun = Cx.index
    def fazla(h):
        r = Cx.shift(-h) / Cx - 1
        return r.sub(r.median(axis=1), axis=0)
    F = {h: fazla(h) for h in (5, 21, 63, 126)}
    # yeni geri alim dalgasi: sirketin 90 gun once bildirimi yoksa
    g = g.sort_values("t")
    ilk = []
    son = {}
    for _, r in g.iterrows():
        if r.hisse not in son or (r.t - son[r.hisse]).days > 90:
            ilk.append(r)
        son[r.hisse] = r.t
    E = pd.DataFrame(ilk)
    def giris(t):
        j = gun.searchsorted(t, side="right")  # bildirim aksam: ertesi gun kapanis
        return gun[j] if j < len(gun) else None
    E["giris"] = E.t.map(giris)
    E = E.dropna(subset=["giris"])
    for h in (5, 21, 63, 126):
        E[f"f{h}"] = [F[h].at[gi, t] if t in F[h].columns else np.nan for t, gi in zip(E.hisse, E.giris)]
    def ozet(x, ad):
        o = []
        for h in (5, 21, 63, 126):
            v = x[f"f{h}"].dropna()
            if len(v) < 10:
                o.append(f"{h}g n<10"); continue
            k = v.clip(v.quantile(.05), v.quantile(.95))
            o.append(f"{h}g ort %{100 * k.mean():+.1f} ortanca %{100 * v.median():+.1f} kazanan %{100 * (v > 0).mean():.0f} (n={len(v)}, t={k.mean() / (k.std() / np.sqrt(len(k))):+.1f})")
        L.append(f"  {ad:28s} " + " | ".join(o))
    L.append("1) YENI GERI ALIM DALGASI (90 gun sessizlikten sonra ilk bildirim), ertesi gun kapanistan, piyasa ortancasina gore fazla getiri:")
    ozet(E, "tum")
    for y, x in E.groupby(E.giris.dt.year):
        ozet(x, str(y))
    sub = E[(E.giris >= "2023-02-06") & (E.giris <= "2023-03-31")]
    ozet(sub, "Subat-Mart 2023 (deprem)")
    ozet(E[~E.index.isin(sub.index)], "deprem donemi haric")
    # 2) devam eden geri alim (son 30 gunde bildirimi olan) - gunluk portfoy, 21 gun ileri
    L.append("\n2) SURDUREN ALICI: bildirim sayisi (bir dalgadaki toplam) yuksek olanlar vs tek-iki kez alanlar (126g):")
    cnt = []
    for _, r in E.iterrows():
        cnt.append(((g.hisse == r.hisse) & (g.t >= r.t) & (g.t <= r.t + pd.Timedelta(days=60))).sum())
    E["n60"] = cnt
    ozet(E[E.n60 >= 10], "60 gunde 10+ bildirim")
    ozet(E[(E.n60 >= 3) & (E.n60 < 10)], "60 gunde 3-9")
    ozet(E[E.n60 < 3], "60 gunde 1-2")
    # 3) sistemle birlikte: AL listesinde, son 30 gunde geri alim yapanlari one alan rastgele portfoy
    L.append("\n3) PORTFOY: AL listesinden secimde son 30 gunde geri alim yapani ONE AL (yoksa rastgele). 25 kosu ortancasi, cikis canli:")
    idx, C, S, PC, VR, TK, xu, m3 = panel()
    GA = pd.DataFrame(0.0, index=idx, columns=C.columns)
    for _, r in g.iterrows():
        if r.hisse in GA.columns:
            m = (idx > r.t) & (idx <= r.t + pd.Timedelta(days=30))
            GA.loc[m, r.hisse] = 1.0
    al = (S.values == "AL cift tik") | (S.values == "AL tek tik")
    L.append(f"   AL gunlerinde geri alim yapan orani: %{100 * (GA.values[al] > 0).mean():.1f}")
    rng = np.random.default_rng(3)
    for per, m in (("2021-24", (idx >= "2021-01-01") & (idx <= "2024-12-31")), ("2025-bugun", idx >= "2025-01-01"), ("2024", idx.year == 2024), ("2025", idx.year == 2025), ("2026", idx.year == 2026)):
        for N in (5, 10):
            a = [sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, iz=(0.20, 0.15), karal=90, sira=rng.random(C[m].shape))[0]["deger"].iloc[-1] / BAS for _ in range(25)]
            b = [sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, iz=(0.20, 0.15), karal=90, sira=GA.values[m] + 0.5 * rng.random(C[m].shape))[0]["deger"].iloc[-1] / BAS for _ in range(25)]
            L.append(f"   {per:10s} {N:2d} hisse: rastgele x{np.median(a):.2f} | geri alim yapani one al x{np.median(b):.2f}")
            print(L[-1])
    txt = "\n".join(L)
    (R / "geri_alim_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def _pas_yon(ozet: str) -> str:
    """Ozetten alim/satim: 'al' / 'sat' / '?'."""
    o = ozet.lower().replace("İ", "i").replace("ı", "i")
    sat = any(k in o for k in ("satis", "satiş", "satış", "satim", "satım", "sattı", "satti", "elden cikar"))
    sat = sat and "alım satım" not in o.replace("i", "ı") or ("satış" in o) or ("satis" in o)
    al = any(k in o for k in ("alim", "alım", "alımı", "alimi", "aldı", "aldi", "edinim", "satın al", "satin al", "pay alım işlem", "pay alimi"))
    genel = o.strip().startswith("pay alım satım bildirimi") or o.strip().startswith("pay alim satim bildirimi")
    if genel or (al and sat and "alım satım" in o):
        return "?"
    if sat and not al:
        return "sat"
    if al and not sat:
        return "al"
    return "?"


def icerden_test():
    """22 Kas: iceriden / ortak pay alimlari (KAP 'Pay Alim Satim Bildirimi'), geri alimla ayni olay testi."""
    from . import kap
    P = kap.pas_topla()
    P["t"] = pd.to_datetime(P["tarih"].str[:10], format="%d.%m.%Y", errors="coerce")
    P["hisse"] = np.where(P["ilgili"].fillna("").str.len() > 1, P["ilgili"].fillna(""), P["gonderen"].fillna(""))
    P["hisse"] = P["hisse"].str.split(",").str[0].str.strip()
    P["yon"] = P["ozet"].fillna("").map(_pas_yon)
    P = P.dropna(subset=["t"])
    L = ["ICERIDEN / ORTAK PAY ALIMI TESTI (22 Kas 2026)",
         f"KAP 'Pay Alim Satim Bildirimi': {len(P)} adet, {P.hisse.nunique()} hisse. Yon (ozetten): " + " ".join(f"{k}:{v}" for k, v in P.yon.value_counts().items()),
         "gonderen sinifi: " + " ".join(f"{k}:{v}" for k, v in P.sinif.value_counts().items()),
         "ozet ornekleri (al): " + " | ".join(P[P.yon == "al"].ozet.head(8).tolist()),
         "ozet ornekleri (sat): " + " | ".join(P[P.yon == "sat"].ozet.head(8).tolist()),
         "ozet ornekleri (?): " + " | ".join(P[P.yon == "?"].ozet.sample(min(10, (P.yon == "?").sum()), random_state=1).tolist()), ""]
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    hep = D.prices(sorted(G.keys()))
    Cx = pd.DataFrame({t: df["close"] for t, df in hep.items()}).sort_index()
    gun = Cx.index
    F = {}
    for h in (5, 21, 63, 126):
        r = Cx.shift(-h) / Cx - 1
        F[h] = r.sub(r.median(axis=1), axis=0)
    def olaylar(x):
        x = x.sort_values("t"); ilk, son = [], {}
        for _, r in x.iterrows():
            if r.hisse not in son or (r.t - son[r.hisse]).days > 90:
                ilk.append(r)
            son[r.hisse] = r.t
        E = pd.DataFrame(ilk)
        if E.empty:
            return E
        E["giris"] = [gun[j] if (j := gun.searchsorted(t, side="right")) < len(gun) else pd.NaT for t in E.t]
        E = E.dropna(subset=["giris"])
        for h in F:
            E[f"f{h}"] = [F[h].at[gi, t] if t in F[h].columns else np.nan for t, gi in zip(E.hisse, E.giris)]
        return E
    def ozet(x, ad):
        o = []
        for h in (5, 21, 63, 126):
            v = x[f"f{h}"].dropna() if len(x) else pd.Series(dtype=float)
            if len(v) < 10:
                o.append(f"{h}g n<10"); continue
            k = v.clip(v.quantile(.05), v.quantile(.95))
            o.append(f"{h}g ort %{100 * k.mean():+.1f} ortanca %{100 * v.median():+.1f} kaz %{100 * (v > 0).mean():.0f} (n={len(v)}, t={k.mean() / (k.std() / np.sqrt(len(k))):+.1f})")
        L.append(f"  {ad:30s} " + " | ".join(o))
    L.append("YENI DALGA (90 gun sessizlikten sonra ilk bildirim), ertesi gun kapanistan piyasa ortancasina gore fazla getiri:")
    for yon in ("al", "sat", "?"):
        E = olaylar(P[P.yon == yon])
        ozet(E, f"yon={yon}")
        if yon == "al" and len(E):
            for y, x in E.groupby(E.giris.dt.year):
                ozet(x, f"  al {y}")
            yk = E.ozet.str.lower().str.contains("yönetim kurulu|genel müdür|ceo|başkan|yonetim kurulu|genel mudur|baskan", regex=True)
            ozet(E[yk], "  al: yonetici (YK/GM)")
            ozet(E[~yk], "  al: diger (ortak/sirket)")
    txt = "\n".join(L)
    (R / "icerden_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def potansiyel_test():
    """22 Kas (Teoman: 'sistem amator; kucuk firmanin potansiyelini/buyumesini nasil olcecek; PD/DD basit').
    (1) tek olcu olay testi: 3 yillik reel satis buyumesi, FAVOK marji degisimi, yatirim/amortisman;
    (2) portfoy: deger olcutlerini SEKTOR ICINDE siralamak; temel puana POTANSIYEL bileseni eklemek."""
    from . import firsat_bt as FB
    FB.SEKTOR_MAP = dict(zip(D.bist_list()["ticker"], D.bist_list()["sektor"]))
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    O = B.olaylar(G, D.m3())
    px = D.prices(sorted(O["t"].unique()))
    FB.HAM_DONDUR = True
    A = FB.puanlar(O, px)
    FB.HAM_DONDUR = False
    Cx = pd.DataFrame({t: df["close"] for t, df in px.items()}).sort_index()
    r = Cx.shift(-126) / Cx - 1
    F126 = r.sub(r.median(axis=1), axis=0)
    A["f126"] = [F126.at[pd.Timestamp(g), t] if pd.Timestamp(g) in F126.index and t in F126.columns else np.nan for t, g in zip(A.t, A.giris)]
    A["yil"] = pd.to_datetime(A["giris"]).dt.year
    L = ["POTANSIYEL / SEKTOR TESTI (22 Kas 2026)\n", "1) TEK OLCU OLAY TESTI (126 gun, piyasa ortancasina gore fazla %, 5 dilim; 5 = en yuksek):"]
    for f in ("buyume3", "marj_deg", "capex_amort"):
        L.append(f"  {f}: dolu %{100 * A[f].notna().mean():.0f}, ortanca {A[f].median():.3f}")
        for ad, m in (("2021-24", A.yil < 2025), ("2025+", A.yil >= 2025)):
            a = A[m & A[f].notna() & A.f126.notna()].copy()
            if len(a) < 200:
                continue
            a["dl"] = a[f].groupby(a["donem"]).rank(pct=True).mul(5).clip(upper=4.999).astype(int) + 1
            km = lambda v: 100 * v.clip(v.quantile(.05), v.quantile(.95)).mean()
            st = a.groupby("dl")["f126"].agg(km)
            v5, v1 = a.loc[a.dl == 5, "f126"], a.loc[a.dl == 1, "f126"]
            v5 = v5.clip(v5.quantile(.05), v5.quantile(.95)); v1 = v1.clip(v1.quantile(.05), v1.quantile(.95))
            tst = (v5.mean() - v1.mean()) / np.sqrt(v5.var() / len(v5) + v1.var() / len(v1))
            L.append(f"    {ad:8s} n={len(a):5d} | " + " ".join(f"D{i} {st.loc[i]:+5.1f}" for i in range(1, 6)) + f" | D5-D1 {st.loc[5] - st.loc[1]:+5.1f} (t={tst:+.1f})")
        print("\n".join(L[-3:]))
    L.append("\n2) PORTFOY (AL'dan rastgele secim, 25 kosu ortancasi, cikis canli): egitim 2021-24 / TEST 2025-bugun / yillar (5 hisse)")
    rng = np.random.default_rng(9)
    for ad, sek, pot in (("CANLI", False, False), ("deger SEKTOR ICINDE", True, False), ("+ POTANSIYEL bileseni", False, True), ("sektor ici + potansiyel", True, True)):
        FB.SEKTOR, FB.POTANSIYEL = sek, pot
        idx, C, S, PC, VR, TK, xu, m3 = panel()
        sat = []
        for per, m in (("egitim", (idx >= "2021-01-01") & (idx <= "2024-12-31")), ("TEST", idx >= "2025-01-01")):
            for N in (10, 5):
                v = [sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, iz=(0.20, 0.15), karal=90, sira=rng.random(C[m].shape))[0]["deger"].iloc[-1] / BAS for _ in range(25)]
                sat.append(f"{per} {N}h x{np.median(v):.2f}")
        yil = []
        for y in (2022, 2023, 2024, 2025, 2026):
            m = idx.year == y
            v = [sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=5, iz=(0.20, 0.15), karal=90, sira=rng.random(C[m].shape))[0]["deger"].iloc[-1] / BAS for _ in range(15)]
            yil.append(f"{y} {100 * (np.median(v) - 1):+.0f}")
        L.append(f"  {ad:26s} " + " | ".join(sat) + " || " + " ".join(yil))
        print(L[-1])
    FB.SEKTOR, FB.POTANSIYEL = False, False
    txt = "\n".join(L)
    (R / "potansiyel_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def icerden2_test():
    """22 Kas: MKK 'Pay Alim Satim Bildirimi' PDF'lerinden ayristirilan gercek alim/satimlar (kim, ne kadar)."""
    from . import kap
    _icerden2_hesap(kismi=True)  # once eldeki veriyle test (hizli), sonra okumaya devam
    kalan = kap.pas_detay_topla(butce_dk=150)
    if kalan > 0:
        print(f"KALAN {kalan}: okuma suruyor"); return
    _icerden2_hesap(kismi=False)


def _icerden2_hesap(kismi=False):
    P = pd.read_csv(D.DATA / "kap_pas.csv", dtype=str)
    X = pd.read_csv(D.DATA / "kap_pas_detay.csv", dtype=str).merge(P[["index", "tarih", "ilgili", "gonderen"]], on="index", how="left")
    for c in ("alim_nom", "satim_nom", "net_nom", "oran_bas", "oran_son", "satir"):
        X[c] = pd.to_numeric(X[c], errors="coerce")
    X["t"] = pd.to_datetime(X["tarih"].str[:10], format="%d.%m.%Y", errors="coerce")
    X["hisse"] = X["ilgili"].fillna(X["gonderen"]).fillna("").str.split(",").str[0].str.strip()
    konu = X["konu"].fillna("").str.lower()
    X["devir"] = konu.str.contains("devir|devri|hediye|miras|teminat|bağış|bagis|intikal|birleşme|bedelsiz", regex=True)
    g = X["gorev"].fillna("").str.lower()
    X["yonetici"] = g.str.contains("yönetim|yonetim|müdür|mudur|başkan|baskan|üye|uye|ceo|cfo|direkt", regex=True)
    X["d_oran"] = X["oran_son"] - X["oran_bas"]
    ok = X[(X.satir > 0) & X.t.notna() & (X.hisse != "")]
    L = ["ICERIDEN ALIM-SATIM (PDF'ten ayristirilmis), 22-23 Kas 2026" + (" [KISMI VERI: okuma suruyor]" if kismi else ""),
         f"bildirim tarih araligi: {X.t.min():%Y-%m-%d} .. {X.t.max():%Y-%m-%d}",
         f"ayristirilan DKB bildirimi {len(X)}, islem tablosu okunan {len(ok)} (%{100 * len(ok) / max(len(X), 1):.0f}); devir/hediye vb. {int(ok.devir.sum())} cikarildi",
         f"yonetici (gorevi yazan) {int(ok.yonetici.sum())}, diger (ortak/sirket/kisi) {int((~ok.yonetici).sum())}",
         "en sik konular: " + " | ".join(f"{k}:{v}" for k, v in ok.konu.value_counts().head(8).items()),
         "en sik gorevler: " + " | ".join(f"{k}:{v}" for k, v in ok[ok.yonetici].gorev.value_counts().head(8).items()), ""]
    ok = ok[~ok.devir]
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    hep = D.prices(sorted(G.keys()))
    Cx = pd.DataFrame({t: df["close"] for t, df in hep.items()}).sort_index()
    gun = Cx.index
    F = {}
    for h in (5, 21, 63, 126):
        r = Cx.shift(-h) / Cx - 1
        F[h] = r.sub(r.median(axis=1), axis=0)
    def olay(x):
        x = x.sort_values("t"); ilk, son = [], {}
        for _, r in x.iterrows():
            if r.hisse not in son or (r.t - son[r.hisse]).days > 90:
                ilk.append(r)
            son[r.hisse] = r.t
        E = pd.DataFrame(ilk)
        if E.empty:
            return E
        E["giris"] = [gun[j] if (j := gun.searchsorted(t, side="right")) < len(gun) else pd.NaT for t in E.t]
        E = E.dropna(subset=["giris"])
        for h in F:
            E[f"f{h}"] = [F[h].at[gi, t] if t in F[h].columns else np.nan for t, gi in zip(E.hisse, E.giris)]
        return E
    def oz(E, ad):
        o = []
        for h in (5, 21, 63, 126):
            v = E[f"f{h}"].dropna() if len(E) else pd.Series(dtype=float)
            if len(v) < 15:
                o.append(f"{h}g n<15"); continue
            k = v.clip(v.quantile(.05), v.quantile(.95))
            o.append(f"{h}g ort %{100 * k.mean():+.1f} ortanca %{100 * v.median():+.1f} kaz %{100 * (v > 0).mean():.0f} (n={len(v)}, t={k.mean() / (k.std() / np.sqrt(len(k))):+.1f})")
        L.append(f"  {ad:38s} " + " | ".join(o))
        print(L[-1])
    L.append("YENI DALGA (hisse bazinda 90 gun sessizlikten sonra ilk bildirim), ertesi gun kapanistan piyasa ortancasina gore fazla getiri (kirpik ort.):")
    al, sat = ok[ok.net_nom > 0], ok[ok.net_nom < 0]
    Ea, Es = olay(al), olay(sat)
    oz(Ea, "NET ALIM (hepsi)")
    oz(Es, "NET SATIM (hepsi)")
    oz(olay(al[al.yonetici]), "alim: YONETICI")
    oz(olay(al[~al.yonetici]), "alim: ortak / diger")
    oz(olay(sat[sat.yonetici]), "satim: YONETICI")
    oz(olay(al[al.d_oran >= 0.5]), "alim: paya etkisi >= 0.5 puan")
    oz(olay(al[(al.d_oran > 0) & (al.d_oran < 0.5)]), "alim: paya etkisi < 0.5 puan")
    # kume: 30 gunde 2+ farkli alici
    kume = []
    for h, x in al.groupby("hisse"):
        x = x.sort_values("t")
        for i, r in x.iterrows():
            w = x[(x.t >= r.t - pd.Timedelta(days=30)) & (x.t <= r.t)]
            if w.kisi.nunique() >= 2:
                kume.append(r)
    oz(olay(pd.DataFrame(kume)) if kume else pd.DataFrame(), "alim: 30 gunde 2+ farkli alici")
    for y, x in Ea.groupby(Ea.giris.dt.year):
        oz(x, f"  net alim {y}")
    txt = "\n".join(L)
    (R / "icerden2_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def grup_listesi():
    """22 Kas: sektor gruplari (TradingView 'sector' cok kaba: Finance 137 sirket). Unvandan."""
    b = D.bist_list()
    a = b["ad"].fillna("").str.upper().str.replace("İ", "I")
    return {"GYO": set(b.ticker[a.str.contains("GAYRIMENKUL YATIRIM")]),
            "HOLDING": set(b.ticker[a.str.contains("HOLDING") & ~a.str.contains("GAYRIMENKUL YATIRIM ORT")]),
            "SIGORTA": set(b.ticker[a.str.contains("SIGORTA|EMEKLILIK", regex=True)]),
            "FAKTORING/LEASING": set(b.ticker[a.str.contains("FAKTORING|FINANSAL KIRALAMA|FINANSMAN", regex=True)]),
            "ARACI KURUM": set(b.ticker[a.str.contains("MENKUL DEGER")])}


def gyo_test():
    """22 Kas (Teoman: 'acilen sektore ayarlama; GYO hesaplamalari uygun olmali'). GYO'lar icinde hangi olcu 6 ayi aciklar?"""
    from . import firsat_bt as FB
    GR = grup_listesi()
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    O = B.olaylar(G, D.m3())
    px = D.prices(sorted(O["t"].unique()))
    FB.HAM_DONDUR = True
    A = FB.puanlar(O, px)
    FB.HAM_DONDUR = False
    Cx = pd.DataFrame({t: df["close"] for t, df in px.items()}).sort_index()
    F = {}
    for h in (63, 126):
        r = Cx.shift(-h) / Cx - 1
        F[h] = r.sub(r.median(axis=1), axis=0)
    for h in F:
        A[f"f{h}"] = [F[h].at[pd.Timestamp(g), t] if pd.Timestamp(g) in F[h].index and t in F[h].columns else np.nan for t, g in zip(A.t, A.giris)]
    A["yil"] = pd.to_datetime(A["giris"]).dt.year
    if "netborc" not in A or "varlik" not in A:
        nb = O.drop_duplicates(["t", "donem"]).set_index(["t", "donem"])[["netborc", "varlik"]]
        A = A.drop(columns=[c for c in ("netborc", "varlik") if c in A]).join(nb, on=["t", "donem"])
    A["ltv"] = pd.to_numeric(A["netborc"], errors="coerce") / pd.to_numeric(A["varlik"], errors="coerce")
    L = ["SEKTOR GRUPLARI ICINDE OLCU TESTI (22 Kas 2026)",
         "Her grup icinde, ayni bilanco donemindeki sirketler 3 dilime ayrilir (3 = olcuye gore en iyi). 126 gun, piyasa ortancasina gore fazla getiri (kirpik ort. / ortanca).",
         "pddd ve ltv'de dusuk iyi; digerlerinde yuksek iyi. v3 = sistemin bugunku temel puani.\n"]
    yon = {"pddd": -1, "ltv": -1}
    for grup in ("GYO", "HOLDING", "SIGORTA", "FAKTORING/LEASING"):
        g = A[A.t.isin(GR[grup])].copy()
        L.append(f"== {grup}: {g.t.nunique()} sirket, {len(g)} bilanco olayi (sistemde puan alan)")
        for f in ("v3", "pddd", "kaz_get", "fav_get", "ltv", "roe", "F", "sue_nk", "satis_reel"):
            if f not in g:
                continue
            for ad, m in (("tum", g.yil >= 2021), ("2025+", g.yil >= 2025)):
                a = g[m & g[f].notna() & g.f126.notna()].copy()
                if len(a) < 60:
                    continue
                a["dl"] = (yon.get(f, 1) * a[f]).groupby(a["donem"]).rank(pct=True).mul(3).clip(upper=2.999).astype(int) + 1
                def km(v):
                    return 100 * v.clip(v.quantile(.05), v.quantile(.95)).mean()
                st = a.groupby("dl")["f126"].agg(km=km, median="median")
                v3_, v1_ = a.loc[a.dl == 3, "f126"], a.loc[a.dl == 1, "f126"]
                v3_ = v3_.clip(v3_.quantile(.05), v3_.quantile(.95)); v1_ = v1_.clip(v1_.quantile(.05), v1_.quantile(.95))
                tst = (v3_.mean() - v1_.mean()) / np.sqrt(v3_.var() / len(v3_) + v1_.var() / len(v1_))
                L.append(f"  {f:10s} {ad:5s} n={len(a):4d} | " + " ".join(f"D{i} {st.loc[i, 'km']:+5.1f}/{100 * st.loc[i, 'median']:+5.1f}" for i in (1, 2, 3)) + f" | D3-D1 {st.loc[3, 'km'] - st.loc[1, 'km']:+5.1f} (t={tst:+.1f})")
        L.append("")
        print("\n".join(L[-12:]))
    txt = "\n".join(L)
    (R / "gyo_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def uzun_test():
    """23 Kas: sistemi 2014-2026'da yil yil sina (2014-2020 hic bakilmamis donem). Rastgele secimli portfoy + tek olcu olay testi."""
    global UZUN
    from . import firsat_bt as FB
    from . import temel as _T
    UZUN = True
    G = _T.gecmis_birlesik()
    O = B.olaylar(G, D.m3())
    L = ["UZUN TEST 2014-2026 (23 Kas 2026). 2014-2020 sistem kurulurken HIC bakilmamis donem.",
         "Uyari: yalniz bugun borsada olan sirketler var (batan/cikan sirketler yok -> sonuc biraz iyimser).",
         "bilanco olayi (yayin yili): " + " ".join(f"{y}:{n}" for y, n in pd.to_datetime(O["yayin"]).dt.year.value_counts().sort_index().items()), ""]
    px = D.prices(sorted(O["t"].unique()), start="2013-01-01")
    FB.HAM_DONDUR = True
    A = FB.puanlar(O, px)
    FB.HAM_DONDUR = False
    Cx = pd.DataFrame({t: df["close"] for t, df in px.items()}).sort_index()
    r = Cx.shift(-126) / Cx - 1
    F126 = r.sub(r.median(axis=1), axis=0)
    A["f126"] = [F126.at[pd.Timestamp(g), t] if pd.Timestamp(g) in F126.index and t in F126.columns else np.nan for t, g in zip(A.t, A.giris)]
    A["yil"] = pd.to_datetime(A["giris"]).dt.year
    L.append("1) TEK OLCU OLAY TESTI (126 gun, piyasa ortancasina gore fazla %, 5 dilim; D5 = en iyi). Kirpik ort.:")
    yon = {"pddd": -1}
    for f in ("v3", "fav_get", "kaz_get", "pddd", "sue_nk", "satis_reel", "roe", "F"):
        for ad, m in (("2014-17", A.yil.between(2014, 2017)), ("2018-20", A.yil.between(2018, 2020)), ("2021-24", A.yil.between(2021, 2024)), ("2025+", A.yil >= 2025)):
            a = A[m & A[f].notna() & A.f126.notna()].copy()
            if len(a) < 150:
                L.append(f"  {f:10s} {ad:7s} n={len(a)} (az)"); continue
            a["dl"] = (yon.get(f, 1) * a[f]).groupby(a["donem"]).rank(pct=True).mul(5).clip(upper=4.999).astype(int) + 1
            def km(v):
                return 100 * v.clip(v.quantile(.05), v.quantile(.95)).mean()
            st = a.groupby("dl")["f126"].agg(km=km, med="median")
            v5, v1 = a.loc[a.dl == 5, "f126"], a.loc[a.dl == 1, "f126"]
            v5 = v5.clip(v5.quantile(.05), v5.quantile(.95)); v1 = v1.clip(v1.quantile(.05), v1.quantile(.95))
            tst = (v5.mean() - v1.mean()) / np.sqrt(v5.var() / len(v5) + v1.var() / len(v1))
            L.append(f"  {f:10s} {ad:7s} n={len(a):5d} | " + " ".join(f"D{i} {st.loc[i, 'km']:+5.1f}" for i in range(1, 6)) + f" | D5-D1 {st.loc[5, 'km'] - st.loc[1, 'km']:+5.1f} (t={tst:+.1f}) ortanca D5 {100 * st.loc[5, 'med']:+.1f} D1 {100 * st.loc[1, 'med']:+.1f}")
        print("\n".join(L[-4:]))
    L.append("\n2) PORTFOY (canli kurallar; AL listesinden rastgele secim 25 kosu ortancasi; her yil 100.000 TL ile sifirdan). Yillik getiri %:")
    idx, C, S, PC, VR, TK, xu, m3 = panel()
    rr = faiz_serisi(idx)
    al = (S.values == "AL cift tik") | (S.values == "AL tek tik")
    rng = np.random.default_rng(14)
    L.append(f"  {'yil':5s} {'BIST100':>8s} {'mevduat':>8s} {'5 hisse':>8s} {'10 hisse':>9s} {'gunluk AL ort':>14s}")
    for y in range(2014, 2027):
        m = idx.year == y
        if m.sum() < 20:
            continue
        ii = np.flatnonzero(m)
        mev = float(np.prod(1 + rr[ii[1:]] * np.diff(idx.values[ii]).astype("timedelta64[D]").astype(float) / 365.0))
        xg = xu[m].iloc[-1] / xu[m].iloc[0]
        res = []
        for N in (5, 10):
            v = [sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, iz=(0.20, 0.15), karal=90, sira=rng.random(C[m].shape))[0]["deger"].iloc[-1] / BAS for _ in range(25)]
            res.append(np.median(v))
        L.append(f"  {y:5d} {100 * (xg - 1):+8.0f} {100 * (mev - 1):+8.0f} {100 * (res[0] - 1):+8.0f} {100 * (res[1] - 1):+9.0f} {al[m].sum(axis=1).mean():14.1f}")
        print(L[-1])
    for per, m in (("2014-2020", (idx.year >= 2014) & (idx.year <= 2020)), ("2021-2026", idx.year >= 2021)):
        ii = np.flatnonzero(m)
        mev = float(np.prod(1 + rr[ii[1:]] * np.diff(idx.values[ii]).astype("timedelta64[D]").astype(float) / 365.0))
        res = []
        for N in (5, 10):
            v = [sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, iz=(0.20, 0.15), karal=90, sira=rng.random(C[m].shape))[0]["deger"].iloc[-1] / BAS for _ in range(25)]
            res.append(np.median(v))
        L.append(f"  {per}: BIST100 x{xu[m].iloc[-1] / xu[m].iloc[0]:.2f} | mevduat x{mev:.2f} | sistem 5 hisse x{res[0]:.2f}, 10 hisse x{res[1]:.2f}")
        print(L[-1])
    UZUN = False
    txt = "\n".join(L)
    (R / "uzun_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def gyo_grup_test():
    """23 Kas: GYO'lari kendi icinde siralamak (iki sartli) portfoyu iyilestiriyor mu?"""
    from . import firsat_bt as FB
    FB.GYO_SET = grup_listesi()["GYO"]
    L = ["GYO GRUP ICI SIRALAMA TESTI (23 Kas 2026). AL'dan rastgele secim, 25 kosu ortancasi, cikis canli."]
    rng = np.random.default_rng(21)
    for ad, on, taban in (("CANLI (GYO tum piyasayla)", False, 0.6), ("GYO kendi icinde, taban %60", True, 0.6), ("GYO kendi icinde, taban %40", True, 0.4)):
        FB.GYO_GRUP, FB.GYO_TABAN = on, taban
        idx, C, S, PC, VR, TK, xu, m3 = panel()
        al = (S.values == "AL cift tik") | (S.values == "AL tek tik")
        gy = np.array([c in FB.GYO_SET for c in S.columns])
        sat = [f"AL gunlerinde ort. GYO sayisi {al[:, gy].sum(axis=1).mean():.1f} / tum AL {al.sum(axis=1).mean():.1f}"]
        for per, m in (("egitim", (idx >= "2021-01-01") & (idx <= "2024-12-31")), ("TEST", idx >= "2025-01-01")):
            for N in (10, 5):
                v = [sim(idx[m], C[m], S[m], PC[m], VR[m], TK[m], N=N, iz=(0.20, 0.15), karal=90, sira=rng.random(C[m].shape))[0]["deger"].iloc[-1] / BAS for _ in range(25)]
                sat.append(f"{per} {N}h x{np.median(v):.2f}")
        L.append(f"  {ad:30s} " + " | ".join(sat))
        print(L[-1])
    FB.GYO_GRUP = False
    txt = "\n".join(L)
    (R / "gyo_grup_sonuc.txt").write_text(txt, encoding="utf-8")
    print(txt)


def gyo_kontrol():
    """23 Kas (Teoman: 'GYO duzgun mu emin ol'). GYO karinda deger artis kazanci (kagit kar) puani yaniltiyor mu?
    Gecmis veride ayri kalem yok; vekil: faaliyet kari - brut kar (GYO'da gider kucuk; buyuk artı = deger artisi faaliyet
    karinda), net kar - faaliyet kari (yatirim faaliyeti gelirleri / finansman / vergi). Nakit (isletme nakit akisi) kagit kari icermez."""
    from . import firsat_bt as FB
    from . import temel as T
    GR = grup_listesi()
    G = json.loads(gzip.decompress((R / "gecmis.json.gz").read_bytes()))
    O = B.olaylar(G, D.m3())
    ek = {}
    for h, g in G.items():
        if h not in GR["GYO"]:
            continue
        tab = {tuple(map(int, k.split("/"))): v for k, v in g["tab"].items()}
        for d in tab:
            ek[(h, f"{d[0]}/{d[1]:02d}")] = {"brut_ttm": T._ttm(tab, d, "3D"), "nk2_ttm": T._ttm(tab, d, "3Z")}
    px = D.prices(sorted(O["t"].unique()))
    FB.HAM_DONDUR = True
    A = FB.puanlar(O, px)
    FB.HAM_DONDUR = False
    Cx = pd.DataFrame({t: df["close"] for t, df in px.items()}).sort_index()
    r = Cx.shift(-126) / Cx - 1
    F = r.sub(r.median(axis=1), axis=0)
    A["f126"] = [F.at[pd.Timestamp(g), t] if pd.Timestamp(g) in F.index and t in F.columns else np.nan for t, g in zip(A.t, A.giris)]
    A["yil"] = pd.to_datetime(A["giris"]).dt.year
    A["v3r_piyasa"] = A["v3"].groupby(A["donem"]).rank(pct=True)
    g = A[A.t.isin(GR["GYO"])].copy()
    g["brut_ttm"] = [ek.get((t, d), {}).get("brut_ttm") for t, d in zip(g.t, g.donem)]
    num = lambda c: pd.to_numeric(g[c], errors="coerce")
    va = num("varlik")
    g["kagit_faal"] = (num("fk_ttm") - num("brut_ttm")) / va            # buyuk = faaliyet karinda deger artisi
    g["kagit_net"] = (num("nk_ttm") - num("fk_ttm")) / va                # buyuk = faaliyet disi kazanc (yatirim geliri vb.)
    g["kagit_pay"] = (num("fk_ttm") - num("brut_ttm")) / num("fk_ttm").abs()
    mc = num("pddd") * num("oz")
    ev = mc + num("netborc")
    g["cekirdek_get"] = (num("brut_ttm") + num("favok_ttm") - num("fk_ttm")) / ev   # brut kar + amortisman (deger artisi haric)
    g["nakit_get"] = num("fnakit_ttm") / ev
    L = ["GYO KONTROL: deger artis kazanci puani yaniltiyor mu? (23 Kas 2026)",
         "126 gun, piyasa ortancasina gore fazla getiri; GYO'lar kendi icinde ayni donemde 3 dilim (3 = olcuye gore yuksek). kirpik ort / ortanca.",
         f"GYO olay sayisi {len(g)}, sirket {g.t.nunique()}. Faaliyet karinin yarisindan fazlasi 'kagit' (faaliyet-brut>0.5*|faaliyet|) olan olay orani: "
         f"%{100 * (g.kagit_pay > 0.5).mean():.0f}", ""]

    def dilim(f, yon=1, maske=None):
        out = []
        for ad, m in (("tum", g.yil >= 2021), ("2025+", g.yil >= 2025)):
            a = g[m & g[f].notna() & g.f126.notna()].copy()
            if maske is not None:
                a = a[maske.reindex(a.index).fillna(False)]
            if len(a) < 60:
                out.append(f"  {f:14s} {ad:5s} n={len(a)} (az)"); continue
            a["dl"] = (yon * a[f]).groupby(a["donem"]).rank(pct=True).mul(3).clip(upper=2.999).astype(int) + 1
            km = lambda v: 100 * v.clip(v.quantile(.05), v.quantile(.95)).mean()
            st = a.groupby("dl")["f126"].agg(km=km, med="median")
            x3, x1 = a.loc[a.dl == 3, "f126"], a.loc[a.dl == 1, "f126"]
            x3 = x3.clip(x3.quantile(.05), x3.quantile(.95)); x1 = x1.clip(x1.quantile(.05), x1.quantile(.95))
            t = (x3.mean() - x1.mean()) / np.sqrt(x3.var() / len(x3) + x1.var() / len(x1))
            out.append(f"  {f:14s} {ad:5s} n={len(a):4d} | " + " ".join(f"D{i} {st.loc[i, 'km']:+5.1f}/{100 * st.loc[i, 'med']:+5.1f}" for i in (1, 2, 3))
                       + f" | D3-D1 {st.loc[3, 'km'] - st.loc[1, 'km']:+5.1f} (t={t:+.1f})")
        return out
    L.append("1) Kagit kar olculeri (yuksek = karin daha cok kagit kismi):")
    for f in ("kagit_faal", "kagit_net"):
        L += dilim(f)
    L.append("\n2) Deger olculeri (yuksek = ucuz):")
    for f in ("fav_get", "cekirdek_get", "nakit_get", "kaz_get"):
        L += dilim(f)
    L.append("\n3) v3 (bugunku puan) GYO icinde, ve kagit kari yuksek/dusuk GYO'larda ayri:")
    L += dilim("v3")
    yuk = g["kagit_faal"] > g.groupby("donem")["kagit_faal"].transform("median")
    L.append("  -- kagit kari YUKSEK yari:")
    L += dilim("v3", maske=yuk)
    L.append("  -- kagit kari DUSUK yari:")
    L += dilim("v3", maske=~yuk)
    L.append("\n4) Bilanco ivmesi bilesenleri GYO icinde (net kar surprizi deger artisindan etkilenir):")
    for f in ("sue_nk", "sue_faal", "satis_reel", "roe", "F"):
        if f in g:
            L += dilim(f)
    L.append("\n5) Sistemin en iyi %20'sine (piyasa geneli v3) giren GYO olaylari: kagit kari yuksek olanlar vs dusuk olanlar (126g):")
    top = g[(g.v3r_piyasa >= 0.8) & g.f126.notna()]
    for ad, m in (("kagit yuksek", top.kagit_faal > g.kagit_faal.median()), ("kagit dusuk", top.kagit_faal <= g.kagit_faal.median())):
        v = top[m]["f126"]
        L.append(f"  {ad:13s} n={len(v):4d} ort {100 * v.clip(v.quantile(.05), v.quantile(.95)).mean():+5.1f} ortanca {100 * v.median():+5.1f} kazanma %{100 * (v > 0).mean():.0f}")
    txt = "\n".join(L)
    (R / "gyo_kontrol.txt").write_text(txt, encoding="utf-8")
    print(txt)
