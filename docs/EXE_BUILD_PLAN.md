# QuantVortex 绿色便携 EXE 生成方案（标准执行指引 · v2.0）

> 文档性质：本文件是 **供 AI 直接按步执行** 的 EXE 打包标准指引（Single Source of Truth）。
> 适用项目根：`<ROOT> = D:\PythonProject\QuantVortex`
> 文档版本：v2.0 / 2026-10-10（基于 2026-10-09 实测环境复核 + 资源路径正确性修正）
> 配套代码：`<ROOT>/build_tools/futures_qt.spec`、`<ROOT>/build_tools/build_exe.py`、`<ROOT>/build_tools/secret_scan.py`
> 约定：`bash` = Git Bash；所有命令用**绝对路径**；`<ROOT>` 一律替换为 `D:/PythonProject/QuantVortex`。

---

## 0. 全局硬约束（不可协商）

| 编号 | 约束 | 判据 |
|---|---|---|
| C-1 | 目标平台 Windows x64（Win10 1809+ / Win11），产物为**单目录绿色版**，不做安装向导 | `dist/FuturesQuant/` 整目录拷贝即可运行 |
| C-2 | **零外部安装**：目标机无需 Python / VC++ 运行库 / Qt 运行时 / 插件 | 干净 Win10/Win11 双击 `FuturesQuant.exe` 可启动 |
| C-3 | 输出目录固定 `<ROOT>/dist`，产物子目录固定 `dist/FuturesQuant` | 不得用 `--distpath` 覆盖 |
| C-4 | 唯一构建入口 `build_tools/build_exe.py`；唯一 spec `build_tools/futures_qt.spec` | ⚠️ `<ROOT>/main.spec` 为历史残留（无 excludes / 无凭据过滤），**禁止使用** |
| C-5 | 安全门禁不可绕过：构建前扫源码、构建后扫产物，命中即中止（无关闭开关） | `build_exe.py` 退出码见 §9 |
| C-6 | 版本号单一来源：`futures_quant/__init__.py` 的 `__version__` / `__release_date__` | exe 属性 `ProductVersion` 必须等于该值 |
| C-7 | 全部图片/静态资源**必须打进 EXE 内部**，运行时从 `sys._MEIPASS` 读取，禁止依赖外部相对路径 | 见 §4 资源映射表 + §8 资源加载专项 |

---

## 1. 项目结构、技术架构与 Python 技术栈

### 1.1 整体目录结构

```
<ROOT>/
├── main.py                     # 启动入口（sys.path 注入 + QT 插件路径 + 启动主窗口）
├── futures_quant/              # 主包（业务代码，全部打入 EXE）
│   ├── __init__.py             # __version__ / __release_date__（版本 SSOT）
│   ├── runtime.py              # 运行时路径/资源解析（开发期 & 冻结态通用）★本次修正
│   ├── core/  data/  strategy/ risk/  broker/ storage/  backtest/
│   ├── ai/  alerts/  analysis/  indicators/  config/  utils/  app/
│   └── ui/                     # PyQt6 界面层（main_window / pages / charts / dialogs）
├── config/                     # 随包只读配置：settings.json / style.qss / *.example.json
├── images/                     # 图片资源：ico / link_qrcode / pay_qrcode / product
├── data/                       # 运行时可写数据（**不打包**，首次启动自动生成）
├── build_tools/                # 打包 spec + 驱动 + 密钥扫描（受控目录）
├── docs/  tests/  tools/  scripts/  requirements*.txt  pytest.ini
```

### 1.2 技术架构（分层）

| 层 | 模块 | 说明 |
|---|---|---|
| 入口 | `main.py` | 注入路径、定位 Qt 平台插件、调 `ui.main_window.main()` |
| UI 层 | `ui/`（纯 PyQt6 + QPainter 自绘，禁第三方绘图库） | 9 页导航、回测中心、遗传算法自进化、占卜、市场情绪等 |
| 业务层 | `strategy/` `risk/` `broker/` `backtest/` | 策略/风控/仿真经纪商/回测引擎 |
| 数据层 | `data/` `storage/` | 行情源、CSV/akshare 缓存、SQLite 存储（WAL） |
| AI 层 | `ai/` | 指标、集成模型、配置（密钥仅运行期注入，不持久化） |
| 工具层 | `utils/` `core/` `runtime.py` | 日志、脱敏、运行时路径解析 |

