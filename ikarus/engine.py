"""IKARUS QUANT hesap motoru: Pine v4.6 aday gostergesinin Python karsiligi.

Girdi: bir hissenin gunluk OHLCV verisi, BIST100 gunluk kapanisi, aylik M3 serisi.
Cikti: her bar icin tablo satirlari (Percentile, Value, Memory, ... Signal, Dip, Tepe, Stop).

Pine semantigi birebir korunur:
  ta.lowest/highest(x, n)  : bugunku bar dahil son n bar (na degerler atlanir, ilk n-1 bar na)
  ta.percentrank(x, n)     : onceki n degerin (x[1]..x[n]) kacinin <= x oldugu, / n * 100
  ta.atr(14)               : RMA(true range), ilk deger ilk 14 TR'nin ortalamasi
  M3                       : aylik deger, damga (ayin 1'i) <= bar tarihi olan son deger.
                             Haftalik barlarda damga <= haftanin pazartesisi.
Haftalik degerler (MTF, makro) "canli tablo" anlamiyla hesaplanir: gun d'de, d'yi iceren
haftanin d'ye kadarki kismi o haftanin kapanisi sayilir (Zippo tablolari canli alindigi icin).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- Pine yardimcilari

def _arr(x) -> np.ndarray:
    return np.asarray(x, dtype=float)


def lowest(x, n: int) -> np.ndarray:
    s = pd.Series(_arr(x)).rolling(n, min_periods=1).min().to_numpy().copy()
    s[: n - 1] = np.nan
    return s


def highest(x, n: int) -> np.ndarray:
    s = pd.Series(_arr(x)).rolling(n, min_periods=1).max().to_numpy().copy()
    s[: n - 1] = np.nan
    return s


def shift(x, k: int = 1) -> np.ndarray:
    x = _arr(x)
    out = np.full_like(x, np.nan)
    if k < len(x):
        out[k:] = x[: len(x) - k]
    return out


def percentrank(x, n: int) -> np.ndarray:
    x = _arr(x)
    out = np.full(len(x), np.nan)
    if len(x) <= n:
        return out
    win = np.lib.stride_tricks.sliding_window_view(x, n)[:-1]  # win[j] = x[j..j+n-1], onceki n deger
    cur = x[n:]
    cnt = (win <= cur[:, None]).sum(axis=1)  # nan karsilastirmalari False
    res = 100.0 * cnt / n
    res[np.isnan(cur)] = np.nan
    out[n:] = res
    return out


def stoch(src, n: int) -> np.ndarray:
    src = _arr(src)
    lo, hi = lowest(src, n), highest(src, n)
    with np.errstate(invalid="ignore", divide="ignore"):
        v = np.where(hi > lo, 10 * (src - lo) / (hi - lo), 5.0)
    v[np.isnan(lo) | np.isnan(hi) | np.isnan(src)] = np.nan
    return v


def sma(x, n: int) -> np.ndarray:
    s = pd.Series(_arr(x)).rolling(n, min_periods=n).mean().to_numpy()
    return s


def rma(x, n: int) -> np.ndarray:
    x = _arr(x)
    out = np.full(len(x), np.nan)
    if len(x) < n:
        return out
    out[n - 1] = np.mean(x[:n])
    a = 1.0 / n
    for i in range(n, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def atr(h, l, c, n: int = 14) -> np.ndarray:
    h, l, c = _arr(h), _arr(l), _arr(c)
    pc = shift(c)
    tr = np.fmax(h - l, np.fmax(np.abs(h - pc), np.abs(l - pc)))
    tr[0] = h[0] - l[0]
    return rma(tr, n)


def rnd(x, d: int) -> float:
    """Zippo/Pine yazimi: yarim yukari yuvarlama."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return float("nan")
    p = 10 ** d
    return float(np.floor(x * p + 0.5 + 1e-7) / p)


def lvlP(v, t1: float, t2: float) -> np.ndarray:
    v = _arr(v)
    out = np.zeros(len(v))
    out[v > t1] = 1
    out[v > t2] = 2
    out[v < -t1] = -1
    out[v < -t2] = -2
    out[np.isnan(v)] = 0
    return out


# ---------------------------------------------------------------- veri hazirligi

def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    hc = (o + h + l + c) / 4
    ho = np.empty_like(hc)
    ho[0] = (o[0] + c[0]) / 2
    for i in range(1, len(hc)):
        ho[i] = (ho[i - 1] + hc[i - 1]) / 2
    out = df.copy()
    out["open"], out["close"] = ho, hc
    out["high"] = np.maximum.reduce([h, ho, hc])
    out["low"] = np.minimum.reduce([l, ho, hc])
    return out


