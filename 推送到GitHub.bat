@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   推送 douyin-parser 到 GitHub
echo   目标: https://github.com/hrkfwq007/douyin-parser
echo ============================================
echo.

git --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Git，请先安装: https://git-scm.com/
    pause
    exit /b 1
)

git remote set-url origin https://github.com/hrkfwq007/douyin-parser.git 2>nul
if errorlevel 1 git remote add origin https://github.com/hrkfwq007/douyin-parser.git

echo [1/2] 检查待推送内容...
git status --short
echo.

echo [2/2] 正在推送...
echo （若弹出登录窗口，请用 GitHub 账号 hrkfwq007 登录授权）
echo.

git push -u origin main

if errorlevel 1 (
    echo.
    echo [推送失败] 常见原因：
    echo   1. 未登录 —— 请在弹出的窗口中完成 GitHub 授权后重试
    echo   2. 仓库地址不对 —— 确认 https://github.com/hrkfwq007/douyin-parser 存在
    echo   3. 网络问题 —— 可挂代理后重试
) else (
    echo.
    echo [完成] 已推送到 https://github.com/hrkfwq007/douyin-parser
)

echo.
pause
