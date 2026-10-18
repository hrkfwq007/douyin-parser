#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把商城首页同步成「可外发版」落地页。

背景：站点的首页是 store/static/index.html，里面用的是相对链接
（/buy?plan=M）。但我们要把同一份页面投放到站外渠道（GitHub Pages、
面包多商品详情、贴吧/知乎的回答里当图床底页等），那些地方没有
我们的域名，相对链接会 404。

所以这里做一次单向转换：
    store/static/index.html  （相对链接，站内用）
        ->  landing/index.html        （绝对链接，站外用）

单向，意味着 store/static/index.html 是唯一真源。以后改页面只改它，
然后跑一次本脚本；不要再手改 landing/index.html，否则两边又走偏了
（之前就偏过一次：站外版漏了「订单查询」入口）。
"""

import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "store", "static", "index.html")
DST = os.path.join(BASE, "landing", "index.html")

# 改成你自己的线上域名（结尾不要带斜杠）
SITE = "https://douyin-parser-42948.app.workbuddy.host"


def main():
    if not os.path.isfile(SRC):
        print(f"[x] 找不到源文件：{SRC}")
        return 1

    with open(SRC, encoding="utf-8") as f:
        html = f.read()

    # 站内相对链接 -> 站外绝对链接。只动以 / 开头的 href，
    # 免得把外链和锚点（#features）一起改坏。
    n = 0

    def _abs(m):
        nonlocal n
        n += 1
        return f'href="{SITE}{m.group(1)}"'

    html = re.sub(r'href="(/[^"]*)"', _abs, html)

    os.makedirs(os.path.dirname(DST), exist_ok=True)
    with open(DST, "w", encoding="utf-8", newline="") as f:
        f.write(html)

    print(f"[ok] 已生成站外落地页：{DST}")
    print(f"     源：{SRC}")
    print(f"     改写了 {n} 处链接 -> {SITE}")

    if "/query" not in html or f'{SITE}/query' not in html:
        print("[warn] 没找到订单查询入口，检查一下导航栏里 /query 这个链接还在不在")

    return 0


if __name__ == "__main__":
    sys.exit(main())
