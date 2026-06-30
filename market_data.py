"""
market_data.py
特殊市場項目資料層：加權、櫃買、小台。
目的：讓 /K加權、/K櫃買、/K小台 也能走同一套 trade_view UI。
"""

from __future__ import annotations

import html
import math
import re
from typing import Optional, Any
from urllib.parse import quote

import pandas as pd
import yfinance as yf


SPECIAL_MARKETS: dict[str, dict[str, Any]] = {
    # 加權指數
    "加權": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index"},
    "大盤": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index"},
    "台股": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index"},
    "加權指數": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index"},
    "twii": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index"},
    "taiex": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index"},

    # 櫃買指數
    "櫃買": {"display_name": "櫃買指數", "code": "^TWOII", "symbol": "^TWOII", "asset_type": "index"},
    "上櫃": {"display_name": "櫃買指數", "code": "^TWOII", "symbol": "^TWOII", "asset_type": "index"},
    "櫃買指數": {"display_name": "櫃買指數", "code": "^TWOII", "symbol": "^TWOII", "asset_type": "index"},
    "otc": {"display_name": "櫃買指數", "code": "^TWOII", "symbol": "^TWOII", "asset_type": "index"},
    "twoii": {"display_name": "櫃買指數", "code": "^TWOII", "symbol": "^TWOII", "asset_type": "index"},

    # 小型台指近一。K 線先用加權作為技術結構參考；即時價盡量抓 Yahoo 期貨頁。
    "小台": {
        "display_name": "小台指近一",
        "code": "WMT&",
        "symbol": "^TWII",
        "asset_type": "future",
        "future_symbol": "WMT&",
        "proxy_note": "小台即時報價；K線結構暫以加權指數代理",
    },
    "小台指": {
        "display_name": "小台指近一",
        "code": "WMT&",
        "symbol": "^TWII",
        "asset_type": "future",
        "future_symbol": "WMT&",
        "proxy_note": "小台即時報價；K線結構暫以加權指數代理",
    },
    "小型台指": {
        "display_name": "小台指近一",
        "code": "WMT&",
        "symbol": "^TWII",
        "asset_type": "future",
        "future_symbol": "WMT&",
        "proxy_note": "小台即時報價；K線結構暫以加權指數代理",
    },
    "mtx": {
        "display_name": "小台指近一",
        "code": "WMT&",
        "symbol": "^TWII",
        "asset_type": "future",
        "future_symbol": "WMT&",
        "proxy_note": "小台即時報價；K線結構暫以加權指數代理",
    },
}


def normalize_market_query(query: str) -> str:
    return (query or "").strip().lower().replace(" ", "")


def resolve_special_market(query: str) -> Optional[dict[str, Any]]:
    key = normalize_market_query(query)
    return SPECIAL_MARKETS.get(key)


def is_special_market_query(query: str) -> bool:
    return resolve_special_market(query) is not None


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _clean_hist(hist: pd.DataFrame) -> pd.DataFrame:
    if hist is None or hist.empty:
        return pd.DataFrame()
    df = hist.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    needed = ["Open", "High", "Low", "Close", "Volume"]
    for col in needed:
        if col not in df.columns:
            df[col] = 0.0
    df = df[needed].dropna(subset=["Open", "High", "Low", "Close"])
    return df


def _ma(series: pd.Series, n: int) -> Optional[float]:
    if series is None or len(series) < n:
        return None
    v = series.tail(n).mean()
    return _num(v)


def _tf_payload(hist: pd.DataFrame) -> Optional[dict[str, Any]]:
    df = _clean_hist(hist)
    if df.empty:
        return None
    close = df["Close"].astype(float)
    latest = _num(close.iloc[-1])
    if latest is None:
        return None
    return {
        "hist": df,
        "price": latest,
        "ma5": _ma(close, 5),
        "ma20": _ma(close, 20),
        "ma60": _ma(close, 60),
    }


def _history(symbol: str, period: str, interval: str) -> pd.DataFrame:
    try:
        return _clean_hist(yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False))
    except Exception:
        return pd.DataFrame()


