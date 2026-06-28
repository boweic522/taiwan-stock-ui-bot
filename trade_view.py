"""
trade_view.py
波段交易判斷層。不 import discord。
整合資料層、price_action、多週期判斷，輸出 UI 可用 dict。
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


def _fmt(value: Optional[float]) -> str:
    return "資料不足" if value is None else f"{value:.2f}"


def _unique_levels(levels: list[tuple[str, Optional[float]]], price: Optional[float] = None,
                   side: str = "any") -> list[str]:
    """去除過近價位，避免同一個價位重複塞爆 UI。"""
    out: list[str] = []
    seen: list[float] = []
    for label, val in levels:
        v = _num(val)
        if v is None:
            continue
        if side == "above" and price is not None and v <= price:
            continue
        if side == "below" and price is not None and v >= price:
            continue
        # 用 0.5% 當作去重門檻，比固定 0.5 元更適合不同股價級距
        if any(abs(v - s) / max(abs(s), 1.0) < 0.005 for s in seen):
            continue
        seen.append(v)
        out.append(f"{label} {v:.2f}")
    return out


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


# ────────────────────────────────────────────
# 2. 交易狀態
# ────────────────────────────────────────────

def _determine_status(d_score: int, h_score: int, m_score: int,
                      m_label: str, pa_event: str) -> tuple[str, str, str, str, int]:
    """回傳 (status, rating, tagline, title_icon, color)。"""
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

    # ── 基礎規則：日K決定方向，60分決定能否執行，5分只作切入參考 ──
    if d_bull and h_bull:
        status, rating, tagline = "可做", "A", "趨勢延續，順勢觀察"
    elif d_bull and h_chop:
        status, rating, tagline = "等修復", "B", "大方向尚可，等60分轉強"
    elif d_bull and h_bear:
        status, rating, tagline = "等修復", "C+", "日線未壞，但波段節奏未修復"
    elif (d_neut or d_chop) and h_bull:
        status, rating, tagline = "觀察", "B-", "短線轉強，但日線方向未明"
    elif (d_neut or d_chop) and h_bear:
        status, rating, tagline = "觀望", "C", "多空拉鋸，等方向"
    elif d_bear and h_bear and m_bullish:
        status, rating, tagline = "反彈觀察", "C", "短線反彈，不追價"
    elif d_bear and h_bear and not m_bullish:
        status, rating, tagline = "避開", "D", "空方主導，避免逆勢"
    else:
        status, rating, tagline = "等待方向", "C", "週期不一致，先等確認"

    # ── price_action 加權調整：只微調，不讓單一K棒凌駕週期結構 ──
    if pa_event == "長紅後回測低點不破":
        if status == "觀望" and not h_bear:
            status, rating, tagline = "觀察", "B-", "回測不破，等60分確認"
    elif pa_event == "長紅後跌破低點":
        if status in ("可做", "觀察", "等修復"):
            status, rating, tagline = "觀望", "C", "跌破長紅低點，結構轉弱"
        if h_bear:
            status, rating, tagline = "避開", "D", "跌破長紅低點且60分偏空"
    elif pa_event == "長紅後跌破又收回":
        if rating in ("A", "B", "C+"):
            status, rating, tagline = "觀察", "B-", "跌破後收回，需量能與60分確認"
    elif pa_event == "長黑後持續弱勢":
        if status in ("可做", "觀察"):
            status, rating, tagline = "等修復", "C+", "長黑壓制，需修復結構"

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
# 3. 價格顯示
# ────────────────────────────────────────────

def _price_line(price: Optional[float], change: Optional[float], change_pct: Optional[float]) -> str:
    price = _num(price)
    change = _num(change) or 0.0
    change_pct = _num(change_pct) or 0.0
    if price is None:
        return "資料不足"
    if change > 0:
        return f"{price:.2f} ▲ +{change:.2f}（+{change_pct:.2f}%）"
    if change < 0:
        return f"{price:.2f} ▼ {change:.2f}（{change_pct:.2f}%）"
    return f"{price:.2f} ─ 0.00（0.00%）"


# ────────────────────────────────────────────
# 4. 關鍵價
# ────────────────────────────────────────────

def _key_levels(data: dict, pa: dict) -> str:
    price = _num(data.get("price"))
    low = _num(data.get("low"))
    high = _num(data.get("high"))
    ma5 = _num(data.get("ma5"))
    ma20 = _num(data.get("ma20"))
    ma60 = _num(data.get("ma60"))
    hist = data.get("hist")

    supports: list[tuple[str, Optional[float]]] = [("今日低", low)]
    if pa.get("key_low") is not None:
        supports.append(("劇本支撐", _num(pa.get("key_low"))))
    if hist is not None and len(hist) >= 10:
        try:
            supports.append(("近20K低", float(hist["Low"].tail(20).min())))
        except Exception:
            pass

    resistances: list[tuple[str, Optional[float]]] = [
        ("MA5", ma5),
        ("MA20", ma20),
        ("今日高", high),
        ("劇本壓力", _num(pa.get("key_high"))),
    ]

    support_parts = _unique_levels(supports, price, side="below") if price is not None else _unique_levels(supports)
    resist_parts = _unique_levels(resistances, price, side="above") if price is not None else _unique_levels(resistances)

    support_str = " / ".join(support_parts) if support_parts else "短線支撐不明"
    resist_str = " / ".join(resist_parts) if resist_parts else "短壓較輕，觀察前高"

    lines = [f"支撐：{support_str}", f"壓力：{resist_str}"]
    if ma60 is not None and price is not None:
        role = "支撐" if price > ma60 else "壓力"
        lines.append(f"長線：MA60 {ma60:.2f}（{role}）")
    return "\n".join(lines)


# ────────────────────────────────────────────
# 5. 量價
# ────────────────────────────────────────────

def _volume_reading(data: dict) -> str:
    volume = int(data.get("volume") or 0)
    avg_volume = int(data.get("avg_volume") or 0)
    change_pct = _num(data.get("change_pct")) or 0.0

    vol_ratio = volume / avg_volume if avg_volume > 0 else 1.0
    vol_tag = "放量" if vol_ratio >= 1.5 else ("量縮" if vol_ratio <= 0.7 else "量平")

    up = change_pct > 0.5
    down = change_pct < -0.5

    if up and vol_ratio >= 1.5:
        reading = "多方主動攻擊"
    elif up and vol_ratio <= 0.7:
        reading = "反彈力道不足，追高小心"
    elif down and vol_ratio >= 1.5:
        reading = "賣壓明確，風險升高"
    elif down and vol_ratio <= 0.7:
        reading = "賣壓未擴大，但承接力不足"
    elif vol_ratio >= 1.5:
        reading = "換手明顯，等待方向確認"
    elif vol_ratio <= 0.7:
        reading = "市場觀望，缺乏方向性資金"
    else:
        reading = "量能普通，方向仍需價格確認"

    return (
        f"今日量：{volume:,}\n"
        f"相對均量：{vol_ratio:.1f}x（{vol_tag}）\n"
        f"判斷：{reading}"
    )


# ────────────────────────────────────────────
# 6. 交易計畫（進場 + 失敗合併）
# ────────────────────────────────────────────

def _trade_plan(status: str, data: dict, pa: dict) -> str:
    ma5 = _num(data.get("ma5"))
    ma20 = _num(data.get("ma20"))
    high = _num(data.get("high"))
    low = _num(data.get("low"))
    pa_event = pa.get("event", "")
    key_low = _num(pa.get("key_low"))

    ma5_s = _fmt(ma5)
    ma20_s = _fmt(ma20)
    high_s = _fmt(high)
    low_s = _fmt(low)

    if pa_event == "長紅後回測低點不破" and key_low is not None:
        entry = f"回測 {key_low:.2f} 不破，且5分轉強、60分不偏空，才列入試多觀察。"
    elif pa_event == "長紅後跌破低點" and key_low is not None:
        entry = f"不低接，需重新站回 {key_low:.2f} 才能重新觀察。"
    elif status == "可做":
        entry = f"回踩不破 MA5 {ma5_s} / MA20 {ma20_s}，或突破今日高 {high_s} 續強。"
    elif status == "等修復":
        entry = f"站回 MA5 {ma5_s}，且60分K轉為偏多。"
    elif status == "反彈觀察":
        entry = f"站回 MA5 {ma5_s}，且60分K不再偏空；未確認前不追價。"
    elif status in ("觀望", "等待方向"):
        entry = f"收盤站回 MA20 {ma20_s}，且日K與60分K方向一致後再評估。"
    elif status == "觀察":
        entry = f"回踩 MA5 {ma5_s} 不破，且日線方向確立後再介入。"
    else:
        entry = f"不建議進場。需先站回 MA5 {ma5_s} / MA20 {ma20_s} 並修復60分K。"

    if pa_event.startswith("長紅") and key_low is not None:
        invalid = f"跌破 {key_low:.2f} 且放量，劇本失效。"
    elif low is not None:
        invalid = f"跌破今日低 {low_s} 且放量，短線轉弱確認。"
    elif ma5 is not None:
        invalid = f"跌破 MA5 {ma5_s} 且無法收回，短線轉弱。"
    else:
        invalid = "資料不足，暫不設定硬停損。"

    return f"進場：{entry}\n失敗：{invalid}"


# ────────────────────────────────────────────
# 7. 結論 / 總結
# ────────────────────────────────────────────

def _conclusion(status: str, d_label: str, h_label: str, m_label: str,
                pa_event: str) -> str:
    base = f"日線 {d_label}，60分 {h_label}，5分 {m_label}。\n當前研判：**{status}**"
    if pa_event not in ("一般結構", "資料不足", ""):
        base += f"\n劇本事件：{pa_event}"
    return base


def _summary(status: str, rating: str, tagline: str) -> str:
    if status == "可做":
        body = "可順勢觀察，但仍需照交易計畫執行，不追失控行情。"
    elif status in ("等修復", "觀察"):
        body = "條件接近但還沒完全成立，等確認比提早猜方向更划算。"
    elif status == "反彈觀察":
        body = "有反彈訊號，但波段結構未完整修復，先看別急著做。"
    elif status == "避開":
        body = "空方主導，先避開，別把低接當成勇敢。"
    else:
        body = "週期訊號不一致，等待方向比硬交易更有性價比。"
    return f"評級 {rating}｜{tagline}\n{body}"


# ────────────────────────────────────────────
# 8. 主函式
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

    status, rating, tagline, title_icon, color = _determine_status(
        d_score, h_score, m_score, m_label, pa_event
    )

    price_line = _price_line(data.get("price"), data.get("change"), data.get("change_pct"))
    cycles = f"日K：{d_label}\n60分：{h_label}\n5分：{m_label}"
    conclusion = _conclusion(status, d_label, h_label, m_label, pa_event)
    scenario = pa.get("scenario") or "近期沒有明確關鍵K棒。\n主要依多週期、均線與量價判斷。"
    key_levels = _key_levels(data, pa)
    volume = _volume_reading(data)
    trade_plan = _trade_plan(status, data, pa)
    summary = _summary(status, rating, tagline)

    return {
        "status": status,
        "rating": rating,
        "tagline": tagline,
        "title_icon": title_icon,
        "color": color,
        "price_line": price_line,
        "conclusion": conclusion,
        "scenario": scenario,
        "cycles": cycles,
        "key_levels": key_levels,
        "volume": volume,
        "trade_plan": trade_plan,
        "summary": summary,
    }
