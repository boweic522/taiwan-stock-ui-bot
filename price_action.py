"""
price_action.py
K棒情境判斷層。不 import discord。
吃 get_stock_data() 回傳的 data，輸出情境 dict。
"""

import pandas as pd


# ────────────────────────────────────────────
# 輔助：實體幅度
# ────────────────────────────────────────────

def _body_size(row: pd.Series) -> float:
    return abs(float(row["Close"]) - float(row["Open"]))


def _avg_body(hist: pd.DataFrame, n: int = 20) -> float:
    tail = hist.tail(n)
    bodies = tail.apply(_body_size, axis=1)
    mean = bodies.mean()
    return float(mean) if not pd.isna(mean) else 0.0


# ────────────────────────────────────────────
# 長紅K / 長黑K 識別
# ────────────────────────────────────────────

def _is_big_red(row: pd.Series, avg_body: float, avg_vol: float) -> bool:
    if float(row["Close"]) <= float(row["Open"]):
        return False
    body = _body_size(row)
    change_pct = (float(row["Close"]) - float(row["Open"])) / float(row["Open"]) * 100
    return body > avg_body * 1.5 or change_pct > 3.0


def _is_big_black(row: pd.Series, avg_body: float, avg_vol: float) -> bool:
    if float(row["Close"]) >= float(row["Open"]):
        return False
    body = _body_size(row)
    change_pct = (float(row["Open"]) - float(row["Close"])) / float(row["Open"]) * 100
    return body > avg_body * 1.5 or change_pct > 3.0


def _with_volume(row: pd.Series, avg_vol: float) -> bool:
    return avg_vol > 0 and float(row["Volume"]) > avg_vol


# ────────────────────────────────────────────
# 主判斷：找最近 20 根內的關鍵K棒
# ────────────────────────────────────────────

