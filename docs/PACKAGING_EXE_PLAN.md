# QuantVortex 打包为 Windows 绿色便携 EXE —— 实施方案（AI 可执行版）

> 文档版本：v1.0 / 2026-10-09
> 适用项目根：`D:\PythonProject\QuantVortex`（下文用 `<ROOT>` 指代）
> 执行者：AI Agent（所有步骤均给出「前置条件 → 执行命令 → 预期结果 → 验证方式」，可直接照搬执行）
> 术语约定：`bash` = Git Bash（本仓库默认 shell）；命令中路径一律用**绝对路径**。

---

## 0. 全局约束（不可协商的硬约束）

| 编号 | 约束 | 判定方式 |
|---|---|---|
| C-1 | 目标平台 Windows x64（Win10 1809+ / Win11），产物为**单目录绿色版**，不做安装向导 | `dist/FuturesQuant/` 可直接拷贝运行 |
| C-2 | **零外部安装**：目标机无需安装 Python / 依赖库 / 插件 / Qt 运行时 | 干净 Win10/Win11 虚机双击 `FuturesQuant.exe` 可启动 |
| C-3 | 输出目录**固定**为 `<ROOT>/dist`，产物子目录固定为 `dist/FuturesQuant` | 不得使用 `--distpath` 覆盖 |
| C-4 | 唯一构建入口：`build_tools/build_exe.py`；唯一 spec：`build_tools/futures_qt.spec` | ⚠️ `<ROOT>/main.spec` 是历史残留（无 excludes、无 datas 安全过滤），**禁止使用** |
| C-5 | 安全门禁不可绕过：构建前扫源码、构建后扫产物，任一命中即中止（无关闭开关） | `build_exe.py` 退出码语义见 §7 |
| C-6 | 版本号单一来源：`futures_quant/__init__.py` 的 `__version__` / `__release_date__` | exe 属性 `ProductVersion` 必须等于该值 |

---

## 1. 输入 / 输出定义

### 1.1 输入（INPUT）

| 项 | 路径 | 说明 |
|---|---|---|
| 入口脚本 | `<ROOT>/main.py` | 仅做 `sys.path` 注入 + 启动 `futures_quant.ui.main_window.main()` |
| 打包 spec | `<ROOT>/build_tools/futures_qt.spec` | 数据源清单 / hiddenimports / excludes / 版本资源 |
| 构建驱动 | `<ROOT>/build_tools/build_exe.py` | 门禁 → 调用 PyInstaller → 产物校验 → 摘要 |
| 密钥扫描器 | `<ROOT>/build_tools/secret_scan.py` | 被 build_exe 内嵌调用 |
| 源码包 | `<ROOT>/futures_quant/` | 整树作为 datas 打入（剔除 `__pycache__`/`*.pyc`） |
| 随包配置 | `<ROOT>/config/` | `settings.json` / `style.qss` / `*.example.json`（真实凭据文件被 spec 排除） |
| 图片资源 | `<ROOT>/images/` | 二维码 / 产品图；`images/ico.ico` 用作 exe 图标 |
| 可选内嵌字体 | `<ROOT>/assets/fonts/` | **当前不存在**；缺失时回退系统 `C:/Windows/Fonts/simhei.ttf` |
| 构建环境 | `/d/anaconda3/python.exe`（3.13.5 x64）+ PyInstaller 6.21.0 | managed 3.13.12 **无 PyQt6**，不可用 |

### 1.2 输出（OUTPUT）

```
<ROOT>/dist/
└── FuturesQuant/                      # ← 分发单元（整个目录打包 zip 即绿色版）
    ├── FuturesQuant.exe               # 主程序（console=False，无黑窗；图标 images/ico.ico）
    └── _internal/                     # PyInstaller 6.x 单目录模式，datas/binaries 全部落此处
        ├── base_library.zip
        ├── config/                    # settings.json / style.qss / ctp_settings.example.json
        ├── images/                    # link_qrcode / pay_qrcode / product
        ├── futures_quant/             # 源码树（.py/.json/.txt，无 __pycache__）
        ├── PyQt6/                     # Qt6 插件与 DLL
        ├── pandas/ numpy/ ...         # 第三方包
        └── *.dll                      # python3xx.dll、Qt6*.dll、MKL 系 DLL 等
```

运行时生成（**不属于构建产物**）：
- `<exe同级>/data/` —— 数据库 / 用户配置 / 会话；exe 所在目录只读时自动回退 `%APPDATA%/FuturesQuant/data`（见 `futures_quant/runtime.py:74`）。

### 1.3 验收标准（Definition of Done，全部为真才算完成）

