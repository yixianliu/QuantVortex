#!/usr/bin/env python3
"""M6-01 冒烟测试：二维码路径修复 + 打包进 EXE（构建配置校验）。

验收（对应 M6-01 DoD）：
    1. 运行时图片路径走 ``get_images_dir()``（开发期=项目根/images，冻结态=
       ``sys._MEIPASS/images``），不再硬编码 ``D:\\`` 绝对路径（G7）。
    2. 4 张二维码图片在开发期路径下均存在（link_qrcode/qq.png、wx.png；
       pay_qrcode/ali-pay.png、wx-pay.png）。
    3. about_page 的 4 个二维码路径常量解析到上述真实文件，且均以 images 目录为前缀
       （非硬编码盘符路径）。
    4. 实际构建用的 spec（build_tools/futures_qt.spec）已将 images 整目录收集进
       datas（``datas.append((images_dir, "images"))``）。
    5. build_exe.py 的图片校验逻辑（_verify_images）按单文件夹模式
       ``dist/FuturesQuant/images/...`` 校验（不写死 ``_internal``）。

运行（offscreen，按项目规范前台 + 文件重定向）：
    QT_QPA_PLATFORM=offscreen /d/anaconda3/python.exe \\
        tests/e2e/smoke_m6_01.py > tests/e2e/m6_01.log 2>&1; echo rc=$?
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from futures_quant import runtime  # noqa: E402
from futures_quant.ui import about_page as ap  # noqa: E402
from futures_quant.ui.about_page import (  # noqa: E402
    _QR_LINK_QQ, _QR_LINK_WX, _QR_PAY_ALI, _QR_PAY_WX,
)

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}"
          + (f" | {detail}" if detail else ""))


# 1) 路径解析入口：get_images_dir（非硬编码）
img_dir = runtime.get_images_dir()
check("images-dir-resolves", os.path.isdir(img_dir), f"img_dir={img_dir}")

# 2) 4 张二维码存在
expected = {
    "QQ": _QR_LINK_QQ, "WX": _QR_LINK_WX,
    "AliPay": _QR_PAY_ALI, "WXPay": _QR_PAY_WX,
}
missing = [k for k, p in expected.items() if not os.path.isfile(p)]
check("all-4-qr-images-exist", not missing, f"missing={missing}")

# 3) 常量基于 get_images_dir（非硬编码 D:\）
check("qr-constants-derived-from-images-dir",
      all(p.startswith(img_dir) for p in expected.values()),
      f"img_dir={img_dir}")

# 4) 实际构建 spec 收集 images
spec_path = os.path.join(ROOT, "build_tools", "futures_qt.spec")
with open(spec_path, encoding="utf-8") as f:
    spec_src = f.read()
check("spec-collects-images",
      'images_dir = os.path.join(ROOT, "images")' in spec_src
      and 'datas.append((images_dir, "images"))' in spec_src)

# 5) build_exe 图片校验按单文件夹模式（无 _internal）
build_path = os.path.join(ROOT, "build_tools", "build_exe.py")
with open(build_path, encoding="utf-8") as f:
    build_src = f.read()
verify_block = build_src.split("def _verify_images")[1].split(
    "def _verify_artifact")[0]
check("build-verify-images-version-robust",
      'os.path.join(dist_dir, "_internal", "images")' in verify_block
      and 'os.path.join(dist_dir, "images")' in verify_block)

# 汇总
fails = [r for r in results if not r[1]]
print("=" * 60)
print(f"M6-01 smoke: {len(results) - len(fails)}/{len(results)} passed")
if fails:
    print("FAILED items:")
    for name, _, detail in fails:
        print(f"  - {name} | {detail}")
sys.exit(1 if fails else 0)