def detect_price_action_context(data: dict) -> dict:
    """
    分析最近 20 根日K，找出關鍵K棒並推演後續情境。
    回傳 dict 供 trade_view.py 使用。
    """
    hist = data.get("hist")
    price = data.get("price")
    avg_volume = data.get("avg_volume", 0)

    _empty = {
        "event": "一般結構",
        "scenario": "近期沒有明確關鍵K棒。\n主要依多週期、均線與量價判斷。",
        "key_candle": None,
        "key_high": None,
        "key_low": None,
        "is_supported": None,
        "is_broken": None,
        "reading": "近期沒有明確關鍵K棒，主要依多週期、均線與量價判斷。",
        "support_level": None,
        "pressure_level": None,
    }

    if hist is None or len(hist) < 5 or price is None:
        _empty["event"] = "資料不足"
        _empty["scenario"] = "K棒資料不足，無法推演情境。"
        _empty["reading"] = "K棒資料不足，無法推演情境。"
        return _empty

    tail20 = hist.tail(20).copy()
    avg_body = _avg_body(tail20)
    if avg_body == 0:
        return _empty

    # ── 從最新往舊找第一根關鍵K棒（排除最後一根，因為還沒收盤確認）──
    key_idx = None
    key_row = None
    key_type = None  # "big_red" | "big_black"

    rows = list(tail20.iterrows())
    # 排除最後一根（當日）
    for idx, row in reversed(rows[:-1]):
        if _is_big_red(row, avg_body, avg_volume):
            key_idx = idx
            key_row = row
            key_type = "big_red"
            key_type_label = "帶量長紅" if _with_volume(row, avg_volume) else "長紅"
            break
        if _is_big_black(row, avg_body, avg_volume):
            key_idx = idx
            key_row = row
            key_type = "big_black"
            key_type_label = "帶量長黑" if _with_volume(row, avg_volume) else "長黑"
            break

    if key_idx is None:
        return _empty

    key_high = float(key_row["High"])
    key_low = float(key_row["Low"])
    key_close = float(key_row["Close"])

    # ── 取關鍵K棒之後的K棒（不含關鍵K棒本身）──
    after_df = hist.loc[hist.index > key_idx]

    # ── 長紅K後情境 ──
    if key_type == "big_red":
        if after_df.empty:
            # 關鍵K就是昨日，還沒有後續
            event = "長紅後待觀察"
            scenario = f"{key_type_label}出現，後續尚未確認方向。"
            reading = f"{key_type_label}出現，後續K棒尚未形成，等待確認。"
            is_supported, is_broken = None, None
        else:
            after_lows = after_df["Low"].astype(float)
            after_closes = after_df["Close"].astype(float)
            # 是否曾跌破長紅低點
            broken = bool((after_lows < key_low).any())
            # 若跌破後，最後收盤是否收回
            recovered = broken and float(after_closes.iloc[-1]) > key_low

            if not broken:
                if price >= key_close * 0.995:
                    # 持續站在長紅高點附近，未回測
                    event = "長紅後直接上攻"
                    scenario = f"{key_type_label}後直接續攻，動能延續。\n但未回測支撐，追價風險較高。"
                    reading = f"{key_type_label}後動能延續，但未回測支撐，追價風險較高。"
                    is_supported, is_broken = True, False
                else:
                    # 有小幅回落但未破低
                    event = "長紅後回測低點不破"
                    scenario = f"{key_type_label}後回測低點未破，支撐暫時有效。\n若60分K轉強並帶量，可列為試多觀察。"
                    reading = f"回測{key_type_label}低點 {key_low:.2f} 未破，支撐暫時有效。"
                    is_supported, is_broken = True, False
            elif recovered:
                event = "長紅後跌破又收回"
                scenario = f"跌破{key_type_label}低點 {key_low:.2f} 後收回，支撐仍有防守。\n需量能與60分K確認延續。"
                reading = f"盤中跌破{key_type_label}低點後收回，支撐仍存在但需確認。"
                is_supported, is_broken = True, True
            else:
                event = "長紅後跌破低點"
                scenario = f"跌破{key_type_label}低點 {key_low:.2f}，原支撐失效。\n多方結構轉弱，避免低接。"
                reading = f"跌破{key_type_label}低點 {key_low:.2f}，多方結構轉弱，避免逆勢。"
                is_supported, is_broken = False, True

        return {
            "event": event,
            "scenario": scenario,
            "key_candle": {
                "type": key_type_label,
                "high": key_high,
                "low": key_low,
                "close": key_close,
            },
            "key_high": key_high,
            "key_low": key_low,
            "is_supported": is_supported,
            "is_broken": is_broken,
            "reading": reading,
            "support_level": key_low,
            "pressure_level": key_high,
        }

    # ── 長黑K後情境 ──
    if key_type == "big_black":
        if after_df.empty:
            event = "長黑後待觀察"
            scenario = f"{key_type_label}出現，後續尚未確認方向。"
            reading = f"{key_type_label}出現，後續K棒尚未形成，等待確認。"
            is_supported, is_broken = None, None
        else:
            after_highs = after_df["High"].astype(float)
            after_closes = after_df["Close"].astype(float)
            # 是否反彈站回長黑高點
            recovered_up = bool((after_highs > key_high).any())
            last_close = float(after_closes.iloc[-1])

            if recovered_up or last_close > key_close:
                event = "長黑後反彈收復"
                scenario = f"{key_type_label}出現後已反彈收復部分跌幅。\n需觀察能否有效突破壓力 {key_high:.2f}。"
                reading = f"{key_type_label}後反彈，需確認能否突破壓力 {key_high:.2f}。"
                is_supported, is_broken = None, False
            else:
                event = "長黑後持續弱勢"
                scenario = f"{key_type_label}後持續弱勢，壓力在 {key_high:.2f}。\n未有效反彈收復，空方仍主導。"
                reading = f"{key_type_label}後未反彈收復，空方仍主導，壓力 {key_high:.2f}。"
                is_supported, is_broken = False, True

        return {
            "event": event,
            "scenario": scenario,
            "key_candle": {
                "type": key_type_label,
                "high": key_high,
                "low": key_low,
                "close": key_close,
            },
            "key_high": key_high,
            "key_low": key_low,
            "is_supported": is_supported,
            "is_broken": is_broken,
            "reading": reading,
            "support_level": key_low,
            "pressure_level": key_high,
        }

    return _empty