| # | 验收项 | 通过判定 |
|---|---|---|
| D-1 | 主程序存在且可启动 | `dist/FuturesQuant/FuturesQuant.exe` 存在，进程存活 ≥15s 未退出 |
| D-2 | 资源齐全 | `_internal/config/`、`_internal/images/link_qrcode/qq.png`、`_internal/images/pay_qrcode/wx-pay.png` 均存在 |
| D-3 | 无密钥 / 无凭据文件 | `build_exe.py` 打印 `[验证] 产物扫描通过` 且退出码 0 |
| D-4 | 无 `__pycache__` 残留 | 产物内 `__pycache__` 目录数 = 0 |
| D-5 | 版本号一致 | exe 属性 `ProductVersion` == `futures_quant.__version__` |
| D-6 | 绿色便携 | 拷贝 `dist/FuturesQuant` 到另一可写目录（如 `D:\_portable_test\`），双击可启动 |
| D-7 | 零安装 | 目标机无需 Python / VC++ 运行库安装即可启动（Win10 1809+ / Win11 自带 UCRT） |
| D-8 | 产物体积在阈值内 | 默认路径 ≤ 900 MB；启用 §6 瘦身方案后目标 ≤ 350 MB |

---

## 2. 环境与现状基线（2026-10-09 实测）

| 项 | 实测值 |
|---|---|
| Python | `3.13.5 (Anaconda) AMD64` |
| PyInstaller | `6.21.0` |
| PyQt6 / pandas / numpy / pymysql / akshare / requests | 已安装（`torch` **未安装**，spec 已将其 exclude） |
| UPX | **不在 PATH** → spec 的 `upx=True` 仅产生告警、不生效 |
| 当前产物体积 | `843 MB`（其中 `_internal` 820 MB） |
| 体积构成 TOP | MKL 系 DLL 约 600 MB；PyQt6 71 MB；pandas 18 MB；ctpbee_api 17 MB |
| 已知环境风险 | anaconda 存在跨项目 `sitecustomize.py`（含 "DLL固定" 注入，指向 `D:\PythonProject\KP-AI-FENGSHUI`），打包子进程会执行它 |
| 工作区状态 | 存在未提交修改（`build_tools/futures_qt.spec`、`main.spec`、`futures_quant/ui/main_window.py`、`splash.py`） |
| 历史残留 | `dist/FuturesQuant.old-1790731607`、`dist/FuturesQuant.old-manual-1790730482` |

---

## 3. 实施步骤总览

```
S01 环境校验          S02 版本与工作区校验     S03 构建环境净化
  → S04 依赖锁定       → S05 构建前安全门禁    → S06 执行构建
  → S07 产物结构校验   → S08 产物安全复查      → S09 绿色便携冒烟
  → S10 体积治理（可选）→ S11 代码签名（可选）  → S12 分发归档
```

---

## 4. 详细步骤

### S01 环境校验

**前置条件**：Git Bash 位于 `<ROOT>`；anaconda Python 可用。

**执行**：

```bash
cd /d/PythonProject/QuantVortex
PY=/d/anaconda3/python.exe

$PY -c "import sys;print('PY',sys.version.split()[0],sys.maxsize>2**32)"
$PY -c "import PyInstaller;print('PYI',PyInstaller.__version__)"
$PY -c "import PyQt6,pandas,numpy;print('DEPS ok')"
$PY -c "import futures_quant as f;print('APP',f.__version__,f.__release_date__)"
ls images/ico.ico config/settings.json config/style.qss main.py
```

**预期结果**：

```
PY 3.13.5 True
PYI 6.21.0
DEPS ok
APP 5.2.15 2026-10-07
（四个路径均存在，无 No such file）
```

**验证方式**：任一命令非 0 退出或输出不符 → 停止，按 §7 排查。
**失败处理**：`PYI` 缺失 → `$PY -m pip install "pyinstaller>=6.0"`（需联网）；`DEPS ok` 缺失 → 按 `requirements.txt` 补齐。

---

### S02 版本与工作区校验

**前置条件**：S01 通过。

**执行**：

```bash
cd /d/PythonProject/QuantVortex
grep -n "__version__\|__release_date__" futures_quant/__init__.py | head -5
git status --short
git diff --stat
```

**预期结果**：`__version__ = "5.2.15"` 等单行定义；`git status` 仅列出预期改动，无意外的新增/删除。

**验证方式**：
- 版本号 SSOT 唯一：除 `futures_quant/__init__.py` 外不得有第二处硬编码版本（spec 在构建时动态读取，不重复定义）。
- 若工作区存在未提交的功能改动，**先确认是否应纳入本次构建**；未确认前不得构建（`git stash` 或提交）。

**失败处理**：版本需变更时只改 `futures_quant/__init__.py` 的 `__version__` 与 `__release_date__`（`__app_version__` 是 import 别名，需同步确认存在），再进入 S03。

---

### S03 构建环境净化（本次新增，针对实测风险）

**前置条件**：S02 通过；无正在运行的 `FuturesQuant.exe`（`tasklist | grep -i futuresquant`）。

**执行**：

```bash
# 3.1 关闭占用进程（否则旧产物目录无法清理，build_exe 会走归档分支）
tasklist 2>/dev/null | grep -i futuresquant || echo "no running exe"

