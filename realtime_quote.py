"""
realtime_quote.py
個股即時報價與 K 線校正層。

目的：
- 主畫面價格優先使用 twstock.realtime。
- 若拿到即時價，將日K / 60分K / 5分K 最新一根 K 的 Close/High/Low 以即時價校正，
  讓 trade_view 的判斷比較接近「即時K線判斷」。
- 無法取得即時報價時，保留原 Yahoo/yfinance 資料，不硬判斷。
"""

from __future__ import annotations

import math
from typing import Optional, Any

import pandas as pd


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        text = str(value).strip().replace(",", "").replace("%", "")
        if text in ("", "-", "--", "None", "none", "nan"):
            return None
        f = float(text)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _plain_code(code: object) -> str:
    raw = str(code or "").upper().strip()
    return raw.replace(".TW", "").replace(".TWO", "")


def _recalc_ma_from_hist(hist: Any) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if hist is None or getattr(hist, "empty", True):
        return None, None, None
    try:
        close = hist["Close"].astype(float)
        ma5 = _num(close.tail(5).mean()) if len(close) >= 5 else None
        ma20 = _num(close.tail(20).mean()) if len(close) >= 20 else None
        ma60 = _num(close.tail(60).mean()) if len(close) >= 60 else None
        return ma5, ma20, ma60
    except Exception:
        return None, None, None


def _patch_latest_candle(hist: Any, price: float, high: Optional[float] = None, low: Optional[float] = None) -> Any:
    """用即時價校正最後一根K，不新增假K，只修正最新 Close / High / Low。"""
    if hist is None or getattr(hist, "empty", True):
        return hist
    try:
        df = hist.copy()
        idx = df.index[-1]
        old_high = _num(df.at[idx, "High"]) or price
        old_low = _num(df.at[idx, "Low"]) or price
        patched_high = max(old_high, price, high if high is not None else price)
        patched_low = min(old_low, price, low if low is not None else price)
        df.at[idx, "Close"] = price
        df.at[idx, "High"] = patched_high
        df.at[idx, "Low"] = patched_low
        return df
    except Exception:
        return hist


def _patch_tf_payload(tf_payload: dict, price: float, high: Optional[float], low: Optional[float]) -> None:
    if not isinstance(tf_payload, dict):
        return
    hist = tf_payload.get("hist")
    patched_hist = _patch_latest_candle(hist, price, high, low)
    tf_payload["hist"] = patched_hist
    tf_payload["price"] = price
    ma5, ma20, ma60 = _recalc_ma_from_hist(patched_hist)
    if ma5 is not None:
        tf_payload["ma5"] = ma5
    if ma20 is not None:
        tf_payload["ma20"] = ma20
    if ma60 is not None:
        tf_payload["ma60"] = ma60


def _patch_all_kline(data: dict, price: float, high: Optional[float], low: Optional[float]) -> None:
    data["hist"] = _patch_latest_candle(data.get("hist"), price, high, low)
    ma5, ma20, ma60 = _recalc_ma_from_hist(data.get("hist"))
    if ma5 is not None:
        data["ma5"] = ma5
    if ma20 is not None:
        data["ma20"] = ma20
    if ma60 is not None:
        data["ma60"] = ma60

    tf = data.get("tf") or {}
    for key in ("1d", "60m", "5m"):
        if isinstance(tf.get(key), dict):
            _patch_tf_payload(tf[key], price, high, low)


def patch_realtime_quote(data: dict, code: str | None = None) -> dict:
    """盡量把個股主畫面報價與最新 K 線判斷改成 twstock 即時校正；失敗則保留原資料。"""
    if not data:
        return data

    # 指數與期貨走 market_data.py，不在這裡處理。
    if data.get("asset_type") in ("index", "future"):
        data.setdefault("quote_quality", "Yahoo Finance報價")
        data.setdefault("kline_quality", "Yahoo K線")
        data.setdefault("realtime_kline", False)
        return data

    plain = _plain_code(code or data.get("code"))
    if not plain.isdigit():
        data.setdefault("quote_quality", "Yahoo Finance報價")
        data.setdefault("kline_quality", "Yahoo K線")
        data.setdefault("realtime_kline", False)
        return data

    try:
        import twstock  # type: ignore
        rt = twstock.realtime.get(plain)
    except Exception:
        data.setdefault("quote_quality", "Yahoo Finance報價")
        data.setdefault("kline_quality", "Yahoo K線")
        data.setdefault("realtime_kline", False)
        return data

    if not rt or not rt.get("success"):
        data.setdefault("quote_quality", "Yahoo Finance報價")
        data.setdefault("kline_quality", "Yahoo K線")
        data.setdefault("realtime_kline", False)
        return data

    info = rt.get("info") or {}
    realtime = rt.get("realtime") or {}

    price = _num(realtime.get("latest_trade_price"))
    if price is None:
        # 有些時段 latest_trade_price 會是 '-'，退而求其次用最佳買/賣中間價。
        bid_raw = realtime.get("best_bid_price")
        ask_raw = realtime.get("best_ask_price")
        bid = _num(bid_raw[0] if isinstance(bid_raw, list) and bid_raw else bid_raw)
        ask = _num(ask_raw[0] if isinstance(ask_raw, list) and ask_raw else ask_raw)
        if bid is not None and ask is not None:
            price = (bid + ask) / 2
    if price is None:
        data.setdefault("quote_quality", "Yahoo Finance報價")
        data.setdefault("kline_quality", "Yahoo K線")
        data.setdefault("realtime_kline", False)
        return data

    prev = _num(realtime.get("yesterday_close"))
    if prev is None:
        old_price = _num(data.get("price"))
        old_change = _num(data.get("change"))
        if old_price is not None and old_change is not None:
            prev = old_price - old_change

    high = _num(realtime.get("high"))
    low = _num(realtime.get("low"))
    volume = _num(realtime.get("accumulate_trade_volume"))

    data["price"] = price
    if prev not in (None, 0):
        data["change"] = price - prev
        data["change_pct"] = (price - prev) / prev * 100
    if high is not None:
        data["high"] = high
    if low is not None:
        data["low"] = low
    if volume is not None:
        data["volume"] = int(volume)

    name = info.get("name")
    if name:
        data["display_name"] = str(name)

    _patch_all_kline(data, price, high, low)

    data["quote_quality"] = "twstock即時報價"
    data["kline_quality"] = "即時報價校正K線"
    data["realtime_kline"] = True
    data["quote_time"] = info.get("time") or rt.get("timestamp")
    return data
