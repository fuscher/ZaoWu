@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title ZaoWu 一键构建

REM ============================================================
REM  ZaoWu 一键构建脚本（前端 → PyInstaller → 组装 → 发布产物 → 验证）
REM  用法:
REM    build.bat                         交互式输入目标目录
REM    build.bat D:\ZaoWu                直接指定目标目录
REM    build.bat -y D:\ZaoWu             跳过确认（覆盖已存在的目标）
REM
REM  目标目录内容 = 扁平部署目录（exe + _internal + settings.json），
REM  同时作为发布包 zip 的源（zip 仅含 exe 与 _internal 两路径）。
REM  发布产物：dist\ZaoWu-{v}-win64.zip + dist\version.json（sha256/体积实测写入）。
REM ============================================================

set "REPO_ROOT=%~dp0.."
set "VENV_PY=%REPO_ROOT%\.venv\Scripts\python.exe"
set "SPEC=%REPO_ROOT%\tobuild\ZaoWu.spec"
set "BUILD_OUT=%REPO_ROOT%\dist\ZaoWu"
set "AUTO_YES=0"

REM 兜底：切到仓库根，保证后续 from version import VERSION 与相对路径一致
REM （双击运行时 cwd 是 tobuild，读不到仓库根的 version.py）
cd /d "%REPO_ROOT%"

REM ---- 目标目录：命令行参数或交互输入 ----
if not "%~1"=="" (
    if "%~1"=="-y" (
        set "AUTO_YES=1"
        if "%~2"=="" goto :ask
        set "DEST=%~2"
    ) else (
        set "DEST=%~1"
    )
) else (
    :ask
    echo 请输入目标目录（将在此构建完整的 ZaoWu 应用，可留空使用默认 E:\ZaoWu）:
    set /p "DEST="
    if "!DEST!"=="" set "DEST=E:\ZaoWu"
)
set "DEST=%DEST:"=%"

echo.
echo 目标目录: %DEST%
echo 仓库根目录: %REPO_ROOT%
echo.

REM ---- 目标目录存在性检查（仅默认路径自动创建，自定义路径需已存在） ----
if not exist "%DEST%" (
    echo [警告] 目标目录不存在: %DEST%
    if /i "%DEST%"=="E:\ZaoWu" (
        echo 默认路径，将自动创建。
    ) else (
        echo 请先创建该目录后重试，或改用默认路径。
        goto :fail
    )
)

if exist "%DEST%\ZaoWu.exe" (
    echo [警告] 目标目录已存在构建产物（ZaoWu.exe）。
    if "%AUTO_YES%"=="1" goto :proceed
    set /p "ANS=是否清空并重新构建？[y/N] "
    if /i not "!ANS!"=="y" goto :abort
)

:proceed
echo.

REM ---- 1. 前端生产构建（Vue → 静态资源） ----
echo [1/5] 前端构建 ...
pushd "%REPO_ROOT%\ZaoWu"
call npm run build
if errorlevel 1 (
    echo [错误] 前端构建失败，请先检查 ZaoWu\ 下的类型错误。
    popd
    goto :fail
)
popd

REM ---- 2. PyInstaller 打包（后端 + 前端 → 目录应用） ----
echo [2/5] PyInstaller 打包（约 50 秒）...
REM 显式钉死输出目录（spec 未设 distpath，依赖 cwd 为仓库根；双击运行时 cwd 是 tobuild）
"%VENV_PY%" -m PyInstaller "%SPEC%" --noconfirm --clean --distpath "%REPO_ROOT%\dist" --workpath "%REPO_ROOT%\build"
if errorlevel 1 goto :fail

if not exist "%BUILD_OUT%\ZaoWu.exe" (
    echo [错误] 未找到构建产物: %BUILD_OUT%\ZaoWu.exe
    goto :fail
)

