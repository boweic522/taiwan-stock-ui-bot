"""
trade_view.py
波段交易判斷層。不 import discord。
整合資料層、price_action、多週期判斷，輸出 UI 可用 dict。
新版重點：主畫面少數字、重位置、重買點品質。
"""

from __future__ import annotations

import math
from typing import Optional, Any

from price_action import detect_price_action_context


# ────────────────────────────────────────────
# 小工具
# ────────────────────────────────────────────

def _num(value: Any) -> Optional[float]:
    """把 pandas/numpy scalar 安全轉成 float；None / NaN 回傳 None。"""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def fmt_price(value: Any) -> str:
    """壓縮價格顯示，避免 Discord 主畫面數字太吵。"""
    v = _num(value)
    if v is None:
        return "資料不足"
    av = abs(v)
    if av >= 1000:
        return f"{v:.0f}"
    if av >= 100:
        return f"{v:.1f}".rstrip("0").rstrip(".")
    return f"{v:.2f}"


def fmt_pct(value: Any, *, show_sign: bool = False) -> str:
    v = _num(value)
    if v is None:
        return "資料不足"
    if show_sign and v > 0:
        return f"+{v:.1f}%"
    return f"{v:.1f}%"


def _pct_distance(price: Optional[float], level: Optional[float]) -> Optional[float]:
    if price is None or level is None or price == 0:
        return None
    return (level - price) / price * 100


def _clean_label(label: str) -> str:
    return {
        "短線反彈": "反彈",
        "短線轉弱": "轉弱",
        "中性偏多": "偏多",
        "資料不足": "不足",
    }.get(label, label)


# ────────────────────────────────────────────
# 1. 週期評分
# ────────────────────────────────────────────

def _score_tf(d: Optional[dict]) -> int:
    """
    0~5 結構分；d is None → -1（資料不足）
    price > MA5  +1 | price > MA20 +1 | price > MA60 +1
    MA5 > MA20   +1 | MA20 > MA60  +1
    """
    if not d:
        return -1

    p = _num(d.get("price"))
    ma5 = _num(d.get("ma5"))
    ma20 = _num(d.get("ma20"))
    ma60 = _num(d.get("ma60"))
    if p is None or ma5 is None or ma20 is None:
        return -1

    s = 0
    if p > ma5:
        s += 1
    if p > ma20:
        s += 1
    if ma60 is not None and p > ma60:
        s += 1
    if ma5 > ma20:
        s += 1
    if ma60 is not None and ma20 > ma60:
        s += 1
    return s


def _tf_label(d: Optional[dict]) -> str:
    """週期短標籤，交易化用語。"""
    if not d:
        return "資料不足"

    p = _num(d.get("price"))
    ma5 = _num(d.get("ma5"))
    ma20 = _num(d.get("ma20"))
    if p is None or ma5 is None or ma20 is None:
        return "資料不足"

    if p > ma5 and p > ma20 and ma5 > ma20:
        return "偏多"
    if p < ma5 and p < ma20 and ma5 < ma20:
        return "偏空"
    if p > ma5 and p < ma20:
        return "短線反彈"
    if p < ma5 and p > ma20:
        return "短線轉弱"
    return "震盪"


def build_compact_cycle_text(d_label: str, h_label: str, m_label: str) -> str:
    return (
        f"週期：日K{_clean_label(d_label)}｜"
        f"60分{_clean_label(h_label)}｜"
        f"5分{_clean_label(m_label)}"
    )


# ────────────────────────────────────────────
# 2. 量價 / 風控
# ────────────────────────────────────────────

def _volume_meta(data: dict) -> tuple[float, str, str]:
    volume = _num(data.get("volume")) or 0.0
    avg_volume = _num(data.get("avg_volume")) or 0.0
    change_pct = _num(data.get("change_pct")) or 0.0

    ratio = volume / avg_volume if avg_volume > 0 else 1.0
    tag = "放量" if ratio >= 1.5 else ("量縮" if ratio <= 0.7 else "量平")

    up = change_pct > 0.5
    down = change_pct < -0.5

    if up and ratio >= 1.5:
        reading = "多方攻擊"
    elif up and ratio <= 0.7:
        reading = "反彈量弱"
    elif down and ratio >= 1.5:
        reading = "賣壓明確"
    elif down and ratio <= 0.7:
        reading = "承接不足"
    elif ratio >= 1.5:
        reading = "換手明顯"
    elif ratio <= 0.7:
        reading = "市場觀望"
    else:
        reading = "量能普通"

    return ratio, tag, reading


