import yfinance as yf
import pandas as pd
import twstock
from typing import Optional


def _fetch_chinese_name(code: str) -> Optional[str]:
    try:
        info = twstock.codes.get(code)
        if info and info.name:
            return info.name
    except Exception:
        pass
    return None


def find_code_by_name(query: str) -> Optional[str]:
    query = query.strip()
    try:
        for code, info in twstock.codes.items():
            if info.name == query:
                return code
        for code, info in twstock.codes.items():
            if query in info.name:
                return code
    except Exception:
        pass
    return None


def _get_tf_data(symbol: str, interval: str, period: str) -> Optional[dict]:
    try:
        hist = yf.Ticker(symbol).history(period=period, interval=interval)
        if hist.empty or len(hist) < 5:
            return None
        hist = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
        hist["MA5"] = hist["Close"].rolling(5).mean()
        hist["MA20"] = hist["Close"].rolling(20).mean()
        hist["MA60"] = hist["Close"].rolling(60).mean()
        latest = hist.iloc[-1]
        ma60 = latest["MA60"] if not pd.isna(latest["MA60"]) else None
        return {
            "price": latest["Close"],
            "ma5": float(latest["MA5"]),
            "ma20": float(latest["MA20"]),
            "ma60": float(ma60) if ma60 is not None else None,
            "hist": hist,
        }
    except Exception:
        return None


def get_stock_data(code: str) -> Optional[dict]:
    symbol = None
    hist = pd.DataFrame()

    for suffix in [".TW", ".TWO"]:
        sym = f"{code}{suffix}"
        try:
            ticker = yf.Ticker(sym)
            h = ticker.history(period="6mo")
            if not h.empty and len(h) >= 5:
                symbol = sym
                hist = h
                break
        except Exception:
            continue

    if symbol is None or hist.empty or len(hist) < 5:
        return None

    hist = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
    hist.index = pd.to_datetime(hist.index).tz_localize(None)
    hist["MA5"] = hist["Close"].rolling(5).mean()
    hist["MA20"] = hist["Close"].rolling(20).mean()
    hist["MA60"] = hist["Close"].rolling(60).mean()

    latest = hist.iloc[-1]
    prev = hist.iloc[-2]
    change = latest["Close"] - prev["Close"]
    change_pct = change / prev["Close"] * 100
    ma60 = float(latest["MA60"]) if not pd.isna(latest["MA60"]) else None

    name = _fetch_chinese_name(code)
    if not name:
        try:
            info = yf.Ticker(symbol).info
            name = info.get("shortName") or info.get("longName") or code
        except Exception:
            name = code
    if len(name) > 30:
        name = name[:28] + ".."

    tf = {
        "1d": {
            "price": float(latest["Close"]),
            "ma5": float(latest["MA5"]),
            "ma20": float(latest["MA20"]),
            "ma60": ma60,
            "hist": hist,
        },
        "60m": _get_tf_data(symbol, "60m", "30d"),
        "5m": _get_tf_data(symbol, "5m", "5d"),
    }

    avg_vol_raw = hist["Volume"].rolling(20).mean().iloc[-1]
    avg_volume = int(avg_vol_raw) if not pd.isna(avg_vol_raw) else int(latest["Volume"])

    return {
        "name": name,
        "code": code,
        "symbol": symbol,
        "price": float(latest["Close"]),
        "change": float(change),
        "change_pct": float(change_pct),
        "high": float(latest["High"]),
        "low": float(latest["Low"]),
        "volume": int(latest["Volume"]),
        "avg_volume": avg_volume,
        "ma5": float(latest["MA5"]),
        "ma20": float(latest["MA20"]),
        "ma60": ma60,
        "hist": hist,
        "tf": tf,
    }


def get_trend(price: float, ma5: float, ma20: float, ma60: Optional[float]) -> str:
    if ma60 and price > ma5 > ma20 > ma60:
        return "強勢多頭 📈"
    if price > ma5 > ma20:
        return "多頭 📈"
    if ma60 and price < ma5 < ma20 < ma60:
        return "強勢空頭 📉"
    if price < ma5 < ma20:
        return "空頭 📉"
    return "震盪 ↔️"