def week_start(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(idx).normalize()
    return idx - pd.to_timedelta(idx.weekday, unit="D")


def to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """Gunluk OHLCV -> haftalik (bar tarihi = pazartesi). Son hafta yarim olabilir."""
    g = df.groupby(week_start(df.index))
    w = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].last(), "volume": g["volume"].sum(),
        "last_day": g.apply(lambda x: x.index[-1], include_groups=False),
    })
    w.index.name = "date"
    return w


def m3_effective(m3: pd.Series, ek_gun: int = 0) -> pd.Series:
    """TradingView'de ECONOMICS:TRM3'un ay damgali degeri (ornek: 1 Eylul) gunluk/haftalik
    grafikte ancak o ay KAPANINCA (1 Ekim) devreye girer. Seriyi bu gecerlilik tarihine tasir."""
    m3 = m3.dropna().sort_index()
    idx = pd.DatetimeIndex(m3.index).to_period("M").to_timestamp() + pd.offsets.MonthBegin(1) + pd.Timedelta(days=ek_gun)
    return pd.Series(m3.to_numpy(float), index=idx)


def align_m3(dates, m3: pd.Series) -> np.ndarray:
    """Her tarih icin gecerlilik tarihi <= tarih olan son deger (m3_effective'ten gecmis seri)."""
    m3 = m3.dropna().sort_index()
    pos = m3.index.searchsorted(pd.DatetimeIndex(dates), side="right") - 1
    vals = m3.to_numpy(float)
    out = np.where(pos >= 0, vals[np.clip(pos, 0, None)], np.nan)
    return out


def align_series(dates, s: pd.Series) -> np.ndarray:
    """request.security benzeri: tarih <= bar tarihi olan son deger (ileri doldurma)."""
    return align_m3(dates, s)


def _live_weekly_rank(daily_dates, daily_val, wk_index, wk_val, n: int) -> np.ndarray:
    """Gun d icin: d'nin haftasindan onceki n tamamlanmis haftalik deger arasinda
    o gunku (yarim hafta) degerin percentrank'i."""
    wk_pos = wk_index.searchsorted(week_start(daily_dates), side="left")
    out = np.full(len(daily_dates), np.nan)
    for i, k in enumerate(wk_pos):
        if k < n or np.isnan(daily_val[i]):
            continue
        prev = wk_val[k - n:k]
        out[i] = 100.0 * np.sum(prev <= daily_val[i]) / n
    return out


# ---------------------------------------------------------------- motor

DEFAULTS = dict(
    pct_n=200, stop_w=55, mem_n=15, ucuz=20.0, rec_n=50, comp_n=200, comp_from="2024-01-01",
    rs_n_d=60, rs_n_w=20, mtf_n=200, macro_n=250, macro_hi=60.0, macro_lo=40.0,
    vol_n=20, kir_esik=3.5, kal5=50.0,
    # sinyal deneme ayarlari (varsayilan = v4.6 aday): hacim penceresi, dusus gun sayisi/esigi, faz kalicilik
    sig_kv=1, sig_kd=1, sig_thr=0.5, sig_m=1,
    sig_mod="v46",  # "faz": faz motoru (deneme)
    faz_m=3, faz_kr=1,
    m3_gecikme_gun=0,  # backtest icin: M3'u TCMB'nin gercek yayim tarihinden sonra kullan (or. 25 gun)
)

MACRO_SC = {"RISK-ON": 10.0, "GENISLEME": 7.0, "TOPARLANMA": 6.0, "NOTR": 5.0, "DARALMA": 3.0}
ARROW = {2: "↑↑", 1: "↑", 0: "→", -1: "↓", -2: "↓↓"}


def _pine_hist_weekly(daily_dates, wk_index, wk_last_day, wk_series) -> np.ndarray:
    """Pine gecmis bar semantigi: gun d'de son TAMAMLANMIS haftanin degeri
    (d haftanin son islem gunuyse o hafta dahil)."""
    k = wk_index.searchsorted(week_start(daily_dates), side="left")
    is_last = pd.DatetimeIndex(daily_dates).normalize() == pd.DatetimeIndex(wk_last_day[np.clip(k, 0, len(wk_last_day) - 1)]).normalize()
    kk = np.where(is_last, k, k - 1)
    out = np.where(kk >= 0, wk_series[np.clip(kk, 0, None)], np.nan)
    return out


