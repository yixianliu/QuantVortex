# 散落验证脚本归档区

## 这是什么

历史上 `tests/` 根目录曾直接堆放 **25 个** `test_*.py` 验证脚本。它们：

- **不含任何 `def test_*` 函数**（pytest 收集 0 个用例）；
- 多为「模块级 / `main()` + `sys.exit`」的一次性验收脚本；
- 其中若干在 import 期就会执行副作用（构造 `MainWindow`、连数据源），
  一旦被 pytest 收集就会在收集阶段崩整个会话。

由于 `pytest.ini` 的 `testpaths = tests/unit tests/e2e`，这些脚本**从未进入门禁**——
也就是「看起来有测试，实际没有被执行」的可信度缺口。

## 这些脚本去哪了

其验证内容已**逐项改写为 pytest 形态并迁入 `tests/unit/`**（真正进门禁），
或**确认已由既有 `tests/unit` 用例覆盖**（重复副本）：

| 原脚本（root） | 现状 |
| --- | --- |
| m2_06 / m2_08 / m2_09 / m2_10 / m2_11 | 已改写为 `tests/unit/test_m2_*.py` |
| m3_01 / m3_03 / m3_04 / m3_05 / m3_06 / m3_07 / m3_08 / m3_10 / m3_11 / m3_12 / m3_13 | 已改写为 `tests/unit/test_m3_*.py` |
| m4_01 / m4_02 / m4_03 | 已改写为 `tests/unit/test_m4_01/02/03.py` |
| design_system / m4_04 | 已由 `tests/unit/test_m4_04_qss_single_source.py` 覆盖 |
| m4_05 | 已由 `tests/unit/test_m4_05_inline_style_refresh.py` 覆盖 |
| m4_06 | 已由 `tests/unit/test_m4_06.py` 覆盖 |
| m4_09 | 已由 `tests/unit/test_m4_09_long_task_ui.py` 覆盖 |
| m2_12 | 已由 `tests/unit/test_m2_12_evolve_failure_regression.py` 覆盖 |

## 为什么保留而不是删除

保留原脚本（重命名为 `*_scattered.py`）作为**历史证据**：旧验收点、当时的复现路径
与注释里有大量「当时为什么这么写」的上下文，迁移改写时容易被遗漏。
需要比对原始契约时可直接查阅。

文件已**去掉 `test_` 前缀**（如 `m4_01_scattered.py`），且 `testpaths` 不含本目录，
因此**不会被 pytest 收集**——既保留证据，又不触发 import 期副作用。

如需彻底清理，先确认对应 `tests/unit/test_*.py` 仍覆盖同等行为，再 `git rm` 即可
（历史仍可从 git 找回）。