def _tf_alignment(ma5: float, ma20: float, ma60: Optional[float]) -> str:
    if ma60:
        if ma5 > ma20 > ma60:
            return "多頭排列"
        if ma5 < ma20 < ma60:
            return "空頭排列"
        if ma5 > ma20 and ma20 < ma60:
            return "短多長空"
        if ma5 < ma20 and ma20 > ma60:
            return "短空長多"
        return "均線糾結"
    return "短中多頭" if ma5 > ma20 else "短中空頭" if ma5 < ma20 else "均線持平"


def _cross_signal(hist: pd.DataFrame, ma5: float, ma20: float) -> str:
    if len(hist) < 3:
        return ""
    prev_ma5 = hist["MA5"].iloc[-2]
    prev_ma20 = hist["MA20"].iloc[-2]
    if pd.isna(prev_ma5) or pd.isna(prev_ma20):
        return ""
    if prev_ma5 <= prev_ma20 and ma5 > ma20:
        return "黃金交叉 ⚡"
    if prev_ma5 >= prev_ma20 and ma5 < ma20:
        return "死亡交叉 ⚡"
    return ""


_ALIGN_ICON = {
    "多頭排列": "📈", "短中多頭": "↗️", "短多長空": "↗️",
    "空頭排列": "📉", "短中空頭": "↘️", "短空長多": "↘️",
    "均線糾結": "↔️", "均線持平": "↔️",
}


def get_mtf_ma_analysis(tf: dict) -> str:
    lines = []
    cross_signals = []

    for label, key in [("日K ", "1d"), ("60分", "60m"), ("5分 ", "5m")]:
        d = tf.get(key)
        if d is None:
            lines.append(f"`{label}` ─ 資料不足")
            continue

        price, ma5, ma20, ma60, hist = d["price"], d["ma5"], d["ma20"], d["ma60"], d["hist"]
        align = _tf_alignment(ma5, ma20, ma60)
        icon = _ALIGN_ICON.get(align, "↔️")

        spread_pct = abs(ma5 - ma20) / ma20 * 100
        conv = "（收斂）" if spread_pct < 0.5 else "（擴散）" if spread_pct > 3 else ""

        p5  = "✅" if price > ma5  else "❌"
        p20 = "✅" if price > ma20 else "❌"
        p60 = ("✅" if price > ma60 else "❌") if ma60 else "─"

        lines.append(f"`{label}` {icon} {align}{conv}　5{p5} 20{p20} 60{p60}")

        sig = _cross_signal(hist, ma5, ma20)
        if sig:
            cross_signals.append(f"⚡ {label.strip()} {sig}")

    if cross_signals:
        lines.append("　".join(cross_signals))

    return "\n".join(lines)


