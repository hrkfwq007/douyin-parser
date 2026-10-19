"""
Douyin Video Downloader - Qt6 GUI Application (Slim Version)

Slim = 不把 719MB 的 Chromium 打进安装包，改用系统已有的 Edge / Chrome。
功能与完整版完全一致（扫码登录、Cookie 获取都在），只是体积从 944MB 降到 223MB。

早期这里靠 DISABLE_LOGIN 把登录功能整个关掉，导致精简版啥也解析不了；
现在改成自动借用系统浏览器，阉割的理由不存在了。
"""
import os
import sys

# 明确不要再关掉登录：精简版不是残废版
os.environ["DISABLE_LOGIN"] = "0"

# 告诉 qt_app 自动更新时该问哪一份安装包（站点 version.json 里的 key）
os.environ["DP_VARIANT"] = "slim"

from qt_app import main


if __name__ == "__main__":
    main()