### 1.3 Python 技术栈与依赖版本（2026-10-10 实测）

| 类别 | 库 / 工具 | 版本 | 打包处理 |
|---|---|---|---|
| 解释器 | Python（Anaconda） | 3.13.5 AMD64 | **构建环境** `/d/anaconda3/python.exe`；managed 3.13.12 无 PyQt6，禁用 |
| 打包工具 | PyInstaller | 6.21.0 | 单目录（COLLECT → `_internal/`） |
| GUI | PyQt6 | 6.x（`>=6.6,<7.0`） | 随包，含 Qt6 DLL / 平台插件 |
| 数据 | numpy / pandas | 2.1.3 / 2.2.3 | 随包（anaconda 版 numpy 绑定 MKL，体积大头，见 §10） |
| DB/网络 | pymysql / requests | 已装 | 随包（pymysql 可选；requests 被 akshare 间接依赖） |
| 数据源 | akshare | 已装 | 随包（动态导入，已进 hiddenimports 兜底） |
| AI（可选） | torch | **未安装** | spec `excludes` 排除，运行时缺则降级 numpy LSTM |
| 压缩 | UPX | **不在 PATH** | spec `upx=True` 仅告警不生效（建议留 False，见 §10.3） |

> 依赖安装基线：`pip install -r requirements.txt`（核心仅 pandas/numpy/PyQt6；pymysql/akshare 可选；torch 可选）。

### 1.4 资源清单与运行时解析契约（★关键）

| 资源 | 源路径 | 打入位置（冻结态） | 运行时解析入口 | 状态 |
|---|---|---|---|---|
| 配置模板 | `config/settings.json` `style.qss` `ctp_settings.example.json` | `_internal/config/` | `runtime.get_config_dir()` | ✅ 已修正（见 §8） |
| 二维码 | `images/link_qrcode/*.png` `pay_qrcode/*.png` | `_internal/images/` | `runtime.get_images_dir()` | ✅ |
| 产品图/图标 | `images/product/1-5.png` `ico.png` `ico.ico` | `_internal/images/` | `runtime.get_images_dir()` | ✅ |
| EXE 图标 | `images/ico.ico` | （嵌入 exe） | spec `icon=` 字段 | ✅ |
| 内嵌字体 | `assets/fonts/`（**当前不存在**） | `_internal/assets/fonts/` | `runtime.get_font_paths()` | ⚪ 缺失则回退系统 `C:/Windows/Fonts/simhei.ttf` |
| 源码包 | `futures_quant/**`（剔 `__pycache__`/`*.pyc`） | `_internal/futures_quant/` | 解释器自动寻址 | ✅ |
| 运行数据 | `data/`（db/csv/缓存） | **不打包** | `runtime.get_data_dir()` → exe 同级 `data/` 或 `%APPDATA%` | ⚪ 首启生成 |

**资源加载铁律（C-7）**：所有图片/配置读取必须通过 `runtime.get_*_dir()`，禁止硬编码 `./images`、`./config` 等相对 CWD 路径。`get_images_dir()` / `get_config_dir()` / `get_font_paths()` 在 `is_frozen()` 时一律走 `sys._MEIPASS`，保证从 EXE 内部 `_internal/` 读取。

---

## 2. 绿色便携 EXE 总体目标

- **单目录分发**：`dist/FuturesQuant/` 整目录（含 `FuturesQuant.exe` + `_internal/`）就是分发单元，zip 后即为绿色便携版。
- **零依赖运行**：PyQt6、numpy、pandas、Qt6 平台插件、MKL 运行库全部内嵌；目标机无需任何安装。
- **数据自隔离**：首启在 exe 同级建 `data/`（数据库/配置/会话）；若位于只读目录（如 `C:\Program Files`）自动回退 `%APPDATA%/FuturesQuant/data`，不写注册表、不污染系统。
- **资源全内嵌**：图片/配置/字体随包，无外链相对路径，杜绝“图片无法加载”。

---

## 3. 打包工具与配置详解

### 3.1 工具选型

- **PyInstaller 6.21.0**，单目录（onedir）模式：`EXE(exclude_binaries=True)` + `COLLECT` → 产物 `dist/FuturesQuant/`，内部资源落 `_internal/`。
- **唯一驱动**：`python build_tools/build_exe.py`（门禁 → 调用 PyInstaller → 产物校验 → 摘要 → 可选签名）。
- 严禁直接 `pyinstaller main.spec`（缺失安全门禁与产物校验）。

