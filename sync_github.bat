@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/3] 检查变更...
git status -s
echo.
set /p MSG=请输入本次更新说明 (直接回车默认: chore: update monitor): 
if "%MSG%"=="" set MSG=chore: update monitor
echo [2/3] 提交变更...
git add .
git commit -m "%MSG%"
echo [3/3] 推送到 GitHub...
git push origin main
pause
