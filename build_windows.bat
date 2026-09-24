@echo off
chcp 65001 >nul
setlocal
echo QQ关键词自动回复 - Windows EXE 构建
echo.
where py >nul 2>nul
if errorlevel 1 (
  echo 未找到 Python。请安装 Python 3.11+，并勾选 Add Python to PATH。
  pause
  exit /b 1
)
py -m pip install --upgrade pip
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo 依赖安装失败。
  pause
  exit /b 1
)
py -m PyInstaller --noconfirm --clean --onefile --windowed --name "QQ关键词自动回复" main.py
if errorlevel 1 (
  echo EXE 构建失败。
  pause
  exit /b 1
)
echo.
echo ============================================
echo 构建完成：
echo dist\QQ关键词自动回复.exe
echo ============================================
pause