# 3.2 清理历史归档残留（每个约 800MB+）
cd /d/PythonProject/QuantVortex
ls -d dist/FuturesQuant.old-* 2>/dev/null
rm -rf dist/FuturesQuant.old-*            # 确认无保留价值后执行；勿动 dist/FuturesQuant 本身

# 3.3 处理跨项目 sitecustomize 污染（anaconda 会在每次 python 启动时执行）
ls -la /d/anaconda3/Lib/site-packages/sitecustomize.py
grep -c "DLL固定" /d/anaconda3/Lib/site-packages/sitecustomize.py
mv /d/anaconda3/Lib/site-packages/sitecustomize.py \
   /d/anaconda3/Lib/site-packages/sitecustomize.py.bak
```

**预期结果**：
- `rm` 后 `ls -d dist/FuturesQuant.old-*` 无输出。
- `mv` 后再次运行 `/d/anaconda3/python.exe -c "print(1)"` **不再打印** `[DLL固定] 检测到项目目录: D:\PythonProject\KP-AI-FENGSHUI`。

**验证方式**：执行 `/d/anaconda3/python.exe -c "print('clean')"` → 输出仅 `clean`。

**失败处理**：
- `mv` 失败（文件被占用/只读）→ 改用 **§6 方案 A 的干净 venv** 构建（venv 不继承 site-packages 的 sitecustomize）。
- **构建完成后必须还原**：
  ```bash
  mv /d/anaconda3/Lib/site-packages/sitecustomize.py.bak \
     /d/anaconda3/Lib/site-packages/sitecustomize.py
  ```

---

### S04 依赖锁定与 spec 复核

**前置条件**：S03 通过。

**执行**：

```bash
cd /d/PythonProject/QuantVortex
# 4.1 确认 spec 关键安全/收集配置仍在（防止被误改回整目录打包）
grep -n "CONFIG_DENY\|_internal\|upx\|console=\|icon=\|version=\|excludes=\|collect_submodules" build_tools/futures_qt.spec

# 4.2 确认 config 目录无未被黑名单覆盖的本地凭据
ls -la config/
```

**预期结果**：
- `CONFIG_DENY` 含 `ctp_settings.json / secrets.json / credentials.json / upstream.json`；
- `console=False`、`icon=images/ico.ico`、`version=_VER_FILE`、`upx=True`（UPX 缺失时仅告警，见 §6.3）；
- `excludes` 列表存在且含 `torch / matplotlib / scipy / notebook / tornado` 等（完整清单见 spec 176-201 行）；
- `config/` 下如出现 `ctp_settings.json`（本地实盘凭据）**不会**被打入（spec 源头跳过）。

**验证方式**：`ls dist/FuturesQuant/_internal/config`（构建后复核，见 S07）不得出现 `ctp_settings.json`。

---

### S05 构建前安全门禁

**前置条件**：S04 通过。

**执行**：

```bash
cd /d/PythonProject/QuantVortex
/d/anaconda3/python.exe build_tools/secret_scan.py \
    --skip-dirs dist --skip-dirs build --skip-dirs __pycache__ . 2>&1 | tail -20
echo "SCAN_RC=$?"
```

> 若需追查已知历史泄露密钥（逗号分隔，仅设在本机环境变量，不入库）：
> `export QV_SCAN_LITERALS="<key1>,<key2>"`

**预期结果**：无 `疑似密钥` 命中行，`SCAN_RC=0`。

**验证方式**：`build_exe.py` 内部强制重跑同一门禁（不可关闭），此步为提前自测，避免 20 分钟构建后才失败。

**失败处理**：命中真实密钥 → 改由运行时环境变量注入（如 `QV_AGNES_API_KEY`），删除源码硬编码后重跑；确属误报 → 在该行加注释 `# secret-scan: allow`（唯一逃生口，会留在代码里被 review）。

---

### S06 执行构建

**前置条件**：S05 通过；磁盘可用空间 ≥ 5 GB（workpath + dist）。

**执行**：

```bash
cd /d/PythonProject/QuantVortex
export TMP=D:/PythonProject/QuantVortex/.pytest_tmp
export TEMP=$TMP TMPDIR=$TMP
mkdir -p "$TMP" .pytest_tmp

/d/anaconda3/python.exe build_tools/build_exe.py > .pytest_tmp/build.log 2>&1
echo "BUILD_RC=$?"
tail -30 .pytest_tmp/build.log
```

> ⚠️ **禁止使用管道**（`| grep`/`| tail`）直接取退出码：会返回管道的 rc 而非构建 rc，历史上造成"全绿其实是失败"的误判。必须 `> log 2>&1` 后 `echo $?`。

**预期结果**（日志尾部关键行）：