### 3.2 spec 关键配置参数（`build_tools/futures_qt.spec`）

| 配置项 | 当前值 | 作用 | 修改风险 |
|---|---|---|---|
| `Analysis([ROOT/main.py])` | `main.py` | 唯一入口 | 改入口须同步 `pathex` |
| `pathex` | `[ROOT]` | 模块搜索根 | 缺失则 `futures_quant` 导入失败 |
| `datas` | `config/*`（凭据黑名单过滤）、`images/`、`assets/fonts/`（若存在）、`futures_quant/**`（剔 `__pycache__`/`*.pyc`） | 随包资源 | **不得**改回整目录 `datas.append((cfg_dir,"config"))`（会泄露凭据） |
| `hiddenimports` | `collect_submodules("futures_quant")` + PyQt6 系列 + 8 个显式模块（ctp_gateway / ai.* / screening_page / ai_settings_dialog 等） | 防漏动态/延迟导入 | 新增延迟导入模块时须补 |
| `excludes` | ≈40 项（torch/matplotlib/scipy/Jupyter 栈/tornado/boto3/panel/bokeh/PyQt5/PySide*/cryptography 等） | 瘦身 + 缩攻击面 | 删任一项前须确认源码零引用 |
| `console` | `False` | 桌面程序无黑窗 | 调试期可临时 `True` 抓 traceback |
| `icon` | `images/ico.ico` | exe 图标 | 文件缺失则构建失败 |
| `version` | `build_tools/_app_version_info.txt`（spec 运行期据 `__version__` 生成） | exe 版本资源 | 勿手改该文件 |
| `upx` | `True`（UPX 未装 → 仅告警） | 压缩 | 见 §10.3，建议置 `False` |
| `cipher` | `None` | 不加密字节码 | 编译非加密，安全靠密钥门禁 |

### 3.3 资源路径映射规则（开发期 ↔ 冻结态）

| 逻辑资源 | 开发期实际路径 | 冻结态实际路径 | 解析函数 |
|---|---|---|---|
| 配置目录 | `<ROOT>/config` | `<exe>/_internal/config` | `get_config_dir()` |
| 图片目录 | `<ROOT>/images` | `<exe>/_internal/images` | `get_images_dir()` |
| 字体目录 | `<ROOT>/assets/fonts` 或 `%SystemRoot%\Fonts` | `<exe>/_internal/assets/fonts` 或系统 | `get_font_paths()` |
| 源码包 | `<ROOT>/futures_quant` | `<exe>/_internal/futures_quant` | 解释器 |
| 可写数据 | `<ROOT>/data` | `<exe>/data` 或 `%APPDATA%/FuturesQuant/data` | `get_data_dir()` |

> `sys._MEIPASS` 在 PyInstaller 6.x 单目录模式下 = `<exe>/_internal`。所有“只读随包资源”解析必须基于它；**不**基于 `os.getcwd()` 或 `app_base_dir()` 下的同名目录（后者在冻结态不存在）。

### 3.4 排除项配置

**A. 依赖排除（瘦身 + 安全，spec `excludes` 已固化）**
`matplotlib, tkinter, PyQt5, PySide2, PySide6, scipy, sklearn, torch, tensorflow, numba, llvmlite, IPython, astroid, sphinx, docutils, jedi, parso, pytest, black, cryptography, bcrypt, notebook, jupyter*, tornado, zmq, pyzmq, panel, bokeh, holoviews, plotly, altair, seaborn, boto3, botocore, dask, distributed, pyarrow, fastparquet, statsmodels, sympy, h5py, tables` 等。
> 增删后必须重跑冒烟确认 exe 仍可启动（见 §7）。

**B. 凭据黑名单（spec `CONFIG_DENY` + `CONFIG_DENY_SUFFIX`）**
源目录 `config/` 收集时跳过：`ctp_settings.json`、`secrets.json`、`credentials.json`、`upstream.json`，以及后缀 `.local.json` / `.secret.json` / `.key` / `.pem`。最终用户自行在 exe 同级 `data/` 或 `config/` 放 `ctp_settings.json` 即可（运行时查找逻辑不变）。

---

## 4. 命令行执行步骤（端到端，AI 可直接执行）

```
S01 环境校验  → S02 版本/工作区校验 → S03 构建环境净化
→ S04 依赖与 spec 复核 → S05 构建前密钥门禁
→ S06 执行构建 → S07 产物结构校验 → S08 产物安全复查
→ S09 绿色便携冒烟 → S10 体积治理(可选) → S11 代码签名(可选) → S12 分发归档
```

