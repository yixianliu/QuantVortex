"""产物验收：结构/资源/体积/残留/凭据。用法：python tools/verify_dist.py [dist_dir]"""
from __future__ import annotations
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIST = os.path.join(ROOT, "dist", "FuturesQuant")
MAX_MB = 900.0
FORBIDDEN = {"ctp_settings.json", "secrets.json", "credentials.json",
             "upstream.json", ".env"}
ALLOW = {"cacert.pem"}


def _size_mb(path: str) -> float:
    total = 0
    for r, _, fs in os.walk(path):
        for f in fs:
            try:
                total += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return total / 1024 / 1024


def main() -> int:
    dist = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIST)
    internal = os.path.join(dist, "_internal")
    checks: list[tuple[str, bool, str]] = []

    def need(rel: str) -> bool:
        return os.path.exists(os.path.join(internal, rel)) or \
               os.path.exists(os.path.join(dist, rel))

    checks.append(("主程序 FuturesQuant.exe", os.path.isfile(os.path.join(dist, "FuturesQuant.exe")), ""))
    for rel in ("config/settings.json", "config/style.qss",
                "images/link_qrcode/qq.png", "images/pay_qrcode/wx-pay.png",
                "futures_quant/runtime.py"):
        checks.append((f"资源 {rel}", need(rel), rel))
    checks.append(("config 无 ctp_settings.json",
                   not os.path.exists(os.path.join(internal, "config", "ctp_settings.json")), ""))
    checks.append(("无 __pycache__", not any("__pycache__" in d for r, ds, _ in os.walk(dist) for d in ds), ""))
    n_pyc = sum(1 for r, _, fs in os.walk(dist) for f in fs if f.endswith(".pyc"))
    checks.append(("无 .pyc 残留", n_pyc == 0, f"pyc={n_pyc}"))
    leaks = [os.path.join(r, f) for r, _, fs in os.walk(dist) for f in fs
             if f.lower() in FORBIDDEN and f.lower() not in ALLOW]
    checks.append(("无凭据文件", not leaks, ",".join(leaks[:5])))
    mb = _size_mb(dist)
    checks.append((f"体积 <= {MAX_MB}MB", mb <= MAX_MB, f"{mb:.1f} MB"))

    failed = 0
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")
        failed += 0 if ok else 1
    print(f"\n总计 {len(checks)} 项，失败 {failed} 项，体积 {mb:.1f} MB")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
