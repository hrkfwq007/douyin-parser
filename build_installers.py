"""把 dist/ 下的软件目录做成「双击即装」的 Windows 安装包。

产物（release/）：
    抖音无水印解析器_v2.1_完整版_安装.exe   —— 含 Chromium 内核，可扫码登录获取 Cookie
    抖音无水印解析器_v2.1_精简版_安装.exe   —— 不含内核，需手动粘贴 Cookie
    激活码生成器_安装.exe                   —— 作者专用，可生成月/半年/年/终身卡密

安装行为：
    双击 → 询问是否安装 → 显示 7-Zip 进度条解压 → 搬到 %LOCALAPPDATA%\\<目录名>
         → 创建桌面快捷方式 → 弹出「安装完成，是否立即运行？」

用法：
    python build_installers.py            # 三个都做
    python build_installers.py full       # 只重建完整版
    python build_installers.py slim gen   # 只重建精简版和激活码生成器
    python build_installers.py --force    # 忽略压缩包缓存，重新压缩

==============================================================================
关于 SFX 模块：踩过的三个坑，改动前请先读
==============================================================================

1) Program Files 里自带的 7z.sfx **不是安装器**。
   实测扫二进制，它只认识 Delete/Progress/Directory 三个字段，
   完全不认识 ";!@Install@!"，所以给它的配置会被整段忽略，
   做出来的包退化成普通自解压，把 900MB 文件直接吐在你双击时的当前目录。
   必须用 7zSD.sfx（来自 LZMA SDK），它才实现了
   「解压到临时目录 → 执行指定脚本 → 删除临时目录」这条管线。

2) 7zSD.sfx **不支持 InstallPath / GUIMode**。
   网上流传的 InstallPath="%LOCALAPPDATA%\\X" 是另一个（旧版 Extra 包里的）
   模块才支持的写法。本脚本走它自己支持的方式：
   解压到临时目录后，用 _setup.bat 把内容搬到目标位置。

3) 7zSD.sfx 是 **32 位 PE**，嵌入清单时 processorArchitecture 必须写 "x86"。
   写成 "amd64" 的话系统认为清单不适用于该文件，直接忽略，
   asInvoker 失效 → 被 Windows 安装程序检测命中 → 双击弹 UAC，
   程序化启动报 [WinError 740] 请求的操作需要提升。

4) 嵌入清单只能对 stub 下手，**绝对不能对拼好的成品 exe 下手**。
   Windows 的资源更新 API 重建 PE 时会丢弃文件末尾的附加数据（overlay），
   而 7z 压缩数据恰恰在 PE 之后 —— 对成品 exe 更新资源会把几百 MB 数据清空
   （实测 61MB 被截成 216KB）。顺序必须是：先给 stub 嵌清单，再拼配置+压缩包。

5) 配置文件里字符串只写 \\n，靠 newline="\\r\\n" 统一转成 CRLF。
   若字符串自带 \\r\\n 再叠加转换会写出 \\r\\r\\n，7-Zip 解析失败，
   后果是整个配置被忽略。
"""

import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
from ctypes import wintypes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(BASE_DIR, "dist")
RELEASE = os.path.join(BASE_DIR, "release")
TMP = os.path.join(BASE_DIR, ".pkg_tmp")

SEVEN_ZIP = r"C:\Program Files\7-Zip\7z.exe"

# 7zSD.sfx 出自 LZMA SDK（https://www.7-zip.org/sdk.html），是唯一实现了
# 安装执行管线的模块。首次构建时若缺失会自动下载 SDK 取出来。
SFX_SRC = os.path.join(TMP, "sfx", "7zSD.sfx")
SDK_URL = "https://www.7-zip.org/a/lzma2604.7z"

VERSION = "v2.1"

