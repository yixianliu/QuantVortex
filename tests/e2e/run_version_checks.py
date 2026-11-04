"""版本同步一键回归入口。

依次运行三个版本相关测试，汇总 PASS/FAIL 并以退出码反映整体结果。
用于「改版本号后」一次性确认 源码 → GUI → 分发 EXE 全链路同步无漂移。

用法：
    python tests/e2e/run_version_checks.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# e2e 涉及 PyQt GUI，强制 offscreen 避免在无显示环境崩溃。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TESTS = [
    "test_version_sync",           # 运行时校验标题/状态栏/托盘/关于页 == 包版本
    "test_build_version_resource", # 校验打包版本资源可被 PyInstaller 解析器加载
    "test_version_no_drift",        # 静态护栏：展示处不得硬编码版本字面量
]


def main() -> None:
    results = []
    for name in TESTS:
        path = os.path.join(ROOT, "tests", "e2e", f"{name}.py")
        print(f"\n>>> 运行 {name}")
        rc = subprocess.call([sys.executable, path], cwd=ROOT)
        results.append((name, rc))

    print("\n" + "=" * 52)
    all_ok = True
    for name, rc in results:
        status = "PASS" if rc == 0 else "FAIL"
        if rc != 0:
            all_ok = False
        print(f"  [{status}] {name:<28} rc={rc}")
    print("=" * 52)
    print("版本同步回归：全部通过 ✅" if all_ok else "版本同步回归：存在失败 ❌")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
