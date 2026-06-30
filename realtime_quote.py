"""
realtime_quote.py
個股即時報價修補層。
目的：yfinance / Yahoo Finance 日線資料可能延遲或只到收盤，這裡嘗試用 twstock.realtime 更新主畫面的現價、高低、量。
"""

from __future__ import annotations

import math
from typing import Optional, Any


def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        text = str(value).strip().replace(",", "").replace("%", "")
        if text in ("", "-", "--", "None"):
            return None
        f = float(text)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _plain_code(code: object) -> str:
    raw = str(code or "").upper().strip()
    return raw.replace(".TW", "").replace(".TWO", "")


def _patch_tf_price(data: dict, price: float) -> None:
    tf = data.get("tf") or {}
    for key in ("1d", "60m", "5m"):
        if isinstance(tf.get(key), dict):
            tf[key]["price"] = price


def patch_realtime_quote(data: dict, code: str | None = None) -> dict:
    """盡量把個股主畫面報價改成 twstock.realtime；失敗則保留原資料。"""
    if not data:
        return data

    if data.get("asset_type") in ("index", "future"):
        data.setdefault("quote_quality", "Yahoo Finance報價")
        return data

    plain = _plain_code(code or data.get("code"))
    if not plain.isdigit():
        data.setdefault("quote_quality", "Yahoo Finance報價")
        return data

    try:
        import twstock  # type: ignore
        rt = twstock.realtime.get(plain)
    except Exception:
        data.setdefault("quote_quality", "Yahoo Finance報價")
        return data

    if not rt or not rt.get("success"):
        data.setdefault("quote_quality", "Yahoo Finance報價")
        return data

    info = rt.get("info") or {}
    realtime = rt.get("realtime") or {}

    price = _num(realtime.get("latest_trade_price"))
    if price is None:
        # 有些時段 latest_trade_price 會是 '-'，退而求其次用最佳買/賣中間價。
        bid = _num(realtime.get("best_bid_price", [None])[0] if isinstance(realtime.get("best_bid_price"), list) else realtime.get("best_bid_price"))
        ask = _num(realtime.get("best_ask_price", [None])[0] if isinstance(realtime.get("best_ask_price"), list) else realtime.get("best_ask_price"))
        if bid is not None and ask is not None:
            price = (bid + ask) / 2
    if price is None:
        data.setdefault("quote_quality", "Yahoo Finance報價")
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

    data["quote_quality"] = "twstock即時報價"
    data["quote_time"] = info.get("time") or rt.get("timestamp")
    _patch_tf_price(data, price)
    return data
