@echo off
setlocal
REM 构建薄启动器（一次性产物，协议稳定后不随版本发布）。
REM 产物：tobuild\out\ZaoWuLauncher.exe（约 2MB，无控制台窗口）。
cd /d "%~dp0"
set "OUT=%~dp0..\tobuild\out"
if not exist "%OUT%" mkdir "%OUT%"
go build -trimpath -ldflags "-s -w -H windowsgui" -o "%OUT%\ZaoWuLauncher.exe" .
if errorlevel 1 (
    echo [失败] 启动器构建失败（请确认已安装 Go 工具链）
    exit /b 1
)
echo [完成] %OUT%\ZaoWuLauncher.exe