# ---------------------------------------------------------------------------
# 安装脚本：由 7zSD 在解压完成后执行，负责「搬到目标位置 + 建快捷方式」
#
# 为什么不直接 move 整个临时文件夹：本脚本自己就在那个文件夹里，
# 正在运行的 bat 无法移动自己所在的目录，会失败。
# 所以改成逐个搬运子目录和根目录文件，并跳过自己。
#
# 为什么用 move 而不是 copy：临时目录（%TEMP%）和目标位置（%LOCALAPPDATA%）
# 默认都在 C 盘同一卷上，move 目录只是改个名字的元数据操作，
# 完整版 944MB 也是瞬间完成；落到不同卷时 move 自动退化为复制，仍然正确，只是慢些。
# ---------------------------------------------------------------------------
#
# 注意下面所有路径参数都刻意「不加结尾反斜杠」：
# 在 cmd 里写 "%DST%\" 时，反斜杠会把后面的双引号转义成普通字符，
# 参数会变成 C:\xxx" 这样的错误路径，move 直接失败。
SETUP_BAT = """@echo off
chcp 65001>nul 2>&1
setlocal
set "SRC=%~dp0"
set "DST=%LOCALAPPDATA%\\@@DIR@@"
title @@TITLE@@

echo 正在安装 @@TITLE@@，请稍候…

if exist "%DST%" rd /s /q "%DST%"
if not exist "%DST%" md "%DST%" 2>nul
if not exist "%DST%" (
  echo 无法创建目标目录，安装中止。
  pause
  exit /b 1
)

for /d %%D in ("%SRC%*") do move /y "%%~D" "%DST%" >nul 2>&1
for %%F in ("%SRC%*") do if /i not "%%~nxF"=="_setup.bat" move /y "%%~F" "%DST%" >nul 2>&1

rem 若旧目录被占用导致没搬干净，退化为复制，保证最终能用
if not exist "%DST%\\@@EXE@@" xcopy "%SRC%*" "%DST%" /E /C /H /R /K /Y >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "$ws=New-Object -ComObject WScript.Shell; $d=[IO.Path]::Combine($ws.SpecialFolders('Desktop'),'@@LNK@@.lnk'); $s=$ws.CreateShortcut($d); $s.TargetPath='%LOCALAPPDATA%\\@@DIR@@\\@@EXE@@'; $s.WorkingDirectory='%LOCALAPPDATA%\\@@DIR@@'; $s.Description='@@LNK@@'; $s.Save()" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms; $m='@@MSG@@'; $r=[System.Windows.Forms.MessageBox]::Show($m,'@@TITLE@@',4,64); if($r -eq 'Yes'){Start-Process '%LOCALAPPDATA%\\@@DIR@@\\@@EXE@@'}" >nul 2>&1

endlocal
exit /b 0
"""


# 32 位是硬要求，见文件头第 3 条
MANIFEST_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">\n'
    '  <assemblyIdentity type="win32" name="DouyinParser.Sfx" version="2.1.0.0" '
    'processorArchitecture="x86"/>\n'
    '  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">\n'
    '    <security>\n'
    '      <requestedPrivileges>\n'
    '        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>\n'
    '      </requestedPrivileges>\n'
    '    </security>\n'
    '  </trustInfo>\n'
    '</assembly>\n'
)


def log(msg: str):
    print(msg, flush=True)


def ensure_sfx() -> str:
    """确保 7zSD.sfx 存在，缺失则从 LZMA SDK 下载取出。"""
    if os.path.exists(SFX_SRC):
        return SFX_SRC
    os.makedirs(os.path.dirname(SFX_SRC), exist_ok=True)
    sdk = os.path.join(TMP, "lzma_sdk.7z")
    if not os.path.exists(sdk):
        log(f"[sdk] 正在下载 LZMA SDK …（{SDK_URL}）")
        urllib.request.urlretrieve(SDK_URL, sdk)
    log("[sdk] 正在取出 7zSD.sfx …")
    subprocess.run(
        [SEVEN_ZIP, "e", sdk, "-o" + os.path.dirname(SFX_SRC),
         "bin/7zSD.sfx", "-y", "-bso0", "-bsp0"],
        check=True)
    return SFX_SRC


