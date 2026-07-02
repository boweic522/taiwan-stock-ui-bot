"""
market_data.py
特殊市場項目資料層：加權、櫃買、小台。

修正版重點：
1. 查詢 alias 更完整。
2. yfinance 抓不到 K 線時，改用 Yahoo 台股/期貨頁抓文字報價，至少讓卡片可顯示。
3. main.py 會在圖表失敗時改送文字卡，所以大盤項目不會因為圖表失敗整個不回覆。
"""

from __future__ import annotations

import html
import math
import re
from datetime import datetime, timedelta
from typing import Optional, Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf


SPECIAL_MARKETS: dict[str, dict[str, Any]] = {
    # 加權指數
    "加權": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWII"},
    "大盤": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWII"},
    "台股": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWII"},
    "加權指數": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWII"},
    "twii": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWII"},
    "taiex": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWII"},
    "上市": {"display_name": "加權指數", "code": "^TWII", "symbol": "^TWII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWII"},

    # 櫃買指數
    "櫃買": {"display_name": "櫃買指數", "code": "^TWOII", "symbol": "^TWOII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWOII"},
    "上櫃": {"display_name": "櫃買指數", "code": "^TWOII", "symbol": "^TWOII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWOII"},
    "櫃買指數": {"display_name": "櫃買指數", "code": "^TWOII", "symbol": "^TWOII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWOII"},
    "上櫃指數": {"display_name": "櫃買指數", "code": "^TWOII", "symbol": "^TWOII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWOII"},
    "otc": {"display_name": "櫃買指數", "code": "^TWOII", "symbol": "^TWOII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWOII"},
    "twoii": {"display_name": "櫃買指數", "code": "^TWOII", "symbol": "^TWOII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWOII"},
    "tpex": {"display_name": "櫃買指數", "code": "^TWOII", "symbol": "^TWOII", "asset_type": "index", "quote_url": "https://tw.stock.yahoo.com/quote/%5ETWOII"},

    # 小型台指近一。K 線暫用加權作為技術結構參考；即時價抓 Yahoo 期貨頁。
    "小台": {"display_name": "小型臺指期貨近月", "code": "WMT&", "symbol": "^TWII", "asset_type": "future", "future_symbol": "WMT&", "quote_url": "https://tw.stock.yahoo.com/future/WMT%26", "proxy_note": "小台＝小型臺指期貨近月；K線結構暫以加權指數代理"},
    "小台指": {"display_name": "小型臺指期貨近月", "code": "WMT&", "symbol": "^TWII", "asset_type": "future", "future_symbol": "WMT&", "quote_url": "https://tw.stock.yahoo.com/future/WMT%26", "proxy_note": "小台＝小型臺指期貨近月；K線結構暫以加權指數代理"},
    "小型臺指期貨近月": {"display_name": "小型臺指期貨近月", "code": "WMT&", "symbol": "^TWII", "asset_type": "future", "future_symbol": "WMT&", "quote_url": "https://tw.stock.yahoo.com/future/WMT%26", "proxy_note": "小台＝小型臺指期貨近月；K線結構暫以加權指數代理"},
    "小型台指": {"display_name": "小型臺指期貨近月", "code": "WMT&", "symbol": "^TWII", "asset_type": "future", "future_symbol": "WMT&", "quote_url": "https://tw.stock.yahoo.com/future/WMT%26", "proxy_note": "小台＝小型臺指期貨近月；K線結構暫以加權指數代理"},
    "mtx": {"display_name": "小型臺指期貨近月", "code": "WMT&", "symbol": "^TWII", "asset_type": "future", "future_symbol": "WMT&", "quote_url": "https://tw.stock.yahoo.com/future/WMT%26", "proxy_note": "小台＝小型臺指期貨近月；K線結構暫以加權指數代理"},
    "wmt": {"display_name": "小型臺指期貨近月", "code": "WMT&", "symbol": "^TWII", "asset_type": "future", "future_symbol": "WMT&", "quote_url": "https://tw.stock.yahoo.com/future/WMT%26", "proxy_note": "小台＝小型臺指期貨近月；K線結構暫以加權指數代理"},
    "wmt&": {"display_name": "小型臺指期貨近月", "code": "WMT&", "symbol": "^TWII", "asset_type": "future", "future_symbol": "WMT&", "quote_url": "https://tw.stock.yahoo.com/future/WMT%26", "proxy_note": "小台＝小型臺指期貨近月；K線結構暫以加權指數代理"},
}


