"""
Douyin Video Downloader - Qt6 GUI Application
Full version with auto cookie acquisition support
"""
import html
import json
import os
import re
import shutil
import sys
import webbrowser
from datetime import datetime

import requests
from PySide6.QtCore import Qt, QSize, QThread, Signal, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QStyle,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QPlainTextEdit,
    QProgressBar,
    QHeaderView,
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QRadioButton,
    QButtonGroup,
    QGroupBox,
    QScrollArea,
    QGraphicsOpacityEffect,
)

from douyin_video_parser import DouyinVideoParser
import activation
import updater

# 安装包变体：精简版入口 qt_app_slim.py 会把它设成 slim。
# 决定自动更新时去站点问哪一份安装包。
VARIANT = (os.environ.get("DP_VARIANT") or "full").strip().lower()

DISABLE_LOGIN = os.environ.get("DISABLE_LOGIN", "0") == "1"

if getattr(sys, "frozen", False):
    os.environ.setdefault(
        "PLAYWRIGHT_BROWSERS_PATH",
        os.path.join(sys._MEIPASS, "playwright-browsers"),
    )
    os.environ.setdefault("PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD", "1")

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
    RESOURCE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = BASE_DIR
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DEFAULT_SAVE_DIR = os.path.join(BASE_DIR, "downloads")

# 购买页地址。试用额度用尽、激活过期时都跳这里。
BUY_URL = "https://douyin-parser-42948.app.workbuddy.host/"


def _find_chrome_exe(base):
    """在 playwright-browsers 目录下定位 chrome.exe。

    Playwright 不同版本的内核目录名不一样：
      - 新版 64 位：chromium-<rev>/chrome-win64/chrome.exe
      - 旧版      ：chromium-<rev>/chrome-win/chrome.exe
      - headless 壳：chromium_headless_shell-<rev>/chrome-win/headless_shell.exe
    只认其中一种会导致完整版被误判成「没带内核」，所以这里全都要找。
    """
    if not base or not os.path.isdir(base):
        return ""
    # (目录名前缀, 候选子目录, 可执行文件名)
    patterns = (
        ("chromium-",      ("chrome-win64", "chrome-win", ""), "chrome.exe"),
        ("chromium_",      ("chrome-win64", "chrome-win", ""), "chrome.exe"),
    )
    try:
        names = sorted(os.listdir(base))
    except Exception:
        return ""
    for prefix, subdirs, exe_name in patterns:
        for name in names:
            if not name.startswith(prefix):
                continue
            root = os.path.join(base, name)
            for sub in subdirs:
                exe = os.path.join(root, sub, exe_name)
                if os.path.exists(exe):
                    return exe
    # 兜底：直接递归找一层，防止以后 Playwright 再改目录结构
    try:
        for name in names:
            if not name.startswith("chromium"):
                continue
            root = os.path.join(base, name)
            for sub in sorted(os.listdir(root)):
                exe = os.path.join(root, sub, "chrome.exe")
                if os.path.exists(exe):
                    return exe
    except Exception:
        pass
    return ""


# 复用系统里已经装好的浏览器，优先 Edge：
#   - Edge 是 Windows 10/11 自带组件，几乎装机率 100%
#   - Chrome 装在标准路径时也能用
# 这样就不必把 719MB 的 Chromium 打进安装包，完整功能版能从 342MB 压到 60MB 上下。
SYSTEM_BROWSER_PATHS = (
    ("msedge", (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    )),
    ("chrome", (
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    )),
)


def _system_browsers():
    """返回本机可用的 [(channel, 可执行文件路径)]，按优先级排序。"""
    found = []
    for channel, candidates in SYSTEM_BROWSER_PATHS:
        for exe in candidates:
            if os.path.exists(exe):
                found.append((channel, exe))
                break
    return found


def _browser_available():
    """返回 (能否扫码登录, 说明)。

    三档兜底，缺一不可：
      1. 安装包自带的 Chromium（完整版有，719MB）
      2. 系统 Edge / Chrome（省掉 719MB 的关键）
      3. 都没有 → 提示用户去装 Edge
    以前只认第 1 档，导致精简版被一刀切成「不能登录」。
    """
    if not getattr(sys, "frozen", False):
        return True, "源码模式"
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""
    if base and os.path.isdir(base):
        exe = _find_chrome_exe(base)
        if exe:
            return True, exe
    for channel, exe in _system_browsers():
        return True, f"{channel} → {exe}"
    return False, "未找到可用浏览器（内置内核、Edge、Chrome 都没有）"


def _launch_browser(p):
    """依次尝试：内置 Chromium → 系统 Edge → 系统 Chrome。

    内置内核优先，保证完整版行为不变；没有内置时才用系统的，
    这样精简版不必再阉割扫码登录功能。
    """
    args = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    # 1) 安装包自带的 Chromium：完整版有，优先用它，行为与以前完全一致
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""
    if base and os.path.isdir(base) and _find_chrome_exe(base):
        return p.chromium.launch(headless=True, args=args), "内置内核"
    # 2) 没有内置内核（精简版）→ 借用系统 Edge / Chrome
    for channel, _exe in _system_browsers():
        try:
            return p.chromium.launch(headless=True, channel=channel, args=args), channel
        except Exception:
            continue        # 这个用不了就换下一个，别让用户自己去猜
    raise RuntimeError("没有可用浏览器：内置内核缺失，且未检测到 Edge / Chrome")


def safe_filename(text: str, fallback: str) -> str:
    text = text or ""
    text = re.sub(r"[\\/:*?\"<>|]", "_", text).strip()
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return fallback
    return text[:60]


def format_time(ts: int | None) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _style_icon(pixmap_name: str):
    """返回 Qt 内置标准图标；枚举不存在时回退空图标，保证不崩溃。"""
    sp = getattr(QStyle, pixmap_name, None)
    if sp is None:
        return QIcon()
    return QApplication.style().standardIcon(sp)


def _esc(text) -> str:
    return html.escape("" if text is None else str(text))


def _kv_table(rows) -> str:
    """rows: [(label, value, mono), ...] -> 键值表格富文本（QLabel 子集）。"""
    body = ""
    for k, v, mono in rows:
        vstyle = "font-family:Consolas, 'Courier New', monospace;" if mono else ""
        body += (
            f"<tr>"
            f"<td style='color:#7c869b; padding:5px 14px 5px 0; vertical-align:top;'>{_esc(k)}</td>"
            f"<td style='color:#e6e6e6; {vstyle} padding:5px 0; vertical-align:top;'>{_esc(v)}</td>"
            f"</tr>"
        )
    return f"<table cellpadding='0' cellspacing='0' style='font-size:14px;'>{body}</table>"