def compact_volume_text(data: dict) -> str:
    ratio, tag, reading = _volume_meta(data)
    return f"{tag} {ratio:.1f}x｜{reading}"


def _is_high_risk_selloff(data: dict, d_label: str, h_label: str, pa_event: str) -> bool:
    change_pct = _num(data.get("change_pct")) or 0.0
    ratio, _, _ = _volume_meta(data)
    both_weak = d_label == "偏空" and h_label == "偏空"
    big_selloff = change_pct <= -5 and ratio >= 1.5
    black_event = pa_event in ("長黑後持續弱勢", "長黑後待觀察") and change_pct <= -3 and ratio >= 1.2
    return both_weak and (big_selloff or black_event)


# ────────────────────────────────────────────
# 3. 交易狀態 / 趨勢評級
# ────────────────────────────────────────────

def _determine_status(
    d_score: int,
    h_score: int,
    m_score: int,
    m_label: str,
    pa_event: str,
    data: dict,
    d_label: str,
    h_label: str,
) -> tuple[str, str, str, str, int]:
    """回傳 (status, trend_rating, tagline, title_icon, color)。"""
    if d_score < 0 or h_score < 0:
        return "等待方向", "C", "資料不足，先不硬判斷", "⚫", 0x8E8E93

    d_bull = d_score >= 4
    d_neut = d_score == 3
    d_chop = d_score == 2
    d_bear = 0 <= d_score <= 1

    h_bull = h_score >= 3
    h_chop = h_score == 2
    h_bear = 0 <= h_score <= 1

    m_bullish = m_score >= 3 or m_label in ("偏多", "短線反彈")

    if d_bull and h_bull:
        status, rating, tagline = "可做", "A", "趨勢延續"
    elif d_bull and h_chop:
        status, rating, tagline = "等修復", "B", "大方向尚可"
    elif d_bull and h_bear:
        status, rating, tagline = "等修復", "C+", "波段節奏未修復"
    elif (d_neut or d_chop) and h_bull:
        status, rating, tagline = "觀察", "B-", "短線轉強"
    elif (d_neut or d_chop) and h_bear:
        status, rating, tagline = "觀望", "C", "多空拉鋸"
    elif d_bear and h_bear and m_bullish:
        status, rating, tagline = "反彈觀察", "C", "短線反彈，不追價"
    elif d_bear and h_bear and not m_bullish:
        status, rating, tagline = "避開", "D", "空方主導"
    else:
        status, rating, tagline = "等待方向", "C", "週期不一致"

    if pa_event == "長紅後回測低點不破":
        if status == "觀望" and not h_bear:
            status, rating, tagline = "觀察", "B-", "回測不破，等確認"
    elif pa_event == "長紅後跌破低點":
        if status in ("可做", "觀察", "等修復"):
            status, rating, tagline = "觀望", "C", "長紅低點失效"
        if h_bear:
            status, rating, tagline = "避開", "D", "長紅失效且60分偏空"
    elif pa_event == "長紅後跌破又收回":
        if rating in ("A", "B", "C+"):
            status, rating, tagline = "觀察", "B-", "跌破收回，待確認"
    elif pa_event == "長黑後持續弱勢":
        if status in ("可做", "觀察"):
            status, rating, tagline = "等修復", "C+", "長黑壓制"

    # 風控優先權：放量大跌 + 日/60弱，不讓5分反彈拉高狀態。
    if _is_high_risk_selloff(data, d_label, h_label, pa_event):
        status, rating, tagline = "避開", "D", "放量長黑，空方主導"

    if status == "可做":
        icon, color = "🟢", 0xFF3B30
    elif status in ("等修復", "觀察", "反彈觀察"):
        icon, color = "🟡", 0xFFD60A
    elif status == "避開":
        icon, color = "🔴", 0x8E8E93
    else:
        icon, color = "⚫", 0x8E8E93

    return status, rating, tagline, icon, color


