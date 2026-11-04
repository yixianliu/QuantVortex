"""M1-08 独立回测页表单校验 - E2E smoke 验收。

DoD（UPGRADE_PLAN_V5 M1-08）：
1) 起止日期 QLineEdit → QDateEdit（calendarPopup=True）
2) 起 < 止 校验 + inline 红色提示（不弹 MessageBox）
3) work() 的 bare `except Exception` → `logger.exception` + 分类提示

运行方式:
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe tests/e2e/smoke_m1_08.py
"""
from __future__ import annotations

import inspect
import logging
import os
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QApplication, QLabel, QDateEdit, QPushButton

app = QApplication.instance() or QApplication([])

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL.append(name)
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


# =========================================================================
# 加载模块（离屏）
# =========================================================================
print("\n=== 加载 SimpleBacktestPage ===")

from futures_quant.ui.simple_backtest_page import SimpleBacktestPage, \
    DEFAULT_START_DATE, DEFAULT_END_DATE, DATE_MIN, DATE_MAX  # noqa: E402

# =========================================================================
# ① 起止日期使用 QDateEdit(calendarPopup=True)
# =========================================================================
print("\n=== ① 日期控件使用 QDateEdit ===")

# 使用最小 mock mdm
class _MockMdm:
    def __init__(self):
        self.universe = [("rb", "螺纹钢", 1, "SHFE", 1000, 1.0)]
        self.feed = None


from futures_quant.config.settings import Config  # noqa: E402

page = SimpleBacktestPage(_MockMdm(), config=Config())
page.show()
app.processEvents()

check("start_edit 是 QDateEdit", isinstance(page.start_edit, QDateEdit))
check("end_edit 是 QDateEdit", isinstance(page.end_edit, QDateEdit))
check("start_edit.calendarPopup=True", page.start_edit.calendarPopup() is True)
check("end_edit.calendarPopup=True", page.end_edit.calendarPopup() is True)
check("start_edit.displayFormat=yyyy-MM-dd",
      page.start_edit.displayFormat() == "yyyy-MM-dd")
check("end_edit.displayFormat=yyyy-MM-dd",
      page.end_edit.displayFormat() == "yyyy-MM-dd")
check("start_edit.date 默认 = 2023-01-01",
      page.start_edit.date() == DEFAULT_START_DATE)
check("end_edit.date 默认 = 2024-12-31",
      page.end_edit.date() == DEFAULT_END_DATE)
check("date range 覆盖 1990-2100",
      page.start_edit.minimumDate() == DATE_MIN
      and page.end_edit.maximumDate() == DATE_MAX)

# 源码层面：不再出现 QLineEdit 用于日期
src = inspect.getsource(SimpleBacktestPage)
check("源码不再有 start_edit = QLineEdit", "start_edit = QLineEdit" not in src)
check("源码不再有 end_edit = QLineEdit", "end_edit = QLineEdit" not in src)

# =========================================================================
# ② 起 < 止 校验 + inline 红色提示
# =========================================================================
print("\n=== ② 起 < 止 校验 + inline 提示 ===")

check("存在 _validation_hint", hasattr(page, "_validation_hint"))
check("_validation_hint 是 QLabel", isinstance(page._validation_hint, QLabel))

# 默认：起<止，无错误
err = page._validate_dates()
check("默认 start<end → _validate_dates() 返回空", err == "", f"err={err!r}")
check("默认 _validation_hint 隐藏", page._validation_hint.isHidden() is True)

# 设置 start > end → 校验失败
page.start_edit.setDate(QDate(2025, 1, 1))
page.end_edit.setDate(QDate(2024, 12, 31))
app.processEvents()
err = page._validate_dates()
check("start(2025) > end(2024) → 校验返回错误描述",
      isinstance(err, str) and "早于" in err, f"err={err!r}")
check("校验失败时 _validation_hint 显示", page._validation_hint.isHidden() is False)
check("校验失败时 _validation_hint 文本含 '早于'",
      "早于" in page._validation_hint.text())
check("校验失败时 _validation_hint 样式为红色 (#ef4444)",
      "#ef4444" in page._validation_hint.styleSheet().lower())

# 恢复：start == end
page.start_edit.setDate(QDate(2024, 12, 31))
page.end_edit.setDate(QDate(2024, 12, 31))
err = page._validate_dates()
check("start == end → 校验失败（提示不能相同）",
      "不能相同" in err, f"err={err!r}")

# 恢复默认
page.start_edit.setDate(DEFAULT_START_DATE)
page.end_edit.setDate(DEFAULT_END_DATE)
app.processEvents()
err = page._validate_dates()
check("默认 start<end → 恢复校验通过", err == "")

