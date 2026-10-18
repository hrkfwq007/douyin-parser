#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 推广/成稿/*.md 编译成一个本地「一键发布台」HTML。

为什么需要这个
--------------
知乎 / 小红书 / CSDN / B站 都没有面向个人创作者的官方发文 API：

  · 知乎   开放平台没有任何写入接口（全量审计 54 个文档条目，
           4 个 POST 接口都与发布无关；openapi/publish 内测需申请）
  · 小红书 笔记发布接口只对企业主体开放，需营业执照 + 企业号 + 单独申请权限
  · CSDN   没有正式发布 API，第三方都在逆向 bizapi 内部接口 + Cookie 签名，
           违反 CSDN《用户协议》5.3 条
  · B站    有官方投稿 API，但需开发者资质 + ARC_BASE 权限 + 与产运沟通

用 Cookie 走逆向接口自动发文，正是各平台用户协议明令禁止的行为（
知乎 8.1 款：禁止使用自动化工具访问），被风控识别 = 限流 / 封号 / 下架。
这个项目在四个账号上的收入全部依赖它们，不值得冒这个险。

退一步能做的：把「打开 md → 选中 → 复制 → 切窗口 → 粘贴」
压缩成「点一下复制 → 点一下打开创作页」。最后那下「粘贴 + 发布」由人来做，
全程不触碰任何平台限制，也不向任何服务器发送数据。

用法
----
    python 推广/build_publish_console.py

