@echo off
chcp 65001>nul 2>&1
set "TARGET=%~dp0LicenseGenerator.exe"
if not exist "%TARGET%" exit /b 0
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command ^
  "$ws=New-Object -ComObject WScript.Shell;" ^
  "$d=[IO.Path]::Combine($ws.SpecialFolders('Desktop'),'激活码生成器.lnk');" ^
  "$s=$ws.CreateShortcut($d);" ^
  "$s.TargetPath='%~dp0LicenseGenerator.exe';" ^
  "$s.WorkingDirectory='%~dp0';" ^
  "$s.Description='激活码生成器';" ^
  "$s.Save()"
exit /b 0
