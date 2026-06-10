"""本地測試：不需要 Discord，直接驗證股票資料與圖表"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from stock_data import get_stock_data, get_trend, get_reading
from chart import generate_chart

TEST_CODES = ["2330", "0050", "2317", "5209"]

for code in TEST_CODES:
    print(f"\n{'='*40}")
    print(f"測試股票：{code}")
    data = get_stock_data(code)
    if data is None:
        print(f"  ❌ 查無資料（可能下市或代號錯誤）")
        continue

    trend = get_trend(data["price"], data["ma5"], data["ma20"], data["ma60"])
    reading = get_reading(data["change_pct"], trend)
    sign = "+" if data["change"] >= 0 else ""

    print(f"  名稱：{data['name']}")
    print(f"  價格：{data['price']:.2f}　{sign}{data['change']:.2f}（{sign}{data['change_pct']:.2f}%）")
    print(f"  最高：{data['high']:.2f}　最低：{data['low']:.2f}")
    print(f"  成交量：{data['volume']:,}")
    ma60_str = f"{data['ma60']:.2f}" if data['ma60'] else 'N/A'
    print(f"  MA5：{data['ma5']:.2f}　MA20：{data['ma20']:.2f}　MA60：{ma60_str}")
    print(f"  趨勢：{trend}")
    print(f"  判讀：{reading}")

    chart = generate_chart(data["hist"], data["code"], data["name"], data["price"])
    path = f"test_{code}.png"
    with open(path, "wb") as f:
        f.write(chart.read())
    print(f"  📊 圖表已儲存：{path}")

print("\n\n✅ 測試完成")
