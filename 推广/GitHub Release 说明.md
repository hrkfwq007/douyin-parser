# GitHub Release v2.2 说明

> 用于 <https://github.com/hrkfwq007/douyin-parser/releases/new>
> 标签填 `v2.2`，下面内容直接粘进发布说明框。

---

## 粘进发布说明框的内容

```
抖音无水印解析器 v2.2

## 这次改了什么

**新增免费试用**：未激活也能用，每天免费解析 3 次。

之前是硬拦截——装完 58MB，双击只看到一个要钱的框，连软件长什么样都看不到。
现在先让人用 3 次，确认真能解析再决定付不付钱。

- 额度按自然日重置，每天 0 点刷新
- 试用解析出的内容与付费版完全一致，不是「试用给低画质、买了才给高清」
- 剩余次数显示在标题栏，也可以在「配置 → 授权」里查看
- 激活后不限次数

**其他改动**
- 精简版支持调用系统 Edge / Chrome 扫码登录，与完整版功能一致
- 落地页激活流程改为「先试用，再决定」
- 修复 activation.example.py 的 SECRET 语法错误（bytes 字面量不能含中文）

## 两个版本怎么选

| 版本 | 安装包 | 安装后 | 说明 |
|---|---|---|---|
| 精简版 | 59 MB | 223 MB | 调用本机 Edge / Chrome，功能全开 |
| 完整版 | 342 MB | 944 MB | 自带浏览器内核，不依赖系统环境 |

**两个版本功能完全一样**，只是浏览器来源不同。
Win10 / 11 自带 Edge，绝大多数人选精简版就够了。

完整版 342MB 超过单文件传输的合理体积，放在网盘：
在 <https://douyin-parser-42948.app.workbuddy.host/> 购买后可见下载入口。

## 套餐

月版 ¥19 / 半年版 ¥68 / 年版 ¥90 / 终身版 ¥160
四档功能一致，只在有效期长短。

## 合规提示

本工具仅用于保存你本人创作的内容，或已获得授权的内容。
下载的视频受著作权保护，请勿用于二次发布、搬运或任何商业用途。

---

官网与购买：<https://douyin-parser-42948.app.workbuddy.host/?ref=github>
```

---

## 发布方式：一条命令（有 token 时）

Release 附件是**二进制文件**，用 `gh` 或网页上传都行，但推荐直接跑脚本——
GitHub 的 Releases API 是公开的、稳定的、完全合规的，不依赖 `gh` 是否安装。

```bash
# token 只从环境变量读，不落盘
export GITHUB_TOKEN=ghp_xxxxxxxxxxxx

python release_github.py --dry-run    # 先看要发什么
python release_github.py              # 真的发
```

脚本会：读本文里的代码块作为 Release 正文 → 创建/复用 `v2.2` Release →
上传附件。已有同名 Release 或附件时会先删旧的再传，**重复跑安全**。

> token 权限：classic token 勾 `repo`；或 fine-grained token 给这一个仓库
> `Contents: Read and write`。不需要其他权限。

当前要传的文件：

```
release\抖音无水印解析器_v2.1_精简版_安装.exe
61,253,021 字节（58.4 MB），md5 a2a2d5fd06082814a6fc526f302c8e82
```

> 2026-10-19 重打：修了图集下载顺序（原来跟抖音页面不一致）。
> 旧包 md5 是 `c8ac136c…`，看到这个就是老版本，重新下载。

## 备选：网页手动发（没 token 时）

1. 打开 <https://github.com/hrkfwq007/douyin-parser/releases/new>
2. **Choose a tag** 里输入 `v2.2`，点「Create new tag」
3. 标题填 `抖音无水印解析器 v2.2`
4. 把上面那段内容粘进说明框
5. 把上面那个 exe 拖进底部的「Attach binaries」区域
6. 点 **Publish release**

> 完整版 342MB 建议**不要**挂到 Release 上，走网盘分发。
> 一是体积大、下载慢，二是之前实测大文件上传容易超时。

## ⚠️ 关于其他四个平台

知乎 / 小红书 / CSDN / B站 **没有面向个人创作者的发文 API**，
所以不能用 token 自动发，只有 GitHub 可以。详见 `推广/推广计划.md` 第三节。
内容平台的发布走 `推广/发布台.html`（一键复制 + 打开创作页，人做最后一步）。