def compute(daily: pd.DataFrame, xu100: pd.Series, m3: pd.Series, tf: str = "D",
            ha: bool = False, live_weekly: bool = True, **kw) -> pd.DataFrame:
    """daily: index=tarih, kolonlar open/high/low/close/volume (temettu duzeltmeli).
    xu100: gunluk BIST100 kapanisi. m3: aylik M3 (index = ayin 1'i).
    tf: "D" gunluk tablo, "W" haftalik tablo. ha: Heikin Ashi mumla hesapla.
    live_weekly: True = haftalik degerler canli tablo gibi (yarim hafta dahil);
                 False = Pine'in gecmis barlardaki davranisi (son tamamlanmis hafta)."""
    P = {**DEFAULTS, **kw}
    daily = daily.sort_index()
    daily = daily[~daily.index.duplicated(keep="last")].dropna(subset=["close"])
    xu100 = xu100.sort_index().dropna()
    m3 = m3_effective(m3, P["m3_gecikme_gun"])

    wk_raw = to_weekly(daily)
    wk = heikin_ashi(wk_raw) if ha else wk_raw
    dd = heikin_ashi(daily) if ha else daily

    # haftalik M3 ve haftalik degerleme (MTF icin, her iki tabloda da kullanilir)
    m3w = align_m3(wk.index, m3)
    adjW = wk["close"].to_numpy(float) / m3w
    # BIST100 haftalik (makro)
    xu_w = to_weekly(pd.DataFrame({"open": xu100, "high": xu100, "low": xu100,
                                   "close": xu100, "volume": 0.0}))["close"]

    if tf == "W":
        bars = wk
        dates = wk.index
        m3b = m3w
        xu_b = align_series(dates, xu_w)
        rs_n = P["rs_n_w"]
        stop_n = P["stop_w"]
    else:
        bars = dd
        dates = dd.index
        m3b = align_m3(dates, m3)
        xu_b = align_series(dates, xu100)
        rs_n = P["rs_n_d"]
        stop_n = P["pct_n"]

    o = bars["open"].to_numpy(float)
    h = bars["high"].to_numpy(float)
    l = bars["low"].to_numpy(float)
    c = bars["close"].to_numpy(float)
    v = bars["volume"].to_numpy(float)

    with np.errstate(invalid="ignore", divide="ignore"):
        adjC = np.where(m3b > 0, c / m3b, np.nan)
    N = P["pct_n"]
    dip = lowest(adjC, N) * m3b
    tepe = highest(adjC, N) * m3b
    pct_raw = percentrank(adjC, N)
    pct = np.where(np.isnan(pct_raw), 50.0, pct_raw)  # Pine: nz(pctM3, 50)
    value = (100 - pct) / 10
    stop = lowest(adjC, P["stop_w"]) * m3b if tf == "W" else dip

    mem = 10.0 * pd.Series((pct <= P["ucuz"]).astype(float)).rolling(P["mem_n"], min_periods=P["mem_n"]).sum().to_numpy() / P["mem_n"]

    # Compression v4.3: ATR14/kapanis, 2024 sonrasi son 200 barin min-max araligi, ters
    atrp = atr(h, l, c, 14) / c
    atrpW = np.where(dates >= pd.Timestamp(P["comp_from"]), atrp, np.nan)
    lo, hi = lowest(atrpW, P["comp_n"]), highest(atrpW, P["comp_n"])
    with np.errstate(invalid="ignore", divide="ignore"):
        comp = np.where(hi > lo, 10 * (hi - atrp) / (hi - lo), 5.0)
    comp[np.isnan(lo) | np.isnan(hi)] = np.nan
    # Pine'da lo/hi na iken (hi > lo) yanlis -> 5.0
    comp = np.where(np.isnan(comp) & ~np.isnan(atrp), 5.0, comp)

    # Recovery v4.6: M3 duzeltmeli kapanisin 50 barlik araliktaki yeri; ok: kapanisin 3 bar % degisimi
    rec = stoch(adjC, P["rec_n"])
    rec45 = stoch(c, 20)
    rec = np.where(np.isnan(rec), rec45, rec)
    recPct = 100 * (c / shift(c, 3) - 1)
    recL = lvlP(recPct, 0.5, 2.0)

    # RS: hisse/BIST100 oraninin araliktaki yeri; ok: oranin 5 bar % degisimi
    ratio = c / xu_b
    rs = stoch(ratio, rs_n)
    rsPct = 100 * (ratio / shift(ratio, 5) - 1)
    rsL = lvlP(rsPct, 2.0, 5.0)

    # Makro: BIST100 haftalik kapanisinin 250 haftalik percentrank'i (canli: yarim hafta dahil)
    xu_w_vals = xu_w.to_numpy(float)
    if tf == "W":
        xuTrend = percentrank(xu_b, P["macro_n"])
        # haftalik barlarda xu_b son haftayi zaten yarim haliyle icerir
    elif live_weekly:
        xuTrend = _live_weekly_rank(dates, xu_b, xu_w.index, xu_w_vals, P["macro_n"])
    else:
        xu_last = to_weekly(pd.DataFrame({"open": xu100, "high": xu100, "low": xu100,
                                          "close": xu100, "volume": 0.0}))["last_day"].to_numpy()
        xuTrend = _pine_hist_weekly(dates, xu_w.index, xu_last, percentrank(xu_w_vals, P["macro_n"]))
    macro = np.where(xuTrend >= P["macro_hi"], "GENISLEME",
                     np.where(xuTrend <= P["macro_lo"], "DARALMA", "NOTR")).astype(object)
    macro[np.isnan(xuTrend)] = "NOTR"
    macroSc = np.array([MACRO_SC[m] for m in macro])

    # MTF: haftalik Percentile (canli)
    if tf == "W":
        mtf = pct.copy()
    else:
        wk_pos = wk.index.searchsorted(week_start(dates), side="left")
        cur_adj = c / m3w[np.clip(wk_pos, 0, len(m3w) - 1)]
        if ha:
            # HA'da yarim haftanin HA kapanisi ayrica hesaplanmali; haftanin nihai HA kapanisi
            # kullanilir (son bar/canli tablo icin birebir, gecmis hafta ici gunler icin yaklasik)
            cur_adj = adjW[np.clip(wk_pos, 0, len(adjW) - 1)]
        if live_weekly:
            mtf_raw = _live_weekly_rank(dates, cur_adj, wk.index, adjW, P["mtf_n"])
        else:
            mtf_raw = _pine_hist_weekly(dates, wk.index, wk["last_day"].to_numpy(), percentrank(adjW, P["mtf_n"]))
        mtf = np.where(np.isnan(mtf_raw), 50.0, mtf_raw)

    with np.errstate(invalid="ignore", divide="ignore"):
        vr = v / sma(v, P["vol_n"])

    total = value + np.nan_to_num(mem) + comp + rec + macroSc + rs
    stars = np.where(total >= P["kal5"], 5, np.where(total >= 41, 4, np.where(total >= 36, 3, 2)))

    c1 = pct <= 35
    c2 = rec >= 6
    c3 = total >= 36
    c4 = mtf <= 50
    vr_s = pd.Series(vr).rolling(P["sig_kv"], min_periods=1).max().values if P["sig_kv"] > 1 else vr
    c5 = vr_s >= 1.2
    c6 = np.isin(macro, ["GENISLEME", "RISK-ON"])
    nMiss = (~c1).astype(int) + (~c2) + (~c3) + (~c4) + (~c5) + (~c6)

    chg1 = 100 * (adjC / shift(adjC, 1) - 1)
    chgk = 100 * (adjC / shift(adjC, P["sig_kd"]) - 1) if P["sig_kd"] > 1 else chg1
    prevStp = lowest(shift(adjC, 1), stop_n - 1)
    dStop = 100 * (adjC / prevStp - 1)

    sig = np.empty(len(c), dtype=object)
    for i in range(len(c)):
        if nMiss[i] == 0:
            sig[i] = "ALINABILIR"
        elif not c1[i]:
            sig[i] = "BEKLE"
        elif chgk[i] < -P["sig_thr"]:
            sig[i] = "BEKLE" if dStop[i] <= -P["kir_esik"] else "DAGITIM"
        elif nMiss[i] <= 2:
            sig[i] = "TOPLANIYOR" if rsL[i] >= 1 else "YAKIN"
        else:
            sig[i] = "BEKLE"
    if P["sig_mod"] == "faz":
        # FAZ MOTORU (deneme, 2 Kas 2026): sinyal en az faz_m bar surmeden degismez.
        # Ucuz bolgeden cikis, stop kirilmasi ve ALINABILIR hemen gecerli.
        kr = P["faz_kr"]
        rsd = rs - shift(rs, kr)
        base = np.empty(len(c), dtype=object)
        for i in range(len(c)):
            if not c1[i]:
                base[i] = "BEKLE"
            elif dStop[i] <= -P["kir_esik"]:
                base[i] = "BEKLE"
            elif nMiss[i] == 0:
                base[i] = "ALINABILIR"
            elif chgk[i] < -P["sig_thr"]:
                base[i] = "DAGITIM"
            elif nMiss[i] <= 2:
                base[i] = "TOPLANIYOR" if rsd[i] > 0 else "YAKIN"
            else:
                base[i] = "BEKLE"
        sig = base.copy()
        fm = P["faz_m"]
        for i in range(1, len(c)):
            if base[i] == "ALINABILIR" or not c1[i] or dStop[i] <= -P["kir_esik"]:
                continue
            if not all(base[j] == base[i] for j in range(max(0, i - fm + 1), i + 1)):
                sig[i] = sig[i - 1]
    m = P["sig_m"]
    if m > 1:  # faz: yeni sinyal m bar surmeden degistirme (ALINABILIR ve ucuz bolgeden cikis hemen)
        base = sig.copy()
        for i in range(1, len(c)):
            if not (base[i] == "ALINABILIR" or not c1[i] or all(base[j] == base[i] for j in range(max(0, i - m + 1), i + 1))):
                sig[i] = sig[i - 1]

    ucuz = pct <= P["ucuz"]
    macroTxt = np.array([m + (" + UCUZ" if u and m == "GENISLEME" else "") for m, u in zip(macro, ucuz)], dtype=object)

    out = pd.DataFrame({
        "open": o, "high": h, "low": l, "close": c, "volume": v, "m3": m3b, "adjC": adjC,
        "percentile": pct, "value": value, "memory": mem, "compression": comp,
        "recovery": rec, "rec_pct3": recPct, "rec_ok": recL.astype(int),
        "macro": macroTxt, "macro_base": macro, "macro_sc": macroSc, "xu_trend": xuTrend,
        "rs": rs, "rs_pct5": rsPct, "rs_ok": rsL.astype(int),
        "mtf": mtf, "hacim": vr, "toplam": total, "kalite": stars,
        "c1": c1, "c2": c2, "c3": c3, "c4": c4, "c5": c5, "c6": c6, "eksik": nMiss,
        "chg1": chg1, "degisim": 100 * (c / shift(c, 1) - 1), "d_stop": dStop, "prev_stop": prevStp * m3b,
        "sinyal": sig, "dip": dip, "tepe": tepe, "stop": stop,
    }, index=pd.DatetimeIndex(dates, name="date"))
    if tf == "W":
        out["last_day"] = wk["last_day"].to_numpy()
    return out