def get_detailed_reading(
    change_pct: float, price: float,
    ma5: float, ma20: float, ma60: Optional[float],
    volume: int, avg_volume: int,
) -> str:
    lines = []
    sign = "+" if change_pct >= 0 else ""
    vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0

    # ── K棒 × 成交量：法人/散戶行為判讀 ──
    if vol_ratio >= 1.5:
        vol_tag = "量增"
        if change_pct > 1.5:
            vol_read = "法人積極買超，主力主導上攻"
        elif change_pct < -1.5:
            vol_read = "法人出貨訊號明顯，散戶承接風險高"
        else:
            vol_read = "大量盤整，多空量力相當，方向待確認"
    elif vol_ratio <= 0.7:
        vol_tag = "量縮"
        if change_pct > 1.5:
            vol_read = "散戶推動為主，力道偏弱，謹慎追高"
        elif change_pct < -1.5:
            vol_read = "市場觀望，空頭能量未盡，下跌仍有空間"
        else:
            vol_read = "法人觀望，市場缺乏方向性資金"
    else:
        vol_tag = "量平"
        if change_pct > 2:
            vol_read = "量價同步，多頭延續，趨勢健康"
        elif change_pct < -2:
            vol_read = "正常量能下跌，空頭壓力真實存在"
        else:
            vol_read = "無異常量能，盤整整理格局"

    lines.append(f"**K棒**　今日 {sign}{change_pct:.1f}%　{vol_tag}（{vol_ratio:.1f}x）→ {vol_read}")

    # ── 均線支撐壓力 ──
    if price > ma5 and price > ma20:
        ma_read = "站穩雙均線，多層支撐有效"
    elif price < ma5 and price < ma20:
        ma_read = "跌破雙均線，均線反壓，偏空操作"
    elif price > ma5 and price < ma20:
        ma_read = "守 MA5 但受 MA20 壓制，突破方為確認"
    else:
        ma_read = "跌破 MA5，MA20 尚支撐，短弱中穩"

    if ma60:
        ma60_read = "MA60 長線支撐成立" if price > ma60 else "跌破 MA60，長線趨勢轉弱"
        lines.append(f"**均線**　{ma_read}　{ma60_read}")
    else:
        lines.append(f"**均線**　{ma_read}")

    # ── 全盤面思維評估 ──
    bull = sum([price > ma5, price > ma20, bool(ma60 and price > ma60), ma5 > ma20, change_pct > 0])
    if bull >= 4:
        view = "多方優勢明確，趨勢健康，順勢操作為主"
    elif bull == 3:
        view = "偏多但需驗證，回踩均線為主要買點策略"
    elif bull == 2:
        view = "多空拉鋸，觀望為宜，等待方向確立"
    elif bull == 1:
        view = "偏空格局，保守應對，輕倉或空手觀望"
    else:
        view = "空方主導，趨勢明確偏空，避免逆勢操作"

    lines.append(f"**評估**　{view}")

    return "\n".join(lines)


def get_mtf_summary(tf: dict, daily_price: float, daily_ma5: float, daily_ma20: float, daily_ma60: Optional[float], change_pct: float) -> str:
    def _score(d: dict) -> int:
        if d is None:
            return -1
        p, ma5, ma20, ma60 = d["price"], d["ma5"], d["ma20"], d["ma60"]
        s = 0
        if p > ma5: s += 1
        if p > ma20: s += 1
        if ma60 and p > ma60: s += 1
        if ma5 > ma20: s += 1
        return s

    daily_s = _score(tf.get("1d"))
    m60_s = _score(tf.get("60m"))
    m5_s = _score(tf.get("5m"))

    if daily_s >= 3:
        bias, emoji = "日線偏多", "📗"
    elif daily_s == 2:
        bias, emoji = "日線中性", "📘"
    else:
        bias, emoji = "日線偏空", "📕"

    if m5_s >= 0 and m60_s >= 0:
        if m5_s >= 3 and m60_s >= 3:
            intraday = "短線動能一致偏多"
        elif m5_s <= 1 and m60_s <= 1:
            intraday = "短線動能一致偏空"
        elif m5_s >= 3 and m60_s <= 1:
            intraday = "5分走強但60分仍弱，需確認延續"
        elif m5_s <= 1 and m60_s >= 3:
            intraday = "5分回落，60分仍多，可觀察回踩買點"
        else:
            intraday = "短線多空交錯，方向待確認"
    else:
        intraday = ""

    support, resist = [], []
    for label, val in [("MA5", daily_ma5), ("MA20", daily_ma20), ("MA60", daily_ma60)]:
        if val is None:
            continue
        (support if val < daily_price else resist).append(f"{label} {val:.2f}")

    lines = [f"{emoji} {bias}" + (f"，{intraday}" if intraday else "")]
    if support:
        lines.append(f"支撐：{' / '.join(support)}")
    if resist:
        lines.append(f"壓力：{' / '.join(resist)}")

    return "\n".join(lines)
