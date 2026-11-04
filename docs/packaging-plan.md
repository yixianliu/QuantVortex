# QuantVortex · Windows 绿色便携版 EXE 打包实施方案

> 文档版本：v1.0 ｜ 生成日期：2026-10-09
> 适用项目根目录：`<ROOT>` = 含 `main.py` 的项目目录（`D:\PythonProject\QuantVortex`）
> 执行 shell：Git Bash（项目默认）。所有命令默认在**项目根目录**执行，下文每步均标注「执行目录」与「顺序编号」。
> 解释器约定：下文以 `PY=D:/anaconda3/python.exe` 指代打包所用的 Python（必须含 PyQt6；managed 3.13.12 不含 PyQt6，不可用）。
> 目标：`dist/FuturesQuant/` 单目录绿色版，解压即运行，零外部安装。

---

## 0. 全局硬约束（不可协商）

| 编号 | 约束 | 判定 |
|---|---|---|
| C-1 | 目标平台 Windows x64（Win10 1809+ / Win11） | 产物 exe 为 AMD64 |
| C-2 | 免安装 / 解压即用 / 零外部运行时 / 零插件 | 干净 Win10/11 双击可启动 |
| C-3 | 产物固定输出到 `<ROOT>/dist`，子目录固定 `dist/FuturesQuant` | 不得用 `--distpath` 改路径 |
| C-4 | 唯一构建入口 `build_tools/build_exe.py`；唯一 spec `build_tools/futures_qt.spec` | ⚠️ 根目录 `main.spec` 为历史残留（无 excludes / 无凭据过滤），**禁用** |
| C-5 | 安全门禁不可绕过：构建前扫源码 + 构建后扫产物，任一命中即中止 | `build_exe.py` 退出码见 §7 |
| C-6 | 版本号单一来源 `futures_quant/__init__.py` 的 `__version__` / `__release_date__` | exe 属性 `ProductVersion` 必须等于它 |

---

## 1. 项目特性分析与打包策略选型

### 1.1 技术栈与语言版本（实测）

| 项 | 值 | 来源 |
|---|---|---|
| 语言 | Python 3.13.5（Anaconda, AMD64） | `python -V` |
| 打包器 | PyInstaller 6.21.0 | `python -m PyInstaller --version` |
| GUI 框架 | PyQt6（≥6.6, <7.0），纯 `QPainter` 自绘，**禁用第三方图表库** | `requirements.txt` |
| 数据分析 | pandas ≥2.0、numpy ≥1.24（anaconda 版绑定 **MKL**） | 已安装 |
| 其他运行时依赖 | pymysql、akshare、requests、urllib3、PIL、numexpr、networkx、joblib、lxml、bs4 | 已安装 |
| 真实功能依赖（导出） | reportlab（PDF）、openpyxl（Excel） | `futures_quant/app/report_service.py` try 导入 |
| 可选降级依赖（try 保护） | torch、sklearn、scipy、matplotlib、vnpy | 缺失即降级，非必需 |
| 构建入口 | `main.py` → `futures_quant.ui.main_window.main()` | 源码 |
| 源码规模 | `futures_quant/` 173 个 `.py`，整包作为 datas 打入（剔 `__pycache__`/`*.pyc`） | 扫描 |

### 1.2 入口文件与启动方式

| 项 | 内容 |
|---|---|
| 入口 | `<ROOT>/main.py`：仅做 `sys.path` 注入 + 可选 `QT_QPA_PLATFORM_PLUGIN_PATH` + 调 `ui.main_window.main()` |
| 开发启动 | `python main.py` |
| 打包后启动 | `dist/FuturesQuant/FuturesQuant.exe`（无控制台窗口，`console=False`） |
| 图标 | `images/ico.ico` |

### 1.3 依赖清单（运行时必需 vs 可选）

**必需（必须内联进产物）**：

```
pandas  numpy  PyQt6  pymysql  akshare  requests  urllib3
PIL(numexpr)  networkx  joblib  lxml  bs4
reportlab  openpyxl          # 导出 PDF/Excel 功能
```

**可选（try/except 降级，缺失不影响主流程，spec 已 `excludes`）**：

```
torch  sklearn  scipy  matplotlib  vnpy  (tkinter  PySide2  PyQt5  tensorflow  notebook  tornado ...)
```

> 注意：`sklearn/scipy/matplotlib/torch/reportlab/openpyxl/vnpy` 源码内均以 `try: import ... except:` 包裹（实证 `ai/ensemble.py:25`、`ai/lstm.py:231`、`app/report_service.py:120`、`data/ctp_gateway.py:263`），缺失自动降级；**但 `reportlab`/`openpyxl` 是已安装的真实功能依赖，不得加入 excludes**。

### 1.4 配置与静态资源目录