def missing_list(row) -> list[dict]:
    """Eksik Sartlar satiri (Zippo bicimi)."""
    items = []
    if not row["c1"]:
        items.append({"k": "Percentile", "v": rnd(row["percentile"], 1), "esik": 35.0})
    if not row["c2"]:
        items.append({"k": "Recovery", "v": rnd(row["recovery"], 1), "esik": 6.0})
    if not row["c3"]:
        items.append({"k": "Kalite", "v": rnd(row["toplam"], 1), "esik": 36.0})
    if not row["c4"]:
        items.append({"k": "MTF", "v": rnd(row["mtf"], 1), "esik": 50.0})
    if not row["c5"]:
        items.append({"k": "Hacim", "v": rnd(row["hacim"], 2), "esik": 1.2})
    if not row["c6"]:
        items.append({"k": "Macro", "v": row["macro_base"], "esik": "GENISLEME/RISK-ON"})
    return items


def table_row(row) -> dict:
    """Bir bari uygulama/JSON icin tablo bicimine cevirir."""
    f = lambda x, d: None if x is None or (isinstance(x, float) and np.isnan(x)) else rnd(x, d)
    return {
        "fiyat": f(row["close"], 2), "degisim": f(row["degisim"], 2), "percentile": f(row["percentile"], 1), "value": f(row["value"], 1),
        "memory": f(row["memory"], 1), "compression": f(row["compression"], 1),
        "recovery": f(row["recovery"], 1), "rec_ok": ARROW[int(row["rec_ok"])],
        "macro": row["macro"], "rs": f(row["rs"], 1), "rs_ok": ARROW[int(row["rs_ok"])],
        "mtf": f(row["mtf"], 1), "hacim": f(row["hacim"], 2), "toplam": f(row["toplam"], 1),
        "kalite": int(row["kalite"]), "sinyal": row["sinyal"], "eksik": missing_list(row),
        "dip": f(row["dip"], 2), "tepe": f(row["tepe"], 2), "stop": f(row["stop"], 2),
        "chg1": f(row["chg1"], 2), "d_stop": f(row["d_stop"], 2),
    }