def fmt_count(n) -> str:
    """抖音计数格式化：亿/万 缩写，None 显示 -。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "-"
    if n >= 100000000:
        return f"{n / 100000000:.1f}亿"
    if n >= 10000:
        return f"{n / 10000:.1f}万"
    return str(n)


def fmt_duration(ms) -> str | None:
    """毫秒 -> mm:ss；无法解析返回 None。"""
    try:
        ms = int(ms)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    total = ms // 1000
    m, s = divmod(total, 60)
    return f"{m:02d}:{s:02d}"


def _stat_tiles(rows) -> str:
    """rows: [(label, value), ...] -> 横向统计磁贴表格（QLabel 富文本子集）。"""
    cells = ""
    for label, value in rows:
        cells += (
            f"<td style='background:#1b2030; padding:8px 6px; text-align:center;'>"
            f"<div style='color:#f5f7fa; font-size:15px; font-weight:bold;'>{_esc(value)}</div>"
            f"<div style='color:#7c869b; font-size:11px; margin-top:3px;'>{_esc(label)}</div>"
            f"</td>"
        )
    return (
        f"<table width='100%' cellpadding='0' cellspacing='8' style='font-size:14px;'>"
        f"<tr>{cells}</tr></table>"
    )


def load_config() -> dict:
    data = {
        "cookie": "",
        "save_dir": DEFAULT_SAVE_DIR,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except Exception:
            pass
    cookie_path = os.path.join(BASE_DIR, "douyin_cookie.txt")
    if os.path.exists(cookie_path):
        try:
            with open(cookie_path, "r", encoding="utf-8") as f:
                data["cookie"] = f.read().lstrip("\ufeff").strip()
        except Exception:
            pass
    return data


def save_config(cookie: str, save_dir: str):
    data = {"cookie": cookie, "save_dir": save_dir}
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(os.path.join(BASE_DIR, "douyin_cookie.txt"), "w", encoding="utf-8") as f:
        f.write(cookie or "")


def cookies_to_header(cookies: list[dict]) -> str:
    parts = []
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        if name and value is not None:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


DOUYIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)

QR_SELECTORS = [
    ".qrcode-img img",
    "img[aria-label*='二维码']",
    "img.RhjdbXj8",
    "img[src^='data:image/png;base64']",
    "img[src*='qrcode']",
    "img[src*='qr']",
    "img[alt*='二维码']",
    "[class*=qrcode] img",
]


def clear_proxy_env():
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "SOCKS_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "socks_proxy",
    ):
        os.environ.pop(key, None)


def has_valid_login_cookie(cookies: list[dict]) -> bool:
    for c in cookies:
        if c.get("name") == "sessionid" and c.get("value"):
            return True
    return False


def is_logged_in_url(url: str) -> bool:
    lower = (url or "").lower()
    if "douyin.com" not in lower:
        return False
    return not any(x in lower for x in ("passport", "/login", "/auth"))


def open_login_panel(page) -> None:
    """打开登录弹窗并切到扫码（只用短超时选择器，避免全页扫描卡顿）"""
    clicked = False
    for fn in (
        lambda: page.click("#login-panel-new", timeout=3000),
        lambda: page.locator("[id*='login-panel'], [id*='login-pannel']").first.click(timeout=2000),
        lambda: page.get_by_role("button", name="登录").first.click(timeout=2000),
    ):
        try:
            fn()
            clicked = True
            break
        except Exception:
            continue
    if clicked:
        page.wait_for_timeout(1500)

    for text in ("扫码登录", "二维码登录", "二维码"):
        try:
            page.get_by_text(text, exact=False).first.click(timeout=1500)
            page.wait_for_timeout(800)
            return
        except Exception:
            continue


def find_qr_element(page):
    scopes = [page, *page.frames]
    for scope in scopes:
        for sel in QR_SELECTORS:
            try:
                el = scope.query_selector(sel)
                if not el:
                    continue
                box = el.bounding_box()
                if box and box.get("width", 0) >= 100 and box.get("height", 0) >= 100:
                    return el
            except Exception:
                continue
    return None


def wait_for_qr_element(page, status_cb=None, timeout_sec: int = 35):
    """轮询等待二维码出现，必要时重试打开登录弹窗。"""
    import time

    deadline = time.time() + timeout_sec
    opened = False
    last_open_retry = 0.0
    last_status_emit = 0.0
    while time.time() < deadline:
        element = find_qr_element(page)
        if element:
            return element

        now = time.time()
        if not opened:
            open_login_panel(page)
            opened = True
            last_open_retry = now
        elif now - last_open_retry >= 8:
            open_login_panel(page)
            last_open_retry = now

        if status_cb and now - last_status_emit >= 2:
            remain = max(0, int(deadline - now))
            status_cb(f"等待二维码出现...（剩余约 {remain}s）")
            last_status_emit = now

        page.wait_for_timeout(500)
    return None


def extract_login_cookies(context, page, status_cb=None) -> str | None:
    """登录成功后提取 Cookie"""
    cookies = context.cookies()
    if has_valid_login_cookie(cookies):
        return cookies_to_header(cookies)

    if status_cb:
        status_cb("登录成功，正在提取 Cookie...")
    try:
        page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)
    except Exception:
        pass

    cookies = context.cookies()
    if has_valid_login_cookie(cookies):
        return cookies_to_header(cookies)
    return None


class QualitySelectionDialog(QDialog):
    """Modern quality selection dialog"""
    def __init__(self, qualities: list[dict], parent=None):
        super().__init__(parent)
        # Deduplicate qualities by ratio and bit_rate
        self.qualities = self._deduplicate_qualities(qualities)
        self.selected_quality = None
        self.setWindowTitle("选择视频质量")
        self.setMinimumWidth(500)
        self.setMaximumHeight(600)  # Limit maximum height
        self.setup_ui()
        self._apply_style()
    
    def _deduplicate_qualities(self, qualities: list[dict]) -> list[dict]:
        """Remove duplicate qualities based on ratio and bit_rate"""
        seen = set()
        unique_qualities = []
        for quality in qualities:
            ratio = quality.get("ratio", "")
            bit_rate = quality.get("bit_rate", 0)
            # Create a unique key
            key = (ratio, bit_rate)
            if key not in seen:
                seen.add(key)
                unique_qualities.append(quality)
        return unique_qualities
    
    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        
        title = QLabel("请选择要下载的视频质量：")
        title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 10px;")
        layout.addWidget(title)
        
        # Create scroll area for quality options
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMinimumHeight(200)
        scroll_area.setMaximumHeight(400)  # Limit scroll area height
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #2b3142;
                border-radius: 8px;
                background: #1b1f2a;
            }
            QScrollBar:vertical {
                background: #1b1f2a;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: #3b82f6;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #2563eb;
            }
        """)
        
        group = QGroupBox()
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)
        self.button_group = QButtonGroup(self)
        
        if not self.qualities:
            no_quality = QLabel("未找到可用的视频质量选项")
            no_quality.setStyleSheet("color: #999; padding: 20px;")
            group_layout.addWidget(no_quality)
        else:
            for idx, quality in enumerate(self.qualities):
                ratio = quality.get("ratio", "未知")
                bit_rate = quality.get("bit_rate", 0)
                quality_label = quality.get("quality_label", ratio)
                
                # Create quality description
                desc = f"{quality_label}"
                if bit_rate > 0 and f"{bit_rate // 1000}Kbps" not in quality_label:
                    desc += f" - {bit_rate // 1000}Kbps"
                
                radio = QRadioButton(desc)
                radio.setProperty("quality", quality)
                if idx == 0:  # Select highest quality by default
                    radio.setChecked(True)
                    self.selected_quality = quality
                self.button_group.addButton(radio, idx)
                group_layout.addWidget(radio)
                
                # Connect signal to update selection
                radio.toggled.connect(lambda checked, q=quality: self._on_quality_selected(checked, q))
        
        group_layout.addStretch()  # Add stretch at the end
        scroll_area.setWidget(group)
        layout.addWidget(scroll_area)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _on_quality_selected(self, checked: bool, quality: dict):
        if checked:
            self.selected_quality = quality
    
    def _apply_style(self):
        self.setStyleSheet("""
            QDialog { background: #0f1115; color: #e6e6e6; }
            QGroupBox { 
                border: 2px solid #2b3142; 
                border-radius: 8px; 
                margin-top: 10px; 
                padding-top: 15px;
                background: #1b1f2a;
            }
            QGroupBox::title { 
                subcontrol-origin: margin; 
                left: 10px; 
                padding: 0 5px;
            }
            QRadioButton {
                padding: 12px;
                font-size: 14px;
                border-radius: 6px;
                margin: 4px;
            }
            QRadioButton:hover {
                background: #2b3142;
            }
            QRadioButton::indicator {
                width: 20px;
                height: 20px;
                border-radius: 10px;
                border: 2px solid #3b82f6;
            }
            QRadioButton::indicator:checked {
                background: #3b82f6;
            }
            QDialogButtonBox QPushButton {
                min-width: 80px;
                padding: 8px 16px;
            }
        """)
    
    def get_selected_quality(self) -> dict | None:
        return self.selected_quality


def download_file(url: str, path: str, progress_cb=None) -> bool:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.douyin.com/",
        "Origin": "https://www.douyin.com",
        "Accept": "*/*",
        "Range": "bytes=0-",
    }
    try:
        resp = requests.get(url, headers=headers, stream=True, timeout=30)
        if resp.status_code not in (200, 206):
            return False
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total > 0:
                        progress_cb(int(downloaded * 100 / total))
        if progress_cb:
            progress_cb(100)
        return True
    except Exception:
        return False


class ParseSingleWorker(QThread):
    result = Signal(dict)
    error = Signal(str)

    def __init__(self, parser: DouyinVideoParser, url: str):
        super().__init__()
        self.parser = parser
        self.url = url

    def run(self):
        if not self.parser.cookie:
            self.error.emit("解析失败：尚未配置 Cookie，请先点击「获取Cookie」扫码登录")
            return
        try:
            info = self.parser.parse_video(self.url)
            if not info:
                # Try to get more debug info
                try:
                    video_id = self.parser.get_video_id(self.url)
                    if video_id:
                        data = self.parser.get_aweme_detail(video_id)
                        if data:
                            aweme = data.get("aweme_detail") or {}
                            aweme_type = aweme.get("aweme_type", "unknown")
                            has_images = bool(aweme.get("images"))
                            self.error.emit(f"解析失败：aweme_type={aweme_type}, 是否有images={has_images}")
                        else:
                            self.error.emit("解析失败：无法获取API数据，请检查Cookie是否有效")
                    else:
                        # Try to get the redirected URL for debugging
                        try:
                            import requests
                            session = requests.Session()
                            session.headers.update({
                                "User-Agent": self.parser.user_agent,
                                "Referer": "https://www.douyin.com/"
                            })
                            resp = session.get(self.url, allow_redirects=True, timeout=10)
                            real_url = resp.url
                            self.error.emit(f"解析失败：无法提取视频ID\n访问URL: {real_url}\n请确认链接是否为有效的抖音视频/图集链接")
                        except Exception:
                            self.error.emit("解析失败：无法提取视频ID，请确认链接格式正确")
                except Exception as e:
                    self.error.emit(f"解析失败：{str(e)}")
                return
            self.result.emit(info)
        except Exception as e:
            self.error.emit(f"解析失败：{str(e)}")


class ParseListWorker(QThread):
    result = Signal(dict)
    done = Signal()
    error = Signal(str)

    def __init__(self, parser: DouyinVideoParser, urls: list[str]):
        super().__init__()
        self.parser = parser
        self.urls = urls

    def run(self):
        if not self.parser.cookie:
            self.error.emit("解析失败：尚未配置 Cookie，请先点击「获取Cookie」扫码登录")
            return
        if not self.urls:
            self.error.emit("列表为空")
            return
        for url in self.urls:
            # Parse full video info including qualities
            info = self.parser.parse_video(url)
            if not info:
                continue
            payload = {"url": url, **info}
            self.result.emit(payload)
        self.done.emit()


class ParseUserWorker(QThread):
    result = Signal(list, str)
    error = Signal(str)

    def __init__(self, parser: DouyinVideoParser, url: str, max_pages: int):
        super().__init__()
        self.parser = parser
        self.url = url
        self.max_pages = max_pages

    def run(self):
        if not self.parser.cookie:
            self.error.emit("解析失败：尚未配置 Cookie，请先点击「获取Cookie」扫码登录")
            return
        url = self.url
        if "douyin.com/video/" in url or "v.douyin.com/" in url:
            user_home = self.parser.get_user_home_from_video_url(url)
            if not user_home:
                self.error.emit("无法从视频解析主页")
                return
            urls = self.parser.get_user_aweme_urls(user_home, max_pages=self.max_pages)
            self.result.emit(urls, user_home)
            return

        urls = self.parser.get_user_aweme_urls(url, max_pages=self.max_pages)
        if not urls:
            self.error.emit("解析主页列表失败")
            return
        self.result.emit(urls, url)


class DownloadWorker(QThread):
    progress = Signal(int)
    status = Signal(str)
    done = Signal(int, int)

    def __init__(self, parser: DouyinVideoParser, video_infos: list[dict], save_dir: str, selected_ratio: str = None):
        super().__init__()
        self.parser = parser
        self.video_infos = video_infos  # List of dicts with url, qualities, etc.
        self.save_dir = save_dir
        self.selected_ratio = selected_ratio  # Optional: filter by ratio

    def run(self):
        os.makedirs(self.save_dir, exist_ok=True)
        success = 0
        total = len(self.video_infos)
        for idx, info in enumerate(self.video_infos, start=1):
            content_type = info.get("content_type", "video")
            
            if content_type == "video":
                ok = self._download_video(info, idx, total)
            elif content_type == "image":
                ok = self._download_album(info, idx, total)
            else:
                continue
            
            if ok:
                success += 1
        self.done.emit(success, total)
    
    def _download_video(self, info: dict, idx: int, total: int) -> bool:
        """Download a single video"""
        self.status.emit(f"下载视频 {idx}/{total}")
        
        # Get video URL
        url = info.get("url")
        if not url:
            return False
        
        # Get download URL from qualities or fallback to nwm_url
        download_url = None
        qualities = info.get("qualities", [])
        
        if qualities:
            if self.selected_ratio:
                # Find quality matching selected ratio
                for q in qualities:
                    if q.get("ratio") == self.selected_ratio:
                        download_url = q.get("url")
                        break
            # If no match or no ratio specified, use highest quality
            if not download_url and qualities:
                download_url = qualities[0].get("url")
        
        # Fallback to nwm_url
        if not download_url:
            download_url = info.get("nwm_url")
        
        if not download_url:
            return False
        
        desc = info.get("desc") or ""
        aweme_id = info.get("aweme_id") or "douyin"
        
        # Add quality suffix to filename
        quality_suffix = ""
        if self.selected_ratio:
            quality_suffix = f"_{self.selected_ratio}"
        elif qualities:
            quality_suffix = f"_{qualities[0].get('ratio', '')}"
        
        name = safe_filename(desc, aweme_id) + quality_suffix + ".mp4"
        path = os.path.join(self.save_dir, name)

        def _cb(p):
            self.progress.emit(p)

        return download_file(download_url, path, progress_cb=_cb)
    
    def _download_album(self, info: dict, idx: int, total: int) -> bool:
        """Download an album (multiple images)"""
        self.status.emit(f"下载图集 {idx}/{total}")
        
        image_data = info.get("image_data", {})
        image_urls = image_data.get("image_urls", [])
        
        if not image_urls:
            return False
        
        desc = info.get("desc") or ""
        aweme_id = info.get("aweme_id") or "douyin"
        
        # Create folder for album
        folder_name = safe_filename(desc, aweme_id)
        album_dir = os.path.join(self.save_dir, folder_name)
        os.makedirs(album_dir, exist_ok=True)
        
        # Check if these are live images
        is_live = image_data.get("is_live", False)
        
        success_count = 0
        for img_idx, img_url in enumerate(image_urls, start=1):
            try:
                # Determine file extension first
                url_lower = img_url.lower()
                if is_live:
                    # Live images are videos, save as mp4
                    ext = ".mp4"
                elif ("gif" in url_lower or url_lower.endswith(".gif") or ".gif?" in url_lower):
                    ext = ".gif"
                elif ("webp" in url_lower or url_lower.endswith(".webp") or ".webp?" in url_lower):
                    ext = ".webp"
                elif ("png" in url_lower or url_lower.endswith(".png") or ".png?" in url_lower):
                    ext = ".png"
                else:
                    ext = ".jpg"  # Default to jpg
                
                img_name = f"{img_idx:03d}{ext}"
                img_path = os.path.join(album_dir, img_name)
                
                # For live images (MP4 videos), use download_file function for better support
                if is_live:
                    def _cb(p):
                        # Progress callback for live images
                        pass
                    ok = download_file(img_url, img_path, progress_cb=_cb)
                    if ok:
                        success_count += 1
                else:
                    # For static images, use simple download
                    resp = requests.get(img_url, timeout=30, stream=True, headers={"User-Agent": self.parser.user_agent})
                    if resp.status_code == 200:
                        with open(img_path, "wb") as f:
                            for chunk in resp.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        success_count += 1
            except Exception:
                pass
        
        # Consider successful if at least one image downloaded
        return success_count > 0


