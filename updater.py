"""客户端自动更新。

设计原则
--------
1. **永远不能因为更新把软件搞崩。** 站点宕机、版本文件写错、下到一半断网，
   全部静默吞掉，软件照常能用。更新是锦上添花，不是启动的前置条件。
2. **不自己替换 exe。** Windows 上程序不能覆盖正在运行的自己。
   所以下载的是完整安装包（7z 自解压），让它在独立进程里装到同一个目录。
   代价是要下 60MB，好处是不会出现半新半旧的残缺安装。
3. **sha256 必须校验。** 更新包如果被劫持或下残，装上去就是给人送马。
   校验不过就删掉重来，绝不将就。

用法（GUI 里）
--------------
    updater.check_async(variant, on_result)   # 后台问一次，回来给 dict 或 None
    updater.download(...)                     # 在下载线程里跑，带进度回调
    updater.launch_installer(path)            # 启动安装包，随后主程序自行退出
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time

try:
    import requests
except Exception:  # 没 requests 时不能让 import 本身炸掉
    requests = None

# 软件版本号。发新版时改这里，站点 version.json 里也要改，两边比对决定要不要更新。
# 这个号只用于比对大小，不要求和安装包文件名里的版本字面一致。
APP_VERSION = "2.2.1"

# 站点地址。改域名时只改这一处（和 qt_app.BUY_URL 保持同一个域名）。
UPDATE_BASE = "https://douyin-parser-42948.app.workbuddy.host"

# 请求超时。更新检查不能拖慢启动，宁可超时跳过。
CHECK_TIMEOUT = 8

# 同一天内不重复问服务器。省流量，也避免用户反复点按钮打爆站点。
_THROTTLE_SEC = 20 * 3600


# ---------------------------------------------------------------------------
# 版本号比对
# ---------------------------------------------------------------------------

def _vtuple(v):
    out = []
    for part in str(v or "").strip().lstrip("vV").replace("_", ".").split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out) if out else (0,)


def is_newer(latest, current):
    """latest 是否比 current 新。'2.1' 与 '2.1.0' 视为相同。"""
    a, b = _vtuple(latest), _vtuple(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


# ---------------------------------------------------------------------------
# 节流：避免每次启动都打服务器
# ---------------------------------------------------------------------------

def _state_path():
    d = os.path.join(tempfile.gettempdir(), "DouyinParserUpdate")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, "state.json")


def _read_state():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(data):
    try:
        with open(_state_path(), "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def should_check(force=False):
    """本次启动要不要真的去问服务器。force 用于用户手动点按钮。"""
    if force:
        return True
    st = _read_state()
    return (time.time() - float(st.get("last_check", 0))) > _THROTTLE_SEC


def mark_checked():
    st = _read_state()
    st["last_check"] = time.time()
    _write_state(st)


def skipped_version(v):
    """把某个版本记进「用户选择跳过」，下次不再提示。"""
    st = _read_state()
    st["skipped"] = str(v)
    _write_state(st)


def is_skipped(v):
    return str(_read_state().get("skipped") or "") == str(v)


# ---------------------------------------------------------------------------
# 检查更新
# ---------------------------------------------------------------------------

def check(variant="slim", timeout=CHECK_TIMEOUT):
    """问服务器有没有新版本。

    返回更新信息 dict（含 __abs_url 绝对下载地址），无更新或出错一律 None。
    """
    if requests is None:
        return None
    url = f"{UPDATE_BASE}/api/version"
    try:
        r = requests.get(url, params={"variant": variant, "v": APP_VERSION},
                         timeout=timeout)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None

    if not data.get("ok"):
        return None
    info = data.get("latest") or {}
    ver = str(info.get("version") or "")
    if not ver:
        return None
    # 以本地比对为准，不盲信服务端算的 has_update（两边版本算法可能不一致）
    if not is_newer(ver, APP_VERSION):
        return None

    dl = str(info.get("url") or "")
    if dl.startswith("/"):
        dl = UPDATE_BASE + dl
    if not dl.startswith("http"):
        return None

    info["__abs_url"] = dl
    info["__variant"] = variant
    info["__has_update"] = True
    return info


# ---------------------------------------------------------------------------
# 下载
# ---------------------------------------------------------------------------

def target_path(info):
    """安装包落地到哪里。放在系统临时目录，不和用户的下载目录混在一起。"""
    d = os.path.join(tempfile.gettempdir(), "DouyinParserUpdate")
    os.makedirs(d, exist_ok=True)
    name = info.get("filename") or f"DouyinParser_{info.get('version')}_Setup.exe"
    # 文件名里的非法字符替换掉，避免写盘失败
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return os.path.join(d, name)


def download(info, progress=None, chunk=256 * 1024):
    """下载安装包并校验 sha256。

    progress(done, total) 会被周期性回调；返回 (ok, path_or_error)。
    """
    if requests is None:
        return False, "缺少 requests 模块"
    url = info.get("__abs_url") or ""
    dest = target_path(info)
    expect = (info.get("sha256") or "").strip().lower()
    total = int(info.get("size") or 0)

    tmp = dest + ".part"
    try:
        with requests.get(url, stream=True, timeout=(10, 60)) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or total or 0)
            done = 0
            h = hashlib.sha256()
            with open(tmp, "wb") as f:
                for block in r.iter_content(chunk_size=chunk):
                    if not block:
                        continue
                    f.write(block)
                    h.update(block)
                    done += len(block)
                    if progress:
                        try:
                            progress(done, total)
                        except Exception:
                            pass
        got = h.hexdigest()
    except Exception as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False, f"下载失败：{e}"

    if expect and got != expect:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False, "文件校验不通过，已放弃本次更新"
    if not expect:
        # 服务端没给摘要（老站点）时至少确认不是空文件
        if os.path.getsize(tmp) < 1024 * 1024:
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False, "下载到的文件异常"

    try:
        if os.path.exists(dest):
            os.remove(dest)
        os.replace(tmp, dest)
    except Exception as e:
        return False, f"保存失败：{e}"
    return True, dest


# ---------------------------------------------------------------------------
# 启动安装包
# ---------------------------------------------------------------------------

def launch_installer(path):
    """以独立进程启动安装包。返回是否成功。

    不起 shell、不等它结束：安装包要在主程序退出后自己把文件替换掉。
    """
    if not os.path.isfile(path):
        return False
    try:
        if sys.platform.startswith("win"):
            # DETACHED_PROCESS：安装器独立存活，主程序退出不会带走它
            subprocess.Popen([path], close_fds=True,
                             creationflags=0x00000008)
        else:
            subprocess.Popen([path], close_fds=True)
        return True
    except Exception:
        return False


def open_download_page():
    """更新不可用时（比如完整版没开自动更新）退化为打开下载页。"""
    import webbrowser
    try:
        webbrowser.open(UPDATE_BASE + "/download")
        return True
    except Exception:
        return False