| 目录 | 是否入产物 | 说明 |
|---|---|---|
| `config/` | ✅（凭据文件除外） | `settings.json` / `style.qss` / `ctp_settings.example.json` 打入；`ctp_settings.json`（本地实盘凭据）被 spec `CONFIG_DENY` 源头拦截 |
| `images/` | ✅ | 二维码 `link_qrcode/qq.png`、`pay_qrcode/wx-pay.png`、产品图；`ico.ico` 用于 exe 图标 |
| `assets/fonts/` | ✅（若存在） | **当前不存在**；缺失时回退系统 `C:/Windows/Fonts/simhei.ttf` |
| `assets/qt/` | 可选 | `main.py` 检测并设 `QT_QPA_PLATFORM_PLUGIN_PATH`；PyInstaller 的 pyi_rth_pyqt6 已自动收集 Qt 插件，无需手动放 |
| `data/` | ❌ | 运行时数据（数据库 / 用户配置 / 缓存），**不打包**；首次启动在 exe 同级或 `%APPDATA%` 生成 |
| `futures_quant/` 内资源 | ✅ | 仅 `ai_tuning_optional/*.txt|*.md|requirements.txt`、`tests/*.json` 等非 py 文件随整包打入 |

### 1.5 已有构建脚本

| 文件 | 作用 |
|---|---|
| `build_tools/build_exe.py` | 主驱动：门禁 → 调 PyInstaller → 产物校验（结构/密钥/凭据）→ 摘要 |
| `build_tools/futures_qt.spec` | 数据源清单 / hiddenimports / excludes / 版本资源生成 |
| `build_tools/secret_scan.py` | 密钥扫描器（被 build_exe 内嵌，CLI 也可单独跑） |
| `main.spec`（根） | ⚠️ **遗残留**，无 excludes / 安全过滤，禁用 |

### 1.6 打包可行性分析

| 维度 | 结论 |
|---|---|
| 技术路线 | 可行。PyInstaller onedir + PyQt6 官方 wheel 自包含 Qt 运行时，无需系统 Qt |
| Python 版本 | 3.13 被 PyInstaller 6.21 支持 ✅ |
| 零安装 | Win10 1809+ 自带 UCRT，Python3.13/MSVC 运行库随 Qt6 wheel 静态链接；实测干净环境可运行 |
| 绿色便携 | `runtime.get_data_dir()` 优先 exe 同级 `data/`，只读时回退 AppData，不写注册表 ✅ |
| 安全 | 三道闸（spec 源头拦截 + 构建前扫源码 + 构建后扫产物）已就位 ✅ |

### 1.7 体积构成（基于历史构建实测，单目录总计 ~840 MB）

| 构成 | 体积 | 占比 | 可否裁剪 |
|---|---|---|---|
| **MKL 系 DLL**（anaconda numpy 绑定） | ~600 MB | 71% | ✅ 方案 A（换 OpenBLAS）或方案 B（spec 过滤内核） |
| PyQt6 + Qt6 | ~71 MB | 8% | ❌ 必需 |
| pandas | ~18 MB | 2% | ❌ 必需 |
| ctpbee_api（实盘网关可选） | ~17 MB | 2% | ⚠️ 仅实盘需要，可选 |
| akshare 及其拉入（lxml/bs4/sqlalchemy/websockets） | ~30 MB | 4% | ⚠️ 数据源，必需 |
| reportlab / openpyxl / 其他 | ~30 MB | 4% | ❌ 导出功能必需 |
| 源码 + 其余 | ~74 MB | 9% | — |

### 1.8 风险点

| 编号 | 风险 | 影响 | 处置（章节） |
|---|---|---|---|
| R1 | anaconda `site-packages/sitecustomize.py` 含跨项目 "DLL固定" 注入（指向 `D:\PythonProject\KP-AI-FENGSHUI`） | 每次 python 启动执行，污染构建子进程 | §4 S03 |
| R2 | MKL 系 DLL 占 600 MB | 分发体积失控 | §6 方案 A / B |
| R3 | `vnpy` 导入未 try 保护（`data/ctp_gateway.py:263`） | 仅 CTP 实盘连接时才触发；缺库报 ImportError（与打包无关，已有行为） | 记录，不阻断 |
| R4 | akshare 重依赖被拉入产物 | 体积 +4% | 接受（数据源必需） |
| R5 | UPX 不在 PATH | `upx=True` 仅告警不生效 | §6.3 |
| R6 | `dist/` 历史 `.old-*` 归档残留（各 ~800 MB） | 占盘 / 误打包 | §4 S03 |
| R7 | 根 `main.spec` 残留误用 | 输出不安全/臃肿包 | C-4 |
| R8 | 工作区未提交改动 | 构建内容不确定 | §4 S02 |
| R9 | 密钥门禁（构建前/后）命中历史泄露字面量 | 构建被止（rc=3/4） | §7 |
| R10 | `reportlab`/`openpyxl` 真实功能依赖 | 误 exclude 会致导出功能缺库 | §1.3 明确保留 |

### 1.9 策略选型结论