class CookieWorker(QThread):
    qr = Signal(bytes)
    status = Signal(str)
    done = Signal(str)
    error = Signal(str)

    def run(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            self.error.emit("缺少 playwright，请先安装：pip install playwright && playwright install chromium")
            return

        clear_proxy_env()
        browser = None
        try:
            self.status.emit("启动浏览器...")
            with sync_playwright() as p:
                browser, source = _launch_browser(p)
                self.status.emit(f"已启动浏览器（{source}）")
                context = browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent=DOUYIN_UA,
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                page = context.new_page()

                self.status.emit("打开抖音...")
                page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)

                cookies = context.cookies()
                if has_valid_login_cookie(cookies):
                    cookie_str = extract_login_cookies(context, page, self.status.emit)
                    if cookie_str:
                        self.done.emit(cookie_str)
                        browser.close()
                        return

                self.status.emit("获取二维码...")
                element = wait_for_qr_element(page, self.status.emit, timeout_sec=35)

                if not element:
                    self.error.emit("未找到二维码，请确认网络正常且页面未被拦截")
                    browser.close()
                    return

                try:
                    self.qr.emit(element.screenshot())
                except Exception:
                    self.error.emit("二维码截图失败")
                    browser.close()
                    return

                self.status.emit("等待扫码，请在手机上确认登录...")
                start_url = page.url

                for i in range(120):
                    cookies = context.cookies()
                    current_url = page.url

                    if has_valid_login_cookie(cookies):
                        cookie_str = extract_login_cookies(context, page, self.status.emit)
                        if cookie_str:
                            self.done.emit(cookie_str)
                            browser.close()
                            return

                    if is_logged_in_url(current_url) and current_url != start_url:
                        cookie_str = extract_login_cookies(context, page, self.status.emit)
                        if cookie_str:
                            self.done.emit(cookie_str)
                            browser.close()
                            return

                    try:
                        text = page.inner_text("body")
                        if "扫码成功" in text:
                            self.status.emit("扫码成功，请在手机上点击确认...")
                        elif any(k in text for k in ("登录成功", "已登录", "登录完成")):
                            cookie_str = extract_login_cookies(context, page, self.status.emit)
                            if cookie_str:
                                self.done.emit(cookie_str)
                                browser.close()
                                return
                    except Exception:
                        pass

                    if i % 5 == 0:
                        self.status.emit(f"等待扫码登录... ({i // 5 + 1}/24)")
                    page.wait_for_timeout(1000)

                self.error.emit("登录超时，请重试（扫码后需在手机上确认）")
                browser.close()
        except Exception as e:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            self.error.emit(f"获取失败: {e}")


class ClickableLabel(QLabel):
    """支持点击信号的 QLabel，用于缩略图点击切换大图。"""

    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class UpdateCheckWorker(QThread):
    """后台问一次服务器有没有新版本。

    单独开线程是因为网络请求可能卡好几秒，绝不能拖住界面启动。
    出错时 result 发 None —— 检查失败和「没有更新」对界面是同一回事。
    """

    result = Signal(object)

    def __init__(self, variant, parent=None):
        super().__init__(parent)
        self.variant = variant

    def run(self):
        try:
            self.result.emit(updater.check(self.variant))
        except Exception:
            self.result.emit(None)


class UpdateDownloadWorker(QThread):
    """后台下载更新包。进度按字节回传，界面自己换算成百分比。"""

    progress = Signal(int, int)
    finished = Signal(bool, str)

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.info = info

    def run(self):
        def on_progress(done, total):
            self.progress.emit(done, total)

        try:
            ok, res = updater.download(self.info, progress=on_progress)
        except Exception as e:
            ok, res = False, str(e)
        self.finished.emit(bool(ok), res if isinstance(res, str) else str(res))