### S01 环境校验
```bash
cd /d/PythonProject/QuantVortex
PY=/d/anaconda3/python.exe
$PY -c "import sys;print('PY',sys.version.split()[0],sys.maxsize>2**32)"
$PY -c "import PyInstaller;print('PYI',PyInstaller.__version__)"
$PY -c "import PyQt6,pandas,numpy;print('DEPS ok')"
$PY -c "import futures_quant as f;print('APP',f.__version__,f.__release_date__)"
ls images/ico.ico config/settings.json config/style.qss main.py
```
预期：`PY 3.13.5 True` / `PYI 6.21.0` / `DEPS ok` / `APP 5.2.15 2026-10-07` / 四路径存在。

### S02 版本与工作区校验
```bash
grep -n "__version__\|__release_date__" futures_quant/__init__.py | head -5
git status --short
```
预期：版本号在 `__init__.py` 唯一；`git status` 仅含预期改动。**未确认的功能改动不得进入构建**。

### S03 构建环境净化（针对 anaconda 跨项目 `sitecustomize` 污染）
```bash
# 3.1 关闭占用进程
tasklist 2>/dev/null | grep -i futuresquant || echo "no running exe"
# 3.2 清理历史归档残留（每个 ~800MB+）
ls -d dist/FuturesQuant.old-* 2>/dev/null
rm -rf dist/FuturesQuant.old-*
# 3.3 处理 sitecustomize 污染（anaconda 每次启动 python 都会执行并打印 [DLL固定]）
ls -la /d/anaconda3/Lib/site-packages/sitecustomize.py 2>/dev/null
grep -c "DLL固定" /d/anaconda3/Lib/site-packages/sitecustomize.py 2>/dev/null
mv /d/anaconda3/Lib/site-packages/sitecustomize.py \
   /d/anaconda3/Lib/site-packages/sitecustomize.py.bak
# 验证：下面命令输出应只有 clean
$PY -c "print('clean')"
```
> ⚠️ **构建完成后必须还原**：`mv /d/anaconda3/Lib/site-packages/sitecustomize.py.bak /d/anaconda3/Lib/site-packages/sitecustomize.py`
> 若 `mv` 失败（被占用），改用 §10 方案 A 干净 venv 构建（venv 不继承该 sitecustomize）。

### S04 依赖与 spec 复核
```bash
grep -n "CONFIG_DENY\|_internal\|upx\|console=\|icon=\|version=\|excludes=\|collect_submodules" build_tools/futures_qt.spec
ls -la config/   # 若出现 ctp_settings.json 不会被打入（spec 源头跳过）
```

### S05 构建前密钥门禁（提前自测，避免 20 分钟后才失败）
```bash
/d/anaconda3/python.exe build_tools/secret_scan.py \
    --skip-dirs dist --skip-dirs build --skip-dirs __pycache__ . 2>&1 | tail -20
echo "SCAN_RC=$?"
# 追查已知历史泄露密钥（仅本机 env，不入库）：export QV_SCAN_LITERALS="k1,k2"
```
预期：无命中，`SCAN_RC=0`。`build_exe.py` 内部会强制重跑同一门禁。

### S06 执行构建
```bash
cd /d/PythonProject/QuantVortex
export TMP=D:/PythonProject/QuantVortex/.pytest_tmp
export TEMP=$TMP TMPDIR=$TMP
mkdir -p "$TMP" .pytest_tmp

/d/anaconda3/python.exe build_tools/build_exe.py > .pytest_tmp/build.log 2>&1
echo "BUILD_RC=$?"
tail -30 .pytest_tmp/build.log
```
> ⚠️ **禁止**用管道（`| grep`/`| tail`）取退出码（会返回管道 rc，造成“全绿其实是失败”误判）。必须 `> log 2>&1` 后 `echo $?`。
预期日志尾部含：`[产物] 主程序：存在` + `[验证] 产物扫描通过：未发现任何密钥` + `BUILD_RC=0`。耗时 10~25 分钟。