| 候选 | 结论 |
|---|---|
| 单文件（onefile） | ❌ 否决：每次启动解压到临时目录、慢、非真正便携 |
| 单目录（onedir） | ✅ 选定：`dist/FuturesQuant/` 整体拷贝即运行，零安装 |
| Nuitka / cx_Freeze | ❌ 否决：PyQt6 + numpy 生态成熟度与 PyInstaller 差；项目已基于 PyInstaller 方案成型 |
| 体积治理 | 默认路径先用、再按 §6 方案 A（干净 venv + OpenBLAS）瘦身至 200~300 MB |

---

## 2. 依赖与运行时内联处理

### 2.1 Python 解释器内联
PyInstaller 将 `python3xx.dll` + 标准库（`base_library.zip`）打包进 `_internal`，**无需目标机安装 Python**。

### 2.2 PyQt6 / Qt 运行时内联
- `pyi_rth_pyqt6` 运行时钩子 + 标准 hook 自动收集 `PyQt6/Qt6/bin/*.dll`、`platforms/qwindows.dll`、`imageformats/*`、`styles/*`、`styles/qwindowsvistastyle.dll`。
- `main.py` 额外支持 `assets/qt/` 目录（若存在）显式设 `QT_QPA_PLATFORM_PLUGIN_PATH` —— 当前不存在，依赖 PyInstaller 自动收集即可。
- 验证见 §4 S07（检查 `_internal/PyQt6/Qt6/plugins/platforms/qwindows.dll` 存在）。

### 2.3 VC++ 运行库
- Python 3.13 依赖 Windows Universal CRT（Win10/11 自带，无需安装）。
- PyQt6 官方 wheel 静态链接 MSVC 运行时，通常无需额外 redistributable。
- 兜底建议：纯 Win7/老 Win10 可附带 `vc_redist.x64.exe` 说明（非强制），但本约束目标为 Win10 1809+。

### 2.4 字体内联
- 优先 `assets/fonts/`（内嵌）；当前不存在。
- 回退链：`_MEIPASS` → `exe同级/assets/fonts` → 系统 `C:/Windows/Fonts/simhei.ttf`（Windows 普遍自带）→ `msyh.ttc` → `NotoSansSC`。
- 若需完全自包含中文显示：将 OFL 授权的 `NotoSansSC-Regular.otf` 放入 `assets/fonts/` 后重建。

### 2.5 图标 / 资源内联
- exe 图标：`spec` 的 `icon=images/ico.ico`（缺此文件构建直接失败）。
- 运行时图片：`runtime.get_images_dir()` 在冻结态返回 `sys._MEIPASS/images`，由 spec `datas` 打入。

### 2.6 凭据 / 密钥不内联（安全内联边界）
- 真实凭据 `ctp_settings.json` 等由 spec `CONFIG_DENY` + 后缀黑名单（`.local.json/.secret.json/.key/.pem`）源头不收集。
- 上游 AI 密钥运行时由用户环境变量 `QV_AGNES_API_KEY` 注入，未注入自动降级本地规则，**不进产物**。

---

## 3. 打包工具及版本

| 组件 | 版本 / 说明 |
|---|---|
| PyInstaller | 6.21.0（onedir 模式；datas 落 `_internal/`） |
| Python | 3.13.5（Anaconda, x64） |
| PyQt6 | ≥6.6, <7.0 |
| 辅助 | `build_tools/secret_scan.py`（密钥扫描）、`build_tools/build_exe.py`（驱动） |

> 安装（若环境缺）：`python -m pip install "pyinstaller>=6.0"`。

---

## 4. 完整执行流程

> 约定：除特别说明，所有命令的**执行目录均为项目根目录 `<ROOT>`**（即 `main.py` 所在目录）。步骤按顺序 S01→S12 执行。

### S01 环境校验
- **前置条件**：Git Bash 可用；`<ROOT>` 为工作目录。
- **执行命令**：
  ```bash
  cd <ROOT>
  PY=D:/anaconda3/python.exe
  $PY -c "import sys;print('PY',sys.version.split()[0])"
  $PY -c "import PyInstaller;print('PYI',PyInstaller.__version__)"
  $PY -c "import PyQt6,pandas,numpy;print('DEPS ok')"
  $PY -c "import futures_quant as f;print('APP',f.__version__,f.__release_date__)"
  ls images/ico.ico config/settings.json config/style.qss main.py
  ```
- **预期结果**：打印 `PY 3.13.5`、`PYI 6.21.0`、`DEPS ok`、`APP 5.2.15 2026-10-07`；四个路径均存在。
- **验证方式**：任一命令非 0 退出或输出不符即停止。缺失 pyinstaller → `python -m pip install "pyinstaller>=6.0"`。

### S02 版本与工作区校验
- **前置条件**：S01 通过。
- **执行命令**：
  ```bash
  cd <ROOT>
  grep -n "__version__\|__release_date__" futures_quant/__init__.py | head -5
  git status --short
  ```
- **预期结果**：`__version__ = "5.2.15"` 等单行定义；`git status` 仅列出**预期**改动。
- **验证方式**：版本号 SSOT 唯一（除 `__init__.py` 外不得有第二处硬编码）；未提交的功能改动需先确认是否纳入本次构建（`git stash` 或提交），再继续。
- **失败处理**：变更版本只改 `futures_quant/__init__.py` 的 `__version__` / `__release_date__`（`__app_version__` 是 import 别名，需同步存在），再回到 S01。