```
[门禁] 源码扫描通过。
[构建] 执行： ... -m PyInstaller --noconfirm --workpath ... --distpath .../dist .../futures_qt.spec
[产物] 主程序：存在  文件数：NNNN  总体积：XXX.X MB
[验证] 产物中无本地凭据文件混入。
[验证] 产物中无 __pycache__ 残留。
[验证] 产物扫描通过：未发现任何密钥。
[完成] 可执行文件位于：
        D:\PythonProject\QuantVortex\dist\FuturesQuant
BUILD_RC=0
```

**验证方式**：`BUILD_RC=0` **且** 日志含 `[产物] 主程序：存在` **且** 含 `[验证] 产物扫描通过`。三者缺一即判失败。

**失败处理**：按 §7 退出码表定位。构建耗时通常 10~25 分钟（Analysis 阶段最慢）；`workpath` 每次用带时间戳的新目录（`build/pyi_<ts>`），保证干净构建。

---

### S07 产物结构与完整性校验

**前置条件**：S06 返回 0。

**执行**：

```bash
cd /d/PythonProject/QuantVortex
D=dist/FuturesQuant

# 7.1 主程序
ls -la $D/FuturesQuant.exe

# 7.2 必需资源
ls $D/_internal/config/
ls $D/_internal/images/link_qrcode/qq.png $D/_internal/images/pay_qrcode/wx-pay.png
ls $D/_internal/futures_quant/ | head -5

# 7.3 源码树已打入且无字节码缓存
find $D/_internal/futures_quant -name "__version__.py" -o -name "runtime.py" | head
echo "pycache_dirs=$(find $D -type d -name __pycache__ | wc -l)"
echo "pyc_files=$(find $D -name '*.pyc' -not -path '*/base_library*' | wc -l)"

# 7.4 凭据文件黑名单复查（构建器已查，此处独立复核）
find $D -type f \( -name "ctp_settings.json" -o -name "secrets.json" \
     -o -name "credentials.json" -o -name "upstream.json" -o -name ".env" \
     -o -name "*.key" -o -name "*.pem" -o -name "*.local.json" \) \
     -not -name "cacert.pem" | tee /tmp/leak.txt
echo "LEAK_COUNT=$(wc -l < /tmp/leak.txt)"

# 7.5 体积
du -sh $D $D/_internal
du -sh $D/_internal/* | sort -rh | head -10
```

**预期结果**：

| 检查 | 期望 |
|---|---|
| `FuturesQuant.exe` | 存在，约 23.8 MB |
| `_internal/config/` | `settings.json`、`style.qss`、`ctp_settings.example.json`（**无** `ctp_settings.json`） |
| 二维码 | 两个 png 均存在 |
| `pycache_dirs` | `0` |
| `pyc_files` | `0` |
| `LEAK_COUNT` | `0` |
| `_internal/futures_quant/` | 含 `__init__.py`、`runtime.py` 等 |

**验证方式**：上表逐行比对；任一不符 → 判定构建不合格，回到 S04 修 spec 后重跑 S06（**不得手工往 dist 里补/删文件**）。

---

### S08 产物安全复查（二进制字节级）

**前置条件**：S07 通过。

**执行**：

```bash
cd /d/PythonProject/QuantVortex
/d/anaconda3/python.exe build_tools/secret_scan.py dist/FuturesQuant --binary-only > .pytest_tmp/artifact_scan.log 2>&1
echo "ARTIFACT_SCAN_RC=$?"
tail -20 .pytest_tmp/artifact_scan.log
```

**预期结果**：`ARTIFACT_SCAN_RC=0`，无命中。

**验证方式**：与 S06 内嵌校验互为独立双证；两者都必须为 0。
**失败处理**：命中 → **该产物不可分发**，直接 `rm -rf dist/FuturesQuant`，排查数据源后重跑 S06。

---

### S09 绿色便携冒烟测试

**前置条件**：S08 通过；`dist/FuturesQuant/FuturesQuant.exe` 存在。

#### 9.1 便携性验证（复制到新目录运行）

```bash
rm -rf /d/_portable_test && mkdir -p /d/_portable_test
cp -r /d/PythonProject/QuantVortex/dist/FuturesQuant /d/_portable_test/
ls /d/_portable_test/FuturesQuant/FuturesQuant.exe
```

#### 9.2 启动冒烟（PowerShell，推荐）

```powershell
$exe = "D:\_portable_test\FuturesQuant\FuturesQuant.exe"
$p = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 20
$p.Refresh()
if ($p.HasExited) { "FAIL: exe exited, code=$($p.ExitCode)" } else { "OK: alive pid=$($p.Id)" }
Get-Process -Id $p.Id | Select-Object Id, ProcessName, MainWindowTitle | Format-List
Get-ChildItem "D:\_portable_test\FuturesQuant\data" -ErrorAction SilentlyContinue | Select-Object -First 10
Stop-Process -Id $p.Id -Force
```

