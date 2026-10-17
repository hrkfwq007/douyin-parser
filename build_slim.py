"""瘦身版打包脚本（不内置 Chromium 浏览器内核）。

与 build.py 的区别：
    - 不打包 playwright-browsers（完整版里它占约 719MB），产物约 230MB
    - 输出目录 dist/DouyinParserSlim，与完整版 dist/DouyinParser 并存，互不影响
    - 功能完全一致，唯一差异：无法「扫码登录」自动获取 Cookie，
      改为手动填写（软件内已给出图文步骤引导）

注意：license_gen.py（激活码生成器）同样不打包。
"""

import os
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")

add_data = []
# 同 build.py：activation.py 含激活私钥，绝不能作为数据文件明文打进包里，
# 只走正常 import（PyInstaller 会编进 PYZ 字节码）。license_gen.py 也不打包。
for f in ["abogus.py", "xbogus.py", "douyin_video_parser.py"]:
    add_data.append(f"--add-data={os.path.join(BASE_DIR, f)};.")

# Logo/icon
add_data.append(f"--add-data={os.path.join(BASE_DIR, 'assets', 'logo.ico')};assets")
for size in [32, 48, 128, 256, 512, 1024]:
    p = os.path.join(BASE_DIR, "assets", f"logo-{size}.png")
    if os.path.exists(p):
        add_data.append(f"--add-data={p};assets")

# 关键：这里刻意不添加 --add-data=.../ms-playwright/*，省掉 719MB

cmd = [
    VENV_PYTHON,
    "-m",
    "PyInstaller",
    "--name=DouyinParserSlim",
    "--windowed",
    "--onedir",
    f"--icon={os.path.join(BASE_DIR, 'assets', 'logo.ico')}",
    "--noconfirm",
    "--clean",
    "--distpath",
    os.path.join(BASE_DIR, "dist"),
    *add_data,
    os.path.join(BASE_DIR, "qt_app.py"),
]

print("Running:\n", " ".join(cmd))
subprocess.run(cmd, check=True)

exe_dir = os.path.join(BASE_DIR, "dist", "DouyinParserSlim")
for placeholder in ["config.json", "douyin_cookie.txt"]:
    dst = os.path.join(exe_dir, placeholder)
    if not os.path.exists(dst):
        with open(dst, "w", encoding="utf-8") as f:
            if placeholder == "config.json":
                f.write('{"cookie": "", "save_dir": "downloads"}\n')
            else:
                f.write("")

print("Slim build finished:", exe_dir)