成稿内容改了之后重跑一次就行。产物是自包含的单个 HTML，双击即可打开。
"""

import json
import os
import re
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DRAFTS = os.path.join(BASE, "成稿")
OUT = os.path.join(BASE, "发布台.html")

CREATOR_URLS = {
    "知乎": "https://www.zhihu.com/",
    "CSDN": "https://mp.csdn.net/mp_blog/creation/editor",
    "小红书": "https://creator.xiaohongshu.com/publish/publish",
    "B站": "https://member.bilibili.com/platform/upload-video/video/frame",
}

PLATFORM_COLORS = {
    "知乎": "#0084ff",
    "CSDN": "#fc5531",
    "小红书": "#ff2442",
    "B站": "#fb7299",
}

# 每个条目的元数据手写，正文从 md 里按标记截取。
# start/end 是成稿文件里的标记，改了成稿结构就要同步改这里。
ITEMS = [
    # ---------------- 第 2 周 ----------------
    dict(id="zhihu-a", platform="知乎", week=2,
         title="怎么把抖音的视频下载到电脑上？",
         target="先搜索这个问题，挑关注人数最多的那个进去回答。链接放文末。",
         src="知乎·三篇回答.md", start="### 正文", nth=0, end="\n---"),
    dict(id="zhihu-b", platform="知乎", week=2,
         title="抖音视频怎么保存无水印的？",
         target="先搜索这个问题，挑关注人数最多的那个进去回答。链接放文末。",
         src="知乎·三篇回答.md", start="### 正文", nth=1, end="\n---"),
    dict(id="zhihu-c", platform="知乎", week=2,
         title="做自媒体怎么拆解对标账号？",
         target="先搜索这个问题，挑关注人数最多的那个进去回答。链接放文末。",
         src="知乎·三篇回答.md", start="### 正文", nth=2, end="\n---"),
    dict(id="csdn-1", platform="CSDN", week=2,
         title="抖音分享链接解析：从短链到无水印直链的完整流程",
         target="发布页里标签填：Python、Playwright、逆向、Qt；分类选「Python」或「爬虫」",
         src="CSDN·技术长文.md", start="## 正文", nth=0, end="## 发完之后"),
    # ---------------- 第 3 周 ----------------
    dict(id="xhs-a", platform="小红书", week=3,
         title="剪辑党的素材库，我终于理清楚了",
         target="链接放主页简介，不要出现在这段正文里",
         src="小红书·三篇笔记.md", start="**正文**：", nth=0, end="**评论区置顶**",
         fence=True, extra="工具在主页简介里 👆", extra_label="评论区置顶（单独复制）"),
    dict(id="xhs-b", platform="小红书", week=3,
         title="拆解对标账号，我的素材归档流程",
         target="链接放主页简介，不要出现在这段正文里",
         src="小红书·三篇笔记.md", start="**正文**：", nth=1, end="**评论区置顶**",
         fence=True, extra="工具在主页简介里 👆", extra_label="评论区置顶（单独复制）"),
    dict(id="xhs-c", platform="小红书", week=3,
         title="自己发的内容，一定要留一份本地备份",
         target="链接放主页简介，不要出现在这段正文里",
         src="小红书·三篇笔记.md", start="**正文**：", nth=2, end="**评论区置顶**",
         fence=True, extra="工具在主页简介里 👆", extra_label="评论区置顶（单独复制）"),
    dict(id="bili-1", platform="B站", week=3,
         title="花两周做了个抖音视频解析工具，聊聊踩了哪些坑",
         target="先按下面「分镜表 + 录屏清单」录屏剪辑，成片好了再回来复制简介",
         src="B站·视频脚本.md", start="## 简介文案", nth=0, end="\n---", fence=True,
         ref_src="B站·视频脚本.md",
         ref=[("分镜表", "## 分镜表", "## 简介文案"),
              ("录屏清单", "## 录屏清单", "## 发布设置")],
         ref_label="分镜表 / 录屏清单（参考资料，不用复制）"),
]

FENCE = re.compile(r"^```[A-Za-z0-9]*\n(.*?)\n```", re.S | re.M)


def cut(text, start, end, nth=0):
    """按标记截取：从 start 的第 nth+1 次出现，到之后的第一个 end。"""
    pos = -1
    for _ in range(nth + 1):
        pos = text.find(start, pos + 1)
        if pos < 0:
            sys.exit(f"[x] 找不到起始标记 {start!r}（第 {nth + 1} 次）")
    stop = text.find(end, pos + len(start))
    if stop < 0:
        sys.exit(f"[x] 找不到结束标记 {end!r}")
    return text[pos + len(start):stop].strip("\n")


def unfence(block):
    """小红书/B站的正文在 md 里被 ``` 包着，复制时要剥掉围栏。

    注意不能要求整段就是一个围栏 —— B站那段前面还跟着
    「（发布时贴进简介框）」这样的说明行，得在段内找。
    """
    block = block.strip("\n")
    m = FENCE.search(block)
    return (m.group(1) if m else block).strip("\n")


def strip_hr(text):
    """去掉结尾的分隔线，粘到编辑器里会渲染成一条多余的横线。"""
    lines = text.rstrip().split("\n")
    while lines and lines[-1].strip() in ("---", "***", "___"):
        lines.pop()
    return "\n".join(lines).strip("\n")


def build():
    cache = {}
    items = []
    for it in ITEMS:
        path = os.path.join(DRAFTS, it["src"])
        if path not in cache:
            if not os.path.isfile(path):
                sys.exit(f"[x] 成稿缺失：{path}")
            with open(path, encoding="utf-8") as f:
                cache[path] = f.read()
        text = cut(cache[path], it["start"], it["end"], it.get("nth", 0))
        if it.get("fence"):
            text = unfence(text)
        text = strip_hr(text.strip("\n"))

        refs = []
        if it.get("ref_src"):
            ref_path = os.path.join(DRAFTS, it["ref_src"])
            with open(ref_path, encoding="utf-8") as f:
                ref_text = f.read()
            for label, s, e in it["ref"]:
                refs.append({"label": label, "text": cut(ref_text, s, e).strip("\n")})

        items.append({
            "id": it["id"],
            "platform": it["platform"],
            "week": it["week"],
            "title": it["title"],
            "target": it["target"],
            "body": text,
            "extra": it.get("extra", ""),
            "extraLabel": it.get("extra_label", ""),
            "refs": refs,
            "refLabel": it.get("ref_label", ""),
            "url": CREATOR_URLS[it["platform"]],
            "color": PLATFORM_COLORS[it["platform"]],
        })
    return items


HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>一键发布台 · 抖音无水印解析器</title>
<style>
:root{
  --bg:#f6f7f9; --card:#fff; --bd:#e3e6ea; --tx:#1a1d21; --tx2:#5f6672;
  --ac:#0084ff; --ok:#0a7d3b; --chip:#eef1f4;
}
@media (prefers-color-scheme:dark){
  :root{--bg:#15171a;--card:#1c1f23;--bd:#2c3138;--tx:#e6e8eb;--tx2:#9aa2ad;--chip:#262b31;--ok:#3ecf8e;}
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
  font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 64px}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:6px}
h1{font-size:22px;margin:0;letter-spacing:-.01em}
.sub{color:var(--tx2);font-size:13px}
.bar{height:6px;background:var(--chip);border-radius:99px;overflow:hidden;margin:16px 0 8px}
.bar>i{display:block;height:100%;width:0;background:var(--ok);transition:width .3s}
.prog{color:var(--tx2);font-size:13px;margin-bottom:22px}
.tabs{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}
.tabs button{background:var(--chip);border:0;color:var(--tx2);padding:7px 15px;
  border-radius:8px;cursor:pointer;font-size:13px;font-family:inherit}
.tabs button.on{background:var(--tx);color:var(--bg)}
h2.week{font-size:14px;color:var(--tx2);margin:26px 0 12px;font-weight:600;
  letter-spacing:.02em;display:flex;align-items:center;gap:10px}
h2.week::after{content:"";flex:1;height:1px;background:var(--bd)}
.card{background:var(--card);border:1px solid var(--bd);border-radius:12px;
  padding:18px 20px;margin-bottom:14px}
.card.done{opacity:.5}
.top{display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}
.tag{font-size:12px;padding:2px 9px;border-radius:6px;color:#fff;font-weight:600;
  letter-spacing:.02em}
.tt{font-size:16px;font-weight:600;flex:1;min-width:200px}
.n{font-size:12px;color:var(--tx2);margin-bottom:12px;padding-left:2px;
  border-left:2px solid var(--bd);padding-left:10px}
pre{background:var(--chip);border:1px solid var(--bd);border-radius:8px;
  padding:12px 14px;overflow:auto;max-height:200px;font-size:13px;line-height:1.65;
  font-family:ui-monospace,"SFMono-Regular",Consolas,"Microsoft YaHei",monospace;
  margin:0 0 12px;white-space:pre-wrap;word-break:break-word}
pre.open{max-height:none}
details summary{cursor:pointer;color:var(--tx2);font-size:13px;
  padding:4px 0;user-select:none;outline:none}
details{margin-bottom:12px}
.btns{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
button.act{border:1px solid var(--bd);background:var(--card);color:var(--tx);
  padding:8px 16px;border-radius:8px;cursor:pointer;font-size:13px;font-family:inherit;
  transition:.15s}
button.act:hover{border-color:var(--ac);color:var(--ac)}
button.act.pri{background:var(--ac);border-color:var(--ac);color:#fff}
button.act.pri:hover{filter:brightness(1.08);color:#fff}
button.act.copied{background:var(--ok);border-color:var(--ok);color:#fff}
button.act.dn{color:var(--tx2)}
.spacer{flex:1}
.warn{margin-top:14px;padding:12px 14px;border-radius:8px;font-size:13px;
  background:var(--chip);color:var(--tx2);line-height:1.7}
.warn b{color:var(--tx)}
footer{margin-top:34px;color:var(--tx2);font-size:12px;line-height:1.8}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>一键发布台</h1>
    <span class="sub">抖音无水印解析器 · 推广第 ②③ 步</span>
  </header>
  <div class="bar"><i id="bar"></i></div>
  <div class="prog" id="prog"></div>
  <div class="tabs">
    <button data-w="all" class="on">全部</button>
    <button data-w="2">第 2 周</button>
    <button data-w="3">第 3 周</button>
  </div>
  <div id="list"></div>
  <footer>
    进度保存在这台电脑的浏览器本地存储里，换浏览器会重置，不发任何数据出去。<br>
    成稿内容改了以后，重跑 <code>python 推广/build_publish_console.py</code> 重新生成本页。
  </footer>
</div>
<script>
const ITEMS = __ITEMS__;
const KEY = 'douyin-parser-publish-console';
let done = JSON.parse(localStorage.getItem(KEY) || '{}');

function save(){ localStorage.setItem(KEY, JSON.stringify(done)); render(); }

function copy(text, btn){
  const fallback = () => {
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position='fixed'; ta.style.opacity='0';
    document.body.appendChild(ta); ta.select();
    document.execCommand('copy'); ta.remove();
  };
  const ok = () => {
    const old = btn.textContent;
    btn.textContent = '已复制 ✓'; btn.classList.add('copied');
    setTimeout(()=>{ btn.textContent = old; btn.classList.remove('copied'); }, 1600);
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(ok, () => { fallback(); ok(); });
  } else { fallback(); ok(); }
}

function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

function preview(text){
  const lines = text.split('\\n');
  const short = lines.length > 12;
  return '<pre' + (short ? '' : ' class="open"') + '>' + esc(short ? lines.slice(0,12).join('\\n') : text)
       + (short ? '\\n…' : '') + '</pre>';
}

function card(it){
  const isDone = !!done[it.id];
  let h = '<div class="card' + (isDone?' done':'') + '" data-w="' + it.week + '" data-id="' + it.id + '">';
  h += '<div class="top"><span class="tag" style="background:' + it.color + '">' + it.platform + '</span>';
  h += '<span class="tt">' + esc(it.title) + '</span></div>';
  h += '<div class="n">' + esc(it.target) + '</div>';
  h += preview(it.body);

  if (it.refs && it.refs.length){
    h += '<details><summary>' + esc(it.refLabel || '参考资料') + '</summary>';
    for (const r of it.refs){
      h += '<details style="margin:8px 0 0 12px"><summary>' + esc(r.label) + '</summary>';
      h += '<pre class="open">' + esc(r.text) + '</pre></details>';
    }
    h += '</details>';
  }

  h += '<div class="btns">';
  h += '<button class="act pri" data-copy="body">复制正文</button>';
  if (it.extra) h += '<button class="act" data-copy="extra">' + esc(it.extraLabel||'复制附加') + '</button>';
  h += '<button class="act" data-open="1">打开 ' + it.platform + ' 创作页</button>';
  h += '<span class="spacer"></span>';
  h += '<button class="act' + (isDone?' dn':'') + '" data-toggle="1">' + (isDone?'撤销已发':'标记已发') + '</button>';
  h += '</div>';

  if (it.platform === '小红书'){
    h += '<div class="warn"><b>小红书发布铁律</b>：正文不要出现「去水印 / 下载抖音 / 搬运 / 解析」，'
       + '链接放主页简介或评论区置顶，不要放正文。</div>';
  }
  h += '</div>';
  return h;
}

function render(){
  const all = ITEMS.length;
  const n = ITEMS.filter(i => done[i.id]).length;
  document.getElementById('bar').style.width = (n / all * 100) + '%';
  document.getElementById('prog').textContent =
    '已发布 ' + n + ' / ' + all + ' 篇　（第 2 周 4 篇 · 第 3 周 4 篇）';
  document.getElementById('list').innerHTML =
    ITEMS.filter(i => cur === 'all' || String(i.week) === cur).map(card).join('');
}

let cur = 'all';
document.querySelectorAll('.tabs button').forEach(b => {
  b.onclick = () => {
    cur = b.dataset.w;
    document.querySelectorAll('.tabs button').forEach(x => x.classList.remove('on'));
    b.classList.add('on'); render();
  };
});

document.getElementById('list').addEventListener('click', e => {
  const btn = e.target.closest('button'); if (!btn) return;
  const el = e.target.closest('.card'); const it = ITEMS.find(x => x.id === el.dataset.id);
  if (btn.dataset.copy === 'body'){ copy(it.body, btn); }
  else if (btn.dataset.copy === 'extra'){ copy(it.extra, btn); }
  else if (btn.dataset.open){ window.open(it.url, '_blank'); }
  else if (btn.dataset.toggle){
    if (done[it.id]) delete done[it.id]; else done[it.id] = Date.now();
    save();
  }
});

render();
</script>
</body>
</html>
"""


def main():
    items = build()
    html = HTML.replace("__ITEMS__", json.dumps(items, ensure_ascii=False))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[ok] 已生成：{OUT}")
    for it in items:
        n = len(it["body"])
        print(f"     {it['platform']:<4} 第{it['week']}周  {it['title'][:28]:<30} 正文 {n} 字")
    print(f"\n共 {len(items)} 篇，双击 发布台.html 即可使用。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