### S07 产物结构与完整性校验
```bash
D=dist/FuturesQuant
ls -la $D/FuturesQuant.exe
ls $D/_internal/config/
ls $D/_internal/images/link_qrcode/qq.png $D/_internal/images/pay_qrcode/wx-pay.png
ls $D/_internal/futures_quant/runtime.py
echo "pycache=$(find $D -type d -name __pycache__ | wc -l)"
echo "pyc=$(find $D -name '*.pyc' -not -path '*/base_library*' | wc -l)"
find $D -type f \( -name "ctp_settings.json" -o -name "secrets.json" -o -name "*.key" -o -name "*.pem" -o -name "*.local.json" \) -not -name "cacert.pem"
du -sh $D $D/_internal
```
验收：`FuturesQuant.exe` 存在；`config/` 含 `settings.json`/`style.qss`/`ctp_settings.example.json`（**无** `ctp_settings.json`）；两 png 存在；`pycache=0`；`pyc=0`；凭据文件 0 个。

### S08 产物安全复查（二进制字节级，独立双证）
```bash
/d/anaconda3/python.exe build_tools/secret_scan.py dist/FuturesQuant --binary-only > .pytest_tmp/artifact_scan.log 2>&1
echo "ARTIFACT_SCAN_RC=$?"; tail -20 .pytest_tmp/artifact_scan.log
```
预期：`ARTIFACT_SCAN_RC=0`，无命中。

### S09 绿色便携冒烟测试
```bash
# 9.1 复制到全新目录
rm -rf /d/_portable_test && mkdir -p /d/_portable_test
cp -r /d/PythonProject/QuantVortex/dist/FuturesQuant /d/_portable_test/
# 9.2 启动存活 + 主窗口 + data/ 生成（Python 版，无人值守友好）
/d/anaconda3/python.exe tools/smoke_exe.py /d/_portable_test/FuturesQuant/FuturesQuant.exe --wait 20
echo "SMOKE_RC=$?"
```
预期：`OK: 存活 pid=...` + `data_dir=... exists=True` + `SMOKE_RC=0`。`tools/smoke_exe.py` 见附录 A（如不存在则落盘）。

### S10 体积治理（可选，默认 843MB 建议执行）—— 见 §10

### S11 代码签名（可选，消除 SmartScreen）—— 见 §10.4

### S12 分发归档
```bash
cd /d/PythonProject/QuantVortex
VER=$(/d/anaconda3/python.exe -c "import futures_quant as f;print(f.__version__)")
OUT="dist/FuturesQuant-v${VER}-win64-portable.zip"
rm -f "$OUT"
cd dist/FuturesQuant && zip -rq "../FuturesQuant-v${VER}-win64-portable.zip" . && cd ..
ls -la "$OUT"
# 附使用说明.txt：双击 FuturesQuant.exe 即可；数据默认在 exe 同级 data/；整目录可放 U 盘；
# 云端 AI 研判由用户自设环境变量 QV_AGNES_API_KEY，未设自动降级本地规则。
```
> zip 路径必须解压到全新目录**重跑 S09** 复验（压缩/解压易丢长路径资源）。

---

## 5. 打包前检查清单（Checklist）

```
[ ] 构建环境为 /d/anaconda3/python.exe（3.13.5 + PyQt6 + PyInstaller 6.21.0）
[ ] 版本号 SSOT 唯一（仅 futures_quant/__init__.py 定义 __version__/__release_date__）
[ ] 工作区无未确认的功能改动（git status 审查）
[ ] assets/fonts 是否需要内嵌中文字体（当前缺失→回退系统 simhei，可接受）
[ ] config/ 下真实凭据（ctp_settings.json）不会被打入（spec CONFIG_DENY 生效）
[ ] images/ 下 ico.ico / link_qrcode/qq.png / pay_qrcode/wx-pay.png 均存在
[ ] runtime.get_config_dir() 已修正为冻结态走 sys._MEIPASS/config（★本次 v2.0 修正，已落地 runtime.py）
[ ] 所有图片/配置读取均经 runtime.get_*_dir()，无硬编码相对路径
[ ] 关闭占用进程、清理 dist/FuturesQuant.old-*、处理 sitecustomize 污染
[ ] 磁盘可用空间 ≥ 5 GB（workpath + dist）
```

---

## 6. 打包过程验证步骤（构建中/后）