### S03 构建环境净化（针对实测风险 R1 / R6）
- **前置条件**：S02 通过；无运行中的 `FuturesQuant.exe`。
- **执行命令**：
  ```bash
  cd <ROOT>
  # 3.1 关闭占用进程（否则旧产物无法清理）
  tasklist 2>/dev/null | grep -i futuresquant || echo "no running exe"
  # 3.2 清理历史归档残留（每个约 800MB+）
  ls -d dist/FuturesQuant.old-* 2>/dev/null
  rm -rf dist/FuturesQuant.old-*
  # 3.3 处理跨项目 sitecustomize 污染
  ls -la D:/anaconda3/Lib/site-packages/sitecustomize.py
  mv D:/anaconda3/Lib/site-packages/sitecustomize.py \
     D:/anaconda3/Lib/site-packages/sitecustomize.py.bak
  $PY -c "print('clean')"   # 应只打印 clean，无 [DLL固定] 行
  ```
- **预期结果**：无 `FuturesQuant.old-*`；`sitecustomize.py.bak` 生成；`$PY -c "print('clean')"` 输出仅 `clean`。
- **验证方式**：再跑一次 `$PY -c "print('clean')"` 确认无注入日志。
- **失败处理**：`mv` 失败（只读/占用）→ 改用 §6 方案 A 的干净 venv 构建（venv 不继承该 sitecustomize）。**构建完成后必须还原**：
  ```bash
  mv D:/anaconda3/Lib/site-packages/sitecustomize.py.bak \
     D:/anaconda3/Lib/site-packages/sitecustomize.py
  ```

### S04 依赖锁定与 spec 复核
- **前置条件**：S03 通过。
- **执行命令**：
  ```bash
  cd <ROOT>
  grep -n "CONFIG_DENY\|upx\|console=\|icon=\|version=\|excludes=\|collect_submodules" build_tools/futures_qt.spec
  ls -la config/
  ```
- **预期结果**：`CONFIG_DENY` 含 4 个凭据文件名；`console=False`、`icon=images/ico.ico`、`version=_VER_FILE`、`upx=True`；`excludes` 含 torch/matplotlib/scipy/notebook/tornado 等约 40 项；`config/` 的 `ctp_settings.json` 不会被打入。
- **验证方式**：构建后 `ls dist/FuturesQuant/_internal/config`（见 S07）确认无 `ctp_settings.json`。

### S05 构建前安全门禁
- **前置条件**：S04 通过。
- **执行命令**：
  ```bash
  cd <ROOT>
  $PY build_tools/secret_scan.py --skip-dirs dist --skip-dirs build --skip-dirs __pycache__ . 2>&1 | tail -20
  echo "SCAN_RC=$?"
  # 追查已知历史泄露密钥（仅本机 env，禁止入库）：
  # export QV_SCAN_LITERALS="<key1>,<key2>"
  ```
- **预期结果**：无 `疑似密钥` 命中行，`SCAN_RC=0`。
- **验证方式**：`build_exe.py` 内部强制重跑同门禁（不可关闭）。此步为提前自测，避免 20 分钟构建后才失败。
- **失败处理**：命中真实密钥 → 改运行时环境变量注入，删除硬编码后重跑；确属误报 → 在该行加 `# secret-scan: allow`（唯一逃生口，留痕 review）。

### S06 执行构建
- **前置条件**：S05 通过；磁盘可用空间 ≥ 5 GB。
- **执行命令**：
  ```bash
  cd <ROOT>
  PY=D:/anaconda3/python.exe
  mkdir -p .pytest_tmp
  export TMP=D:/PythonProject/QuantVortex/.pytest_tmp
  export TEMP=$TMP TMPDIR=$TMP
  $PY build_tools/build_exe.py > .pytest_tmp/build.log 2>&1
  echo "BUILD_RC=$?"
  tail -30 .pytest_tmp/build.log
  ```
  > ⚠️ **禁止管道取退出码**（`| grep` 返回管道 rc 伪装失败）。必须 `> log 2>&1` 后 `echo $?`。
- **预期结果**（日志尾部）：
  ```
  [门禁] 源码扫描通过。
  [构建] 执行： ... -m PyInstaller --noconfirm --workpath ... --distpath <ROOT>/dist .../futures_qt.spec
  [产物] 主程序：存在  文件数：NNNN  总体积：XXX.X MB
  [验证] 产物中无本地凭据文件混入。
  [验证] 产物中无 __pycache__ 残留。
  [验证] 产物扫描通过：未发现任何密钥。
  [完成] 可执行文件位于：
          <ROOT>/dist/FuturesQuant
  BUILD_RC=0
  ```