# ────────────────────────────────────────────
# 4. 價格 / 位置
# ────────────────────────────────────────────

def _price_line(price: Any, change: Any, change_pct: Any) -> str:
    p = _num(price)
    c = _num(change) or 0.0
    pct = _num(change_pct) or 0.0
    if p is None:
        return "資料不足"
    if c > 0:
        return f"{fmt_price(p)} ▲ {fmt_pct(abs(pct))}"
    if c < 0:
        return f"{fmt_price(p)} ▼ {fmt_pct(abs(pct))}"
    return f"{fmt_price(p)} ─ 0.0%"


def _nearest_above(price: Optional[float], candidates: list[tuple[str, Optional[float]]]) -> tuple[str, Optional[float]]:
    valid: list[tuple[str, float]] = []
    for label, val in candidates:
        v = _num(val)
        if price is not None and v is not None and v > price:
            valid.append((label, v))
    if not valid:
        return "前高", None
    return min(valid, key=lambda x: x[1])


def _fallback_20_low(data: dict) -> Optional[float]:
    hist = data.get("hist")
    if hist is not None and len(hist) >= 5:
        try:
            return float(hist["Low"].tail(20).min())
        except Exception:
            return None
    return None


def build_position_summary(data: dict, pa: dict) -> dict:
    """只挑主畫面最重要三個價位：防守、修復、壓力。"""
    price = _num(data.get("price"))
    low = _num(data.get("low")) or _fallback_20_low(data)
    high = _num(data.get("high"))
    ma5 = _num(data.get("ma5"))
    ma20 = _num(data.get("ma20"))
    ma60 = _num(data.get("ma60"))
    key_low = _num(pa.get("key_low"))
    key_high = _num(pa.get("key_high"))
    pa_event = pa.get("event", "")

    if pa_event.startswith("長紅") and key_low is not None:
        defense_label, defense = "劇本低", key_low
    else:
        defense_label, defense = "今日低", low

    # 修復價：弱勢時優先看短均；短均不存在才看今日高。
    if price is not None and ma5 is not None and ma5 > price:
        repair_label, repair = "短均", ma5
    elif price is not None and high is not None and high > price:
        repair_label, repair = "今日高", high
    elif ma5 is not None:
        repair_label, repair = "短均", ma5
    else:
        repair_label, repair = "今日高", high

    pressure_label, pressure = _nearest_above(
        price,
        [
            ("中均", ma20),
            ("季線", ma60),
            ("劇本壓力", key_high),
            ("今日高", high),
        ],
    )

    # 避免修復價與壓力價幾乎一樣，改取下一個較高壓力。
    if repair is not None and pressure is not None:
        if abs(pressure - repair) / max(abs(repair), 1.0) < 0.005:
            alternatives: list[tuple[str, float]] = []
            for label, val in [("中均", ma20), ("季線", ma60), ("劇本壓力", key_high), ("今日高", high)]:
                v = _num(val)
                if price is not None and v is not None and v > price:
                    if abs(v - repair) / max(abs(repair), 1.0) >= 0.005:
                        alternatives.append((label, v))
            if alternatives:
                pressure_label, pressure = min(alternatives, key=lambda x: x[1])

    position = (
        f"防守：{fmt_price(defense)}（{defense_label}）\n"
        f"修復：{fmt_price(repair)}（{repair_label}）\n"
        f"壓力：{fmt_price(pressure)}（{pressure_label}）"
    )

    return {
        "defense": defense,
        "defense_label": defense_label,
        "repair": repair,
        "repair_label": repair_label,
        "pressure": pressure,
        "pressure_label": pressure_label,
        "text": position,
    }


# ────────────────────────────────────────────
# 5. 買點評級
# ────────────────────────────────────────────

def _range_pct(data: dict, n: int = 10) -> Optional[float]:
    hist = data.get("hist")
    if hist is None or len(hist) < n:
        return None
    try:
        tail = hist.tail(n)
        high = float(tail["High"].max())
        low = float(tail["Low"].min())
        if low <= 0:
            return None
        return (high - low) / low * 100
    except Exception:
        return None


