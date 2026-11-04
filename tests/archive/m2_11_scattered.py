#!/usr/bin/env python
"""测试 M2-11：修复超参搜索器

验收要点：
  ① 无 sklearn 环境下 import 本模块不崩（顶层不再硬导入 sklearn）
  ② 调用搜索接口时给出明确 ImportError 与安装命令
  ③ LSTM 导入路径 `..lstm` 正确（不再解析成 ..ai.lstm）
"""

import sys
import importlib
sys.path.insert(0, 'D:/PythonProject/QuantVortex')

# ============================================================
# ① 模块可正常导入（不依赖 sklearn 是否已安装）
# ============================================================
print("测试 ①: 模块可正常导入（顶层无硬 sklearn import）")
import futures_quant.ai.tuning.parameter_optimizer as po
assert hasattr(po, "ModelParameterOptimizer"), "模块应暴露 ModelParameterOptimizer"
# 顶层命名空间不应残留 sklearn 符号（证明已改为惰性导入）
assert not hasattr(po, "GridSearchCV"), \
    "GridSearchCV 不应出现在模块顶层命名空间（应为惰性导入）"
assert not hasattr(po, "make_scorer"), \
    "make_scorer 不应出现在模块顶层命名空间（应为惰性导入）"
print("✅ 模块导入成功，且顶层无 sklearn 符号")

# ============================================================
# ② 惰性依赖校验：_require_sklearn 缺失时抛出带安装命令的 ImportError
# ============================================================
print("\n测试 ②: 缺失 sklearn 时给出明确安装提示")

# 模拟「无 sklearn」环境：临时把 sklearn 从 sys.modules 屏蔽
class _BlockSklearn:
    """上下文管理器：让 import sklearn 抛 ImportError。"""
    def __enter__(self):
        self._saved = {}
        for k in list(sys.modules):
            if k == "sklearn" or k.startswith("sklearn."):
                self._saved[k] = sys.modules.pop(k)
        self._orig_find = sys.meta_path[:]
        class Blocker:
            def find_module(self, name, path=None):
                return None
            def find_spec(self, name, path=None, target=None):
                if name == "sklearn" or name.startswith("sklearn."):
                    raise ImportError(f"blocked: {name}")
                return None
        sys.meta_path.insert(0, Blocker())
        self._blocker = Blocker()
        return self
    def __exit__(self, *a):
        try:
            sys.meta_path.remove(self._blocker)
        except ValueError:
            pass
        sys.modules.update(self._saved)

with _BlockSklearn():
    try:
        po._require_sklearn()
        print("   （本机已安装 sklearn，跳过缺失分支；仍验证提示语存在）")
        sklearn_present = True
    except ImportError as e:
        sklearn_present = False
        msg = str(e)
        assert "scikit-learn" in msg, f"错误信息应指明依赖名 scikit-learn，实际：{msg}"
        assert "pip install" in msg, f"错误信息应给出安装命令 pip install，实际：{msg}"
        print(f"✅ 缺失 sklearn 时抛出明确 ImportError：{msg}")

# 无论本机是否装了 sklearn，安装提示常量都应存在且可用
assert "scikit-learn" in po._SKLEARN_INSTALL_HINT
assert "pip install" in po._SKLEARN_INSTALL_HINT
print(f"✅ 安装提示常量就绪：{po._SKLEARN_INSTALL_HINT}")

# ============================================================
# ③ LSTM 导入路径修正：源码中不应再有 ..ai.lstm
# ============================================================
print("\n测试 ③: LSTM 导入路径已修正为 ..lstm")
import inspect
src = inspect.getsource(po)
assert "from ..ai.lstm import" not in src, "源码仍存在错误路径 ..ai.lstm"
# 若本机有 ai/lstm 模块，验证 ..lstm 路径确实可解析
try:
    import futures_quant.ai.lstm as _lstm_mod
    assert hasattr(_lstm_mod, "LSTM"), "futures_quant.ai.lstm 应暴露 LSTM"
    print("✅ 源码无 ..ai.lstm 错误路径；futures_quant/ai/lstm.py 存在且含 LSTM")
except Exception as e:
    print(f"   （ai/lstm 模块不可用：{e}，仅校验源码路径已修正）")
    print("✅ 源码无 ..ai.lstm 错误路径")

# ============================================================
# ④ cv 折改为 TimeSeriesSplit（源码校验）
# ============================================================
print("\n测试 ④: 搜索接口使用 TimeSeriesSplit 而非整数 cv")
assert "_time_series_cv(self.cv_folds)" in src, "grid/random_search 应改用 _time_series_cv"
assert "TimeSeriesSplit" in src, "应引用 TimeSeriesSplit"
print("✅ grid_search / random_search 均改用 TimeSeriesSplit（时序不随机打散）")

# 若装了 sklearn，验证 _time_series_cv 真的产出 TimeSeriesSplit 且是时序折
try:
    cv = po._time_series_cv(5)
    name = type(cv).__name__
    assert name == "TimeSeriesSplit", f"应返回 TimeSeriesSplit，实际 {name}"
    print(f"✅ _time_series_cv(5) 返回 {name}")
except ImportError:
    print("   （本机无 sklearn，跳过 TimeSeriesSplit 实例化校验）")

print("\n" + "="*50)
print("🎉 所有 M2-11 测试通过!")
print("="*50)