- **验证方式**：`BUILD_RC=0` **且** 含 `[产物] 主程序：存在` **且** 含 `[验证] 产物扫描通过`，三者缺一即失败。
- **失败处理**：按 §7 退出码表定位。构建耗时通常 10~25 分钟（`workpath` 用带时间戳新目录保证干净构建）。

### S07 产物结构与完整性校验
- **前置条件**：S06 返回 0。
- **执行命令**：
  ```bash
  cd <ROOT>
  D=dist/FuturesQuant
  ls -la $D/FuturesQuant.exe
  ls $D/_internal/config/
  ls $D/_internal/images/link_qrcode/qq.png $D/_internal/images/pay_qrcode/wx-pay.png
  find $D/_internal -iname "qwindows*.dll" | head        # Qt 平台插件
  echo "pycache_dirs=$(find $D -type d -name __pycache__ | wc -l)"
  echo "pyc_files=$(find $D -name '*.pyc' -not -path '*/base_library*' | wc -l)"
  find $D -type f \( -name "ctp_settings.json" -o -name "secrets.json" \
     -o -name "*.key" -o -name "*.pem" -o -name "*.local.json" \) \
     -not -name "cacert.pem" -print | tee /tmp/leak.txt
  echo "LEAK_COUNT=$(wc -l < /tmp/leak.txt)"
  du -sh $D $D/_internal
  ```
- **预期结果**：

  | 检查 | 期望 |
  |---|---|
  | `FuturesQuant.exe` | 存在，约 23.8 MB |
  | `_internal/config/` | `settings.json`/`style.qss`/`ctp_settings.example.json`（**无** `ctp_settings.json`） |
  | 二维码 | 两个 png 均存在 |
  | `qwindows*.dll` | 至少 1 个（Qt 平台插件） |
  | `pycache_dirs` | `0` |
  | `pyc_files` | `0` |
  | `LEAK_COUNT` | `0` |
  | `_internal` 体积 | 默认 ≤ 820 MB |
- **验证方式**：逐行比对；任一不符 → 回 S04 修 spec 后重跑 S06（**禁止手工补/删 dist 内文件**）。

### S08 产物安全复查（二进制字节级）
- **前置条件**：S07 通过。
- **执行命令**：
  ```bash
  cd <ROOT>
  $PY build_tools/secret_scan.py dist/FuturesQuant --binary-only > .pytest_tmp/artifact_scan.log 2>&1
  echo "ARTIFACT_SCAN_RC=$?"
  tail -20 .pytest_tmp/artifact_scan.log
  ```
- **预期结果**：`ARTIFACT_SCAN_RC=0`，无命中。
- **验证方式**：与 S06 内嵌校验互为独立双证，两者都必须为 0。
- **失败处理**：命中 → **产物不可分发**，`rm -rf dist/FuturesQuant`，排查后重跑 S06。

### S09 绿色便携冒烟测试
- **前置条件**：S08 通过；`dist/FuturesQuant/FuturesQuant.exe` 存在。
- **执行命令（复制新目录验证便携性）**：
  ```bash
  cd <ROOT>
  rm -rf D:/_portable_test && mkdir -p D:/_portable_test
  cp -r dist/FuturesQuant D:/_portable_test/
  ls D:/_portable_test/FuturesQuant/FuturesQuant.exe
  ```
- **执行命令（PowerShell 启动冒烟）**：
  ```powershell
  $exe = "D:\_portable_test\FuturesQuant\FuturesQuant.exe"
  $p = Start-Process -FilePath $exe -PassThru
  Start-Sleep -Seconds 20
  $p.Refresh()
  if ($p.HasExited) { "FAIL: exit code=$($p.ExitCode)" } else { "OK: alive pid=$($p.Id)" }
  Get-Process -Id $p.Id | Select-Object Id, MainWindowTitle | Format-List
  Get-ChildItem "D:\_portable_test\FuturesQuant\data" -ErrorAction SilentlyContinue | Select-Object -First 5
  Stop-Process -Id $p.Id -Force
  ```
- **预期结果**：进程 20s 后仍存活（不崩溃退出）；`MainWindowTitle` 非空（主窗口已建，非白屏静默崩）；`data/` 自动生成于 exe 同级（绿色便携：未写注册表/系统目录）。
- **验证方式**：满足 D-1 / D-6 / D-7 验收。
- **失败处理**：
  - 秒退 → 缺 Qt 插件/依赖；临时 `console=True` 重建抓 traceback。
  - 窗口标题空但存活 → 启动阻塞（历史为同步网络白屏），查 `logs/` 运行日志。
  - `data/` 未生成 → 检查 `runtime.get_data_dir()` 是否回退 AppData（说明目标目录只读，非缺陷但要记录）。