class ThumbnailWorker(QThread):
    """后台异步下载图集缩略图，逐张回传给主线程渲染。"""

    loaded = Signal(int, QPixmap, str)
    error = Signal(str)

    def __init__(self, urls, parent=None):
        super().__init__(parent)
        self.urls = urls

    def run(self):
        for idx, url in enumerate(self.urls):
            if self.isInterruptionRequested():
                break
            try:
                resp = requests.get(url, timeout=10, headers={"User-Agent": DOUYIN_UA})
                if resp.status_code == 200:
                    pix = QPixmap()
                    if pix.loadFromData(resp.content):
                        thumb = pix.scaled(
                            100, 100, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
                        )
                        self.loaded.emit(idx, thumb, url)
            except Exception as e:
                self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.parser = DouyinVideoParser()
        self.config = load_config()
        self.parser.set_cookie(self.config.get("cookie"))
        self.save_dir = self.config.get("save_dir", DEFAULT_SAVE_DIR)
        self.thumbnail_worker = None

        # 标题带上当前授权状态，用户随时可见：已激活显示套餐与到期日，
        # 未激活显示今日剩余免费次数（消耗额度后会重新刷新）
        self._refresh_trial_title()
        self.setMinimumSize(1220, 860)
        icon_path = os.path.join(RESOURCE_DIR, "assets", "logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        tabs = QTabWidget()
        tabs.addTab(self._build_single_tab(), "单视频下载")
        tabs.addTab(self._build_user_tab(), "主页/视频解析")
        tabs.addTab(self._build_config_tab(), "配置")
        self.setCentralWidget(tabs)
        self._apply_style()
        self._apply_icons()

        # 启动后自己去问一次有没有新版本。不弹窗打扰，只在配置页按钮上标出来。
        QTimer.singleShot(1500, self._autocheck_update)

    def _autocheck_update(self):
        """启动时静默检查。失败、无更新都无声无息。"""
        try:
            self._start_check(force=False)
        except Exception:
            pass

    # ---------------- 授权与免费试用 ----------------

    def _refresh_trial_title(self):
        """刷新标题栏右侧的授权状态。

        已激活 → 「（终身授权）」或「（年版 · 至 2027-10-18）」
        未激活 → 「（试用 · 今日剩 N 次）」，额度用尽则「（未激活）」
        """
        label, expiry = activation.active_plan()
        if label:
            tail = "（终身授权）" if expiry == "终身" else f"（{label} · 至 {expiry}）"
        else:
            left = activation.trial_left()
            tail = f"（试用 · 今日剩 {left} 次）" if left > 0 else "（未激活）"
        self.setWindowTitle(f"抖音无水印解析器 v{updater.APP_VERSION}{tail}")

    def _take_trial_quota(self):
        """消耗一次免费额度，返回 True 才允许继续解析。

        已激活直接放行。额度用尽时弹窗说明，并给一个直达购买页的按钮——
        这一步是转化漏斗的关键：用户刚体验过、确认能用，此刻购买意愿最高。
        """
        if activation.trial_consume():
            self._refresh_trial_title()
            return True

        box = QMessageBox(self)
        box.setWindowTitle("今日免费额度已用完")
        box.setText(
            f"未激活版本每天可免费解析 {activation.TRIAL_DAILY_LIMIT} 次，"
            "今天的额度已经用完了。\n\n"
            "激活后不限次数，解析出来的内容与试用完全一致——"
            "不是试用版给低画质、买了才给高清那套。"
        )
        buy_btn = box.addButton("去购买激活", QMessageBox.AcceptRole)
        box.addButton("明天再来", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is buy_btn:
            webbrowser.open(BUY_URL)
        return False

    def _apply_style(self):
        self.setStyleSheet(
            """
            QWidget { background: #0f1115; color: #e6e6e6; font-size: 14px;
                font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif; }
            #Card { background: #181c25; border: 1px solid #262c3a; border-radius: 14px; padding: 20px; }
            QLabel#Title { font-size: 19px; font-weight: bold; color: #f5f7fa; }
            QLabel#Hint { font-size: 12px; color: #7c869b; }
            QLineEdit, QSpinBox, QPlainTextEdit { background: #1b1f2a; border: 1px solid #2b3142;
                padding: 10px 13px; border-radius: 9px; color: #e6e6e6; }
            QLineEdit:focus, QSpinBox:focus, QPlainTextEdit:focus { border: 1px solid #3b82f6; }
            QPushButton { background: #2b3142; border: none; padding: 10px 16px;
                border-radius: 9px; color: #d6dbe6; }
            QPushButton:hover { background: #343c52; }
            QPushButton:disabled { background: #1d2130; color: #555d72; }
            QPushButton#Primary { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3b82f6, stop:1 #2563eb); color: #ffffff; font-weight: bold; }
            QPushButton#Primary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #4c8ef7, stop:1 #2f6fe6); }
            QPushButton#Primary:disabled { background: #233048; color: #8094ba; }
            QPushButton#Accent { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #fe2c55, stop:1 #e01e4b); color: #ffffff; font-weight: bold; }
            QPushButton#Accent:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #ff3d63, stop:1 #ec2453); }
            QPushButton#Accent:disabled { background: #3a1a24; color: #b07a89; }
            QLabel#Label { color: #7c869b; font-size: 13px; }
            QTabBar::tab { padding: 11px 20px; background: #14171f; margin: 3px 3px;
                border-radius: 9px; color: #9aa3b2; }
            QTabBar::tab:hover { color: #d6dbe6; }
            QTabBar::tab:selected { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2b3142, stop:1 #222838); color: #ffffff; }
            QTabWidget::pane { border: 1px solid #262c3a; border-radius: 14px; top: -1px; }
            QTableWidget { background: #121520; border: 1px solid #2b3142; border-radius: 10px;
                gridline-color: #222838; }
            QHeaderView::section { background: #1b1f2a; padding: 9px; border: none; color: #9aa3b2; }
            QProgressBar { background: #1b1f2a; border: 1px solid #2b3142; border-radius: 7px;
                text-align: center; color: #cdd3e0; height: 14px; }
            QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3b82f6, stop:1 #22d3ee); border-radius: 6px; }
            QGroupBox { border: 1px solid #262c3a; border-radius: 12px; margin-top: 12px;
                padding-top: 14px; }
            QGroupBox::title { subcontrol-origin: margin; left: 16px; color: #9aa3b2; }
            QScrollArea { border: none; }
            """
        )

    def _apply_icons(self):
        icon_map = {
            "解析": "SP_MediaPlay",
            "下载到默认目录": "SP_ArrowDown",
            "下载勾选(默认目录)": "SP_ArrowDown",
            "清空": "SP_TrashIcon",
            "清空记录": "SP_TrashIcon",
            "恢复记录": "SP_FileDialogBack",
            "打开文件夹": "SP_DirOpenIcon",
            "选择目录": "SP_DirIcon",
            "获取Cookie": "SP_DialogApplyButton",
            "保存配置": "SP_DialogSaveButton",
        }
        for btn in self.findChildren(QPushButton):
            name = btn.text()
            if name in icon_map:
                btn.setIcon(_style_icon(icon_map[name]))
                btn.setIconSize(QSize(18, 18))

    def _fade_in(self, widget):
        """解析完成后对结果区做 0→1 淡入；动画对象挂到 widget 上防止被回收，
        结束后移除特效。任何异常都静默降级为不透明（绝不留下透明面板）。"""
        try:
            if widget.graphicsEffect() is not None:
                widget.setGraphicsEffect(None)
            effect = QGraphicsOpacityEffect(widget)
            widget.setGraphicsEffect(effect)
            # 关键：把动画挂到 widget 作为父对象，避免 Python 引用释放后被 C++ 回收，
            # 否则 opacity 会卡在起始值 0.0，导致结果面板整块不可见。
            anim = QPropertyAnimation(effect, b"opacity", widget)
            anim.setDuration(420)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(lambda: widget.setGraphicsEffect(None))
            anim.start(QPropertyAnimation.DeleteWhenStopped)
            # 安全兜底：0.6s 后若仍透明（极端情况下动画未触发），强制显示。
            QTimer.singleShot(600, lambda: widget.setGraphicsEffect(None) if widget.graphicsEffect() else None)
        except Exception:
            widget.setGraphicsEffect(None)

    def _build_single_tab(self):
        widget = QWidget()
        widget.setObjectName("Card")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        # Header
        header = QVBoxLayout()
        title = QLabel("单视频 / 图集下载")
        title.setObjectName("Title")
        hint = QLabel("粘贴抖音分享链接，支持 video、note 以及用户主页 modal_id 弹窗链接")
        hint.setObjectName("Hint")
        header.addWidget(title)
        header.addWidget(hint)
        layout.addLayout(header)

        # Input row
        row = QHBoxLayout()
        row.setSpacing(12)
        self.single_input = QLineEdit()
        self.single_input.setPlaceholderText("https://v.douyin.com/xxxxx 或 https://www.douyin.com/video/xxxxx")
        self.single_input.setMinimumHeight(42)

        self.single_parse_btn = QPushButton("解析")
        self.single_parse_btn.setObjectName("Primary")
        self.single_parse_btn.setMinimumHeight(42)
        self.single_parse_btn.setCursor(Qt.PointingHandCursor)

        self.single_clear_btn = QPushButton("清空")
        self.single_clear_btn.setMinimumHeight(42)
        self.single_clear_btn.setCursor(Qt.PointingHandCursor)

        self.single_download_btn = QPushButton("下载到默认目录")
        self.single_download_btn.setObjectName("Accent")
        self.single_download_btn.setEnabled(False)
        self.single_download_btn.setMinimumHeight(42)
        self.single_download_btn.setCursor(Qt.PointingHandCursor)

        self.single_open_dir_btn = QPushButton("打开文件夹")
        self.single_open_dir_btn.setMinimumHeight(42)
        self.single_open_dir_btn.setCursor(Qt.PointingHandCursor)

        # 复制无水印直链（仅视频解析出直链时显示）
        self.single_copy_btn = QPushButton("复制链接")
        self.single_copy_btn.setMinimumHeight(42)
        self.single_copy_btn.setCursor(Qt.PointingHandCursor)
        self.single_copy_btn.setVisible(False)

        row.addWidget(self.single_input, 4)
        row.addWidget(self.single_parse_btn, 1)
        row.addWidget(self.single_clear_btn, 1)
        row.addWidget(self.single_download_btn, 1)
        row.addWidget(self.single_open_dir_btn, 1)
        row.addWidget(self.single_copy_btn, 1)

        # Preview + info cards
        content_row = QHBoxLayout()
        content_row.setSpacing(18)

        cover_card = QWidget()
        cover_card.setObjectName("Card")
        cover_layout = QVBoxLayout(cover_card)
        cover_layout.setContentsMargins(12, 12, 12, 12)
        cover_layout.setSpacing(12)

        self.single_cover = QLabel("封面预览")
        self.single_cover.setFixedSize(520, 300)
        self.single_cover.setAlignment(Qt.AlignCenter)
        self.single_cover.setStyleSheet(
            "background: #121520; border-radius: 10px; color: #7c869b; font-size: 16px;"
        )
        cover_layout.addWidget(self.single_cover)

        content_row.addWidget(cover_card, 2)

        info_card = QWidget()
        info_card.setObjectName("Card")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(18, 18, 18, 18)
        info_title = QLabel("解析结果")
        info_title.setObjectName("Title")
        info_layout.addWidget(info_title)
        self.single_info = QLabel("等待解析…")
        self.single_info.setWordWrap(True)
        self.single_info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info_layout.addWidget(self.single_info)
        info_layout.addStretch(1)
        content_row.addWidget(info_card, 3)

        # Progress
        self.single_loading = QProgressBar()
        self.single_loading.setRange(0, 0)
        self.single_loading.setVisible(False)
        self.single_loading.setTextVisible(False)

        self.single_progress = QProgressBar()
        self.single_progress.setRange(0, 100)
        self.single_progress.setVisible(False)

        layout.addLayout(row)
        layout.addLayout(content_row)

        # 图集缩略图：从封面卡片下方移到页面通栏，宽度随窗口，不被封面卡片挤窄
        thumb_card = QWidget()
        thumb_card.setObjectName("Card")
        thumb_layout = QVBoxLayout(thumb_card)
        thumb_layout.setContentsMargins(12, 12, 12, 12)
        thumb_layout.setSpacing(10)

        thumb_header = QLabel("缩略图")
        thumb_header.setObjectName("Label")
        thumb_layout.addWidget(thumb_header)

        self.thumbnail_scroll = QScrollArea()
        self.thumbnail_scroll.setWidgetResizable(True)
        self.thumbnail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.thumbnail_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 104px 缩略图 + 上下边距 + 水平滚动条，必须留足空间，避免底部被滚动条遮住。
        self.thumbnail_scroll.setMinimumHeight(180)
        self.thumbnail_scroll.setMaximumHeight(220)
        self.thumbnail_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.thumbnail_scroll.setVisible(False)

        self.thumbnails_container = QWidget()
        self.thumbnails_layout = QHBoxLayout(self.thumbnails_container)
        self.thumbnails_layout.setSpacing(10)
        # 底部边距加大，避免缩略图贴着滚动条下沿
        self.thumbnails_layout.setContentsMargins(8, 8, 8, 12)
        self.thumbnail_scroll.setWidget(self.thumbnails_container)

        thumb_layout.addWidget(self.thumbnail_scroll)
        layout.addWidget(thumb_card)

        layout.addWidget(self.single_loading)
        layout.addWidget(self.single_progress)
        layout.addStretch(1)

        self.single_parse_btn.clicked.connect(self._on_single_parse)
        self.single_clear_btn.clicked.connect(self._on_single_clear)
        self.single_download_btn.clicked.connect(self._on_single_download)
        self.single_open_dir_btn.clicked.connect(self._on_single_open_dir)
        self.single_copy_btn.clicked.connect(self._on_single_copy)
        return widget

    def _build_user_tab(self):
        widget = QWidget()
        widget.setObjectName("Card")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        header = QVBoxLayout()
        title = QLabel("主页 / 视频批量解析")
        title.setObjectName("Title")
        hint = QLabel("粘贴抖音用户主页或视频合集链接，批量解析后勾选下载")
        hint.setObjectName("Hint")
        header.addWidget(title)
        header.addWidget(hint)
        layout.addLayout(header)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("https://www.douyin.com/user/xxx 或视频合集链接")
        self.user_input.setMinimumHeight(42)
        self.user_max_pages = QSpinBox()
        self.user_max_pages.setRange(1, 50)
        self.user_max_pages.setValue(1)
        self.user_max_pages.setMinimumHeight(42)
        self.user_parse_btn = QPushButton("解析")
        self.user_parse_btn.setObjectName("Primary")
        self.user_parse_btn.setMinimumHeight(42)
        self.user_parse_btn.setCursor(Qt.PointingHandCursor)
        self.user_select_all_btn = QPushButton("全选")
        self.user_select_all_btn.setMinimumHeight(42)
        self.user_select_all_btn.setCursor(Qt.PointingHandCursor)
        self.user_clear_all_btn = QPushButton("全不选")
        self.user_clear_all_btn.setMinimumHeight(42)
        self.user_clear_all_btn.setCursor(Qt.PointingHandCursor)
        self.user_download_btn = QPushButton("下载勾选(默认目录)")
        self.user_download_btn.setObjectName("Accent")
        self.user_download_btn.setMinimumHeight(42)
        self.user_download_btn.setCursor(Qt.PointingHandCursor)
        self.user_download_btn.setEnabled(False)

        row.addWidget(self.user_input, 4)
        pages_label = QLabel("页数上限")
        pages_label.setObjectName("Label")
        row.addWidget(pages_label, 0)
        row.addWidget(self.user_max_pages, 0)
        row.addWidget(self.user_parse_btn, 1)
        row.addWidget(self.user_select_all_btn, 1)
        row.addWidget(self.user_clear_all_btn, 1)
        row.addWidget(self.user_download_btn, 1)

        # 第二行操作按钮：打开目录 / 清空记录 / 恢复记录
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self.user_open_dir_btn = QPushButton("打开文件夹")
        self.user_open_dir_btn.setMinimumHeight(42)
        self.user_open_dir_btn.setCursor(Qt.PointingHandCursor)
        self.user_clear_records_btn = QPushButton("清空记录")
        self.user_clear_records_btn.setMinimumHeight(42)
        self.user_clear_records_btn.setCursor(Qt.PointingHandCursor)
        self.user_restore_records_btn = QPushButton("恢复记录")
        self.user_restore_records_btn.setMinimumHeight(42)
        self.user_restore_records_btn.setCursor(Qt.PointingHandCursor)
        row2.addWidget(self.user_open_dir_btn, 0)
        row2.addWidget(self.user_clear_records_btn, 0)
        row2.addWidget(self.user_restore_records_btn, 0)
        row2.addStretch(1)

        self.user_table = self._build_table()
        self.user_loading = QProgressBar()
        self.user_loading.setRange(0, 0)
        self.user_loading.setVisible(False)
        self.user_loading.setTextVisible(False)
        self.user_progress = QProgressBar()
        self.user_progress.setRange(0, 100)
        self.user_progress.setVisible(False)

        layout.addLayout(row)
        layout.addLayout(row2)
        layout.addWidget(self.user_table)
        layout.addWidget(self.user_loading)
        layout.addWidget(self.user_progress)

        self.user_parse_btn.clicked.connect(self._on_user_parse)
        self.user_download_btn.clicked.connect(self._on_user_download)
        self.user_select_all_btn.clicked.connect(lambda: self._toggle_all(self.user_table, True))
        self.user_clear_all_btn.clicked.connect(lambda: self._toggle_all(self.user_table, False))
        self.user_open_dir_btn.clicked.connect(self._on_user_open_dir)
        self.user_clear_records_btn.clicked.connect(self._on_user_clear_records)
        self.user_restore_records_btn.clicked.connect(self._on_user_restore_records)
        return widget

    def _build_config_tab(self):
        widget = QWidget()
        widget.setObjectName("Card")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(18)

        header = QVBoxLayout()
        title = QLabel("登录态与存储设置")
        title.setObjectName("Title")
        hint = QLabel("扫码获取抖音登录 Cookie，并设置文件默认保存目录")
        hint.setObjectName("Hint")
        header.addWidget(title)
        header.addWidget(hint)
        layout.addLayout(header)

        # Cookie 区域：二维码卡片 + 操作侧栏
        cookie_row = QHBoxLayout()
        cookie_row.setSpacing(20)
        qr_card = QWidget()
        qr_card.setObjectName("Card")
        qr_layout = QVBoxLayout(qr_card)
        qr_layout.setContentsMargins(16, 16, 16, 16)
        qr_layout.setAlignment(Qt.AlignCenter)
        self.cookie_qr = QLabel("二维码预览")
        self.cookie_qr.setFixedSize(240, 240)
        self.cookie_qr.setAlignment(Qt.AlignCenter)
        self.cookie_qr.setStyleSheet(
            "background: #0f1115; border-radius: 10px; color: #7c869b; font-size: 14px;"
        )
        qr_layout.addWidget(self.cookie_qr)
        cookie_row.addWidget(qr_card)

        cookie_side = QVBoxLayout()
        cookie_side.setSpacing(12)
        self.cookie_status = QLabel("状态：未获取")
        self.cookie_status.setObjectName("Label")
        get_cookie_btn = QPushButton("获取Cookie")
        get_cookie_btn.setObjectName("Primary")
        get_cookie_btn.setMinimumHeight(42)
        get_cookie_btn.setCursor(Qt.PointingHandCursor)
        paste_tip = QLabel("点击后在弹窗中用抖音 App 扫码登录，Cookie 将自动保存")
        paste_tip.setObjectName("Hint")
        cookie_side.addWidget(self.cookie_status)
        cookie_side.addWidget(get_cookie_btn)
        cookie_side.addWidget(paste_tip)
        cookie_side.addStretch(1)
        cookie_row.addLayout(cookie_side, 1)
        layout.addLayout(cookie_row)

        # Cookie 文本框
        cookie_label = QLabel("Cookie（高级：可手动粘贴）")
        cookie_label.setObjectName("Label")
        layout.addWidget(cookie_label)
        self.cookie_editor = QPlainTextEdit()
        self.cookie_editor.setPlaceholderText("粘贴抖音 Cookie")
        self.cookie_editor.setPlainText(self.config.get("cookie", ""))
        self.cookie_editor.setMinimumHeight(90)
        layout.addWidget(self.cookie_editor)

        # 保存路径
        path_label = QLabel("保存路径")
        path_label.setObjectName("Label")
        layout.addWidget(path_label)
        path_row = QHBoxLayout()
        path_row.setSpacing(12)
        self.save_path_input = QLineEdit()
        self.save_path_input.setText(self.save_dir)
        browse_btn = QPushButton("选择目录")
        browse_btn.setMinimumHeight(42)
        browse_btn.setCursor(Qt.PointingHandCursor)
        save_btn = QPushButton("保存配置")
        save_btn.setObjectName("Primary")
        save_btn.setMinimumHeight(42)
        save_btn.setCursor(Qt.PointingHandCursor)
        path_row.addWidget(self.save_path_input, 1)
        path_row.addWidget(browse_btn, 0)
        path_row.addWidget(save_btn, 0)
        layout.addLayout(path_row)

        # 授权区域：常驻入口。试用用户中途想买，不用重启软件。
        license_label = QLabel("授权")
        license_label.setObjectName("Label")
        layout.addWidget(license_label)
        lic_row = QHBoxLayout()
        lic_row.setSpacing(12)
        self.license_status = QLabel("")
        self.license_status.setObjectName("Label")
        activate_btn = QPushButton("填入激活码")
        activate_btn.setMinimumHeight(42)
        activate_btn.setCursor(Qt.PointingHandCursor)
        buy_btn = QPushButton("购买激活")
        buy_btn.setObjectName("Primary")
        buy_btn.setMinimumHeight(42)
        buy_btn.setCursor(Qt.PointingHandCursor)
        lic_row.addWidget(self.license_status, 1)
        lic_row.addWidget(activate_btn, 0)
        lic_row.addWidget(buy_btn, 0)
        layout.addLayout(lic_row)
        self._refresh_license_status()
        layout.addWidget(self._build_update_section())

        layout.addStretch(1)

        if DISABLE_LOGIN:
            get_cookie_btn.setEnabled(False)
            self.cookie_qr.setText("精简版不支持自动登录")
            self.cookie_status.setText("状态：已禁用")
        else:
            get_cookie_btn.clicked.connect(self._on_get_cookie)
        browse_btn.clicked.connect(self._on_browse_dir)
        save_btn.clicked.connect(self._on_save_config)
        activate_btn.clicked.connect(self._on_activate)
        buy_btn.clicked.connect(lambda: webbrowser.open(BUY_URL))
        return widget

    # ---------------- 软件更新 ----------------

    def _build_update_section(self):
        """配置页底部的更新区：当前版本 + 检查/更新按钮 + 进度条。"""
        box = QVBoxLayout()
        box.setSpacing(10)

        title = QLabel("软件更新")
        title.setObjectName("Label")
        box.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(12)

        self.update_status = QLabel(f"当前版本 v{updater.APP_VERSION}")
        self.update_status.setObjectName("Label")

        self.update_btn = QPushButton("检查更新")
        self.update_btn.setMinimumHeight(42)
        self.update_btn.setCursor(Qt.PointingHandCursor)

        row.addWidget(self.update_status, 1)
        row.addWidget(self.update_btn, 0)
        box.addLayout(row)

        self.update_progress = QProgressBar()
        self.update_progress.setMinimum(0)
        self.update_progress.setMaximum(100)
        self.update_progress.setValue(0)
        self.update_progress.setTextVisible(True)
        self.update_progress.hide()
        box.addWidget(self.update_progress)

        self.update_btn.clicked.connect(self._on_check_update)
        # 有更新时按钮变主色，是这个区块唯一的视觉信号
        self._pending_update = None
        self._update_worker = None
        self._download_worker = None
        return self._wrap(box)

    def _wrap(self, layout):
        """把一段布局塞进一个空白 widget（addLayout 只接受 widget 时用它）。"""
        w = QWidget()
        w.setLayout(layout)
        return w

    def _on_check_update(self):
        """点按钮：有待装的更新就直接装，否则去问一次服务器。"""
        if self._pending_update:
            self._confirm_install(self._pending_update)
            return
        self.update_btn.setEnabled(False)
        self.update_status.setText("正在检查…")
        self._start_check(force=True)

    def _start_check(self, force=False):
        """启动后台检查。force 表示用户手动点的，跳过每日节流。"""
        if not force and not updater.should_check():
            return
        self._update_worker = UpdateCheckWorker(VARIANT, self)
        self._update_worker.result.connect(self._on_update_result)
        self._update_worker.start()
        updater.mark_checked()

    def _on_update_result(self, info):
        """检查回来。没更新就恢复原样，有更新就把按钮变醒目。"""
        if self.sender() is self._update_worker:
            self.update_btn.setEnabled(True)
        if not info:
            self._pending_update = None
            self.update_status.setText(
                f"当前版本 v{updater.APP_VERSION}（已是最新）" if self.sender() is self._update_worker
                else f"当前版本 v{updater.APP_VERSION}"
            )
            self.update_btn.setText("检查更新")
            self.update_btn.setObjectName("")
            self._restylize_button(self.update_btn)
            return

        ver = info.get("version", "")
        if updater.is_skipped(ver) and not info.get("force"):
            self.update_status.setText(f"当前版本 v{updater.APP_VERSION}（已跳过 v{ver}）")
            self.update_btn.setEnabled(True)
            return

        self._pending_update = info
        mb = int(info.get("size") or 0) / 1024 / 1024
        self.update_status.setText(f"发现新版本 v{ver}（{mb:.0f} MB）")
        self.update_btn.setText(f"更新到 v{ver}")
        self.update_btn.setObjectName("Primary")
        self._restylize_button(self.update_btn)
        self.update_btn.setEnabled(True)

    def _restylize_button(self, btn):
        """改了 objectName 之后必须重新套样式，否则新配色不生效。"""
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _confirm_install(self, info):
        """问一句再装。force 的更新不给「跳过」。"""
        ver = info.get("version", "")
        notes = (info.get("notes") or "").strip()
        mb = int(info.get("size") or 0) / 1024 / 1024
        text = (
            f"新版本 v{ver}（{mb:.0f} MB）\n\n"
            + (notes + "\n\n" if notes else "")
            + "更新会关闭本程序并打开安装程序，按提示点「是」即可。\n"
            "你的 Cookie、激活状态和已下载的视频都会保留。"
        )
        box = QMessageBox(self)
        box.setWindowTitle("软件更新")
        box.setText(text)
        ok_btn = box.addButton("立即更新", QMessageBox.AcceptRole)
        if not info.get("force"):
            box.addButton("以后再说", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not ok_btn:
            updater.skipped_version(ver)
            return
        self._start_download(info)

    def _start_download(self, info):
        self.update_btn.setEnabled(False)
        self.update_progress.setValue(0)
        self.update_progress.show()
        self.update_status.setText("正在下载更新包…")
        self._download_worker = UpdateDownloadWorker(info, self)
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.finished.connect(self._on_download_done)
        self._download_worker.start()

    def _on_download_progress(self, done, total):
        if total > 0:
            self.update_progress.setValue(min(100, int(done * 100 / total)))
            self.update_status.setText(
                f"正在下载… {done / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB"
            )
        else:
            self.update_status.setText(f"正在下载… {done / 1024 / 1024:.1f} MB")

    def _on_download_done(self, ok, res):
        self.update_progress.hide()
        if not ok:
            self.update_btn.setEnabled(True)
            self.update_status.setText(f"更新失败：{res}")
            QMessageBox.warning(self, "更新失败", f"{res}\n\n软件仍可正常使用，可稍后重试。")
            return
        self.update_status.setText("下载完成，正在打开安装程序…")
        if updater.launch_installer(res):
            # 立刻退出：安装器要替换本程序的 exe，占着不放会失败
            QApplication.exit(0)
        else:
            self.update_btn.setEnabled(True)
            self.update_status.setText("无法启动安装程序，请手动安装")
            QMessageBox.warning(
                self, "需要手动安装",
                f"安装包已下载到：\n{res}\n\n请双击它完成更新。"
            )

    def _refresh_license_status(self):
        """刷新配置页里的授权说明文字。"""
        label, expiry = activation.active_plan()
        if label:
            self.license_status.setText(
                f"已激活【{label}】，"
                + ("永久有效" if expiry == "终身" else f"有效期至 {expiry}")
            )
        else:
            left = activation.trial_left()
            self.license_status.setText(
                f"未激活 · 今日剩余免费额度 {max(left, 0)} / "
                f"{activation.TRIAL_DAILY_LIMIT} 次"
            )

    def _on_activate(self):
        """手动填入激活码。"""
        dlg = ActivationDialog()
        if dlg.exec() == QDialog.Accepted:
            self._refresh_trial_title()
            self._refresh_license_status()
            QMessageBox.information(self, "激活成功", "已激活，现在不限次数使用。")

    def _build_table(self):
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["选择", "封面", "类型", "文案", "视频ID", "时间"])
        table.setColumnWidth(0, 60)
        table.setColumnWidth(1, 200)
        table.setColumnWidth(2, 100)
        table.setColumnWidth(3, 320)
        table.setColumnWidth(4, 180)
        table.setColumnWidth(5, 180)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        return table

    def _on_single_parse(self):
        url = self.single_input.text().strip()
        if not url:
            return
        # 先扣额度再校验 Cookie：额度没了就别让人白跑一趟扫码登录
        if not self._take_trial_quota():
            return
        if not self.parser.cookie:
            QMessageBox.warning(
                self,
                "Cookie 未配置",
                "尚未获取抖音 Cookie，请先点击「获取Cookie」按钮扫码登录。\n"
                "登录成功后会自动保存，之后即可解析和下载。",
            )
            return
        self.single_parse_btn.setEnabled(False)
        self.single_clear_btn.setEnabled(False)
        self.single_download_btn.setEnabled(False)
        self.single_loading.setVisible(True)
        self.single_info.setText("解析中...")

        self.single_worker = ParseSingleWorker(self.parser, url)
        self.single_worker.result.connect(self._single_result)
        self.single_worker.error.connect(self._single_error)
        self.single_worker.finished.connect(self._single_parse_done)
        self.single_worker.start()

    def _on_single_clear(self):
        self.single_input.clear()
        self.single_cover.setText("封面预览")
        self.single_cover.setPixmap(QPixmap())
        self.single_info.setText("")
        self.single_progress.setVisible(False)
        self.single_download_btn.setEnabled(False)
        self.current_single_info = None
        self._clear_thumbnails()
        self.thumbnail_scroll.setVisible(False)
        self.single_copy_btn.setText("复制链接")
        self._set_copy_btn(False, None)

    def _clear_thumbnails(self):
        """停止缩略图下载线程并清空缩略图容器。"""
        if self.thumbnail_worker is not None:
            try:
                self.thumbnail_worker.loaded.disconnect()
                self.thumbnail_worker.error.disconnect()
            except Exception:
                pass
            if self.thumbnail_worker.isRunning():
                self.thumbnail_worker.requestInterruption()
                self.thumbnail_worker.quit()
                self.thumbnail_worker.wait(2000)
            self.thumbnail_worker = None
        layout = self.thumbnails_layout
        while layout.count():
            item = layout.takeAt(0)
            wgt = item.widget()
            if wgt is not None:
                wgt.deleteLater()
        self.thumbnail_scroll.setVisible(False)

    def _show_thumbnails(self, urls):
        """异步加载图集缩略图，逐张塞进横向滚动条。"""
        self._clear_thumbnails()
        if not urls:
            return
        self.thumbnail_scroll.setVisible(True)
        self.thumbnail_worker = ThumbnailWorker(urls)
        self.thumbnail_worker.loaded.connect(self._on_thumbnail_loaded)
        self.thumbnail_worker.error.connect(lambda _e: None)
        self.thumbnail_worker.start()

    def _on_thumbnail_loaded(self, idx, pixmap, url):
        label = ClickableLabel()
        label.setFixedSize(104, 104)
        label.setAlignment(Qt.AlignCenter)
        label.setPixmap(pixmap)
        label.setCursor(Qt.PointingHandCursor)
        label.setStyleSheet(
            "background:#121520; border:2px solid transparent; border-radius:8px;"
        )
        label.setToolTip("点击查看大图")
        label.clicked.connect(
            lambda: self._set_cover(self.single_cover, url, 520, 300)
        )
        self.thumbnails_layout.addWidget(label)

    def _on_single_open_dir(self):
        try:
            os.makedirs(self.save_dir, exist_ok=True)
            os.startfile(self.save_dir)
        except Exception as e:
            QMessageBox.warning(self, "打开文件夹失败", f"无法打开保存目录：\n{str(e)}")

    def _set_copy_btn(self, show: bool, url):
        """视频有直链时才显示「复制链接」按钮，并把地址挂在按钮上。"""
        self.single_copy_btn.setVisible(bool(show))
        self.single_copy_btn.setProperty("nwm_url", url)

    def _on_single_copy(self):
        url = (
            self.single_copy_btn.property("nwm_url")
            or self.single_download_btn.property("nwm_url")
        )
        if not url:
            QMessageBox.information(self, "复制链接", "当前没有可复制的无水印直链")
            return
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(url)
        self.single_copy_btn.setText("已复制 ✓")
        QTimer.singleShot(1500, lambda: self.single_copy_btn.setText("复制链接"))

    def _single_parse_done(self):
        self.single_loading.setVisible(False)
        self.single_parse_btn.setEnabled(True)
        self.single_clear_btn.setEnabled(True)

    def _single_result(self, info: dict):
        content_type = info.get("content_type", "video")
        ctype = "图集" if content_type == "image" else "视频"

        # --- 基础信息表 ---
        rows = [
            ("ID", info.get("aweme_id") or "-", True),
            ("类型", ctype, False),
            ("时间", format_time(info.get("create_time")) or "-", False),
            ("作者", info.get("author_nickname") or "-", False),
        ]
        dur = fmt_duration(info.get("duration")) if content_type == "video" else None
        if dur:
            rows.append(("时长", dur, False))
        html = _kv_table(rows)

        # --- 文案（选题最关心的内容）---
        desc = info.get("desc") or "-"
        html += (
            f"<div style='margin-top:14px; color:#7c869b; font-size:12px;'>文案</div>"
            f"<div style='margin-top:5px; color:#e6e6e6; background:#1b2030; "
            f"border-radius:8px; padding:10px 12px;'>{_esc(desc)}</div>"
        )

        # --- 互动数据（点赞/评论/分享/收藏）---
        stats = [
            ("点赞", fmt_count(info.get("digg_count"))),
            ("评论", fmt_count(info.get("comment_count"))),
            ("分享", fmt_count(info.get("share_count"))),
            ("收藏", fmt_count(info.get("collect_count"))),
        ]
        if any(v != "-" for _, v in stats):
            html += (
                f"<div style='margin-top:14px; color:#7c869b; font-size:12px;'>互动数据</div>"
                f"<div style='margin-top:6px;'>{_stat_tiles(stats)}</div>"
            )

        if content_type == "video":
            qualities = info.get("qualities", [])
            nwm = info.get("nwm_url")
            q_text = ""
            if qualities:
                q_text = "，".join([q.get("quality_label", q.get("ratio", "未知")) for q in qualities[:4]])
            html += (
                f"<div style='margin-top:14px;'><span style='color:#7c869b;'>无水印</span> "
                f"<span style='color:#22d3ee;'>✓ 已就绪</span></div>"
            )
            if q_text:
                html += (
                    f"<div style='margin-top:6px; color:#7c869b; font-size:12px;'>清晰度</div>"
                    f"<div style='margin-top:2px; color:#e6e6e6;'>{_esc(q_text)}</div>"
                )
            if nwm:
                html += (
                    f"<div style='margin-top:6px; color:#7c869b; font-size:12px;'>"
                    f"无水印直链（可点右侧「复制链接」）</div>"
                    f"<div style='margin-top:2px; color:#9fb3c8; "
                    f"font-family:Consolas,\"Courier New\",monospace; font-size:12px; "
                    f"background:#1b2030; border-radius:8px; padding:8px 10px;'>{_esc(nwm)}</div>"
                )
            self.single_download_btn.setEnabled(bool(nwm or qualities))
            self.single_download_btn.setProperty("nwm_url", nwm)
            self.single_download_btn.setProperty("qualities", qualities)
            self._set_copy_btn(bool(nwm), nwm)
        elif content_type == "image":
            image_count = info.get("image_count", 0)
            image_data = info.get("image_data", {}) or {}
            image_urls = image_data.get("image_urls", []) if image_data else []
            html += (
                f"<div style='margin-top:14px;'><span style='color:#7c869b;'>图片</span> "
                f"<span style='color:#22d3ee;'>✓ 共 {image_count} 张</span></div>"
            )
            self.single_download_btn.setEnabled(bool(image_urls))
            self.single_download_btn.setProperty("image_data", image_data)
            self._set_copy_btn(False, None)
            if image_urls:
                self._show_thumbnails(image_urls)

        self.single_info.setText(html)
        self.single_download_btn.setProperty("content_type", content_type)
        self.single_download_btn.setProperty("desc", info.get("desc"))
        self.single_download_btn.setProperty("aweme_id", info.get("aweme_id"))
        cover_url = info.get("cover_url")
        if cover_url:
            self._set_cover(self.single_cover, cover_url, 520, 300)
        self._fade_in(self.single_info)

    def _single_error(self, msg: str):
        self.single_info.setText(f"<span style='color:#ef4444;'>{_esc(msg)}</span>")

    def _on_single_download(self):
        content_type = self.single_download_btn.property("content_type") or "video"
        
        if content_type == "video":
            # Video download
            qualities = self.single_download_btn.property("qualities") or []
            url = self.single_download_btn.property("nwm_url")
            
            # Show quality selection dialog if multiple qualities available
            selected_quality = None
            if qualities and len(qualities) > 1:
                dialog = QualitySelectionDialog(qualities, self)
                if dialog.exec() != QDialog.Accepted:
                    return
                selected_quality = dialog.get_selected_quality()
                if selected_quality:
                    url = selected_quality.get("url")
            elif not url and qualities:
                # Fallback to first quality if no default URL
                url = qualities[0].get("url")
            
            if not url:
                QMessageBox.warning(self, "错误", "未找到可用的视频地址")
                return
            
            os.makedirs(self.save_dir, exist_ok=True)
            desc = self.single_download_btn.property("desc") or ""
            aweme_id = self.single_download_btn.property("aweme_id") or "douyin"
            
            # Add quality suffix to filename if selected
            quality_suffix = ""
            if selected_quality:
                ratio = selected_quality.get("ratio", "")
                if ratio:
                    quality_suffix = f"_{ratio}"
            
            name = safe_filename(desc, aweme_id) + quality_suffix + ".mp4"
            path = os.path.join(self.save_dir, name)

            self.single_progress.setVisible(True)
            self.single_progress.setValue(0)

            def _cb(p):
                self.single_progress.setValue(p)

            ok = download_file(url, path, progress_cb=_cb)
            QMessageBox.information(self, "下载", "完成" if ok else "失败")
            self.single_progress.setVisible(False)
        
        elif content_type == "image":
            # Album download
            image_data = self.single_download_btn.property("image_data") or {}
            image_urls = image_data.get("image_urls", [])
            
            if not image_urls:
                QMessageBox.warning(self, "错误", "未找到可用的图片地址")
                return
            
            os.makedirs(self.save_dir, exist_ok=True)
            desc = self.single_download_btn.property("desc") or ""
            aweme_id = self.single_download_btn.property("aweme_id") or "douyin"
            
            # Create folder for album
            folder_name = safe_filename(desc, aweme_id)
            album_dir = os.path.join(self.save_dir, folder_name)
            os.makedirs(album_dir, exist_ok=True)
            
            self.single_progress.setVisible(True)
            self.single_progress.setRange(0, len(image_urls))
            self.single_progress.setValue(0)
            
            # Check if these are live images
            is_live = image_data.get("is_live", False)
            
            success = 0
            for idx, img_url in enumerate(image_urls, start=1):
                try:
                    # Determine file extension first
                    url_lower = img_url.lower()
                    if is_live:
                        # Live images are videos, save as mp4
                        ext = ".mp4"
                    elif ("gif" in url_lower or url_lower.endswith(".gif") or ".gif?" in url_lower):
                        ext = ".gif"
                    elif ("webp" in url_lower or url_lower.endswith(".webp") or ".webp?" in url_lower):
                        ext = ".webp"
                    elif ("png" in url_lower or url_lower.endswith(".png") or ".png?" in url_lower):
                        ext = ".png"
                    else:
                        ext = ".jpg"  # Default to jpg
                    
                    img_name = f"{idx:03d}{ext}"
                    img_path = os.path.join(album_dir, img_name)
                    
                    # For live images (MP4 videos), use download_file function for better support
                    if is_live:
                        def _cb(p):
                            self.single_progress.setValue(int((idx - 1) * 100 / len(image_urls) + p / len(image_urls)))
                        ok = download_file(img_url, img_path, progress_cb=_cb)
                        if ok:
                            success += 1
                    else:
                        # For static images, use simple download
                        resp = requests.get(img_url, timeout=30, stream=True, headers={"User-Agent": self.parser.user_agent})
                        if resp.status_code == 200:
                            with open(img_path, "wb") as f:
                                for chunk in resp.iter_content(chunk_size=8192):
                                    if chunk:
                                        f.write(chunk)
                            success += 1
                except Exception:
                    pass
                
                self.single_progress.setValue(idx)
            
            QMessageBox.information(self, "下载", f"完成 {success}/{len(image_urls)}")
            self.single_progress.setVisible(False)

    def _on_user_parse(self):
        url = self.user_input.text().strip()
        if not url:
            return
        # 主页批量也算一次：拉一次列表就是一次完整解析
        if not self._take_trial_quota():
            return
        if not self.parser.cookie:
            QMessageBox.warning(
                self,
                "Cookie 未配置",
                "尚未获取抖音 Cookie，请先点击「获取Cookie」按钮扫码登录。\n"
                "登录成功后会自动保存，之后即可解析和下载。",
            )
            return
        self.user_parse_btn.setEnabled(False)
        self.user_download_btn.setEnabled(False)
        self.user_table.setRowCount(0)
        self.user_loading.setVisible(True)

        self.user_worker = ParseUserWorker(
            self.parser, url, self.user_max_pages.value()
        )
        self.user_worker.result.connect(self._user_list_result)
        self.user_worker.error.connect(self._user_error)
        self.user_worker.finished.connect(self._user_parse_done)
        self.user_worker.start()

    def _user_parse_done(self):
        self.user_parse_btn.setEnabled(True)

    def _user_list_result(self, urls: list, user_home: str):
        self.user_table.setRowCount(0)
        self.user_download_btn.setEnabled(True)

        self.list_worker = ParseListWorker(self.parser, urls)
        self.list_worker.result.connect(lambda info: self._append_row(self.user_table, info))
        self.list_worker.error.connect(self._user_error)
        self.list_worker.done.connect(lambda: self.user_loading.setVisible(False))
        self.list_worker.done.connect(self._save_user_records)
        self.user_loading.setVisible(True)
        self.list_worker.start()

    def _user_error(self, msg: str):
        self.user_loading.setVisible(False)
        QMessageBox.warning(self, "解析失败", msg)

    def _on_user_download(self):
        video_infos = self._get_checked_video_infos(self.user_table)
        if not video_infos:
            QMessageBox.warning(self, "提示", "请先勾选要下载的内容")
            return
        
        # Filter videos only for quality selection
        video_only_infos = [info for info in video_infos if info.get("content_type", "video") == "video"]
        selected_ratio = None
        
        # Show quality selection dialog only if there are videos with multiple ratios
        if video_only_infos:
            available_ratios = self._get_all_available_ratios(video_only_infos)
            
            if available_ratios and len(available_ratios) > 1:
                # Create a simplified quality list for selection
                quality_list = []
                for ratio in available_ratios:
                    # Find a representative quality for this ratio
                    for info in video_only_infos:
                        qualities = info.get("qualities", [])
                        for q in qualities:
                            if q.get("ratio") == ratio:
                                quality_list.append(q)
                                break
                        if any(q.get("ratio") == ratio for q in qualities):
                            break
                
                if quality_list:
                    dialog = QualitySelectionDialog(quality_list, self)
                    dialog.setWindowTitle("选择批量下载的视频质量")
                    if dialog.exec() == QDialog.Accepted:
                        selected_quality = dialog.get_selected_quality()
                        if selected_quality:
                            selected_ratio = selected_quality.get("ratio")
                    else:
                        return
        
        self.user_progress.setVisible(True)
        self.user_progress.setValue(0)
        self.user_download_btn.setEnabled(False)

        self.download_worker = DownloadWorker(self.parser, video_infos, self.save_dir, selected_ratio)
        self.download_worker.progress.connect(self.user_progress.setValue)
        self.download_worker.status.connect(lambda _: None)
        self.download_worker.done.connect(self._download_done)
        self.download_worker.start()

    def _download_done(self, success: int, total: int):
        self.user_progress.setVisible(False)
        self.user_download_btn.setEnabled(True)
        QMessageBox.information(self, "下载完成", f"成功 {success} / {total}")

    # ---------------- 批量解析记录（清空 / 恢复） ----------------

    def _user_records_path(self):
        """主页批量解析的记录文件路径（APPDATA/DouyinParser/user_records.json）。"""
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, "DouyinParser")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "user_records.json")

    def _user_records_backup_path(self):
        return self._user_records_path() + ".bak"

    @staticmethod
    def _serialize_info(info: dict) -> dict:
        """把 info 里需要持久化的字段挑出来，保证能 JSON 序列化。"""
        keys = (
            "content_type", "desc", "aweme_id", "cover_url", "nwm_url",
            "create_time", "image_count", "image_data", "qualities",
            "digg_count", "comment_count", "share_count", "collect_count",
        )
        out = {}
        for k in keys:
            v = info.get(k)
            if v is not None:
                out[k] = v
        return out

    def _save_user_records(self):
        """把当前主页批量解析表格里的记录落盘。"""
        infos = []
        for row in range(self.user_table.rowCount()):
            item = self.user_table.item(row, 0)
            if item:
                info = item.data(Qt.UserRole)
                if isinstance(info, dict):
                    infos.append(self._serialize_info(info))
        if not infos:
            return
        try:
            with open(self._user_records_path(), "w", encoding="utf-8") as f:
                json.dump(infos, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[warn] 保存记录失败：{e}")

    def _load_user_records(self, src: str = None):
        """从指定文件恢复记录到主页批量解析表格。"""
        path = src or self._user_records_path()
        if not os.path.exists(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                infos = json.load(f)
        except Exception as e:
            print(f"[warn] 读取记录失败：{e}")
            return 0
        if not isinstance(infos, list):
            return 0
        self.user_table.setRowCount(0)
        for info in infos:
            self._append_row(self.user_table, info)
        if infos:
            self.user_download_btn.setEnabled(True)
        return len(infos)

    def _on_user_clear_records(self):
        """清空记录：把当前表格内容备份到 .bak，然后清空表格。"""
        path = self._user_records_path()
        backup = self._user_records_backup_path()
        # 先保存当前表格（确保内存数据写盘），再移到备份位置
        self._save_user_records()
        if os.path.exists(path):
            try:
                shutil.move(path, backup)
            except Exception as e:
                print(f"[warn] 备份记录失败：{e}")
        self.user_table.setRowCount(0)
        self.user_download_btn.setEnabled(False)
        QMessageBox.information(self, "清空记录", "当前记录已清空。如需恢复，可点击「恢复记录」。")

    def _on_user_restore_records(self):
        """恢复记录：优先恢复当前 records.json；没有则把 .bak 复制回来恢复。"""
        path = self._user_records_path()
        backup = self._user_records_backup_path()
        if os.path.exists(path):
            n = self._load_user_records(path)
            msg = f"已恢复 {n} 条记录。" if n else "当前没有可恢复的记录。"
        elif os.path.exists(backup):
            try:
                shutil.copyfile(backup, path)
            except Exception as e:
                QMessageBox.warning(self, "恢复失败", f"无法复制备份文件：{e}")
                return
            n = self._load_user_records(path)
            msg = f"已从备份恢复 {n} 条记录。"
        else:
            msg = "没有找到记录或备份文件，无法恢复。"
        QMessageBox.information(self, "恢复记录", msg)

    def _on_user_open_dir(self):
        """打开主页批量解析的保存目录。"""
        path = self.save_dir
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception:
                pass
        try:
            os.startfile(path)
        except Exception as e:
            QMessageBox.warning(self, "打开文件夹失败", f"无法打开保存目录：\n{str(e)}")

    def _toggle_all(self, table: QTableWidget, checked: bool):
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item:
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def _get_checked_video_infos(self, table: QTableWidget) -> list[dict]:
        """Get checked video info dicts instead of just URLs"""
        infos = []
        for row in range(table.rowCount()):
            item = table.item(row, 0)
            if item and item.checkState() == Qt.Checked:
                info = item.data(Qt.UserRole)
                if info and isinstance(info, dict):
                    infos.append(info)
        return infos
    
    def _get_all_available_ratios(self, video_infos: list[dict]) -> set[str]:
        """Extract all available ratios from video infos"""
        ratios = set()
        for info in video_infos:
            qualities = info.get("qualities", [])
            for q in qualities:
                ratio = q.get("ratio")
                if ratio:
                    ratios.add(ratio)
        return sorted(ratios, key=lambda x: {"1080p": 5, "720p": 4, "540p": 3, "480p": 2, "360p": 1}.get(x, 0), reverse=True)

    def _append_row(self, table: QTableWidget, info: dict):
        row = table.rowCount()
        table.insertRow(row)
        table.setRowHeight(row, 110)

        check_item = QTableWidgetItem()
        check_item.setCheckState(Qt.Unchecked)
        # Store full info dict instead of just URL
        check_item.setData(Qt.UserRole, info)
        table.setItem(row, 0, check_item)

        cover_label = QLabel()
        cover_label.setFixedSize(180, 100)
        cover_label.setAlignment(Qt.AlignCenter)
        cover_label.setStyleSheet("background: #1b1f2a; border-radius: 6px;")
        if info.get("cover_url"):
            self._set_cover(cover_label, info["cover_url"], 180, 100)
        table.setCellWidget(row, 1, cover_label)

        # Content type column
        content_type = info.get("content_type", "video")
        type_text = "视频"
        if content_type == "image":
            image_count = info.get("image_count", 0)
            type_text = f"图集({image_count}张)"
        
        type_item = QTableWidgetItem(type_text)
        if content_type == "image":
            # Green background for albums
            type_item.setBackground(Qt.GlobalColor.darkGreen)
            type_item.setForeground(Qt.GlobalColor.white)
        table.setItem(row, 2, type_item)

        table.setItem(row, 3, QTableWidgetItem(info.get("desc") or ""))
        table.setItem(row, 4, QTableWidgetItem(info.get("aweme_id") or ""))
        table.setItem(row, 5, QTableWidgetItem(format_time(info.get("create_time"))))

    def _set_cover(self, label: QLabel, url: str, w: int, h: int):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                pix = QPixmap()
                if pix.loadFromData(resp.content):
                    label.setPixmap(pix.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        except Exception:
            pass

    def _on_browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存目录", self.save_dir)
        if path:
            self.save_path_input.setText(path)

    def _on_save_config(self):
        cookie = self.cookie_editor.toPlainText().strip()
        save_dir = self.save_path_input.text().strip() or DEFAULT_SAVE_DIR
        save_config(cookie, save_dir)
        self.parser.set_cookie(cookie)
        self.save_dir = save_dir
        QMessageBox.information(self, "保存", "配置已保存")

    def _on_get_cookie(self):
        if DISABLE_LOGIN:
            QMessageBox.information(self, "提示", "精简版不支持自动获取Cookie")
            return
        ok, detail = _browser_available()
        if not ok:
            # 两种情况必须分开提示，否则完整版出问题时会被误报成「精简版」
            browser_dir = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or ""
            if getattr(sys, "frozen", False) and os.path.isdir(browser_dir):
                QMessageBox.warning(
                    self, "完整版异常",
                    "完整版内置了浏览器内核，但没能定位到 chrome.exe。\n\n"
                    "多半是安装包解压不完整，或被杀毒软件隔离了。\n"
                    "请确认安装包里有这个目录：\n"
                    "  _internal\\playwright-browsers\\chromium-*\n"
                    "并重新解压/下载完整版。\n\n"
                    "急着用的话，也可以先按下面方式手动填 Cookie：\n"
                    "1. 浏览器打开 douyin.com 并登录\n"
                    "2. F12 → 应用(Application) → Cookie → https://www.douyin.com\n"
                    "3. 复制整条 cookie 值，粘贴到下方输入框 → 「保存配置」\n\n"
                    f"（技术信息：{detail}）"
                )
                return
            QMessageBox.warning(
                self, "没找到可用浏览器",
                "扫码登录需要调用本机的 Edge 或 Chrome，但都没检测到。\n\n"
                "最省事的解决办法：装一个 Edge\n"
                "  https://www.microsoft.com/edge\n"
                "（Windows 10/11 正常是自带的，若被卸载过才会缺）\n"
                "装完重启本软件即可扫码登录。\n\n"
                "不想装浏览器，也可以手动填 Cookie（只需一次）：\n"
                "1. 用任意浏览器打开 douyin.com 并登录\n"
                "2. F12 → 应用(Application) → Cookie → https://www.douyin.com\n"
                "3. 复制整条 cookie 值，粘贴到下方输入框 → 「保存配置」\n\n"
                f"（技术信息：{detail}）"
            )
            return
        self.cookie_status.setText("状态：获取中...")
        self.cookie_qr.clear()
        self.cookie_qr.setText("启动浏览器...")
        self.cookie_worker = CookieWorker()
        self.cookie_worker.qr.connect(self._on_cookie_qr)
        self.cookie_worker.status.connect(self._on_cookie_status)
        self.cookie_worker.done.connect(self._on_cookie_done)
        self.cookie_worker.error.connect(self._on_cookie_error)
        self.cookie_worker.start()

    def _on_cookie_qr(self, img_bytes: bytes):
        pix = QPixmap()
        if pix.loadFromData(img_bytes):
            self.cookie_qr.setPixmap(pix.scaled(260, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _on_cookie_status(self, text: str):
        self.cookie_status.setText(f"状态：{text}")
        if not self.cookie_qr.pixmap():
            self.cookie_qr.setText(text)

    def _on_cookie_done(self, cookie: str):
        self.cookie_status.setText("状态：获取成功")
        self.cookie_editor.setPlainText(cookie)
        self.parser.set_cookie(cookie)
        save_dir = self.save_path_input.text().strip() or DEFAULT_SAVE_DIR
        save_config(cookie, save_dir)
        QMessageBox.information(self, "Cookie", "已保存到文件")

    def _on_cookie_error(self, msg: str):
        self.cookie_status.setText("状态：失败")
        QMessageBox.warning(self, "Cookie", msg)


DIALOG_STYLE = """
QWidget { background: #0f1115; color: #e6e6e6; font-size: 14px;
    font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif; }
QLabel#Title { font-size: 19px; font-weight: bold; color: #f5f7fa; }
QLabel#Hint { font-size: 12px; color: #7c869b; }
QLabel#Label { font-size: 12px; color: #7c869b; }
QLineEdit { background: #1b1f2a; border: 1px solid #2b3142; padding: 10px 13px;
    border-radius: 9px; color: #e6e6e6; }
QLineEdit:focus { border: 1px solid #3b82f6; }
QPushButton { background: #2b3142; border: none; padding: 10px 16px;
    border-radius: 9px; color: #d6dbe6; }
QPushButton:hover { background: #343c52; }
QPushButton#Primary { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 #3b82f6, stop:1 #2563eb); color: #ffffff; font-weight: bold; }
QLabel#Plan { font-size: 12px; color: #9aa5bd; background: #151a24;
    border: 1px solid #232a38; border-radius: 9px; padding: 10px 12px; }
QLabel#Warn { font-size: 12px; color: #f0a35e; }
"""


def _plan_menu_text() -> str:
    """四档套餐说明，供激活窗口展示。"""
    parts = []
    for key in ("M", "H", "Y", "L"):
        name, days, price = activation.PLANS[key]
        dur = "永久有效" if days is None else f"{days} 天"
        parts.append(f"{name} {price} / {dur}")
    return "  ·  ".join(parts)


class ActivationDialog(QDialog):
    """首次启动的激活窗口：展示机器码、套餐价目，收取并校验激活码。"""

    def __init__(self, parent=None, expired_msg: str = ""):
        super().__init__(parent)
        self.setWindowTitle("软件激活 · 授权已到期" if expired_msg else "软件激活")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setStyleSheet(DIALOG_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("授权已到期，请续费" if expired_msg else "需要激活才能使用")
        title.setObjectName("Title")
        layout.addWidget(title)

        if expired_msg:
            warn = QLabel(expired_msg)
            warn.setObjectName("Warn")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        hint = QLabel("把下方【本机机器码】发给作者，拿到激活码后填入并点击「激活」。")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        plan = QLabel(_plan_menu_text())
        plan.setObjectName("Plan")
        plan.setWordWrap(True)
        layout.addWidget(plan)

        mid_label = QLabel("本机机器码")
        mid_label.setObjectName("Label")
        layout.addWidget(mid_label)

        self.machine_id = activation.get_machine_id()
        mid_row = QHBoxLayout()
        mid_row.setSpacing(10)
        self.mid_edit = QLineEdit(self.machine_id)
        self.mid_edit.setReadOnly(True)
        self.mid_edit.setMinimumHeight(42)
        copy_btn = QPushButton("复制")
        copy_btn.setMinimumHeight(42)
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.clicked.connect(self._copy_mid)
        mid_row.addWidget(self.mid_edit, 4)
        mid_row.addWidget(copy_btn, 1)
        layout.addLayout(mid_row)

        code_label = QLabel("激活码")
        code_label.setObjectName("Label")
        layout.addWidget(code_label)

        self.code_edit = QLineEdit()
        self.code_edit.setPlaceholderText("XXXX-XXXX-XXXX-XXXX-XXX")
        self.code_edit.setMinimumHeight(42)
        layout.addWidget(self.code_edit)

        buttons = QDialogButtonBox()
        ok_btn = buttons.addButton("激活", QDialogButtonBox.AcceptRole)
        ok_btn.setObjectName("Primary")
        exit_btn = buttons.addButton("退出", QDialogButtonBox.RejectRole)
        ok_btn.setMinimumHeight(42)
        exit_btn.setMinimumHeight(42)
        buttons.accepted.connect(self._try_activate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _copy_mid(self):
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self.machine_id)

    def _try_activate(self):
        code = self.code_edit.text().strip()
        if not code:
            QMessageBox.warning(self, "激活", "请先填入激活码")
            return
        ok, label, msg = activation.verify_detail(self.machine_id, code)
        if not ok:
            QMessageBox.warning(
                self, "激活失败",
                f"{msg}\n\n请确认：\n"
                "1. 激活码与本机机器码匹配（换机器需重新获取）\n"
                "2. 复制完整（去掉横线共 19 位），未漏字符"
            )
            return
        if activation.save_license(code):
            expiry = activation.expiry_of(self.machine_id, code)
            QMessageBox.information(
                self, "激活成功",
                f"已激活【{label}】\n有效期至：{expiry}\n\n感谢使用！"
            )
            self.accept()
        else:
            QMessageBox.warning(self, "激活失败", "无法写入激活文件，请检查目录权限。")


def main():
    app = QApplication([])
    # 未激活且今日免费额度已用尽 → 才拦下来弹激活窗口。
    # 之前是「未激活一律拦」，买家装好 58MB 却连软件长什么样都看不到；
    # 现在改成先让人用 3 次，确认真能解析再决定付不付钱。
    if activation.trial_left() == 0:
        expired_msg = ""
        saved = activation.read_saved_code()
        if saved:
            ok, _label, msg = activation.verify_detail(activation.get_machine_id(), saved)
            if not ok:
                expired_msg = msg
        dlg = ActivationDialog(expired_msg=expired_msg)
        if dlg.exec() != QDialog.Accepted:
            return 0
    window = MainWindow()
    window.show()
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())