# =========================================================================
# ② 补充：run_btn 状态与校验联动
# =========================================================================
print("\n=== ② 补充：run_btn 状态联动 ===")

# 校验失败 → run_btn 应禁用
page.start_edit.setDate(QDate(2025, 6, 1))
page.end_edit.setDate(QDate(2024, 6, 1))
app.processEvents()
check("校验失败 → run_btn 禁用", page.run_btn.isEnabled() is False)

# 恢复 → run_btn 启用
page.start_edit.setDate(DEFAULT_START_DATE)
page.end_edit.setDate(DEFAULT_END_DATE)
app.processEvents()
check("校验通过 → run_btn 启用", page.run_btn.isEnabled() is True)

# =========================================================================
# ③ work() 不再吞异常：logger.exception + 分类
# =========================================================================
print("\n=== ③ work() 用 logger.exception + 分类提示 ===")

# 检查源码：work 内部不再有裸 `except Exception:` 直接 return（旧的 fallback 分支）
work_src = textwrap.dedent(src[src.index("def _run_backtest"):])
# 从源码里定位 work() 函数体
import re  # noqa: E402
work_match = re.search(r"def work\(\).*?(?=\n        def done)", src, re.DOTALL)
check("work() 函数存在", work_match is not None)

work_body = work_match.group(0) if work_match else ""
check("work() 内含 logger.exception（分类错误记录）",
      "logger.exception" in work_body, f"len={len(work_body)}")
check("work() 含 KeyError 分支（服务未注册→fallback）",
      "except KeyError" in work_body)
check("work() 含 ValueError/TypeError 分支（参数/日期错误）",
      "except (ValueError, TypeError)" in work_body)
check("work() 含通用 Exception 分支并 raise RuntimeError",
      "except Exception" in work_body and "RuntimeError" in work_body)
# 旧的 bare `except Exception:` 直接 return 已移除
check("work() 不再有裸 `except Exception:` 直接 return（无 raise）",
      not re.search(r"except Exception:\s*\n\s*(cfg|logger\.warning|return)", work_body),
      "旧代码 except Exception 直接 fallback 已改为分类捕获")

# err() 分类提示
err_match = re.search(r"def err\(.*?\).*?(?=\n        self\._run_worker)", src, re.DOTALL)
check("err() 函数存在", err_match is not None)
err_body = err_match.group(0) if err_match else ""
check("err() 分类提示：数据/参数/其他",
      "数据" in err_body and "参数" in err_body)

# =========================================================================
# ④ 端到端：SimpleBacktestPage 构造不崩 + 触发一次 _run_backtest 不 crash
# =========================================================================
print("\n=== ④ 端到端：构造 + 触发不 crash ===")

# 触发一次点击（校验通过时应进入 worker）
orig_worker = page._run_worker
captured = {"called": False, "args": None}


def _fake_worker(work, done, on_err=None):
    """捕获 work 但不真的运行；确认 work 是 callable。"""
    captured["called"] = True
    captured["args"] = (work, done, on_err)
    # 触发 on_err 路径验证分类提示
    if on_err is not None:
        on_err("test_error")


page._run_worker = _fake_worker
page.run_btn.click()
app.processEvents()

check("_run_backtest 触发 _run_worker", captured["called"] is True)
check("_run_worker 收到 3 个参数（work/done/on_err）",
      captured["args"] is not None and len(captured["args"]) == 3)

# 校验失败时不应触发 worker
page.start_edit.setDate(QDate(2025, 6, 1))
page.end_edit.setDate(QDate(2024, 6, 1))
app.processEvents()
captured["called"] = False
page.run_btn.click()
app.processEvents()
check("校验失败时 _run_backtest 不触发 worker",
      captured["called"] is False)

# =========================================================================
# ⑤ _dates_str 返回 YYYY-MM-DD 格式字符串
# =========================================================================
print("\n=== ⑤ _dates_str 返回 ISO 格式字符串 ===")

page.start_edit.setDate(QDate(2023, 3, 15))
page.end_edit.setDate(QDate(2024, 8, 20))
s, e = page._dates_str()
check("_dates_str 返回 YYYY-MM-DD", s == "2023-03-15" and e == "2024-08-20",
      f"s={s} e={e}")

# =========================================================================
# 汇总
# =========================================================================
print("\n" + "=" * 60)
print(f"M1-08 smoke: PASS={len(PASS)}  FAIL={len(FAIL)}")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print(f"  - {f}")
    print("=" * 60)
    sys.exit(1)
print("=" * 60)
sys.exit(0)
