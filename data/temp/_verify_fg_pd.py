# 验证玻璃和钯金品种数据完整性
import sys
sys.path.insert(0, '.')
from futures_quant.data.contract_specs import CONTRACT_SPECS, get_contract_spec, build_contract
from futures_quant.data.synthetic import FUTURES_UNIVERSE, SyntheticFeed
from futures_quant.ai.news_feed import NAME_ALIASES, _WSJ_FUTURES_KEYWORDS, _JIN10_FUTURES_KEYWORDS

print("=" * 60)
print("1. FUTURES_UNIVERSE 检查")
print("=" * 60)
fg_row = next((r for r in FUTURES_UNIVERSE if r[0] == "FG"), None)
pd_row = next((r for r in FUTURES_UNIVERSE if r[0] == "PD"), None)
print(f"玻璃(FG): {fg_row}")
print(f"钯金(PD): {pd_row}")
print(f"FUTURES_UNIVERSE 总数: {len(FUTURES_UNIVERSE)} (期望43)")
assert fg_row is not None, "❌ FG 缺失于 FUTURES_UNIVERSE"
assert pd_row is not None, "❌ PD 缺失于 FUTURES_UNIVERSE"
print("✅ FUTURES_UNIVERSE 验证通过")

print("\n" + "=" * 60)
print("2. CONTRACT_SPECS 规格检查")
print("=" * 60)
print(f"CONTRACT_SPECS 总数: {len(CONTRACT_SPECS)} (期望43)")
for code in ("FG", "PD"):
    s = get_contract_spec(code)
    print(f"  {code}: name={s['name']}, category={s['category']}, exchange={s['exchange']}, "
          f"margin={s['margin_rate']}, commission={s['commission_per_lot']}, "
          f"mult={s['multiplier']}, tick={s['min_price_tick']}, close_today={s['close_today_commission_ratio']}")
    assert s['name'] != '未知', f"❌ {code} 规格异常"
print("✅ CONTRACT_SPECS 验证通过")

print("\n" + "=" * 60)
print("3. 合成行情验证")
print("=" * 60)
feed = SyntheticFeed()
for sym, expected_price in [("FG.CZCE", 1400), ("PD.SHFE", 320)]:
    df = feed.get_recent(sym, "D", limit=5)
    last_price = float(df["close"].iloc[-1])
    print(f"  {sym}: 最新收盘={last_price:.2f} (预期≈{expected_price})")
    assert not df.empty, f"❌ {sym} 行情为空"
print("✅ 合成行情验证通过")

print("\n" + "=" * 60)
print("4. 新闻关键词检查")
print("=" * 60)
print(f"玻璃别名: {NAME_ALIASES.get('玻璃', '缺失')}")
print(f"钯金别名: {NAME_ALIASES.get('钯金', '缺失')}")
assert NAME_ALIASES.get('玻璃'), "❌ 玻璃别名缺失"
assert NAME_ALIASES.get('钯金'), "❌ 钯金别名缺失"
assert '玻璃' in _WSJ_FUTURES_KEYWORDS, "❌ WSJ关键词缺玻璃"
assert '钯金' in _WSJ_FUTURES_KEYWORDS, "❌ WSJ关键词缺钯金"
assert '钯' in _WSJ_FUTURES_KEYWORDS, "❌ WSJ关键词缺钯"
assert '钯金' in _JIN10_FUTURES_KEYWORDS, "❌ 金10关键词缺钯金"
assert '钯' in _JIN10_FUTURES_KEYWORDS, "❌ 金10关键词缺钯"
print("✅ 新闻关键词验证通过")

print("\n" + "=" * 60)
print("5. build_contract 验证")
print("=" * 60)
for sym in ("FG.CZCE", "PD.SHFE"):
    c = build_contract(sym)
    print(f"  {sym}: symbol={c.symbol}, mult={c.multiplier}, tick={c.min_price_tick}, "
          f"margin={c.margin_rate}, comm={c.commission_per_lot}")
print("✅ build_contract 验证通过")

print("\n" + "=" * 60)
print("✅✅✅ 全部验证通过，玻璃(FG)和钯金(PD)数据完整 ✅✅✅")
print("=" * 60)
