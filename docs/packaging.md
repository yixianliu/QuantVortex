# 打包为桌面 exe（PyInstaller）

本项目是 PyQt6 桌面程序，依赖仅为 `PyQt6 + numpy + pandas`（KP预测用原生 numpy 实现，K 线用 QPainter 绘制，无 torch/matplotlib/pyqtgraph）。可一键打包成免配置、双击即用的 exe，分发时**无需目标机安装 Python**。

## 1. 安装构建依赖

```bash
pip install pyinstaller      # 仅构建期需要，与运行时 requirements.txt 分离
```

## 2. 构建

```bash
python build_exe.py
```

`build_exe.py` 会调用 `futures_qt.spec`，将 `main.py` + `futures_quant` 包 + `config/` 目录打包成单目录产物 `dist/FuturesQuant/`，并打印启动器路径与首次运行说明。

等价于原始命令：

```bash
pyinstaller futures_qt.spec --clean --noconfirm
```

## 3. spec 关键点

- `console=False`：桌面程序，不弹黑色控制台窗口。
- `datas`：把 `config/`（含 `settings.json` 模板）打入；若仓库存在 `assets/fonts/` 也会一并打入（见第 5 节字体）。
- `hiddenimports`：`collect_submodules("futures_quant")` 收集整个包，确保动态/延迟导入的指标、存储、数据源、KP预测等都被包含；并显式列出 `PyQt6` 子模块。
- `excludes`：排除 `matplotlib`/`tkinter`/`PyQt5`/`PySide*`/`scipy`/`sklearn`/`torch`/`tensorflow` 等无关或重型库，显著减小体积。
- `upx=True`：可执行文件压缩（如遇杀软误报可在 spec 中关闭）。

## 4. 运行时数据落盘位置（重要）

打包后用户可能从任意目录（甚至只读的 `C:\Program Files`）双击启动，因此**所有运行时数据都不再依赖当前工作目录**，而是统一由 `futures_quant/runtime.py` 解析：

- `app_base_dir()`：开发期=项目根；打包后=exe 所在目录（而非 CWD）。
- `get_data_dir()`：优先 `<exe 目录>/data/`（数据库 `quant_analysis.db`、用户配置 `user_settings.json`、会话 `session_state.json`、sina 缓存 `sina_cache/`）。若该目录不可写（如安装到 Program Files），自动回退到 `%APPDATA%/FuturesQuant/data`。
- `normalize_data_path()`：旧配置里若写了相对路径 `data/xxx.db`，会自动归一到上述可写 `data/` 目录，杜绝 CWD 依赖导致的「启动即报错/写不进」。

> 分发建议：把 `dist/FuturesQuant/` 整体拷贝到用户**有写权限的目录**（如 `D:\Tools\FuturesQuant\` 或用户文档目录），首次启动会自创 `data/`。若坚持装到 Program Files，程序会自动使用 AppData，不影响功能。

## 5. 中文字体策略

主程序启动时通过 `runtime.get_font_paths()` 注册字体，按优先级：

1. 内嵌字体：打包后的资源目录或 `<exe 目录>/assets/fonts/`（若有）；
2. 系统字体：`C:/Windows/Fonts/simhei.ttf`（Windows 普遍自带）、NotoSansSC、msyh。

按「注册成功的字体家族」设置应用字体；若全部缺失则退回 Qt 系统默认（带 CJK 回退），避免显示 tofu。

**完全自包含（可选）**：把任一 OFL 许可的中文字体（如 `NotoSansSC-Regular.otf`）放入 `assets/fonts/`，重新构建即随包打入，目标机无需任何系统中文字体。

## 6. 单文件模式（可选）

若想要单个 exe（而非目录），把 spec 中 `COLLECT(...)` 改为 `EXE(..., a.binaries, a.datas, ...)` 并加 `onefile`，或命令行加 `--onefile`：

```bash
pyinstaller futures_qt.spec --onefile
```

> 单文件模式每次启动会解压到临时目录，启动略慢；常规分发推荐默认的单目录模式。

## 7. 分发

把 `dist/FuturesQuant/` 整个目录拷贝到目标机器即可运行，无需安装 Python。如接入实盘 CTP，还需目标机具备对应期货公司前置地址与授权（见 `docs/ctp_wiring.md`）。

## 8. 注意事项

- 打包机需与目标机架构一致（Windows → Windows exe）。
- 若启用 `ctpbee`/`vnpy` 实盘网关：需在 spec 的 `hiddenimports` 补 `ctpbee` 相关模块，并确保目标机装有对应 CTP 动态库（`.dll`/`.so`）；当前 `ctp_gateway.py` 顶层不硬依赖它们，默认不会拖入。
- 本环境已实际执行 PyInstaller 6.x 构建验证（见 `dist/FuturesQuant/`），导入冒烟测试 `--test` 通过；GUI 因无显示环境未能在此处实机点击验证，请在目标机首次运行时确认窗口与中文显示正常。

## 9. 安装向导（InnoSetup）

若需要桌面快捷方式 / 程序组 / 卸载入口，用 InnoSetup 把绿色目录封装为安装包：

1. 先 `python build_exe.py` 得到 `dist/FuturesQuant/`；
2. 本机安装 InnoSetup（确保 `iscc` 在 PATH）；
3. 编译并产出安装包：
   ```bash
   iscc packaging/installer.iss
   # 或双击 packaging/build_installer.bat（含前置检查）
   ```
4. 产物：`installer_out/FuturesQuant_Setup_<版本>.exe`。

脚本要点（`packaging/installer.iss`）：
- 打包整个 `dist/FuturesQuant/`；安装到 `Program Files`（非管理员也可装到用户目录）；
- 可选桌面快捷方式 + 程序组 + 卸载；首次运行由程序自动初始化数据目录；
- 卸载默认保留用户 `data/`（可在 `installer.iss` 取消 `UninstallDelete` 注释改为清空）。

完整分发步骤与 CTP 接入说明见 `packaging/分发说明.md`。

## 10. 代码签名（消除 SmartScreen）

未签名 exe 在 Windows 上会被 SmartScreen 标记为「未知发布者」。`build_exe.py` 已内置可选签名阶段：

1. 获取代码签名证书（普通 OV 证书 / EV 证书，EV 自带 SmartScreen 信誉）；
2. 安装 Windows SDK（含 `signtool.exe`）并加入 PATH；
3. 设置环境变量后重新构建，自动对主 exe 及全部 `.dll/.pyd` 签名并带时间戳：
   ```bash
   set QV_SIGN=1
   set QV_SIGN_THUMBPRINT=<证书 SHA1 指纹>   # 或 set QV_SIGN_SUBJECT=<主题名>
   set QV_TIMESTAMP_URL=http://timestamp.digicert.com
   python build_exe.py
   ```
4. `signtool` 或证书缺失时自动跳过并提示，**不阻断构建**。

