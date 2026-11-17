"""Heikin Ashi faz motoru neden 200+ gun BEKLE'de kaliyor? (17 Kas 2026 tani)"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from . import data as D
from . import engine as E

R = D.ROOT / "temel"


def main():
    lst = D.bist_list()
    px = D.prices(lst["ticker"].tolist())
    xu = D.xu100(); m3 = D.m3()
    L = []
    takili = []
    for t, df in sorted(px.items()):
        if len(df) < 400:
            continue
        try:
            sat = {}
            for ad, kw in (("normal", {}), ("ha", {"ha": True})):
                r = E.compute(df, xu, m3, "D", sig_mod="faz", **kw)
                sg = r["sinyal"].values
                k = len(sg) - 1
                while k > 0 and sg[k - 1] == sg[-1]:
                    k -= 1
                sat[ad] = (r, sg[-1], len(sg) - k)
        except Exception:
            continue
        r, s, g = sat["ha"]
        if g >= 150:
            son = r.iloc[-g:]
            neden = {
                "pct>35 (ucuz degil)": float((~son["c1"].astype(bool)).mean()),
                "stop kirik (d_stop<=-3.5)": float((son["d_stop"] <= -3.5).mean()),
                "eksik>=3": float((son["eksik"] >= 3).mean()),
            }
            takili.append(dict(t=t, sinyal=s, gun=int(g), normal=sat["normal"][1], normal_gun=int(sat["normal"][2]),
                               ha_pct=round(float(r["percentile"].iloc[-1]), 1), n_pct=round(float(sat["normal"][0]["percentile"].iloc[-1]), 1),
                               ha_dstop=round(float(r["d_stop"].iloc[-1]), 1), n_dstop=round(float(sat["normal"][0]["d_stop"].iloc[-1]), 1),
                               ha_stop=round(float(r["stop"].iloc[-1]), 2), n_stop=round(float(sat["normal"][0]["stop"].iloc[-1]), 2),
                               ha_close=round(float(r["close"].iloc[-1]), 2), n_close=round(float(sat["normal"][0]["close"].iloc[-1]), 2),
                               **{k: round(v, 2) for k, v in neden.items()}))
    T = pd.DataFrame(takili).sort_values("gun", ascending=False)
    L.append(f"HA faz 150+ gun ayni sinyalde: {len(T)} hisse")
    L.append(T.to_string(index=False))
    # KCHOL ayrinti
    for t in ("KCHOL", "TUPRS"):
        if t in px:
            r = E.compute(px[t], xu, m3, "D", sig_mod="faz", ha=True)
            n = E.compute(px[t], xu, m3, "D", sig_mod="faz")
            X = pd.DataFrame({"ha_close": r["close"], "ha_pct": r["percentile"], "ha_dstop": r["d_stop"], "ha_stop": r["stop"],
                              "ha_sig": r["sinyal"], "n_close": n["close"], "n_pct": n["percentile"], "n_dstop": n["d_stop"], "n_sig": n["sinyal"]})
            L.append(f"\n{t} son 260 gun, 10 gunde bir:\n" + X.iloc[-260::10].round(2).to_string())
    for t in ("KCHOL", "AYGAZ", "EBEBK"):
        if t in px:
            r = E.compute(px[t], xu, m3, "D", sig_mod="faz", ha=True)
            X = r[["close", "percentile", "d_stop", "eksik", "chg1", "rs", "sinyal"]].copy()
            X["rs_fark"] = X["rs"].diff()
            L.append(f"\n{t} HA son 30 gun (gunluk):\n" + X.iloc[-30:].round(2).to_string())
    txt = "\n".join(L)
    (R / "faz_tani.txt").write_text(txt, encoding="utf-8")
    print(txt[:3000])


if __name__ == "__main__":
    main()


def istikrar():
    """Faz grubu degisim sikligi (yilda kac kez alim<->dagitim<->bekle) ve bugunku durum; FAZ_GRUP ortamina gore."""
    import os
    lst = D.bist_list(); px = D.prices(lst["ticker"].tolist()); xu = D.xu100(); m3 = D.m3()
    AL_ = ("ALINABILIR", "TOPLANIYOR", "YAKIN")
    deg, alim_bugun, ornek = {"normal": [], "ha": []}, {"normal": 0, "ha": 0}, {}
    for t, df in sorted(px.items()):
        if len(df) < 400:
            continue
        for ad, kw in (("normal", {}), ("ha", {"ha": True})):
            try:
                r = E.compute(df, xu, m3, "D", sig_mod="faz", **kw)
            except Exception:
                continue
            g = pd.Series(["AL" if x in AL_ else x for x in r["sinyal"].values], index=r.index)
            g = g[g.index >= pd.Timestamp("2021-01-01")]
            yil = max((g.index[-1] - g.index[0]).days / 365.25, 0.5)
            deg[ad].append((g != g.shift()).sum() / yil)
            alim_bugun[ad] += int(g.iloc[-1] == "AL")
            if t in ("KCHOL", "TUPRS", "THYAO", "ALARK", "TTKOM"):
                ornek[f"{t} {ad}"] = r["sinyal"].iloc[-1]
    L = [f"FAZ_GRUP={os.environ.get('FAZ_GRUP', '0')}",
         f"yilda grup degisimi (medyan): normal {np.median(deg['normal']):.1f}, HA {np.median(deg['ha']):.1f}",
         f"bugun alim tarafinda: normal {alim_bugun['normal']}, HA {alim_bugun['ha']} hisse",
         "ornekler: " + ", ".join(f"{k}={v}" for k, v in ornek.items())]
    print("\n".join(L))
    return L