def embed_asinvoker_manifest(path: str) -> None:
    """给 exe 嵌入 asInvoker 清单，跳过 Windows 的安装程序检测。"""
    k32 = ctypes.windll.kernel32
    k32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    k32.BeginUpdateResourceW.restype = wintypes.HANDLE
    k32.UpdateResourceW.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                    ctypes.c_void_p, wintypes.WORD,
                                    ctypes.c_char_p, wintypes.DWORD]
    k32.UpdateResourceW.restype = wintypes.BOOL
    k32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    k32.EndUpdateResourceW.restype = wintypes.BOOL

    data = MANIFEST_XML.encode("utf-8")
    handle = k32.BeginUpdateResourceW(path, False)
    if not handle:
        raise OSError(f"BeginUpdateResource 失败: {ctypes.get_last_error()}")
    ok = k32.UpdateResourceW(handle, ctypes.c_void_p(24), ctypes.c_void_p(1),
                             0, data, len(data))
    if not ok:
        k32.EndUpdateResourceW(handle, True)
        raise OSError(f"UpdateResource 失败: {ctypes.get_last_error()}")
    if not k32.EndUpdateResourceW(handle, False):
        raise OSError(f"EndUpdateResource 失败: {ctypes.get_last_error()}")


def prepare_sfx() -> str:
    """复制一份 7zSD.sfx 并嵌入 asInvoker 清单，返回其路径。"""
    dst = os.path.join(TMP, "7zSD_asinvoker.sfx")
    if not os.path.exists(dst):
        shutil.copyfile(ensure_sfx(), dst)
        before = os.path.getsize(dst)
        embed_asinvoker_manifest(dst)
        after = os.path.getsize(dst)
        # 体积不应缩小 —— 变了说明附加数据被丢了
        if after < before:
            raise RuntimeError("嵌入清单后体积缩小，附加数据可能被丢弃")
        log(f"[sfx] 已嵌入 asInvoker 清单（{before} -> {after} 字节）")
    return dst