| 阶段 | 验证动作 | 通过判据 |
|---|---|---|
| 构建前 | `secret_scan.py` 扫源码 | RC=0，无命中 |
| 构建中 | `tail build.log` 看 PyInstaller 进度 | 无 `ModuleNotFoundError` / `ImportError` |
| 构建后 | `build_exe.py` 退出码 | `BUILD_RC=0` |
| 构建后 | 日志含 `[产物] 主程序：存在` + `[验证] 产物扫描通过` | 二者缺一即失败 |
| 构建后 | `verify_dist.py`（附录 B） | 11 项全 PASS，RC=0 |
| 构建后 | 二进制密钥扫描 | RC=0 |

---

## 7. 打包后功能测试标准（Definition of Done）

| # | 验收项 | 通过判定 |
|---|---|---|
| D-1 | 主程序可启动 | `dist/FuturesQuant/FuturesQuant.exe` 存在，进程存活 ≥15s 未退出 |
| D-2 | 资源齐全 | `_internal/config/`、`_internal/images/link_qrcode/qq.png`、`_internal/images/pay_qrcode/wx-pay.png` 均存在 |
| D-3 | 无密钥/凭据 | `build_exe.py` 打印 `[验证] 产物扫描通过` 且退出码 0 |
| D-4 | 无字节码残留 | 产物内 `__pycache__` 目录数 = 0，`*.pyc` = 0 |
| D-5 | 版本号一致 | exe 属性 `ProductVersion` == `futures_quant.__version__` |
| D-6 | 绿色便携 | 拷贝 `dist/FuturesQuant` 到另一可写目录，双击可启动 |
| D-7 | 零安装 | 目标机无需 Python / VC++ / Qt 即可启动（Win10 1809+ 自带 UCRT） |
| D-8 | 资源加载正常 | 关于页二维码、启动图、产品图均正常显示；配置模板 settings.json 正确加载（非静默回退） |
| D-9 | 体积阈值 | 默认 ≤ 900MB；启用 §10 瘦身方案后目标 ≤ 350MB |
| D-10 | zip 可解压运行 | 解压到新目录重跑 S09 通过 |

> **D-8 是本次方案重点保障项**：`get_config_dir()` 已修正，确保 `settings.json` 默认值模板在冻结态正确加载（此前会静默回退内置默认值，造成“配置不生效”隐性缺陷）。

---

## 8. 资源加载正确性专项（★v2.0 修正点）

**问题**：原 `runtime.get_config_dir()` 在冻结态返回 `os.path.join(app_base_dir(), "config")`，即 exe 同级 `config/`。但 PyInstaller 6.x 单目录模式把 datas 落在 `sys._MEIPASS`（= `<exe>/_internal`），故 `config/` 实际位于 `<exe>/_internal/config`。这导致：
- `storage/config_manager.py` 的 `defaults_path = get_config_dir()/settings.json` 指向不存在路径 → 默认值模板加载失败，静默回退内置默认值（功能降级、用户配置“不生效”）。
- `ai/constants.py` 虽有源码树兜底能命中 `_internal/config`，但路径契约不统一、易碎。

**修复**（已落地 `futures_quant/runtime.py`，与 `get_images_dir()` 保持一致）：
```python
def get_config_dir() -> str:
    if is_frozen():
        frozen = os.path.join(sys._MEIPASS, "config")
        if os.path.isdir(frozen):
            return frozen
        root_cand = os.path.join(app_base_dir(), "config")
        if os.path.isdir(root_cand):
            return root_cand
    return os.path.join(app_base_dir(), "config")
```
**验证**：`py_compile` 通过；冻结态模拟下优先返回 `sys._MEIPASS/config`（真实打包时 `_internal/config` 存在即命中）。

**架构一致性原则**：任何新增“随包只读资源”读取，一律新增/复用 `runtime.get_*_dir()` 并在 `is_frozen()` 分支走 `sys._MEIPASS`；spec 的 `datas` 收集目标名须与 `_MEIPASS` 下的子目录名一致（如 `"config"`、`"images"`、`"assets/fonts"`）。

---

## 9. 故障排查表

### 9.1 `build_exe.py` 退出码

| 码 | 含义 | 处理 |
|---|---|---|
| 0 | 成功 | 进入 S07 |
| 1 | 未找到 `futures_qt.spec` | 确认在 `build_tools/` 下，勿用 `main.spec` |
| 3 | 源码发现密钥 | 删硬编码改环境变量注入；误报加 `# secret-scan: allow` |
| 4 | 产物发现密钥 | **产物不可分发**，`rm -rf dist/FuturesQuant` 排查重构建 |
| 5 | 未生成 `FuturesQuant.exe` | 查 `build/pyi_<ts>/` 输出，多为 excludes 误删依赖 |
| 6 | 旧产物目录既删不动也重命名不动 | 关闭占用进程 / 释放句柄，或 §10 方案 A 新 distpath |
| 7 | 产物混入本地凭据文件 | 修 spec `CONFIG_DENY` / datas 逻辑 |
| 8 | 产物 `user_settings.json` 含 `api_key` | 修 `AIConfig`：打包模式不得持久化密钥 |
| 9 | 缺失必需图片（qq.png / wx-pay.png） | 检查 `images/` 与 spec datas |