**预期结果**：
- `OK: alive pid=...`（进程 20 秒后仍存活，未崩溃退出）；
- `MainWindowTitle` 非空（主窗口已创建，非黑屏/静默崩溃）；
- `D:\_portable_test\FuturesQuant\data\` 被自动创建（绿色便携：数据落在 exe 同级，未写注册表、未写系统目录）。

#### 9.3 启动冒烟（Python 版，便于 CI/无人值守）

落盘为 `<ROOT>/tools/smoke_exe.py` 后执行：

```python
"""EXE 启动冒烟：进程存活 + 主窗口出现 + data 目录生成。用法：
   python tools/smoke_exe.py <exe_path> [--wait 20]"""
import argparse, os, subprocess, sys, time

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("exe"); ap.add_argument("--wait", type=int, default=20)
    a = ap.parse_args()
    exe = os.path.abspath(a.exe)
    if not os.path.isfile(exe):
        print(f"FAIL: exe 不存在 {exe}"); return 2
    proc = subprocess.Popen([exe], cwd=os.path.dirname(exe))
    time.sleep(a.wait)
    rc = proc.poll()
    if rc is not None:
        print(f"FAIL: 进程已退出 rc={rc}"); return 1
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
```

```bash
/d/anaconda3/python.exe tools/smoke_exe.py /d/_portable_test/FuturesQuant/FuturesQuant.exe --wait 20
echo "SMOKE_RC=$?"
```

**预期结果**：`OK: 存活 pid=...` + `data_dir=... exists=True` + `SMOKE_RC=0`。

**验证方式**：D-1 / D-6 / D-7 三项验收以此为准。
**失败处理**：
- 进程秒退 → 大概率缺 Qt 平台插件或依赖；改用临时控制台版（`console=True` 重建一次）抓 traceback；
- `MainWindowTitle` 为空但进程存活 → 疑似启动阻塞（历史上为 showEvent 同步网络导致白屏），检查 `logs/` 下运行时日志；
- `data/` 未生成 → 检查 `runtime.get_data_dir()` 是否回退到 `%APPDATA%/FuturesQuant/data`（说明目标目录不可写，非缺陷但要记录）。

---

### S10 体积治理（可选，但 843 MB 默认产物建议执行）

**前置条件**：S09 通过（先保证可用，再瘦身）。

**现状**：`843 MB`，其中 MKL 系 DLL 约 600 MB（anaconda 版 numpy 绑定 MKL：`mkl_core` 75M、`mkl_avx512` 56M、`mkl_intel_thread` 53M、`mkl_pgi_thread` 52M、`mkl_avx` 44M、`mkl_mc3` 43M、`mkl_mc` 42M、`mkl_avx2` 42M、`mkl_def` 38M、`mkl_rt` 32M、`mkl_tbb_thread` 31M、`mkl_sequential` 25M 及 vml_* 系列）。

#### 方案 A（推荐，安全）：干净 venv + pip 版 numpy（OpenBLAS）

```bash
cd /d/PythonProject/QuantVortex
/d/anaconda3/python.exe -m venv .build_venv
.build_venv/Scripts/python.exe -m pip install -U pip setuptools wheel
.build_venv/Scripts/python.exe -m pip install "numpy>=1.24" "pandas>=2.0" \
    "PyQt6>=6.6,<7.0" "pymysql>=1.1" "requests" "pyinstaller>=6.0"
.build_venv/Scripts/python.exe -c "import numpy;print(numpy.__config__.show())" 2>&1 | head -20
```

- 预期：numpy 后端为 `openblas`（非 `mkl`），产物预计降至 **200~300 MB**。
- venv 不继承 anaconda 的 `sitecustomize.py`，S03 的改名步骤可省略。
- 用 venv 解释器驱动构建：`/d/PythonProject/QuantVortex/.build_venv/Scripts/python.exe build_tools/build_exe.py`。
- ⚠️ 若项目实际用到 `akshare`（当前已安装、spec 未排除），需一并 `pip install akshare` 到 venv，否则运行时功能缺失。
- 完成后**必须重跑 S06→S09 全部验证**（换解释器 = 换依赖基线）。

#### 方案 B（激进，需实测）：spec 内过滤未使用 MKL 内核

在 `build_tools/futures_qt.spec` 的 `a = Analysis(...)` 之后、`pyz = PYZ(...)` 之前插入：

```python
# 体积治理：剔除与本机无关/未被加载的 MKL 内核（保留 core/rt/intel_thread/avx2/def）
_MKL_KEEP = ("mkl_core", "mkl_rt", "mkl_intel_thread", "mkl_avx2", "mkl_def")
def _mkl_filter(binaries):
    kept, dropped = [], []
    for b in binaries:
        name = os.path.basename(b[0]).lower()
        if name.startswith("mkl_") and not name.startswith(_MKL_KEEP):
            dropped.append(name)
        else:
            kept.append(b)
    print(f"[spec][瘦身] 剔除 MKL 内核 {len(dropped)} 个：{sorted(set(dropped))}")
    return kept

