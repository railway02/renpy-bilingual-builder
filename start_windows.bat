@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
pushd "%~dp0"
if errorlevel 1 goto directory_error
if not exist "app\gui.py" goto incomplete_project
if not exist "requirements.txt" goto incomplete_project
set "RBB_VENV=.venv\Scripts\python.exe"
set "RBB_REBUILD=0"
if exist ".venv\pyvenv.cfg" goto check_existing
if exist ".venv" goto invalid_venv
goto find_python

:check_existing
"%RBB_VENV%" -c "import sys; sys.exit(sys.version_info < (3, 10) or sys.prefix == sys.base_prefix)" >nul 2>&1
if not errorlevel 1 goto venv_ready
set "RBB_REBUILD=1"

:find_python
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto find_python_command
set "RBB_PYTHON=py -3"
goto python_ready

:find_python_command
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto missing_python
set "RBB_PYTHON=python"

:python_ready
if "%RBB_REBUILD%"=="1" goto backup_venv
goto create_venv

:backup_venv
set "RBB_BACKUP=.venv.backup-%RANDOM%-%RANDOM%"
if exist "%RBB_BACKUP%" goto backup_venv
move ".venv" "%RBB_BACKUP%" >nul
if errorlevel 1 goto backup_error
echo 旧虚拟环境已失效，已保存在 %RBB_BACKUP%。

:create_venv
echo 正在创建项目虚拟环境 .venv ...
%RBB_PYTHON% -m venv ".venv"
if errorlevel 1 goto venv_error

:venv_ready
"%RBB_VENV%" -m pip --version >nul 2>&1
if not errorlevel 1 goto check_tk
"%RBB_VENV%" -m ensurepip --upgrade
if errorlevel 1 goto pip_error

:check_tk
"%RBB_VENV%" -c "import tkinter"
if errorlevel 1 goto tk_error
echo 正在检查并安装界面依赖；首次运行需要联网。
"%RBB_VENV%" -m pip install --disable-pip-version-check -r "requirements.txt"
if errorlevel 1 goto pip_error
echo 正在启动 Ren'Py Bilingual Builder ...
"%RBB_VENV%" "app\gui.py"
if errorlevel 1 goto gui_error
popd
exit /b 0

:missing_python
echo [错误] 未找到 Python 3.10 或更高版本。
echo 请从 https://www.python.org/downloads/windows/ 安装 Python。
echo 安装时保留 Tcl/Tk 组件，并启用 Python 命令或 Python Launcher。
echo 安装完成后，重新双击 start_windows.bat。
goto failed

:incomplete_project
echo [错误] 项目文件不完整。请解压完整源码，再双击 start_windows.bat。
goto failed

:invalid_venv
echo [错误] .venv 已存在，但不是虚拟环境。请先将这个目录移到别处再重试。
goto failed

:backup_error
echo [错误] 无法备份旧虚拟环境。请关闭相关 Python 程序并检查目录写入权限。
goto failed

:venv_error
echo [错误] 创建虚拟环境失败。请检查上方错误，并确认 Python 安装完整。
goto failed

:tk_error
echo [错误] 当前 Python 缺少 Tk 图形组件。请通过 Python 安装程序补装 Tcl/Tk。
goto failed

:pip_error
echo [错误] 依赖安装失败。请检查上方网络或安装错误，修复后重新运行。
goto failed

:gui_error
echo [错误] 界面启动或运行失败。请复制上方错误信息，按问题模板反馈。
goto failed

:directory_error
echo [错误] 无法打开项目目录。请将完整源码解压到可访问的文件夹。
pause
exit /b 1

:failed
echo.
echo 窗口会保留错误信息，按任意键关闭。
pause >nul
popd
exit /b 1