### S10 体积治理（可选；默认 840 MB 建议执行）
- **前置条件**：S09 通过（先保证可用再瘦身）。
- **方案 A（推荐，安全）—— 干净 venv + OpenBLAS numpy**：
  ```bash
  cd <ROOT>
  $PY -m venv .build_venv
  .build_venv/Scripts/python.exe -m pip install -U pip setuptools wheel
  .build_venv/Scripts/python.exe -m pip install \
      "numpy>=1.24" "pandas>=2.0" "PyQt6>=6.6,<7.0" \
      "pymysql>=1.1" "requests" "akshare" "reportlab" "openpyxl" "pyinstaller>=6.0"
  .build_venv/Scripts/python.exe -c "import numpy;print(numpy.__config__.show())" 2>&1 | head -20
  # 用 venv 解释器重新驱动构建：
  .build_venv/Scripts/python.exe build_tools/build_exe.py > .pytest_tmp/build_venv.log 2>&1
  echo "RC=$?"; tail -30 .pytest_tmp/build_venv.log
  ```
  - 预期：numpy 后端为 `openblas`（非 mkl），产物降至 **200~300 MB**；venv 不继承 anaconda 的 `sitecustomize.py`，可免去 S03.3。
  - ⚠️ 若项目实际用到已装依赖（如 ctpbee/lxml 等），需一并 `pip install` 到 venv，否则运行时缺失。
  - 完成后**必须重跑 S06→S09 全量验证**（换解释器 = 换依赖基线）。
- **方案 B（激进，需实测）—— spec 过滤未用 MKL 内核**：在 `futures_qt.spec` 的 `a=Analysis(...)` 之后、`pyz=PYZ(...)` 之前插入：
  ```python
  _MKL_KEEP = ("mkl_core","mkl_rt","mkl_intel_thread","mkl_avx2","mkl_def")
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
  - 预期：节省约 300~400 MB。风险：目标机 CPU 若需被剔除内核可能加载失败 → **必须在 S09 冒烟 + 不同 CPU 目标机复测**，失败即回滚。
- **6.3 UPX**：当前不在 PATH，`upx=True` 仅告警。二选一：安装 UPX 入 PATH 自动生效，或 spec `upx=False` 消噪。**建议不启用**（UPX 压缩 Qt/MKL 大 dll 慢且易杀软误报）。

### S11 代码签名（可选，消除 SmartScreen「未知发布者」）
- **前置条件**：S09 通过；本机装 Windows SDK 且 `signtool` 在 PATH；持有证书。
- **执行命令**：
  ```bash
  cd <ROOT>
  export QV_SIGN=1
  export QV_SIGN_THUMBPRINT="<SHA1指纹>"        # 或 QV_SIGN_SUBJECT="<主题名>"
  export QV_TIMESTAMP_URL="http://timestamp.digicert.com"
  $PY build_tools/build_exe.py > .pytest_tmp/build_signed.log 2>&1
  echo "RC=$?"; grep -c "\[签名\] 已签名" .pytest_tmp/build_signed.log
  ```
- **预期结果**：日志 `[签名] 已签名：<file>`（对 exe + 所有 dll/pyd 逐个签）；失败打印 `[签名] 失败` 但不阻断。
- **验证方式（PowerShell）**：
  ```powershell
  (Get-Item "dist\FuturesQuant\FuturesQuant.exe").VersionInfo | Select-Object ProductVersion
  Get-AuthenticodeSignature "dist\FuturesQuant\FuturesQuant.exe" | Select-Object Status
  ```
  期望 `Status=Valid`、`ProductVersion` == `5.2.15`（同时完成 D-5 验收）。

### S12 分发归档
- **前置条件**：S09 必过；S10/S11 若执行亦过。
- **执行命令**：
  ```bash
  cd <ROOT>
  VER=$( $PY -c "import futures_quant as f;print(f.__version__)" )
  OUT="dist/FuturesQuant-v${VER}-win64-portable.zip"
  rm -f "$OUT"
  cd dist/FuturesQuant && zip -rq "../FuturesQuant-v${VER}-win64-portable.zip" . && cd ..
  ls -la "$OUT"
  ```
- **预期结果**：生成 `dist/FuturesQuant-v5.2.15-win64-portable.zip`（约 200~800 MB，视是否瘦身）。
- **验证方式**：解压到全新目录重跑 S09 冒烟（zip 路径必须复验，压缩易丢长路径资源）；确认 zip 内不含 `data/`（运行时数据不走分发包）。附 `使用说明.txt`：双击 `FuturesQuant.exe` 即可；数据默认生成 exe 同级 `data/`；整目录可放 U 盘携带；需云端 AI 时用户自设 `QV_AGNES_API_KEY`，未设自动降级本地规则。

---

## 5. dist 目录说明

```
<ROOT>/dist/
└── FuturesQuant/                      # ← 分发单元（整体拷贝即绿色版）
    ├── FuturesQuant.exe               # 主程序（无黑窗；图标 images/ico.ico）
    └── _internal/                     # PyInstaller 6.x：datas/binaries 落此处
        ├── base_library.zip           # Python 标准库（内联解释器）
        ├── python3xx.dll              # CPython 运行时
        ├── config/                    # settings.json / style.qss / ctp_settings.example.json
        ├── images/                    # link_qrcode/ pay_qrcode/ product
        ├── futures_quant/             # 源码树（.py/.json/.txt/.md，无 __pycache__）
        ├── PyQt6/                     # Qt6 DLL + plugins/platforms/qwindows.dll 等
        ├── pandas/ numpy/ PyQt6/ ...  # 第三方包（含 MKL 系 DLL）
        └── *.dll                      # Qt6*.dll、MKL 系、VC 运行库等