def _extract_number(text: str, labels: list[str]) -> Optional[float]:
    for label in labels:
        m = re.search(rf"{re.escape(label)}\s*([+-]?\d[\d,]*(?:\.\d+)?)", text)
        if m:
            return _num(m.group(1))
    return None


def _fetch_yahoo_future_quote(future_symbol: str) -> dict[str, Any]:
    """嘗試抓 Yahoo 台灣期貨單頁報價；失敗就回空 dict。"""
    try:
        import requests  # type: ignore
    except Exception:
        return {}

    url = f"https://tw.stock.yahoo.com/future/{quote(future_symbol, safe='')}"
    try:
        resp = requests.get(url, timeout=6, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code >= 400:
            return {}
        raw = html.unescape(resp.text)
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text)
    except Exception:
        return {}

    price = _extract_number(text, ["成交", "最後成交價", "成交價"])
    high = _extract_number(text, ["最高"])
    low = _extract_number(text, ["最低"])
    prev = _extract_number(text, ["參考價", "昨收"])
    change = _extract_number(text, ["漲跌"])
    change_pct = _extract_number(text, ["漲幅", "漲跌幅"])
    volume = _extract_number(text, ["總量", "成交量"])

    if price is None:
        return {}
    if change is None and prev is not None:
        change = price - prev
    if change_pct is None and change is not None and prev not in (None, 0):
        change_pct = change / prev * 100

    return {
        "price": price,
        "high": high,
        "low": low,
        "change": change,
        "change_pct": change_pct,
        "volume": volume,
        "quote_quality": "Yahoo期貨頁報價",
        "quote_url": url,
    }


def get_special_market_data(query: str) -> Optional[dict[str, Any]]:
    spec = resolve_special_market(query)
    if not spec:
        return None

    symbol = spec["symbol"]
    daily = _history(symbol, "6mo", "1d")
    if daily.empty:
        return None

    h60 = _history(symbol, "60d", "60m")
    m5 = _history(symbol, "5d", "5m")

    close = daily["Close"].astype(float)
    price = _num(close.iloc[-1])
    prev = _num(close.iloc[-2]) if len(close) >= 2 else None
    high = _num(daily["High"].iloc[-1])
    low = _num(daily["Low"].iloc[-1])
    volume = _num(daily["Volume"].iloc[-1]) or 0.0
    avg_volume = _num(daily["Volume"].tail(20).mean()) or 0.0
    change = (price - prev) if price is not None and prev not in (None, 0) else 0.0
    change_pct = (change / prev * 100) if prev not in (None, 0) else 0.0

    tf1d = _tf_payload(daily)
    tf60 = _tf_payload(h60) or tf1d
    tf5 = _tf_payload(m5) or tf60 or tf1d

    data: dict[str, Any] = {
        "code": spec["code"],
        "name": spec["display_name"],
        "display_name": spec["display_name"],
        "symbol": symbol,
        "asset_type": spec.get("asset_type", "index"),
        "hist": daily,
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "high": high,
        "low": low,
        "volume": int(volume),
        "avg_volume": int(avg_volume) if avg_volume else 1,
        "ma5": _ma(close, 5),
        "ma20": _ma(close, 20),
        "ma60": _ma(close, 60),
        "tf": {"1d": tf1d, "60m": tf60, "5m": tf5},
        "quote_quality": "Yahoo Finance報價",
        "quote_note": spec.get("proxy_note", ""),
    }

    if spec.get("asset_type") == "future":
        quote_data = _fetch_yahoo_future_quote(spec.get("future_symbol", ""))
        if quote_data:
            for key in ("price", "change", "change_pct", "high", "low"):
                if quote_data.get(key) is not None:
                    data[key] = quote_data[key]
            if quote_data.get("volume") is not None:
                data["volume"] = int(quote_data["volume"])
            data["quote_quality"] = quote_data.get("quote_quality", "Yahoo期貨頁報價")
            data["quote_url"] = quote_data.get("quote_url")
            # 小台即時價和加權 proxy 的均線接近但不完全相同；讓 tf price 也跟著最新價，避免分數完全用舊價。
            for tf_key in ("1d", "60m", "5m"):
                if data["tf"].get(tf_key):
                    data["tf"][tf_key]["price"] = data["price"]

    return data
