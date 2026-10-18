"""把激活码生成器（license_gen_gui.py）打包成可执行目录。

产物：dist/LicenseGenerator/
      再经 build_installers.py 做成 release/激活码生成器_安装.exe

说明：
- 采用 onedir 而非 onefile：单文件版实测会在启动 70 秒后崩溃，
  退出码 -1073740791（0xC0000409，Windows 栈缓冲溢出终止）。
  改成目录模式后启动正常。代价是不能只发一个裸 exe，
  但我们会用 7z SFX 把它包成双击即装的安装包，用户侧体验一样。
- activation.py 走正常 import，PyInstaller 会编成字节码（PYZ），
  不会像 add-data 那样把私钥明文留在磁盘上。
- 本工具含激活私钥，仅供作者本人使用，切勿放进分发给买家的安装包。
"""

import os
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")

# 体积大头且本工具用不到的 Qt 模块
EXCLUDES = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtNetworkAuth",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine",
    "PySide6.QtTextToSpeech",
    "PySide6.QtUiTools",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "tkinter",
    "numpy",
    "pandas",
    "PIL",
]

cmd = [
    VENV_PYTHON,
    "-m",
    "PyInstaller",
    # 目录名用英文，避免后续 7z / Python 处理中文路径出编码问题
    "--name=LicenseGenerator",
    "--onedir",
    "--windowed",
    f"--icon={os.path.join(BASE_DIR, 'assets', 'logo.ico')}",
    "--noconfirm",
    "--clean",
    *[f"--exclude-module={m}" for m in EXCLUDES],
    os.path.join(BASE_DIR, "license_gen_gui.py"),
]

print("Running:\n", " ".join(cmd))
subprocess.run(cmd, check=True)

out = os.path.join(BASE_DIR, "dist", "LicenseGenerator")
print("Build finished:", out)