def normalize_market_query(query: str) -> str:
    return (query or "").strip().lower().replace(" ", "").replace("　", "")


def resolve_special_market(query: str) -> Optional[dict[str, Any]]:
    return SPECIAL_MARKETS.get(normalize_market_query(query))


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
    return _num(series.tail(n).mean())


def _tf_payload(hist: pd.DataFrame) -> Optional[dict[str, Any]]:
    df = _clean_hist(hist)
    if df.empty:
        return None
    close = df["Close"].astype(float)
    latest = _num(close.iloc[-1])
    if latest is None:
        return None
    return {"hist": df, "price": latest, "ma5": _ma(close, 5), "ma20": _ma(close, 20), "ma60": _ma(close, 60)}


def _history(symbol: str, period: str, interval: str) -> pd.DataFrame:
    try:
        return _clean_hist(yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=False))
    except Exception:
        return pd.DataFrame()


def _fetch_url_text(url: str) -> str:
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=8) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        raw = html.unescape(raw)
        text = re.sub(r"<[^>]+>", " ", raw)
        return re.sub(r"\s+", " ", text)
    except Exception:
        return ""


def _extract_number(text: str, labels: list[str]) -> Optional[float]:
    for label in labels:
        # Yahoo 台股頁常見：成交32,572.43 / 最高33,497.58 / 漲跌599.00
        m = re.search(rf"{re.escape(label)}\s*([+-]?\d[\d,]*(?:\.\d+)?)", text)
        if m:
            return _num(m.group(1))
    return None


def _fetch_yahoo_quote_page(url: str, *, is_future: bool = False) -> dict[str, Any]:
    text = _fetch_url_text(url)
    if not text:
        return {}

    price = _extract_number(text, ["成交", "最後成交價", "成交價"])
    high = _extract_number(text, ["最高"])
    low = _extract_number(text, ["最低"])
    open_ = _extract_number(text, ["開盤"])
    prev = _extract_number(text, ["昨收", "參考價"])
    change = _extract_number(text, ["漲跌"])
    change_pct = _extract_number(text, ["漲幅", "漲跌幅"])
    volume = _extract_number(text, ["總量", "成交量", "成交金額"])

    # 指數頁有時 search 到的第一個成交不是主成交，用保守條件補救：至少要有最高/最低。 
    if price is None and prev is not None and change is not None:
        price = prev + change
    if price is None:
        return {}
    if change is None and prev is not None:
        change = price - prev
    if change_pct is None and change is not None and prev not in (None, 0):
        change_pct = change / prev * 100

    return {
        "price": price,
        "open": open_,
        "high": high,
        "low": low,
        "prev": prev,
        "change": change,
        "change_pct": change_pct,
        "volume": volume,
        "quote_quality": "Yahoo台股頁報價" if not is_future else "Yahoo期貨頁報價",
        "quote_url": url,
    }


def _synthetic_hist(quote: dict[str, Any]) -> pd.DataFrame:
    """報價頁可用但 K 線不可用時，建立最小資料，讓文字卡可正常顯示。"""
    price = _num(quote.get("price"))
    if price is None:
        return pd.DataFrame()
    prev = _num(quote.get("prev"))
    high = _num(quote.get("high")) or price
    low = _num(quote.get("low")) or price
    open_ = _num(quote.get("open")) or prev or price
    vol = _num(quote.get("volume")) or 0.0
    idx = [pd.Timestamp(datetime.now() - timedelta(days=1)), pd.Timestamp(datetime.now())]
    if prev is None:
        prev = open_
    return pd.DataFrame(
        [
            {"Open": prev, "High": max(prev, open_), "Low": min(prev, open_), "Close": prev, "Volume": vol},
            {"Open": open_, "High": high, "Low": low, "Close": price, "Volume": vol},
        ],
        index=idx,
    )


