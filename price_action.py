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

# ────────────────────────────────────────────
# 盤中 5分K：空排失效試多訊號
# ────────────────────────────────────────────

def _safe_float(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def detect_intraday_reversal_setup(data: dict) -> dict:
    """
    偵測 5分K「空排後第一根有效紅K，低點不破，再站回均線組」的短線試多條件。

    這不是波段轉強訊號，只是進場觸發層：
    - 日K / 60分K 決定大方向與能否做波段
    - 5分K 空排失效只用來判斷是否出現小倉試單點
    """
    empty = {
        "event": "無盤中試多訊號",
        "valid": False,
        "watch": False,
        "trigger_price": None,
        "defense_price": None,
        "candle_high": None,
        "candle_low": None,
        "reading": "5分K尚未出現明確空排失效試多訊號。",
    }

    tf = data.get("tf") or {}
    tf5 = tf.get("5m") or {}
    hist = tf5.get("hist")
    if hist is None or len(hist) < 30:
        empty["event"] = "5分資料不足"
        empty["reading"] = "5分K資料不足，無法判斷空排失效。"
        return empty

    try:
        df = hist.tail(90).copy()
        for col in ("Open", "High", "Low", "Close"):
            df[col] = df[col].astype(float)

        df["MA5"] = df["Close"].rolling(5).mean()
        df["MA20"] = df["Close"].rolling(20).mean()
        df["MA60"] = df["Close"].rolling(60).mean()
        df["body"] = (df["Close"] - df["Open"]).abs()
        avg_body = float(df["body"].tail(30).mean())
        if pd.isna(avg_body) or avg_body <= 0:
            return empty
    except Exception:
        return empty

    def bearish_before(i: int) -> bool:
        """候選紅K前是否曾被均線壓制。"""
        start = max(0, i - 12)
        prev = df.iloc[start:i]
        if len(prev) < 5:
            return False

        count = 0
        for _, r in prev.iterrows():
            close = _safe_float(r.get("Close"))
            ma5 = _safe_float(r.get("MA5"))
            ma20 = _safe_float(r.get("MA20"))
            ma60 = _safe_float(r.get("MA60"))
            if close is None or ma5 is None or ma20 is None:
                continue
            under_short = close < ma5 and close < ma20
            stacked = ma60 is None or ma5 <= ma20 or close < ma60
            if under_short and stacked:
                count += 1
        return count >= 3

    candidate_idx = None
    candidate = None
    rows = list(df.iterrows())

    # 掃最近 20 根，找「空排後第一根比較有效的紅K」。排除最後一根，避免未收K太早判斷。
    start_i = max(20, len(rows) - 22)
    end_i = max(start_i, len(rows) - 1)
    for i in range(start_i, end_i):
        _, row = rows[i]
        open_ = _safe_float(row.get("Open"))
        close = _safe_float(row.get("Close"))
        high = _safe_float(row.get("High"))
        low = _safe_float(row.get("Low"))
        ma5 = _safe_float(row.get("MA5"))
        if None in (open_, close, high, low, ma5):
            continue

        is_red = close > open_
        body = abs(close - open_)
        body_ok = body >= avg_body * 0.75
        reclaimed_ma5 = close > ma5 or high > ma5
        if is_red and body_ok and reclaimed_ma5 and bearish_before(i):
            candidate_idx = i
            candidate = row
            break

    if candidate_idx is None or candidate is None:
        return empty

    candle_low = float(candidate["Low"])
    candle_high = float(candidate["High"])
    after = df.iloc[candidate_idx + 1:]
    if after.empty:
        return {
            **empty,
            "event": "5分紅K待確認",
            "watch": True,
            "defense_price": candle_low,
            "candle_high": candle_high,
            "candle_low": candle_low,
            "reading": "5分空排後出現第一根紅K，但後續尚未確認低點是否守住。",
        }

    last = df.iloc[-1]
    last_close = _safe_float(last.get("Close"))
    last_ma5 = _safe_float(last.get("MA5"))
    last_ma20 = _safe_float(last.get("MA20"))
    last_ma60 = _safe_float(last.get("MA60"))

    # 允許極小幅刺破，避免一檔股票一個 tick 就判失效。
    tolerance = max(candle_low * 0.001, 0.01)
    low_held = bool((after["Low"].astype(float) >= candle_low - tolerance).all())

    ma_group = [v for v in (last_ma5, last_ma20, last_ma60) if v is not None]
    trigger = max(ma_group) if ma_group else candle_high
    stood_back = last_close is not None and trigger is not None and last_close >= trigger

    if low_held and stood_back:
        return {
            "event": "5分空排失效試多",
            "valid": True,
            "watch": True,
            "trigger_price": float(trigger),
            "defense_price": candle_low,
            "candle_high": candle_high,
            "candle_low": candle_low,
            "reading": "5分空排後紅K低點未破，且重新站上均線組；短線空方壓力開始鬆動。",
        }

    if low_held:
        return {
            "event": "5分紅K低點未破",
            "valid": False,
            "watch": True,
            "trigger_price": float(trigger) if trigger is not None else None,
            "defense_price": candle_low,
            "candle_high": candle_high,
            "candle_low": candle_low,
            "reading": "5分空排後紅K低點暫時守住，但尚未站上均線組；先觀察，不急著進。",
        }

    return {
        "event": "5分紅K低點失守",
        "valid": False,
        "watch": False,
        "trigger_price": float(trigger) if trigger is not None else None,
        "defense_price": candle_low,
        "candle_high": candle_high,
        "candle_low": candle_low,
        "reading": "5分空排後紅K低點已失守，短線試多劇本失效。",
    }


# ────────────────────────────────────────────
# 三週期 + 六盤型 + 六關鍵位 + 三根K進場法
# ────────────────────────────────────────────

def _ensure_ma(hist: pd.DataFrame) -> pd.DataFrame:
    """確保 hist 有 MA5/MA20/MA60 欄位，不改動原物件。"""
    df = hist.copy()
    close = df["Close"].astype(float)
    if "MA5" not in df.columns:
        df["MA5"] = close.rolling(5).mean()
    if "MA20" not in df.columns:
        df["MA20"] = close.rolling(20).mean()
    if "MA60" not in df.columns:
        df["MA60"] = close.rolling(60).mean()
    return df


def _last_swing_levels(hist: pd.DataFrame, n: int = 40) -> dict:
    """用簡化法抓最近波段高低：不是精準畫線工具，只用來給方向與關鍵位參考。"""
    if hist is None or len(hist) < 8:
        return {"prev_high": None, "prev_low": None, "last_high": None, "last_low": None}

    df = hist.tail(n).copy()
    highs = df["High"].astype(float).tolist()
    lows = df["Low"].astype(float).tolist()

    swing_highs: list[float] = []
    swing_lows: list[float] = []
    for i in range(2, len(df) - 2):
        h = highs[i]
        l = lows[i]
        if h >= max(highs[i - 2:i + 3]):
            swing_highs.append(h)
        if l <= min(lows[i - 2:i + 3]):
            swing_lows.append(l)

    # 找不到局部轉折時，用區間高低替代。
    if not swing_highs:
        swing_highs = [float(df["High"].max())]
    if not swing_lows:
        swing_lows = [float(df["Low"].min())]

    return {
        "prev_high": swing_highs[-2] if len(swing_highs) >= 2 else None,
        "prev_low": swing_lows[-2] if len(swing_lows) >= 2 else None,
        "last_high": swing_highs[-1] if swing_highs else None,
        "last_low": swing_lows[-1] if swing_lows else None,
    }


def detect_market_structure(data: dict) -> dict:
    """
    以日K判斷六種盤型：
    多頭趨勢盤 / 多頭整理盤 / 多頭反轉盤 / 空頭趨勢盤 / 空頭整理盤 / 空頭反轉盤。
    """
    hist = data.get("hist")
    empty = {
        "pattern": "資料不足",
        "bias": "unknown",
        "reading": "K棒資料不足，暫不判斷盤型。",
        "swings": {},
    }
    if hist is None or len(hist) < 25:
        return empty

    df = _ensure_ma(hist).tail(60)
    last = df.iloc[-1]
    close = _safe_float(last.get("Close"))
    ma5 = _safe_float(last.get("MA5"))
    ma20 = _safe_float(last.get("MA20"))
    ma60 = _safe_float(last.get("MA60"))
    swings = _last_swing_levels(df, 50)
    ph, pl = swings.get("prev_high"), swings.get("prev_low")
    lh, ll = swings.get("last_high"), swings.get("last_low")

    ma_converged = False
    if ma5 is not None and ma20 is not None and ma20 != 0:
        ma_converged = abs(ma5 - ma20) / abs(ma20) <= 0.035

    range_pct = None
    try:
        tail20 = df.tail(20)
        low20 = float(tail20["Low"].min())
        high20 = float(tail20["High"].max())
        range_pct = (high20 - low20) / low20 * 100 if low20 > 0 else None
    except Exception:
        pass
    is_box = bool(range_pct is not None and range_pct <= 14)

    hh_hl = lh is not None and ph is not None and ll is not None and pl is not None and lh > ph and ll > pl
    lh_ll = lh is not None and ph is not None and ll is not None and pl is not None and lh < ph and ll < pl

    if close is None or ma20 is None:
        return empty

    if hh_hl and close >= ma20:
        pattern = "多頭趨勢盤"
        bias = "bull"
        reading = "高點墊高、低點墊高，順勢偏多。"
    elif lh_ll and close <= ma20:
        pattern = "空頭趨勢盤"
        bias = "bear"
        reading = "高點降低、低點降低，空方仍主導。"
    elif (is_box or ma_converged) and ma60 is not None and close >= ma60:
        pattern = "多頭整理盤"
        bias = "bull_watch"
        reading = "趨勢未壞但進入整理，等待突破或回測不破。"
    elif (is_box or ma_converged) and ma60 is not None and close < ma60:
        pattern = "空頭整理盤"
        bias = "bear_watch"
        reading = "弱勢整理，反彈需先收復關鍵位。"
    elif lh_ll and ma5 is not None and close > ma5:
        pattern = "空頭反轉盤"
        bias = "reversal_watch"
        reading = "原本偏空但出現反彈型態，先看能否站穩修復價。"
    elif hh_hl and ma5 is not None and close < ma5:
        pattern = "多頭反轉盤"
        bias = "pullback_watch"
        reading = "多頭結構出現拉回，重點看支撐是否守住。"
    else:
        pattern = "整理盤"
        bias = "neutral"
        reading = "方向尚未明確，等待關鍵位表態。"

    return {"pattern": pattern, "bias": bias, "reading": reading, "swings": swings, "range_pct": range_pct}


def detect_gap_context(data: dict) -> dict:
    """偵測日K跳空缺口。跳空視為強表態，但仍要看缺口是否守住。"""
    hist = data.get("hist")
    empty = {"event": "無明顯缺口", "valid": False, "gap_low": None, "gap_high": None, "reading": ""}
    if hist is None or len(hist) < 2:
        return empty
    df = hist.tail(2)
    prev = df.iloc[-2]
    cur = df.iloc[-1]
    prev_high = _safe_float(prev.get("High"))
    prev_low = _safe_float(prev.get("Low"))
    open_ = _safe_float(cur.get("Open"))
    close = _safe_float(cur.get("Close"))
    if None in (prev_high, prev_low, open_, close):
        return empty

    if open_ > prev_high:
        low, high = prev_high, open_
        held = close >= low
        return {
            "event": "跳空向上缺口",
            "valid": bool(held),
            "gap_low": low,
            "gap_high": high,
            "reading": "跳空向上屬強表態，缺口未補前偏多觀察。" if held else "跳空向上後回補缺口，強表態失效。",
        }
    if open_ < prev_low:
        low, high = open_, prev_low
        recovered = close >= high
        return {
            "event": "跳空向下缺口",
            "valid": not recovered,
            "gap_low": low,
            "gap_high": high,
            "reading": "跳空向下屬弱表態，未收復缺口前偏空。" if not recovered else "跳空向下後收復缺口，空方力道減弱。",
        }
    return empty


def detect_multi_cycle_key_levels(data: dict) -> dict:
    """
    回傳 6 個關鍵位：
    1 前高死壓、2 前低死撐、3 60K波段高、4 60K波段低、5 5K攻擊高、6 5K防守低。
    """
    hist = data.get("hist")
    tf = data.get("tf", {}) or {}
    levels = {
        "dead_pressure": None,
        "dead_support": None,
        "wave60_high": None,
        "wave60_low": None,
        "attack5_high": None,
        "defense5_low": None,
        "reading": "",
    }

    if hist is not None and len(hist) >= 10:
        swings = _last_swing_levels(hist, 50)
        levels["dead_pressure"] = swings.get("last_high")
        levels["dead_support"] = swings.get("last_low")

    h60 = ((tf.get("60m") or {}).get("hist"))
    if h60 is not None and len(h60) >= 10:
        tail = h60.tail(60)
        levels["wave60_high"] = float(tail["High"].astype(float).max())
        levels["wave60_low"] = float(tail["Low"].astype(float).min())

    h5 = ((tf.get("5m") or {}).get("hist"))
    if h5 is not None and len(h5) >= 10:
        tail = h5.tail(36)
        levels["attack5_high"] = float(tail["High"].astype(float).max())
        levels["defense5_low"] = float(tail["Low"].astype(float).min())

    levels["reading"] = "前高/前低看大盤型，60K看波段，5K看進場與失敗。"
    return levels


def detect_three_candle_entry_setup(data: dict) -> dict:
    """
    簡化版三根K進場法：反轉K → 表態K → 確認K。
    優先使用 5分K，因為它是進場時機層；沒有5分資料則回傳資料不足。
    """
    tf = data.get("tf", {}) or {}
    h5 = ((tf.get("5m") or {}).get("hist"))
    empty = {
        "event": "三根K未成形",
        "valid": False,
        "side": None,
        "defense_price": None,
        "trigger_price": None,
        "reading": "三根K進場條件尚未成形。",
    }
    if h5 is None or len(h5) < 12:
        empty["event"] = "5分資料不足"
        empty["reading"] = "5分K資料不足，無法判斷三根K進場。"
        return empty

    df = _ensure_ma(h5).copy()
    candles = df.tail(3)
    c1, c2, c3 = [candles.iloc[i] for i in range(3)]

    def green(c):
        return _safe_float(c.get("Close")) is not None and _safe_float(c.get("Open")) is not None and float(c["Close"]) > float(c["Open"])

    def black(c):
        return _safe_float(c.get("Close")) is not None and _safe_float(c.get("Open")) is not None and float(c["Close"]) < float(c["Open"])

    c1_high, c1_low = _safe_float(c1.get("High")), _safe_float(c1.get("Low"))
    c2_high, c2_low = _safe_float(c2.get("High")), _safe_float(c2.get("Low"))
    c3_close, c3_low, c3_high = _safe_float(c3.get("Close")), _safe_float(c3.get("Low")), _safe_float(c3.get("High"))
    if None in (c1_high, c1_low, c2_high, c2_low, c3_close, c3_low, c3_high):
        return empty

    # 做多：第一根反轉紅、第二根突破、第三根收在相對高檔且不跌破第二根低點。
    long_valid = (
        green(c1)
        and green(c2)
        and c2_high > c1_high
        and c3_close >= (c2_low + (c2_high - c2_low) * 0.55)
        and c3_low >= min(c1_low, c2_low)
    )

    # 做空：第一根反轉黑、第二根跌破、第三根收在相對低檔且不上破第二根高點。
    short_valid = (
        black(c1)
        and black(c2)
        and c2_low < c1_low
        and c3_close <= (c2_low + (c2_high - c2_low) * 0.45)
        and c3_high <= max(c1_high, c2_high)
    )

    if long_valid:
        return {
            "event": "三根K做多確認",
            "valid": True,
            "side": "long",
            "defense_price": float(min(c1_low, c2_low)),
            "trigger_price": float(c2_high),
            "reading": "5分出現反轉K、表態K、確認K，短線試多條件成立。",
        }
    if short_valid:
        return {
            "event": "三根K做空確認",
            "valid": True,
            "side": "short",
            "defense_price": float(max(c1_high, c2_high)),
            "trigger_price": float(c2_low),
            "reading": "5分出現反轉K、表態K、確認K，短線偏空條件成立。",
        }
    return empty