a.binaries = _mkl_filter(a.binaries)
```

- 预期：节省约 300~400 MB。
- **风险**：目标机 CPU 若需被剔除的内核（老 CPU 需 `mkl_def`/`mkl_sequential`，特定指令集需 `mkl_avx512`/`mkl_mc*`）可能加载失败 → 必须在 **S09 冒烟 + 至少一台不同 CPU 的目标机** 上复测；任一失败即回滚本改动。
- **验证方式**：`du -sh dist/FuturesQuant/_internal` 下降 ≥ 250 MB 且 S09 全部通过。

#### 6.3 UPX 压缩

UPX 当前不在 PATH → `upx=True` 不生效（仅告警）。二选一：
- 安装 UPX 并加入 PATH（构建期自动生效，可再压 20~35%）；
- 或把 spec 的 `upx=True` 改为 `upx=False` 消除告警噪音。

> ⚠️ UPX 压缩 Qt/MKL 大 dll 会显著拖慢构建，且个别杀软对 UPX 壳误报；**建议不启用**。

---

### S11 代码签名（可选，消除 SmartScreen「未知发布者」）

**前置条件**：S09 通过；本机安装 Windows SDK 且 `signtool` 在 PATH；持有代码签名证书。

**执行**：

```bash
cd /d/PythonProject/QuantVortex
export QV_SIGN=1
export QV_SIGN_THUMBPRINT="<证书 SHA1 指纹>"      # 或用 QV_SIGN_SUBJECT="<证书主题名>"
export QV_TIMESTAMP_URL="http://timestamp.digicert.com"
/d/anaconda3/python.exe build_tools/build_exe.py > .pytest_tmp/build_signed.log 2>&1
echo "RC=$?"; grep -c "\[签名\] 已签名" .pytest_tmp/build_signed.log
```

**预期结果**：日志出现 `[签名] 已签名：<file>`（对 exe + 所有 dll/pyd 逐个签名）；任一失败会打印 `[签名] 失败` 但不阻断构建。

**验证方式**：

```powershell
(Get-Item "dist\FuturesQuant\FuturesQuant.exe").VersionInfo | Select-Object ProductVersion, FileVersion
Get-AuthenticodeSignature "dist\FuturesQuant\FuturesQuant.exe" | Select-Object Status, SignerCertificate
```

- 期望：`Status = Valid`，`ProductVersion` == `5.2.15`（同时完成 D-5 验收）。

---

### S12 分发归档

**前置条件**：S09 必过；S10/S11 若执行则亦通过。

**执行**：

```bash
cd /d/PythonProject/QuantVortex
VER=$(/d/anaconda3/python.exe -c "import futures_quant as f;print(f.__version__)")
OUT="dist/FuturesQuant-v${VER}-win64-portable.zip"
rm -f "$OUT"
cd dist/FuturesQuant && zip -rq "../FuturesQuant-v${VER}-win64-portable.zip" . && cd ..
ls -la "$OUT"
```

**预期结果**：生成 `dist/FuturesQuant-v5.2.15-win64-portable.zip`（约 200~800 MB，取决于是否瘦身）。

**验证方式**：
1. 解压到全新目录 → 重跑 S09 冒烟（**zip 路径必须复验**，压缩/解压易丢空目录或长路径资源）；
2. 确认 zip 内不含 `data/`（运行时数据不得随分发包走）；
3. 附一份 `使用说明.txt`：双击 `FuturesQuant.exe` 即可；数据默认生成在 exe 同级 `data/`；整个目录可放 U 盘携带；如需云端 AI 研判，由用户自行设置环境变量 `QV_AGNES_API_KEY`，未设置自动降级本地规则。

---

## 5. 配置参考

### 5.1 spec 关键配置（`<ROOT>/build_tools/futures_qt.spec`）

| 配置项 | 当前值 | 作用 | 修改风险 |
|---|---|---|---|
| `Analysis([ROOT/main.py])` | `main.py` | 唯一入口 | 改入口须同步 `pathex` |
| `pathex` | `[ROOT]` | 模块搜索根 | 缺失则 `futures_quant` 导入失败 |
| `datas` | `config/*`（凭据黑名单过滤）、`images/`、`assets/fonts/`（若存在）、`futures_quant/**`（剔 `__pycache__`/`*.pyc`） | 随包资源 | **不得**改回整目录 `datas.append((cfg_dir,"config"))` |
| `hiddenimports` | `collect_submodules("futures_quant")`(实测 136) + PyQt6 + 8 个显式模块 | 防漏动态导入 | 新增延迟导入模块时须补 |
| `excludes` | 约 40 项（torch/matplotlib/scipy/Jupyter 栈/tornado/boto3/panel/bokeh 等） | 瘦身 + 缩攻击面 | 删除任一项须确认源码零引用 |
| `console` | `False` | 无黑窗 | 调试期可临时 `True` |
| `icon` | `images/ico.ico` | exe 图标 | 文件缺失则构建失败 |
| `version` | `build_tools/_app_version_info.txt`（spec 运行期自动生成） | exe 版本资源 | 勿手改该文件 |
| `upx` | `True`（UPX 未安装 → 仅告警） | 压缩 | 见 §6.3 |
| `cipher` | `None`（EXE）/ `None`（PYZ） | 不加密字节码 | **编译不是加密**，安全靠密钥门禁而非加密 |

### 5.2 环境变量

| 变量 | 取值 | 作用 | 备注 |
|---|---|---|---|
| `QV_SCAN_LITERALS` | 逗号分隔密钥串 | 追查已知历史泄露 | 仅本机 env，禁止入库 |
| `QV_SIGN` | `1` | 启用签名 | 缺省跳过 |
| `QV_SIGN_THUMBPRINT` / `QV_SIGN_SUBJECT` | 指纹 / 主题名 | 指定证书 | 二选一 |
| `QV_TIMESTAMP_URL` | 时间戳服务 | 签名时间戳 | 默认 digicert |
| `QV_AGNES_API_KEY` | 用户自持密钥 | 运行时注入云端 AI | **不进产物** |
| `TMP/TEMP/TMPDIR` | `<ROOT>/.pytest_tmp` | 加速构建（避开慢速系统临时盘） | 见 S06 |

---

## 6. 验证矩阵（一次性全量核对）

| # | 检查 | 命令 | 期望 | 不符时动作 |
|---|---|---|---|---|
| V1 | 构建退出码 | `echo $?` after S06 | `0` | 查 §7 |
| V2 | 主程序 | `ls dist/FuturesQuant/FuturesQuant.exe` | 存在 ~23.8MB | 重跑 S06 |
| V3 | 随包配置 | `ls dist/FuturesQuant/_internal/config` | 3 个文件，无 `ctp_settings.json` | 修 spec datas |
| V4 | 图片资源 | `ls .../_internal/images/{link_qrcode/qq.png,pay_qrcode/wx-pay.png}` | 均存在 | 修 spec（build_exe 会以 rc=9 阻断） |
| V5 | 源码树 | `ls .../_internal/futures_quant/runtime.py` | 存在 | 修 spec datas |
| V6 | 字节码残留 | `find dist/FuturesQuant -name __pycache__ \| wc -l` | `0` | 修 spec 收集逻辑 |
| V7 | 凭据文件 | S07 步骤 7.4 | `LEAK_COUNT=0` | 修 spec `CONFIG_DENY` |
| V8 | 产物密钥扫描 | S08 | `RC=0` | 作废产物重构建 |
| V9 | 版本号 | PowerShell `VersionInfo.ProductVersion` | `5.2.15` | 改 `futures_quant/__init__.py` |
| V10 | 启动存活 | S09.2 / S09.3 | 20s 未退出 + 窗口标题非空 | 控制台版抓 traceback |
| V11 | 便携性 | 复制到 `D:\_portable_test` 运行 | 可启动 + 同级生成 `data/` | 检查 `runtime.get_data_dir()` |
| V12 | 体积 | `du -sh dist/FuturesQuant` | 默认 ≤900MB；瘦身后 ≤350MB | 执行 S10 |
| V13 | zip 可解压运行 | 解压后重跑 S09 | 通过 | 检查压缩参数 |

---

## 7. 故障排查表

### 7.1 `build_exe.py` 退出码

| 码 | 含义 | 处理 |
|---|---|---|
| 0 | 成功 | 进入 S07 |
| 1 | 未找到 `futures_qt.spec` | 确认在 `build_tools/` 下执行，勿用 `main.spec` |
| 3 | 源码发现密钥 | 删除硬编码，改环境变量注入；误报加 `# secret-scan: allow` |
| 4 | 产物发现密钥 | **产物不可分发**，`rm -rf dist/FuturesQuant` 后排查重构建 |
| 5 | 未生成 `FuturesQuant.exe` | 查看 `build/pyi_<ts>/` 下 PyInstaller 输出，多为 excludes 误删依赖 |
| 6 | 旧产物目录既不能删也不能重命名 | 关闭占用进程 / 释放句柄，或用 §6 方案 A 的新 distpath |
| 7 | 产物混入本地凭据文件 | 修 spec `CONFIG_DENY` / datas 收集逻辑 |
| 8 | 产物 `user_settings.json` 含 `api_key` | 修 `AIConfig`：打包模式不得持久化密钥 |
| 9 | 缺失必需图片（qq.png / wx-pay.png） | 检查 `images/` 目录与 spec datas |

### 7.2 常见故障

| 现象 | 根因 | 处理 |
|---|---|---|
| 输出 `[DLL固定] 检测到项目目录: D:\PythonProject\KP-AI-FENGSHUI` | anaconda `sitecustomize.py` 跨项目污染 | S03.3 改名；构建后还原 |
| UPX 相关告警刷屏 | UPX 未安装 | 安装 UPX 入 PATH，或 spec `upx=False` |
| PyInstaller 找不到模块（运行时 `ModuleNotFoundError`） | 动态/延迟导入未进 hiddenimports | 补 `hiddenimports`；本项目已靠整包 datas 兜底 |
| exe 双击无反应/秒退 | 缺 Qt 平台插件或依赖被 exclude | 临时 `console=True` 重建抓栈；检查是否误排除必要包 |
| 启动白屏 | 主线程同步网络阻塞事件循环 | 已有 `_lazy_refresh_all()`；检查是否新增长耗时同步调用 |
| 构建极慢（>40 min） | `excludes` 被删导致 Analysis 扫描科学计算栈 | 恢复 excludes 清单 |
| `COLLECT` 阶段 `PermissionError` | 旧产物被占用 | S03.1 关闭进程；build_exe 已内置归档兜底 |
| 分发后客户端无 AI 功能 | 云端密钥未注入 | 用户设 `QV_AGNES_API_KEY`，未设自动降级本地规则（非缺陷） |

---

## 8. 执行清单（AI 逐条勾选）

```
[ ] S01 环境校验通过（PY 3.13.5 / PYI 6.21.0 / DEPS ok / APP 5.2.15）
[ ] S02 版本 SSOT 唯一，工作区状态已确认
[ ] S03 旧归档清理 + sitecustomize 改名（并在构建后还原）
[ ] S04 spec 安全配置与 config 目录复核
[ ] S05 构建前密钥门禁 RC=0
[ ] S06 build_exe.py BUILD_RC=0，日志含 [产物] 主程序：存在 + [验证] 产物扫描通过
[ ] S07 产物结构校验（含 pycache=0 / LEAK_COUNT=0）
[ ] S08 产物二进制扫描 RC=0
[ ] S09 绿色便携冒烟（新目录启动存活 + data/ 生成）
[ ] S10 体积治理（可选；843MB → 目标 ≤350MB）
[ ] S11 代码签名（可选；Status=Valid）
[ ] S12 zip 归档 + 解压复验
```

---

## 9. 附录：一键复验脚本（AI 可直接落盘执行）

落盘为 `<ROOT>/tools/verify_dist.py`：

```python
"""产物验收：结构 / 资源 / 体积 / 残留 / 凭据。用法：
   python tools/verify_dist.py [dist_dir]   # 默认 dist/FuturesQuant"""
from __future__ import annotations
import os, sys

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
    checks: list[tuple[str, bool, str]] = []
    exe = os.path.join(dist, "FuturesQuant.exe")
    internal = os.path.join(dist, "_internal")

    def need(rel: str) -> bool:
        for base in (os.path.join(internal, rel), os.path.join(dist, rel)):
            if os.path.exists(base):
                return True
        return False

    checks.append(("主程序 FuturesQuant.exe", os.path.isfile(exe), exe))
    for rel in ("config/settings.json", "config/style.qss",
                "images/link_qrcode/qq.png", "images/pay_qrcode/wx-pay.png",
                "futures_quant/runtime.py"):
        checks.append((f"资源 {rel}", need(rel), rel))
    checks.append(("config 无 ctp_settings.json",
                   not os.path.exists(os.path.join(internal, "config", "ctp_settings.json")),
                   "config/ctp_settings.json"))
    n_pyc = sum(1 for r, _, fs in os.walk(dist) for f in fs if f.endswith(".pyc"))
    checks.append(("无 __pycache__", not any("__pycache__" in d for r, ds, _ in os.walk(dist) for d in ds), ""))
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
```

```bash
/d/anaconda3/python.exe tools/verify_dist.py dist/FuturesQuant
echo "VERIFY_RC=$?"      # 期望 0
```

### 9.1 实测记录（2026-10-09，未重新构建，仅对现存 `dist/FuturesQuant` 执行）

```
VERIFY_RC=0
[PASS] 主程序 FuturesQuant.exe
[PASS] 资源 config/settings.json / config/style.qss
[PASS] 资源 images/link_qrcode/qq.png / images/pay_qrcode/wx-pay.png
[PASS] 资源 futures_quant/runtime.py
[PASS] config 无 ctp_settings.json
[PASS] 无 __pycache__      [PASS] 无 .pyc 残留 pyc=0
[PASS] 无凭据文件           [PASS] 体积 <= 900.0MB  → 839.7 MB
总计 11 项，失败 0 项
```

exe 版本资源实测：`ProductVersion=5.2.15; FileVersion=5.2.15; ProductName=QuantVortex`（与 `futures_quant.__version__` 一致，D-5 通过）。

> 说明：该产物为 2026-10-07 构建，体积 839.7 MB 未瘦身。下次构建按 S10 执行方案 A 后，预计降至 200~300 MB。
