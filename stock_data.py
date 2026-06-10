import yfinance as yf
import pandas as pd
from typing import Optional


def get_stock_data(code: str) -> Optional[dict]:
    for suffix in [".TW", ".TWO"]:
        symbol = f"{code}{suffix}"
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="6mo")
            if not hist.empty and len(hist) >= 5:
                break
        except Exception:
            hist = pd.DataFrame()
    else:
        return None

    if hist.empty or len(hist) < 5:
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

    try:
        info = ticker.info
        name = info.get("shortName") or info.get("longName") or code
        if len(name) > 30:
            name = name[:28] + ".."
    except Exception:
        name = code

    ma60 = latest["MA60"] if not pd.isna(latest["MA60"]) else None

    return {
        "name": name,
        "code": code,
        "symbol": symbol,
        "price": latest["Close"],
        "change": change,
        "change_pct": change_pct,
        "high": latest["High"],
        "low": latest["Low"],
        "volume": int(latest["Volume"]),
        "ma5": latest["MA5"],
        "ma20": latest["MA20"],
        "ma60": ma60,
        "hist": hist,
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


def get_reading(change_pct: float, trend: str) -> str:
    if change_pct > 5:
        return "強力上攻，短線追高注意風險"
    if change_pct > 2:
        return "多頭延續，可觀察回踩均線機會"
    if change_pct > 0.5:
        return "小幅收紅，趨勢偏多"
    if change_pct < -5:
        return "明顯下殺，注意支撐是否守住"
    if change_pct < -2:
        return "空頭壓力，觀察是否跌破關鍵均線"
    if change_pct < -0.5:
        return "小幅收黑，短線偏弱"
    return "盤整格局，等待方向確立"