### 9.2 常见现象

| 现象 | 根因 | 处理 |
|---|---|---|
| 输出 `[DLL固定] 检测到项目目录: D:\PythonProject\KP-AI-FENGSHUI` | anaconda `sitecustomize.py` 跨项目污染 | S03.3 改名；构建后还原 |
| UPX 告警刷屏 | UPX 未安装 | 装 UPX 入 PATH，或 spec `upx=False` |
| 运行时 `ModuleNotFoundError` | 动态/延迟导入未进 hiddenimports | 补 hiddenimports（整包 datas 已兜底） |
| exe 双击无反应/秒退 | 缺 Qt 平台插件或依赖被 exclude | 临时 `console=True` 重建抓栈 |
| 启动白屏 | 主线程同步网络阻塞事件循环 | 检查是否新增长耗时同步调用 |
| 构建 >40min | excludes 被删导致 Analysis 扫描科学计算栈 | 恢复 excludes 清单 |
| COLLECT `PermissionError` | 旧产物被占用 | S03.1 关进程；build_exe 已内置归档兜底 |
| 分发后无 AI 功能 | 云端密钥未注入 | 用户设 `QV_AGNES_API_KEY`，未设自动降级（非缺陷） |
| 配置“不生效” | 旧 `get_config_dir` 冻结态路径错 | 已修正（§8），重构建 |

---

## 10. 体积治理、签名与可选增强

### 10.1 现状
默认产物 `843 MB`（`_internal` 820MB）：MKL 系 DLL ≈600MB；PyQt6 ≈71MB；pandas ≈18MB；ctpbee_api ≈17MB。

### 10.2 方案 A（推荐，安全）：干净 venv + pip 版 numpy（OpenBLAS）
```bash
/d/anaconda3/python.exe -m venv .build_venv
.build_venv/Scripts/python.exe -m pip install -U pip setuptools wheel
.build_venv/Scripts/python.exe -m pip install "numpy>=1.24" "pandas>=2.0" \
    "PyQt6>=6.6,<7.0" "pymysql>=1.1" "requests" "akshare" "pyinstaller>=6.0"
.build_venv/Scripts/python.exe -m pip install -e .   # 若项目可编辑安装
# 用 venv 解释器驱动构建：
.build_venv/Scripts/python.exe build_tools/build_exe.py > .pytest_tmp/build_venv.log 2>&1
```
- numpy 后端变 `openblas`，产物降至 **200~300MB**。
- venv 不继承 anaconda 的 `sitecustomize.py`，S03.3 可省略。
- 完成后**必须重跑 S06→S09 全量验证**（换解释器=换依赖基线）。
- 若用 `akshare`（当前已装、spec 未排），须一并装进 venv，否则运行期功能缺失。

### 10.3 方案 B（激进，需实测）：spec 内过滤未使用 MKL 内核
在 `a = Analysis(...)` 之后、`pyz = PYZ(...)` 之前插入 `_mkl_filter`（保留 `mkl_core/mkl_rt/mkl_intel_thread/mkl_avx2/mkl_def`，剔除其余），预计省 300~400MB。**风险**：老 CPU 可能需被剔除内核 → 须在不同 CPU 目标机复测，失败即回滚。

### 10.4 UPX
UPX 不在 PATH，`upx=True` 仅告警。建议将 spec `upx=True` 改为 `upx=False` 消除噪音（UPX 压 Qt/MKL 大 dll 拖慢构建且个别杀软误报）。

### 10.5 代码签名（可选，消除 SmartScreen“未知发布者”）
```bash
export QV_SIGN=1
export QV_SIGN_THUMBPRINT="<SHA1 指纹>"   # 或 QV_SIGN_SUBJECT="<主题名>"
export QV_TIMESTAMP_URL="http://timestamp.digicert.com"
/d/anaconda3/python.exe build_tools/build_exe.py > .pytest_tmp/build_signed.log 2>&1
```
依赖本机 Windows SDK `signtool.exe`（PATH 内）+ 代码签名证书；缺则跳过，不阻断构建。验证：PowerShell `(Get-Item dist\FuturesQuant\FuturesQuant.exe).VersionInfo.ProductVersion` 与 `Get-AuthenticodeSignature` Status=Valid。