def _entry_score(data: dict, d_label: str, h_label: str, status: str, position: dict) -> int:
    price = _num(data.get("price"))
    ma5 = _num(data.get("ma5"))
    ma20 = _num(data.get("ma20"))
    ma60 = _num(data.get("ma60"))
    change_pct = _num(data.get("change_pct")) or 0.0
    ratio, tag, _ = _volume_meta(data)
    defense = _num(position.get("defense"))
    pressure = _num(position.get("pressure"))

    score = 0
    if price is not None and ma20 is not None:
        dist20 = (price - ma20) / ma20 * 100
        if -2 <= dist20 <= 5:
            score += 2
        elif dist20 > 10:
            score -= 3
    if price is not None and ma60 is not None:
        dist60 = (price - ma60) / ma60 * 100
        if 0 <= dist60 <= 8:
            score += 1
        elif dist60 < 0:
            score -= 4
    if tag == "量縮" and status != "避開":
        score += 2
    if _range_pct(data, 10) is not None and (_range_pct(data, 10) or 99) <= 12:
        score += 2
    if ma5 is not None and ma20 is not None and ma20 != 0:
        if abs(ma5 - ma20) / ma20 * 100 <= 3:
            score += 1
    if price is not None and defense is not None and price > defense:
        support_dist = (price - defense) / price * 100
        if 0 <= support_dist <= 4:
            score += 2
        elif support_dist > 8:
            score -= 2
    if h_label in ("震盪", "短線反彈", "偏多"):
        score += 1
    if price is not None and defense is not None and pressure is not None and price > defense:
        downside = price - defense
        upside = pressure - price
        if downside > 0 and upside > 0 and upside / downside >= 2:
            score += 3
        elif upside > 0 and upside / downside < 1:
            score -= 2

    if change_pct >= 5 and ratio >= 1.5:
        score -= 2
    if change_pct <= -5 and ratio >= 1.5:
        score -= 4
    if d_label == "偏空" and h_label == "偏空":
        score -= 2
    if status == "避開":
        score -= 3

    return score


def _entry_rating(score: int) -> tuple[str, str]:
    if score >= 10:
        return "A", "買點佳"
    if score >= 7:
        return "B", "買點觀察"
    if score >= 4:
        return "C", "等待確認"
    return "D", "不適合進場"


# ────────────────────────────────────────────
# 6. 文案組裝
# ────────────────────────────────────────────

def _headline(status: str, d_label: str, h_label: str, m_label: str, pa_event: str, data: dict, position: dict) -> str:
    high_risk = _is_high_risk_selloff(data, d_label, h_label, pa_event)
    repair = fmt_price(position.get("repair"))

    if high_risk or status == "避開":
        if m_label in ("短線反彈", "偏多"):
            return f"放量長黑後仍偏弱，5分反彈只視為跌深反抽。\n未收復 {repair} 前，先不低接。"
        return f"空方仍主導，反彈先視為修正。\n未收復 {repair} 前，先不低接。"
    if status == "可做":
        return "多週期結構偏多，趨勢仍有延續。\n避免追高，回踩守住再看。"
    if status in ("等修復", "觀察"):
        return f"趨勢沒有完全壞，但還不到舒服買點。\n先看能否站回 {repair}。"
    if status == "反彈觀察":
        return f"短線有反彈，但波段結構還沒修好。\n先等站回 {repair}，不要急著追。"
    return "週期訊號不一致，先等方向。\n有位置再做，沒位置就放過。"


def _scenario_compact(pa: dict, status: str) -> str:
    event = pa.get("event", "一般結構")
    if event == "長黑後持續弱勢":
        return "長黑後弱勢延續，空方仍主導。\n反彈需先收復修復價，否則只是修正。"
    if event == "長黑後反彈收復":
        return "長黑後出現反彈，但還不是反轉。\n需要站穩修復價，才有重新評估價值。"
    if event == "長紅後直接上攻":
        return "長紅後動能延續，但尚未回測支撐。\n強歸強，買點不一定舒服。"
    if event == "長紅後回測低點不破":
        return "長紅後回測未破，支撐暫時有效。\n若60分轉強，可列入買點觀察。"
    if event == "長紅後跌破低點":
        return "長紅低點失守，原多方劇本失效。\n重新站回前，不低接。"
    if event == "長紅後跌破又收回":
        return "跌破長紅低點後收回，仍有防守。\n需量能與60分確認。"
    if event == "資料不足":
        return "K棒資料不足，先不硬判斷劇本。\n主要看週期與關鍵位置。"
    return "近期沒有明確關鍵K棒。\n主要依週期、位置與量能判斷。"