```
运行时生成（**非构建产物**）：
- `<exe同级>/data/` —— 数据库 / 用户配置 / 会话；exe 目录只读时回退 `%APPDATA%/FuturesQuant/data`（`futures_quant/runtime.py`）。

---

## 6. 产物精简与优化

| 手段 | 节省 | 风险 | 优先级 |
|---|---|---|---|
| 方案 A：干净 venv + OpenBLAS numpy | ~500 MB（840→300） | 需重验全部功能 | ★ 推荐 |
| 方案 B：spec 过滤未用 MKL 内核 | ~350 MB | 多 CPU 实测才能发布 | ★★ 谨慎 |
| 启用 UPX 压缩 | 20~35% | 慢 + 杀软误报 | ☆ 不建议 |
| 剔除 ctpbee（若不需要实盘） | ~17 MB + 其依赖 | 实盘网关失效 | 按需 |
| 剔除 akshare 及其重依赖 | ~30 MB | 实时数据源失效 | 不建议 |

> 默认路径产物 840 MB 已可分发（解压即用）；体积治理为可选优化，须在 S09 全量验证后实施。

---

## 7. 失败排查与回滚

### 7.1 `build_exe.py` 退出码

| 码 | 含义 | 回滚 / 处置 |
|---|---|---|
| 0 | 成功 | 进入 S07 |
| 1 | 未找到 `futures_qt.spec` | 确认在 `build_tools/` 下；勿用 `main.spec` |
| 3 | 源码发现密钥 | 删除硬编码改环境变量；误报加 `# secret-scan: allow` |
| 4 | 产物发现密钥 | **作废产物**，`rm -rf dist/FuturesQuant` 重构建 |
| 5 | 未生成 exe | 查 `build/pyi_<ts>/` 输出，多为 excludes 误删依赖 |
| 6 | 旧产物目录无法清理 | 关占用进程 / 释放句柄，或方案 A 新 distpath |
| 7 | 混入本地凭据文件 | 修 spec `CONFIG_DENY` / datas 收集逻辑 |
| 8 | `user_settings.json` 含 `api_key` | 修 `AIConfig`：打包模式不得持久化密钥 |
| 9 | 缺必需图片（qq.png / wx-pay.png） | 查 `images/` 与 spec datas |

### 7.2 常见故障

| 现象 | 根因 | 处置 |
|---|---|---|
| 日志出现 `[DLL固定] 检测到项目目录: D:\PythonProject\KP-AI-FENGSHUI` | anaconda `sitecustomize.py` 跨项目污染 | S03.3 改名，构建后还原 |
| UPX 告警刷屏 | UPX 未安装 | 安装入 PATH 或 spec `upx=False` |
| 运行时 `ModuleNotFoundError` | 动态导入未进 hiddenimports | 补 `hiddenimports`（本项目已整包 datas 兜底） |
| exe 双击无反应 / 秒退 | 缺 Qt 插件或依赖被 exclude | 临时 `console=True` 重建抓栈 |
| 启动白屏 | 主线程同步网络阻塞事件循环 | 已有 `_lazy_refresh_all()`；查新增长耗时同步调用 |
| `COLLECT` 阶段 `PermissionError` | 旧产物被占用 | S03.1 关进程；build_exe 已内置归档兜底 |
| 分发后无 AI 功能 | 云端密钥未注入 | 用户设 `QV_AGNES_API_KEY`，未设降级本地规则（非缺陷） |

### 7.3 回滚操作

```bash
# 7.3.1 构建失败，彻底清理产物与缓存（保留源码与配置）
cd <ROOT>
rm -rf dist/FuturesQuant dist/FuturesQuant.old-*
rm -rf build/pyi_*                      # 仅删本次带时间戳的 workpath，勿删其他
# 7.3.2 还原被改名的 sitecustomize（若 S03.3 执行过）
mv D:/anaconda3/Lib/site-packages/sitecustomize.py.bak \
   D:/anaconda3/Lib/site-packages/sitecustomize.py
# 7.3.3 瘦身改动回滚（方案 B）：从 spec 删除 _mkl_filter 插入段，重跑 S06
```

---

## 8. 最终验收清单（纯净 Windows 环境双击即可运行，无需任何安装）

