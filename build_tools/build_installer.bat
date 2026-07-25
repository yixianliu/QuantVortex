@echo off
REM ============================================================================
REM 构建 FuturesQuant 安装包（InnoSetup）
REM 前置：1) 已运行 python build_exe.py 生成 dist\FuturesQuant\
REM       2) 本机安装 InnoSetup，且 iscc 已加入 PATH
REM ============================================================================
setlocal
cd /d %~dp0

if not exist "..\dist\FuturesQuant\FuturesQuant.exe" (
    echo [错误] 未找到 dist\FuturesQuant\FuturesQuant.exe
    echo         请先在本项目根目录运行：python build_exe.py
    pause
    exit /b 1
)

where iscc >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 iscc（InnoSetup 编译器）。
    echo         请安装 InnoSetup 并将其加入系统 PATH，再运行本脚本。
    pause
    exit /b 1
)

echo [构建] 编译安装脚本 installer.iss ...
iscc installer.iss
if errorlevel 1 (
    echo [失败] iscc 返回错误，请检查 installer.iss。
    pause
    exit /b 1
)

echo [完成] 安装包位于 ..\installer_out\
echo         将该 FuturesQuant_Setup_*.exe 发给用户即可一键安装。
endlocal
pause