def _patch_latest_candle(hist: pd.DataFrame, quote: dict[str, Any]) -> pd.DataFrame:
    """用報價頁最新價校正最後一根 K，讓大盤/小台文字判斷更接近即時。"""
    if hist is None or hist.empty or not quote:
        return hist
    price = _num(quote.get("price"))
    if price is None:
        return hist
    high = _num(quote.get("high")) or price
    low = _num(quote.get("low")) or price
    try:
        df = hist.copy()
        idx = df.index[-1]
        old_high = _num(df.at[idx, "High"]) or price
        old_low = _num(df.at[idx, "Low"]) or price
        df.at[idx, "Close"] = price
        df.at[idx, "High"] = max(old_high, high, price)
        df.at[idx, "Low"] = min(old_low, low, price)
        if quote.get("volume") is not None:
            df.at[idx, "Volume"] = _num(quote.get("volume")) or df.at[idx, "Volume"]
        return df
    except Exception:
        return hist


def _patch_tf_with_quote(tf_payload: Optional[dict[str, Any]], quote: dict[str, Any]) -> Optional[dict[str, Any]]:
    if not tf_payload:
        return tf_payload
    patched_hist = _patch_latest_candle(tf_payload.get("hist"), quote)
    close = patched_hist["Close"].astype(float) if patched_hist is not None and not patched_hist.empty else None
    price = _num(quote.get("price")) or tf_payload.get("price")
    tf_payload["hist"] = patched_hist
    tf_payload["price"] = price
    if close is not None:
        tf_payload["ma5"] = _ma(close, 5)
        tf_payload["ma20"] = _ma(close, 20)
        tf_payload["ma60"] = _ma(close, 60)
    return tf_payload


def _patch_with_quote(data: dict[str, Any], quote: dict[str, Any]) -> dict[str, Any]:
    if not quote:
        return data
    for key in ("price", "change", "change_pct", "high", "low"):
        if quote.get(key) is not None:
            data[key] = quote[key]
    if quote.get("volume") is not None:
        data["volume"] = int(quote["volume"])
    data["quote_quality"] = quote.get("quote_quality", data.get("quote_quality"))
    data["quote_url"] = quote.get("quote_url")
    return data


def get_special_market_data(query: str) -> Optional[dict[str, Any]]:
    spec = resolve_special_market(query)
    if not spec:
        return None

    symbol = spec["symbol"]
    quote = _fetch_yahoo_quote_page(spec.get("quote_url", ""), is_future=spec.get("asset_type") == "future")

    daily = _history(symbol, "6mo", "1d")
    if daily.empty:
        daily = _synthetic_hist(quote)
    if daily.empty:
        return None

    h60 = _history(symbol, "60d", "60m")
    m5 = _history(symbol, "5d", "5m")

    close = daily["Close"].astype(float)
    price = _num(close.iloc[-1])
    prev = _num(close.iloc[-2]) if len(close) >= 2 else _num(quote.get("prev"))
    high = _num(daily["High"].iloc[-1])
    low = _num(daily["Low"].iloc[-1])
    volume = _num(daily["Volume"].iloc[-1]) or 0.0
    avg_volume = _num(daily["Volume"].tail(20).mean()) or max(volume, 1.0)
    change = (price - prev) if price is not None and prev not in (None, 0) else (_num(quote.get("change")) or 0.0)
    change_pct = (change / prev * 100) if prev not in (None, 0) else (_num(quote.get("change_pct")) or 0.0)

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

    data = _patch_with_quote(data, quote)

    # 報價頁比 yfinance 更新時，用最新報價校正最後一根K。
    if quote.get("price") is not None:
        data["hist"] = _patch_latest_candle(data.get("hist"), quote)
        close2 = data["hist"]["Close"].astype(float) if data.get("hist") is not None and not data["hist"].empty else close
        data["ma5"] = _ma(close2, 5)
        data["ma20"] = _ma(close2, 20)
        data["ma60"] = _ma(close2, 60)
        for tf_key in ("1d", "60m", "5m"):
            if data["tf"].get(tf_key):
                data["tf"][tf_key] = _patch_tf_with_quote(data["tf"][tf_key], quote)
        data["kline_quality"] = "即時報價校正K線"
        data["realtime_kline"] = True
    else:
        data.setdefault("kline_quality", "Yahoo K線")
        data.setdefault("realtime_kline", False)

    return data