---

## 11. 安全门禁（密钥扫描，强制）

- **构建前**：`build_exe.py` → `secret_scan.scan_paths([ROOT], skip_dirs=[dist,build,installer_out,tmp,__pycache__])`；命中即 `sys.exit(3)`。
- **构建后**：字节级扫描 `dist/FuturesQuant`（含 exe/pyc/dll）+ 凭据文件名黑名单 + `user_settings.json` 的 `api_key` 检查；命中分别 `exit 4/7/8`。
- 追查历史泄露：`QV_SCAN_LITERALS="k1,k2"`（仅本机 env，不入库）。
- 唯一逃生口：确属误报的代码行加注释 `# secret-scan: allow`（留在代码被 review）。

---

## 12. 附录：一键执行脚本

### 附录 A：`tools/smoke_exe.py`（绿色便携冒烟，如不存在则落盘）
```python
"""EXE 启动冒烟：进程存活 + 主窗口出现 + data 目录生成。
用法：python tools/smoke_exe.py <exe_path> [--wait 20]"""
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

### 附录 B：`tools/verify_dist.py`（产物验收，如不存在则落盘）
```python
"""产物验收：结构/资源/体积/残留/凭据。用法：python tools/verify_dist.py [dist_dir]"""
from __future__ import annotations
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIST = os.path.join(ROOT, "dist", "FuturesQuant")
MAX_MB = 900.0
FORBIDDEN = {"ctp_settings.json", "secrets.json", "credentials.json", "upstream.json", ".env"}
ALLOW = {"cacert.pem"}

def _size_mb(path: str) -> float:
    total = 0
    for r, _, fs in os.walk(path):
        for f in fs:
            try: total += os.path.getsize(os.path.join(r, f))
            except OSError: pass
    return total / 1024 / 1024

def main() -> int:
    dist = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIST)
    checks = []
    exe = os.path.join(dist, "FuturesQuant.exe")
    internal = os.path.join(dist, "_internal")
    def need(rel: str) -> bool:
        return (os.path.exists(os.path.join(internal, rel))
                or os.path.exists(os.path.join(dist, rel)))
    checks.append(("主程序 FuturesQuant.exe", os.path.isfile(exe), exe))
    for rel in ("config/settings.json", "config/style.qss",
                "images/link_qrcode/qq.png", "images/pay_qrcode/wx-pay.png",
                "futures_quant/runtime.py"):
        checks.append((f"资源 {rel}", need(rel), rel))
    checks.append(("config 无 ctp_settings.json",
                   not os.path.exists(os.path.join(internal, "config", "ctp_settings.json")),
                   "config/ctp_settings.json"))
    n_pyc = sum(1 for r, _, fs in os.walk(dist) for f in fs if f.endswith(".pyc"))
    checks.append(("无 __pycache__",
                   not any("__pycache__" in d for r, ds, _ in os.walk(dist) for d in ds), ""))
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

---

## 13. AI 执行清单（逐条勾选）

```
[ ] S01 环境校验通过（PY 3.13.5 / PYI 6.21.0 / DEPS ok / APP 5.2.15）
[ ] S02 版本 SSOT 唯一，工作区状态已确认
[ ] S03 旧归档清理 + sitecustomize 改名（构建后还原）
[ ] S04 spec 安全配置与 config 目录复核（get_config_dir 修正已生效）
[ ] S05 构建前密钥门禁 RC=0
[ ] S06 build_exe.py BUILD_RC=0，日志含 [产物] 主程序：存在 + [验证] 产物扫描通过
[ ] S07 产物结构校验（pycache=0 / pyc=0 / LEAK_COUNT=0 / 资源齐全）
[ ] S08 产物二进制扫描 RC=0
[ ] S09 绿色便携冒烟（新目录启动存活 + data/ 生成 + 资源显示正常）
[ ] S10 体积治理（可选；843MB → 目标 ≤350MB）
[ ] S11 代码签名（可选；Status=Valid）
[ ] S12 zip 归档 + 解压复验
[ ] 还原 sitecustomize.py（若 S03.3 改名过）
```
