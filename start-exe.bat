@echo off
chcp 65001 >nul
cd /d "%~dp0dist\DouyinParser"
start "" "DouyinParser.exe"