def build_one(tag: str, src_dir: str, exe_name: str, out_name: str,
              title: str, size_hint: str, level: str, install_dir: str,
              lnk: str, finish_msg: str, force: bool = False):
    src = os.path.join(DIST, src_dir)
    if not os.path.isdir(src):
        log(f"[跳过] {src} 不存在，请先运行对应的 build 脚本")
        return False

    os.makedirs(TMP, exist_ok=True)
    os.makedirs(RELEASE, exist_ok=True)

    # 1) 把安装脚本放进待打包目录（文件名用 ASCII，避免压缩包内编码问题）
    bat_path = os.path.join(src, "_setup.bat")
    bat = (SETUP_BAT
           .replace("@@DIR@@", install_dir)
           .replace("@@EXE@@", exe_name)
           .replace("@@LNK@@", lnk)
           .replace("@@TITLE@@", title)
           .replace("@@MSG@@", finish_msg))
    with open(bat_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(bat)
    log(f"[{tag}] 已写入安装脚本（目标 %LOCALAPPDATA%\\{install_dir}）")

    # 2) 压缩目录内容（不带外层目录，避免解压出双层）
    #    压缩包缓存必须与安装脚本内容绑定：否则复用旧包时，
    #    包里装的是上一次的 _setup.bat，改了脚本却不生效，非常隐蔽。
    arc = os.path.join(TMP, f"{tag}.7z")
    sig = os.path.join(TMP, f"{tag}.batsig")
    cur_sig = hashlib.md5(bat.encode("utf-8")).hexdigest()
    cached_sig = ""
    if os.path.exists(sig):
        cached_sig = open(sig, encoding="utf-8").read().strip()
    if os.path.exists(arc) and not force and cached_sig == cur_sig:
        log(f"[{tag}] 复用已有压缩包（{os.path.getsize(arc) // 1024 // 1024}MB）")
    else:
        if os.path.exists(arc):
            os.remove(arc)
        cmd = [
            SEVEN_ZIP, "a", f"-mx={level}", "-r", "-bso0", "-bsp0",
            arc, ".\\*",
        ]
        log(f"[{tag}] 压缩中（级别 {level}，源约 {size_hint}）…")
        subprocess.run(cmd, cwd=src, check=True)
        with open(sig, "w", encoding="utf-8") as f:
            f.write(cur_sig)
        log(f"[{tag}] 压缩包 {os.path.getsize(arc) // 1024 // 1024}MB")

    # 3) 写 SFX 配置（行尾只写 \n，由 newline 统一转 CRLF，见文件头第 5 条）
    #    7zSD 只支持 Title/BeginPrompt/Progress/RunProgram/Directory/ExecuteFile/…
    #    InstallPath 和 GUIMode 它不认识，写了也无效。
    cfg_path = os.path.join(TMP, f"{tag}.cfg")
    cfg = (
        ";!@Install@!UTF-8!\n"
        f'Title="{title}"\n'
        f'BeginPrompt="即将安装 {title}。\\n'
        f'安装位置：%LOCALAPPDATA%\\\\{install_dir}\\n'
        f'解压体积约 {size_hint}。\\n\\n'
        f'是否继续？"\n'
        'Progress="yes"\n'
        'RunProgram="_setup.bat"\n'
        ";!@InstallEnd@!\n"
    )
    with open(cfg_path, "w", encoding="utf-8", newline="\r\n") as f:
        f.write(cfg)
    raw_cfg = open(cfg_path, "rb").read()
    if b"\r\r\n" in raw_cfg:
        raise RuntimeError(f"[{tag}] 配置出现 \\r\\r\\n，7-Zip 会忽略整个配置")

    # 4) 拼接：带清单的 stub + 配置 + 压缩包
    out = os.path.join(RELEASE, out_name)
    sfx = prepare_sfx()
    with open(out, "wb") as out_f:
        with open(sfx, "rb") as f:
            out_f.write(f.read())
        with open(cfg_path, "rb") as f:
            out_f.write(f.read())
        with open(arc, "rb") as f:
            shutil.copyfileobj(f, out_f)
    log(f"[{tag}] 完成 -> {out}（{os.path.getsize(out) // 1024 // 1024}MB）")

    # 5) 清理临时脚本，保持 dist 干净
    try:
        os.remove(bat_path)
    except OSError:
        pass
    return True


def main():
    args = sys.argv[1:]
    force = "--force" in args
    keep_arc = "--keep" in args
    args = [a for a in args if not a.startswith("--")]
    picks = set(args) if args else {"all"}

    jobs = []
    if picks & {"all", "gen"}:
        jobs.append((
            "gen", "LicenseGenerator", "LicenseGenerator.exe",
            "激活码生成器_安装.exe",
            "激活码生成器（作者专用）",
            "130MB", "9", "LicenseGenerator", "激活码生成器",
            "安装完成！桌面已创建快捷方式。是否立即运行？",
        ))
    if picks & {"all", "full"}:
        jobs.append((
            "full", "DouyinParser", "DouyinParser.exe",
            f"抖音无水印解析器_{VERSION}_完整版_安装.exe",
            f"抖音无水印解析器 {VERSION} 完整版",
            "944MB", "1", "DouyinParser", "抖音无水印解析器(完整版)",
            "安装完成！内置浏览器内核，可直接扫码获取 Cookie。是否立即运行？",
        ))
    if picks & {"all", "slim"}:
        jobs.append((
            "slim", "DouyinParserSlim", "DouyinParserSlim.exe",
            f"抖音无水印解析器_{VERSION}_精简版_安装.exe",
            f"抖音无水印解析器 {VERSION} 精简版",
            "223MB", "5", "DouyinParserSlim", "抖音无水印解析器(精简版)",
            "安装完成！首次使用需手动粘贴 Cookie。是否立即运行？",
        ))

    for job in jobs:
        build_one(*job, force=force)

    # 清理（--keep 时保留 .7z，下次可直接复用，省掉几分钟压缩）
    if keep_arc:
        for name in os.listdir(TMP):
            # .batsig 要留着，下次才能判断缓存是否与当前脚本匹配
            if not (name.endswith(".7z") or name.endswith(".batsig")):
                p = os.path.join(TMP, name)
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
        log("已保留压缩包缓存")
    else:
        shutil.rmtree(TMP, ignore_errors=True)
    log("全部完成，产物在 release/ 目录")


if __name__ == "__main__":
    main()
