"""发新版：把 release/ 里的安装包搬到站点目录并更新版本清单。

为什么要有这个脚本
------------------
自动更新能不能生效，全看 store/version.json 里的 version 和客户端 updater.APP_VERSION
对不对得上。以前发版要手工改好几处，漏一处就是「明明发了新版，买家点了检查更新
却说已是最新」，而且这类问题在本地怎么点都测不出来。

现在合成一条命令，顺带把 sha256 算准（手抄 64 位十六进制迟早抄错）：

    python bump_version.py slim 2.2 --notes "修了图集下载顺序"

它会做三件事：
    1. 在 release/ 里找到对应安装包
    2. 复制到 store/static/download/（文件名固定，不带版本号）
    3. 把 version / size / sha256 / notes 写进 store/version.json

然后你还要做两件它没法代劳的事：
    bash store/deploy.sh     # 对账，别把线上订单盖掉
    重新部署站点              # 站点不更新，买家永远看不到新版

常用参数
--------
    --notes "说明"     更新说明，会显示在客户端的更新弹窗里
    --force            强制更新，客户端不提供「以后再说」
    --disable          关掉这个 variant 的自动更新
    --no-copy          只改版本清单，不复制文件（文件已经手动放好时用）
"""

import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
RELEASE = os.path.join(BASE, "release")
SITE_DL = os.path.join(BASE, "store", "static", "download")
VERSION_FILE = os.path.join(BASE, "store", "version.json")

# variant -> (release 里的文件名特征, 站点固定文件名)
VARIANTS = {
    "slim": ("*精简版_安装.exe", "DouyinParser_Slim_Setup.exe"),
    "full": ("*完整版_安装.exe", "DouyinParser_Full_Setup.exe"),
}


def log(msg):
    print(msg, flush=True)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_release_file(variant):
    pattern, _ = VARIANTS[variant]
    hits = [p for p in glob.glob(os.path.join(RELEASE, pattern))
            if os.path.isfile(p)]
    if not hits:
        return ""
    # 多个就取最新的，避免翻旧账
    return max(hits, key=os.path.getmtime)


def main():
    ap = argparse.ArgumentParser(description="发布新版本并更新自动更新清单")
    ap.add_argument("variant", choices=sorted(VARIANTS), help="slim / full")
    ap.add_argument("version", help="新版本号，例如 2.2")
    ap.add_argument("--notes", default="", help="更新说明")
    ap.add_argument("--force", action="store_true", help="强制更新")
    ap.add_argument("--disable", action="store_true", help="关闭该版本自动更新")
    ap.add_argument("--no-copy", action="store_true", help="只改清单，不复制安装包")
    args = ap.parse_args()

    ver = args.version.strip().lstrip("vV")
    if not re.match(r"^\d+(\.\d+)*$", ver):
        log(f"[x] 版本号格式不对：{args.version}（应形如 2.2 或 2.2.1）")
        return 1

    _, site_name = VARIANTS[args.variant]
    site_path = os.path.join(SITE_DL, site_name)

    if not args.no_copy:
        src = find_release_file(args.variant)
        if not src:
            log(f"[x] release/ 里找不到 {VARIANTS[args.variant][0]}，先跑打包脚本")
            return 1
        os.makedirs(SITE_DL, exist_ok=True)
        shutil.copyfile(src, site_path)
        log(f"[1/3] 已复制 {os.path.basename(src)}\n      -> static/download/{site_name}")
    else:
        log(f"[1/3] 跳过复制，直接用 static/download/{site_name}")

    if not os.path.isfile(site_path):
        log(f"[x] 站点目录里没有 {site_name}")
        return 1

    size = os.path.getsize(site_path)
    log(f"[2/3] 计算 sha256（{size / 1024 / 1024:.1f} MB，稍等）…")
    digest = sha256_of(site_path)

    try:
        with open(VERSION_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        log(f"[x] 读 store/version.json 失败：{e}")
        return 1

    item = data.setdefault(args.variant, {})
    item.update({
        "version": ver,
        "url": "",
        "size": size,
        "sha256": digest,
        "notes": args.notes or item.get("notes") or "",
        "force": bool(args.force),
        "enabled": not args.disable,
    })
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    log(f"[3/3] version.json 已更新：{args.variant} -> v{ver}"
        + ("（已关闭自动更新）" if args.disable else ""))
    log(f"      size   {size}")
    log(f"      sha256 {digest}")

    if args.disable:
        return 0

    # 提醒同步改客户端常量，否则发了对不上
    try:
        sys.path.insert(0, BASE)
        import updater
        if updater.APP_VERSION != ver:
            log("")
            log(f"[!] updater.APP_VERSION 还是 {updater.APP_VERSION}，"
                f"和这次发布的 v{ver} 不一致。")
            log("    客户端是用它跟服务器比对的，不改的话买家那边永远显示「已是最新」。")
            log("    改 updater.py 顶部的 APP_VERSION，然后重新打包。")
    except Exception:
        pass

    log("")
    log("接下来：")
    log("    bash store/deploy.sh     # 对账（不跑会丢线上订单）")
    log("    重新部署站点              # 站点不更新 = 白发")
    log("    同步百度网盘              # 网盘那份也要换")
    return 0


if __name__ == "__main__":
    sys.exit(main())