def _trade_plan(status: str, data: dict, pa: dict, position: dict, h_label: str) -> str:
    defense = fmt_price(position.get("defense"))
    repair = fmt_price(position.get("repair"))
    pressure = fmt_price(position.get("pressure"))
    pa_event = pa.get("event", "")

    if status == "避開":
        observe = f"能否守住 {defense}"
        entry = f"站回 {repair}，且60分轉強"
        invalid = f"跌破 {defense} 且續放量"
    elif pa_event == "長紅後回測低點不破":
        observe = f"回測不破 {defense}"
        entry = "5分轉強，且60分不偏空"
        invalid = f"跌破 {defense} 且放量"
    elif status == "可做":
        observe = f"回踩是否守住 {defense}"
        entry = f"突破 {pressure} 或回踩守住後續強"
        invalid = f"跌破 {defense} 且無法收回"
    elif status in ("等修復", "反彈觀察", "觀察"):
        observe = f"能否站回 {repair}"
        entry = f"站回 {repair}，且60分轉強"
        invalid = f"跌破 {defense} 且放量"
    else:
        observe = f"守 {defense}、攻 {repair}"
        entry = "日K與60分方向一致後再評估"
        invalid = f"跌破 {defense} 且放量"

    return f"觀察：{observe}\n進場：{entry}\n失敗：{invalid}"


def _extra(d_label: str, h_label: str, m_label: str, data: dict) -> str:
    return f"{build_compact_cycle_text(d_label, h_label, m_label)}\n量能：{compact_volume_text(data)}"


# ────────────────────────────────────────────
# 7. 主函式
# ────────────────────────────────────────────

def build_trade_view(data: dict) -> dict:
    """吃 get_stock_data() 回傳的 data，輸出 Discord Embed 所需的交易判斷 dict。"""
    tf = data.get("tf", {})
    d_data = tf.get("1d")
    h_data = tf.get("60m")
    m_data = tf.get("5m")

    d_score = _score_tf(d_data)
    h_score = _score_tf(h_data)
    m_score = _score_tf(m_data)

    d_label = _tf_label(d_data)
    h_label = _tf_label(h_data)
    m_label = _tf_label(m_data)

    pa = detect_price_action_context(data)
    pa_event = pa.get("event", "一般結構")

    status, trend_rating, tagline, title_icon, color = _determine_status(
        d_score, h_score, m_score, m_label, pa_event, data, d_label, h_label
    )

    position = build_position_summary(data, pa)
    entry_score = _entry_score(data, d_label, h_label, status, position)
    entry_rating, entry_tagline = _entry_rating(entry_score)

    price_line = _price_line(data.get("price"), data.get("change"), data.get("change_pct"))
    headline = _headline(status, d_label, h_label, m_label, pa_event, data, position)
    scenario = _scenario_compact(pa, status)
    trade_plan = _trade_plan(status, data, pa, position, h_label)
    extra = _extra(d_label, h_label, m_label, data)

    return {
        "status": status,
        "title_icon": title_icon,
        "color": color,
        "price_line": price_line,
        "trend_rating": trend_rating,
        "entry_rating": entry_rating,
        "trend_text": f"趨勢：{trend_rating}",
        "entry_text": f"買點：{entry_rating}",
        "tagline": tagline,
        "entry_tagline": entry_tagline,
        "headline": headline,
        "scenario": scenario,
        "position": position["text"],
        "trade_plan": trade_plan,
        "extra": extra,
        # 舊 key 保留，避免其他地方還有引用時爆掉。
        "rating": trend_rating,
        "conclusion": headline,
        "cycles": build_compact_cycle_text(d_label, h_label, m_label),
        "key_levels": position["text"],
        "volume": compact_volume_text(data),
        "summary": f"趨勢 {trend_rating}｜買點 {entry_rating}\n{tagline}｜{entry_tagline}",
    }
