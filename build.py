import os
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PYTHON = os.path.join(BASE_DIR, "venv", "Scripts", "python.exe")

# Detect playwright browser dirs
MS_PLAYWRIGHT = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
BROWSER_NAMES = []
if os.path.isdir(MS_PLAYWRIGHT):
    for name in os.listdir(MS_PLAYWRIGHT):
        if name.startswith(("chromium", "ffmpeg", "winldd")):
            BROWSER_NAMES.append(name)

if not BROWSER_NAMES:
    print("ERROR: No Playwright browsers found under", MS_PLAYWRIGHT)
    print("Please run: python -m playwright install chromium")
    sys.exit(1)

print("Browsers to bundle:", BROWSER_NAMES)

add_data = []
# Core source files
# 注意 1：license_gen.py（激活码生成器）刻意不打包——那是作者本地专用工具。
# 注意 2：activation.py **不能**放进 add-data！它里面有激活私钥，
#         作为数据文件会原样明文出现在 _internal 里，任何人拿到 exe 都能提取
#         并自己生成激活码。让它走正常 import，PyInstaller 只会打进编译后的
#         字节码（PYZ），不再是明文源码。
for f in ["abogus.py", "xbogus.py", "douyin_video_parser.py"]:
    add_data.append(f"--add-data={os.path.join(BASE_DIR, f)};.")

# Logo/icon
add_data.append(f"--add-data={os.path.join(BASE_DIR, 'assets', 'logo.ico')};assets")
for size in [32, 48, 128, 256, 512, 1024]:
    p = os.path.join(BASE_DIR, "assets", f"logo-{size}.png")
    if os.path.exists(p):
        add_data.append(f"--add-data={p};assets")

# Playwright browsers
for name in BROWSER_NAMES:
    src = os.path.join(MS_PLAYWRIGHT, name)
    add_data.append(f"--add-data={src};playwright-browsers/{name}")

cmd = [
    VENV_PYTHON,
    "-m",
    "PyInstaller",
    "--name=DouyinParser",
    "--windowed",
    "--onedir",
    f"--icon={os.path.join(BASE_DIR, 'assets', 'logo.ico')}",
    "--noconfirm",
    "--clean",
    *add_data,
    os.path.join(BASE_DIR, "qt_app.py"),
]

print("Running:\n", " ".join(cmd))
subprocess.run(cmd, check=True)

# Post-build: copy optional empty config / cookie placeholders next to exe
exe_dir = os.path.join(BASE_DIR, "dist", "DouyinParser")
for placeholder in ["config.json", "douyin_cookie.txt"]:
    dst = os.path.join(exe_dir, placeholder)
    if not os.path.exists(dst):
        with open(dst, "w", encoding="utf-8") as f:
            if placeholder == "config.json":
                f.write('{"cookie": "", "save_dir": "downloads"}\n')
            else:
                f.write("")

print("Build finished:", exe_dir)
