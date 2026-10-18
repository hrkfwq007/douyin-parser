#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用 GitHub 官方 API 创建 Release 并上传安装包附件。

这是整个推广链条里**唯一能用官方 API 全自动**的环节。
知乎 / 小红书 / CSDN / B站 都没有面向个人创作者的发文 API，
只有 GitHub 的 Releases API 是公开、稳定、完全合规的。

用法
----
    # token 只从环境变量读，不落盘、不写进任何配置或记忆
    set GITHUB_TOKEN=ghp_xxxxxxxxxxxx        # Windows cmd
    $env:GITHUB_TOKEN="ghp_xxxxxxxxxxxx"     # PowerShell
    export GITHUB_TOKEN=ghp_xxxxxxxxxxxx     # bash

    python release_github.py --dry-run       # 先看要发什么，不真的发
    python release_github.py                 # 真的发

token 需要的权限
----------------
classic token 勾 `repo`；或 fine-grained token 给这一个仓库
Contents: Read and write。不需要其他权限。

说明
----
- Release 正文来自 `推广/GitHub Release 说明.md` 里的代码块，
  改了那个文件再跑本脚本，正文就会跟着变 —— 只有一个内容源。
- 已存在同名 Release 或同名附件时会先删掉旧的再传，重复跑安全。
- 只传精简版。完整版 342MB 走网盘，之前实测大文件容易超时。
"""

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
UPLOAD = "https://uploads.github.com"

OWNER = "hrkfwq007"
REPO = "douyin-parser"
TAG = "v2.2"
RELEASE_NAME = "抖音无水印解析器 v2.2"

BASE = os.path.dirname(os.path.abspath(__file__))
NOTES_MD = os.path.join(BASE, "推广", "GitHub Release 说明.md")
ASSET = os.path.join(BASE, "release", "抖音无水印解析器_v2.1_精简版_安装.exe")
# GitHub 下载下来要是 ASCII 名，中文名在本地会被各种工具折腾
ASSET_NAME = "DouyinParser_v2.1_Slim_Setup.exe"

FENCE = re.compile(r"^```[A-Za-z0-9]*\n(.*?)\n```", re.S | re.M)


def req(url, token, method="GET", body=None, ctype="application/json", timeout=120):
    data = None
    if body is not None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("Authorization", f"Bearer {token}")
    r.add_header("Accept", "application/vnd.github+json")
    r.add_header("X-GitHub-Api-Version", "2022-11-28")
    if body is not None:
        r.add_header("Content-Type", ctype)
    if data is not None:
        r.add_header("Content-Length", str(len(data)))
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            detail = json.loads(raw) if raw else {}
        except Exception:
            detail = {"message": raw.decode("utf-8", "replace")[:300]}
        return e.code, detail


def load_notes():
    with open(NOTES_MD, encoding="utf-8") as f:
        md = f.read()
    m = FENCE.search(md)
    if not m:
        sys.exit(f"[x] {NOTES_MD} 里找不到代码块，Release 正文没来源")
    return m.group(1).strip("\n")


def md5sum(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_release(token):
    code, data = req(f"{API}/repos/{OWNER}/{REPO}/releases/tags/{TAG}", token)
    return data if code == 200 else None


def delete_asset(token, rel_id, name):
    _, assets = req(f"{API}/repos/{OWNER}/{REPO}/releases/{rel_id}/assets", token)
    if isinstance(assets, list):
        for a in assets:
            if a.get("name") == name:
                code, _ = req(
                    f"{API}/repos/{OWNER}/{REPO}/releases/assets/{a['id']}",
                    token, method="DELETE")
                print(f"    删掉旧附件（{code}）")


def upload_asset(token, rel_id, path, name, timeout=900):
    with open(path, "rb") as f:
        blob = f.read()
    url = (f"{UPLOAD}/repos/{OWNER}/{REPO}/releases/{rel_id}/assets"
           f"?name={urllib.parse.quote(name)}")
    code, data = req(url, token, method="POST", body=blob,
                     ctype="application/octet-stream", timeout=timeout)
    if code not in (200, 201):
        return None, data
    return data.get("browser_download_url"), data


def main():
    dry = "--dry-run" in sys.argv

    if not os.path.isfile(ASSET):
        sys.exit(f"[x] 安装包不存在：{ASSET}")
    size = os.path.getsize(ASSET)
    digest = md5sum(ASSET)
    notes = load_notes()

    print("=" * 56)
    print(f"  仓库   {OWNER}/{REPO}")
    print(f"  标签   {TAG}")
    print(f"  标题   {RELEASE_NAME}")
    print(f"  附件   {ASSET_NAME}  {size:,} 字节  md5 {digest}")
    print(f"  正文   {len(notes)} 字（来自 推广/GitHub Release 说明.md）")
    print("=" * 56)

    if dry:
        print("\n[dry-run] 正文前 300 字：\n")
        print(notes[:300])
        print("\n[dry-run] 到此为止，没有真的发。去掉 --dry-run 才发。")
        return 0

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        sys.exit("[x] 环境变量 GITHUB_TOKEN 没设。\n"
                 "    Windows cmd:  set GITHUB_TOKEN=ghp_xxx\n"
                 "    PowerShell :  $env:GITHUB_TOKEN='ghp_xxx'\n"
                 "    bash       :  export GITHUB_TOKEN=ghp_xxx")

    print("\n>> 检查 Release 是否已存在")
    rel = find_release(token)
    if rel:
        print(f"   已有 Release #{rel['id']}，复用它")
        rel_id = rel["id"]
        delete_asset(token, rel_id, ASSET_NAME)
    else:
        code, data = req(f"{API}/repos/{OWNER}/{REPO}/releases", token, method="POST",
                         body={"tag_name": TAG, "name": RELEASE_NAME,
                               "body": notes, "draft": False, "prerelease": False})
        if code not in (200, 201):
            sys.exit(f"[x] 创建 Release 失败（{code}）：{data.get('message')}")
        rel_id = data["id"]
        print(f"   已创建 Release #{rel_id}")

    print(f"\n>> 上传附件（{size/1024/1024:.1f} MB，慢是正常的）")
    url, info = upload_asset(token, rel_id, ASSET, ASSET_NAME)
    if not url:
        sys.exit(f"[x] 上传失败：{info.get('message', info)}")

    print(f"\n[ok] 全部完成")
    print(f"    Release: https://github.com/{OWNER}/{REPO}/releases/tag/{TAG}")
    print(f"    附件直链: {url}")
    print(f"\n    把这条直链填进 推广/渠道文案包.md 的 GitHub 引流段。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