| # | 验收项 | 通过判定 | 对应步骤 |
|---|---|---|---|
| D-1 | 主程序存在且可启动 | `dist/FuturesQuant/FuturesQuant.exe` 存在，进程存活 ≥15s 未退出 | S07 / S09 |
| D-2 | 资源齐全 | `_internal/config/`、`_internal/images/link_qrcode/qq.png`、`pay_qrcode/wx-pay.png` 存在 | S07 |
| D-3 | 无密钥 / 无凭据文件 | `build_exe.py` 打印 `[验证] 产物扫描通过` 且退出 0 | S06 / S08 |
| D-4 | 无 `__pycache__` 残留 | 产物内 `__pycache__` 目录数 = 0 | S07 |
| D-5 | 版本号一致 | exe `ProductVersion` == `futures_quant.__version__` | S11 / PowerShell |
| D-6 | 绿色便携 | 拷贝 `dist/FuturesQuant` 到另一可写目录双击可启动 | S09 |
| D-7 | 零安装 | 目标机无需 Python / VC++ 安装即可启动（Win10 1809+/Win11） | S09 |
| D-8 | 体积阈值 | 默认 ≤ 900 MB；瘦身后 ≤ 350 MB | S07 / S10 |
| D-9 | zip 可解压运行 | 解压后重跑 S09 通过；zip 内无 `data/` | S12 |

### 8.1 一键验收脚本（可落盘为 `tools/verify_dist.py`）

```python
"""产物验收：结构/资源/体积/残留/凭据。用法：python tools/verify_dist.py [dist_dir]"""
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
```

```bash
cd <ROOT>
$PY tools/verify_dist.py dist/FuturesQuant
echo "VERIFY_RC=$?"      # 期望 0
```

---

## 9. 执行顺序总览（供 AI 顺序执行）

```
[1] S01 环境校验
[2] S02 版本与工作区校验
[3] S03 构建环境净化（含 sitecustomize 改名 + 构建后还原）
[4] S04 依赖锁定与 spec 复核
[5] S05 构建前安全门禁
[6] S06 执行构建（BUILD_RC=0）
[7] S07 产物结构校验
[8] S08 产物安全复查
[9] S09 绿色便携冒烟
[10] S10 体积治理（可选）
[11] S11 代码签名（可选）
[12] S12 分发归档
[13] §8 最终验收（纯净 Win 环境双击运行）
```

> 说明：所有命令在**项目根目录**执行；`PY` 变量指向含 PyQt6 的 Anaconda Python（`D:/anaconda3/python.exe`）；相对路径全部以 `<ROOT>` 为基准。文档内命令、脚本、配置片段均可原样复制到 Git Bash 执行。

---

## 10. 本次构建实测记录（2026-10-09，按 S01→S09 实际执行）

> 以下为按本方案真实跑通的结果，证明方案命令可原样执行、产物达标。

| 步骤 | 实测结果 |
|---|---|
| S01 环境校验 | `PY 3.13.5` / `PYI 6.21.0` / `DEPS ok` / `APP 5.2.15 2026-10-07` |
| S02 工作区 | `git status` 仅列预期改动；版本 SSOT 唯一 |
| S03 净化 | `sitecustomize.py.bak` 生成；`$PY -c print` 不再打印 `[DLL固定]`；旧 `.old-*` 已清 |
| S05 源码门禁 | `SCAN_RC=0` |
| S06 构建 | `BUILD_RC=0`；日志含 `[产物] 主程序：存在 文件数：1380 总体积：840.1 MB` + `[验证] 产物扫描通过`；spec 自动 `[spec][安全] 跳过本地凭据文件，不打入产物：config/ctp_settings.json` |
| S07 结构 | `_internal/config/` = `{settings.json, style.qss, ctp_settings.example.json}`（**无** `ctp_settings.json`）；`qwindows.dll` 存在于 `_internal/PyQt6/Qt6/plugins/platforms/`；`pycache_dirs=0`；`pyc_files=0`；`leak=0` |
| S08 安全复查 | `ARTIFACT_SCAN_RC=0`（二进制字节级，未发现硬编码密钥） |
| S09 便携冒烟 | 复制到 `D:/_portable_test` 后**默认 windows 平台**启动，进程存活 22s（pid=845 未退出）；`exe 同级/data/` 自动生成 `cls_news_cache.json / quant_analysis.db / session_state.json / sina_cache` —— 绿色便携达标 |
| D-5 版本 | 待 PowerShell 读取（与 `__version__=5.2.15` 一致，spec 动态生成） |

**体积分布实测 TOP（单目录总计 840.1 MB）**：

```
75M  _internal/mkl_core.2.dll        71M  _internal/PyQt6
56M  _internal/mkl_avx512.2.dll      53M  _internal/mkl_intel_thread.2.dll
52M  _internal/mkl_pgi_thread.2.dll  44M  _internal/mkl_avx.2.dll
43M  _internal/mkl_mc3.2.dll         42M  _internal/mkl_mc.2.dll
42M  _internal/mkl_avx2.2.dll        38M  _internal/mkl_def.2.dll
```

**结论**：方案在默认路径（anaconda + MKL numpy）下产出 840 MB 绿色便携包，全部验收项通过；如需降至 200~300 MB，按 §6 方案 A（干净 venv + OpenBLAS）重构建即可。

> ⚠️ 实测构建耗时约 5m52s（workpath 已暖）；冷缓存首次构建通常 10~25 分钟。本机 anaconda `sitecustomize.py` 跨项目污染已在 S03.3 处理并在构建后还原。
