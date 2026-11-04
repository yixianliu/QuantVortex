"""品种合约数据完整性自检模块。

职责：
    在系统启动时（或测试流程中）对品种数据执行一致性校验，
    确保 FUTURES_UNIVERSE、CONTRACT_SPECS、_SPEC_TUNING 三者
    相互对齐，无孤立配置或数据缺失。

输出：
    - validate_universe() 返回 (ok: bool, issues: list[str])
    - ok=True 表示数据完整；issues 列表包含所有发现的问题
"""
from __future__ import annotations

from typing import List, Tuple

from .synthetic import FUTURES_UNIVERSE
from .contract_specs import CONTRACT_SPECS, _SPEC_TUNING, _CLOSE_TODAY_FREE


# 各品种规格表中的必需字段（缺一不可）
_REQUIRED_FIELDS = {
    "symbol", "name", "category", "exchange",
    "multiplier", "min_price_tick", "typical_price",
    "margin_rate", "commission_per_lot", "leverage",
    "close_today_commission_ratio", "delivery_date",
}


def validate_universe() -> Tuple[bool, List[str]]:
    """校验品种总表与规格表的完整性与一致性。

    检查项：
        1. FUTURES_UNIVERSE 中每个品种在 CONTRACT_SPECS 中均有对应规格
        2. CONTRACT_SPECS 中每个规格均有合法字段值（乘数>0、保证金率∈(0,1] 等）
        3. _SPEC_TUNING 中配置的品种码均存在于 CONTRACT_SPECS 中（否则配置无效）
        4. _CLOSE_TODAY_FREE 中配置的品种码均存在于 CONTRACT_SPECS 中
        5. 交易所代码均为合法值（SHFE/DCE/CZCE/INE/CFFEX）
        6. 分类（category）属于已知集合

    返回:
        (ok, issues): ok=True 表示全部通过；issues 为问题描述列表
    """
    issues: List[str] = []

    # ---- 检查 1：Universe 中所有品种均在 specs 中有记录 ----
    universe_codes = {row[0] for row in FUTURES_UNIVERSE}
    spec_codes = set(CONTRACT_SPECS.keys())
    missing_in_specs = universe_codes - spec_codes
    if missing_in_specs:
        issues.append(f"FUTURES_UNIVERSE 中但 CONTRACT_SPECS 缺少的品种: {sorted(missing_in_specs)}")

    orphan_in_specs = spec_codes - universe_codes
    if orphan_in_specs:
        issues.append(f"CONTRACT_SPECS 中但 FUTURES_UNIVERSE 未定义的品种: {sorted(orphan_in_specs)}")

    # ---- 检查 2：规格字段合法性 ----
    for code, spec in CONTRACT_SPECS.items():
        missing = _REQUIRED_FIELDS - set(spec.keys())
        if missing:
            issues.append(f"品种 {code} 规格缺少字段: {sorted(missing)}")
        if spec.get("multiplier", 0) <= 0:
            issues.append(f"品种 {code} multiplier 不合法: {spec.get('multiplier')}")
        mr = spec.get("margin_rate", 0.0)
        if mr <= 0 or mr > 1.0:
            issues.append(f"品种 {code} margin_rate 越界: {mr}（应为 0~1）")
        if spec.get("min_price_tick", 0) <= 0:
            issues.append(f"品种 {code} min_price_tick 不合法: {spec.get('min_price_tick')}")

    # ---- 检查 3：_SPEC_TUNING 中孤立配置 ----
    tuning_codes = set(_SPEC_TUNING.keys())
    tuning_orphans = tuning_codes - spec_codes
    if tuning_orphans:
        issues.append(f"_SPEC_TUNING 中但无 Universe 记录的品种（配置无效）: {sorted(tuning_orphans)}")

    # ---- 检查 4：_CLOSE_TODAY_FREE 中孤立配置 ----
    close_free_orphans = _CLOSE_TODAY_FREE - spec_codes
    if close_free_orphans:
        issues.append(f"_CLOSE_TODAY_FREE 中但无 Universe 记录的品种（配置无效）: {sorted(close_free_orphans)}")

    # ---- 检查 5：交易所代码合法性 ----
    valid_exchanges = {"SHFE", "DCE", "CZCE", "INE", "CFFEX"}
    for code, spec in CONTRACT_SPECS.items():
        exch = spec.get("exchange", "")
        if exch and exch not in valid_exchanges:
            issues.append(f"品种 {code} 交易所 '{exch}' 不在合法集合 {sorted(valid_exchanges)} 中")

    # ---- 检查 6：分类合法性 ----
    valid_categories = {
        "黑色系", "有色金属", "贵金属", "能源化工",
        "农产品", "金融", "化工建材",
    }
    for code, spec in CONTRACT_SPECS.items():
        cat = spec.get("category", "")
        if cat and cat not in valid_categories:
            issues.append(f"品种 {code} 分类 '{cat}' 不在合法集合中")

    ok = len(issues) == 0
    return ok, issues


def print_validation_report() -> None:
    """打印品种数据自检报告（供启动脚本调用）。"""
    ok, issues = validate_universe()
    status = "✅ 通过" if ok else f"⚠️ 发现 {len(issues)} 个问题"
    print(f"[品种数据自检] {status}")
    if issues:
        for iss in issues:
            print(f"  - {iss}")
    else:
        print(f"  共 {len(CONTRACT_SPECS)} 个品种，全部校验通过")


if __name__ == "__main__":
    print_validation_report()
