; ============================================================================
; FuturesQuant 期货智能分析预测系统 · 安装脚本（InnoSetup）
; ----------------------------------------------------------------------------
; 用法（本机需先安装 InnoSetup，且 iscc 在 PATH）：
;   1) 先构建 EXE：python build_exe.py   （产物 dist\FuturesQuant\）
;   2) 编译安装包：iscc packaging\installer.iss
;      或双击运行 packaging\build_installer.bat
; 安装包输出：installer_out\FuturesQuant_Setup_<版本>.exe
;
; 说明：
;   - 打包的是整个 dist\FuturesQuant\ 目录（exe + 依赖 + config\）；
;   - 桌面快捷方式 + 程序组；首次运行由程序自动创建 data\（若装在
;     Program Files 等只读目录，自动回退到 %APPDATA%\FuturesQuant\data）；
;   - 如需完全自包含中文字体，把 OFL 字体放进 assets\fonts\ 后再 build_exe.py。
; ============================================================================

#define MyAppName "FuturesQuant 期货智能分析预测系统"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "QuantVortex"
#define MyAppURL "https://example.com"
#define MyAppExeName "FuturesQuant.exe"

[Setup]
; 唯一 AppId，升级时用于识别
AppId={{F8A1C4B2-9E3F-4D5A-8B2C-000000000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
; 安装到 Program Files 时需提权；设为 lowest 让非管理员也能装到用户目录
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
OutputDir=..\installer_out
OutputBaseFilename=FuturesQuant_Setup_{#MyAppVersion}
SetupIconFile=
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
; 卸载时清理（data\ 含用户数据库，默认保留；如需一并删除可加 UninstallDelete）
UninstallDisplayName={#MyAppName}

[Languages]
; 中文向导（若本机 InnoSetup 无 ChineseSimplified.isl，改为 "compiler:Default.isl"）
Name: "chinese"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: unchecked

[Files]
; 整个已构建目录打进安装包
Source: "..\dist\FuturesQuant\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 默认保留用户数据（data\）。如需卸载时彻底清空，取消下一行注释：
; Type: filesandordirs; Name: "{app}\data"