REM 剔除开发态状态文件（发布卫生：开发机运行时生成的用户状态不得随包分发；
REM 文件由应用运行期生成，开发态树随时可能重新出现）
if exist "%BUILD_OUT%\_internal\plugins\.plugin_state.json" del /q "%BUILD_OUT%\_internal\plugins\.plugin_state.json"
if exist "%BUILD_OUT%\_internal\agent_modules\skills\.skill_state.json" del /q "%BUILD_OUT%\_internal\agent_modules\skills\.skill_state.json"

REM ---- 3. 组装部署目录 ----
echo [3/5] 组装部署目录 ...
if exist "%DEST%" (
    echo   清空目标目录旧内容 ...
    robocopy "%DEST%" "%DEST%.old-%RANDOM%" /E /NJH /NJS >nul 2>&1
    rmdir /s /q "%DEST%" >nul 2>&1
)
mkdir "%DEST%" 2>nul

robocopy "%BUILD_OUT%" "%DEST%" /E /NJH /NJS /NFL /NDL
if errorlevel 8 goto :fail

REM 目标目录兜底剔除历史残留（防御旧版构建曾随包分发过状态文件）
if exist "%DEST%\_internal\plugins\.plugin_state.json" del /q "%DEST%\_internal\plugins\.plugin_state.json"
if exist "%DEST%\_internal\agent_modules\skills\.skill_state.json" del /q "%DEST%\_internal\agent_modules\skills\.skill_state.json"

REM 预置 settings.json（唯一必须预置的 marker；其余 json 后端首次启动自动生成）
if not exist "%DEST%\settings.json" (
    copy /y "%REPO_ROOT%\settings.json" "%DEST%\settings.json" >nul
)

REM ---- 4. 发布产物（zip + version.json：调 assemble_release.py 复用排除+自检）----
echo [4/5] 生成发布产物 ...
REM 版本号单一来源：读 version.py（编译期常量）；exe 路径无空格不可加引号
REM （for /f 命令串与嵌套引号不兼容）
for /f "delims=" %%v in ('%VENV_PY% -c "from version import VERSION;print(VERSION)"') do set "APP_VER=%%v"
REM 打 zip（排除 __pycache__/状态文件）+ 自检（状态文件/缓存/未知插件目录）+ 生成 version.json，一步完成
"%VENV_PY%" "%REPO_ROOT%\tobuild\assemble_release.py" package --src "%DEST%" --out "%REPO_ROOT%\dist" --version "%APP_VER%"
if errorlevel 1 goto :fail
echo [完成] %REPO_ROOT%\dist\ZaoWu-%APP_VER%-win64.zip

REM ---- 5. 运行验证（启动 → 健康检查 → 关闭） ----
echo [5/5] 启动验证 ...
start "" "%DEST%\ZaoWu.exe"

set "OK=0"
for /l %%i in (1,1,20) do (
    timeout /t 1 /nobreak >nul
    curl -s -m 2 -o nul "http://127.0.0.1:5000/api/health" && set "OK=1" && goto :checked
)
:checked
if "%OK%"=="1" (
    echo [通过] 后端健康检查 OK（http://127.0.0.1:5000/api/health）
) else (
    echo [警告] 30 秒内未检测到服务健康。请手动检查：
    echo         %DEST%\ZaoWu.exe
    echo         端口 5000 被占用时，设环境变量 ZAOWU_PORT 后重试。
)

REM 等待自动生成的 settings.json（后端首次启动时创建）
for /l %%i in (1,1,10) do (
    if exist "%DEST%\settings.json" goto :files_ok
    timeout /t 1 /nobreak >nul
)
:files_ok
echo [提示] 首次启动已自动生成: settings.json / chat_config.json / chat_presets.json / providers.json / data\ / logs\

REM 关闭验证实例（若进程未启动则忽略）
taskkill /f /im ZaoWu.exe >nul 2>&1

echo.
echo ============================================================
echo  构建完成: %DEST%
echo  分发: 将整个目录复制到目标 Windows 主机，双击 ZaoWu.exe
echo ============================================================
echo.
exit /b 0

:fail
echo.
echo [失败] 构建中止，请检查上方错误信息。
exit /b 1

:abort
echo.
echo 已取消，未做任何更改。
exit /b 1
