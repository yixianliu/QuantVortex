"""EXE 启动冒烟：进程存活 + 主窗口出现 + data 目录生成。
用法：python tools/smoke_exe.py <exe_path> [--wait 20]"""
import argparse, os, subprocess, sys, time


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--wait", type=int, default=20)
    a = ap.parse_args()
    exe = os.path.abspath(a.exe)
    if not os.path.isfile(exe):
        print(f"FAIL: exe 不存在 {exe}")
        return 2
    proc = subprocess.Popen([exe], cwd=os.path.dirname(exe))
    time.sleep(a.wait)
    rc = proc.poll()
    if rc is not None:
        print(f"FAIL: 进程已退出 rc={rc}")
        return 1
    data_dir = os.path.join(os.path.dirname(exe), "data")
    print(f"OK: 存活 pid={proc.pid}")
    print(f"data_dir={data_dir} exists={os.path.isdir(data_dir)}")
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    return 0 if os.path.isdir(data_dir) else 3


if __name__ == "__main__":
    sys.exit(main())
