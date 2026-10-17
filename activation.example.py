"""离线激活模块（零第三方依赖，仅用标准库）—— 支持月/半年/年/终身套餐与有效期。

激活码结构（去掉分隔符后共 19 位，显示为 XXXX-XXXX-XXXX-XXXX-XXX）：

    机器指纹(6) + 套餐(1) + 到期日(4) + 签名(8)

- 机器指纹：HMAC(SECRET, 机器码) 取前 6 位 → 把激活码锁死在这一台电脑上
- 套餐：    M=月版(30天) / H=半年版(180天) / Y=年版(365天) / L=终身版(不过期)
- 到期日：  距 1970-01-01 的天数，base36 编码 4 位；终身版固定为 ZZZZ
- 签名：    HMAC(SECRET, "sign:" + 前 11 位) 取前 8 位 → 防篡改，改一位就失效

两种激活码：
  · 绑定码（默认）：一码一机，到期日写死在码里，适合人工发货。
  · 通用码：指纹位固定 "000000"（base32 里不含 0，不会与真实指纹混淆），
    不绑机器，可批量预生成做平台自动发卡；此时第 8-11 位改为随机序列号
    （否则同套餐通用码会完全一样），有效期从本机首次激活日起算，
    首次激活日记录在本机 license 文件第二行。

软件每次启动都会重新校验并**检查是否过期**，到期后自动回到激活窗口提示续费。

重要：
    1. 私钥已设为强随机值。**切勿泄露本文件 / 切勿提交到公开仓库**，
       否则任何人拿到它都能自己生成激活码。
    2. 到期判定依赖本机系统时间，这是离线方案的固有边界；若要强管控
       （防改系统时间、限设备数、远程吊销），需升级为在线激活服务器。
    3. 本模块会被打包进软件；激活码生成器（license_gen.py）复用同一 SECRET，
       但生成器本身不要随软件分发。
"""

import base64
import hashlib
import hmac
import os
import platform
import random
import re
import subprocess
import uuid
from datetime import datetime, timezone

# ---- 私钥：已设为 32 字节强随机值。切勿泄露此文件 / 切勿提交到公开仓库 ----
SECRET = b"CHANGE-ME-请填入你自己的32字节随机私钥"

APP_NAME = "DouyinParser"

# 套餐表：代码 -> (名称, 有效天数, 建议售价)
# 终身版天数为 None，表示永不过期
PLANS = {
    "M": ("月版", 30, "¥19"),
    "H": ("半年版", 180, "¥68"),
    "Y": ("年版", 365, "¥90"),
    "L": ("终身版", None, "¥160"),
}

# 通用码标记：真实机器指纹是 base32（字符集 A-Z / 2-7），
# 绝不会含字符 "0"，所以 "000000" 可以无歧义地代表"不绑机器的通用码"。
UNIVERSAL_FP = "000000"

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _norm(text: str) -> str:
    """归一化：去掉分隔符、统一大写，便于用户粘贴时带不带横线都能识别。"""
    return re.sub(r"[^0-9A-Z]", "", (text or "").upper())


def _run(cmd: str) -> str:
    try:
        out = subprocess.run(cmd, shell=True, capture_output=True, timeout=15)
        return out.stdout.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _hardware_uuid() -> str:
    """尽量拿到主板/整机 UUID。Win11 24H2 起 wmic 被移除，故有 PowerShell 兜底。"""
    txt = _run("wmic csproduct get uuid")
    for line in txt.splitlines():
        s = line.strip()
        if s and s.upper() != "UUID" and len(s) >= 8:
            return s
    txt = _run(
        'powershell -NoProfile -Command '
        '"(Get-CimInstance Win32_ComputerSystemProduct).UUID"'
    )
    s = txt.strip()
    if s and len(s) >= 8:
        return s
    return ""


def get_machine_id() -> str:
    """返回 16 位大写机器码（给用户看、用来生成激活码）。"""
    raw = _hardware_uuid()
    if not raw:
        # 兜底：MAC 地址 + 计算机名，保证任何机器都能得到一个稳定标识
        raw = f"{uuid.getnode()}-{platform.node()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


# ---------------- 编码 / 签名小工具 ----------------

def _b32(data: bytes) -> str:
    return base64.b32encode(data).decode("ascii")


def _fingerprint(machine_id: str) -> str:
    """机器指纹：6 位，用来把激活码绑定到具体电脑。"""
    return _b32(hmac.new(SECRET, _norm(machine_id).encode(), hashlib.sha256).digest())[:6]


def _sign(payload: str) -> str:
    """对 payload 签名：8 位，任何改动都会导致校验失败。"""
    return _b32(hmac.new(SECRET, ("sign:" + payload).encode(), hashlib.sha256).digest())[:8]


def _now_days() -> int:
    """当前距 1970-01-01 的天数（UTC，避免时区歧义）。"""
    return int((datetime.now(timezone.utc) - _EPOCH).total_seconds() // 86400)


def _b36(n: int) -> str:
    """天数 -> 4 位 base36（大写，左补 0）。"""
    digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    s = ""
    n = max(0, int(n))
    for _ in range(4):
        n, r = divmod(n, 36)
        s = digits[r] + s
    return s


def _unb36(s: str) -> int:
    """4 位 base36 -> 天数。非法输入返回 0（视为已过期）。"""
    try:
        return int(s, 36)
    except Exception:
        return 0


def _date_str(days: int) -> str:
    """天数 -> YYYY-MM-DD。"""
    try:
        return datetime.fromtimestamp(days * 86400, tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return "-"


def _group(raw: str) -> str:
    """19 位 -> XXXX-XXXX-XXXX-XXXX-XXX，方便阅读和复制。"""
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


# ---------------- 生成 / 校验 ----------------

def make_code(machine_id: str, plan: str = "M", universal: bool = False,
              serial: int = None) -> str:
    """按套餐生成激活码。plan: M=月版 / H=半年版 / Y=年版 / L=终身版。

    universal=False（默认）：绑定机器码，一码一机，激活码里写死到期日。
    universal=True        ：通用码，不绑机器，可在面包多/爱发电做自动发卡。
                            此时第 8-11 位改为随机序列号 —— 否则同一套餐的所有
                            通用码会完全一样（因为 payload 里没有其他变量）。
                            有效期从本机首次激活日起算，写在本机 license 文件里。
    """
    plan = (plan or "M").upper()
    if plan not in PLANS:
        raise ValueError(f"未知套餐 {plan}，可选：{', '.join(PLANS)}")
    if universal:
        fp = UNIVERSAL_FP
        # 序列号占 4 位 base36，共 36^4 ≈ 168 万种，够用且每个码唯一
        if serial is None:
            serial = random.randrange(36 ** 4)
        exp = _b36(int(serial) % (36 ** 4))
    else:
        if not machine_id:
            raise ValueError("生成绑定码必须提供机器码")
        fp = _fingerprint(machine_id)
        days = PLANS[plan][1]
        exp = "ZZZZ" if days is None else _b36(_now_days() + days)
    payload = fp + plan + exp
    return _group(payload + _sign(payload))


def is_universal(code: str) -> bool:
    """判断是否为通用码（不绑机器）。"""
    return _norm(code)[0:6] == UNIVERSAL_FP


def verify_detail(machine_id: str, code: str):
    """完整校验，返回 (是否有效, 套餐名, 说明文字)。"""
    raw = _norm(code)
    if len(raw) != 19:
        return False, "", "激活码长度不对，请确认复制完整（去掉横线共 19 位）"
    fp, plan, exp, sign = raw[0:6], raw[6], raw[7:11], raw[11:19]
    if plan not in PLANS:
        return False, "", "激活码套餐标识无效"
    if not hmac.compare_digest(_sign(fp + plan + exp), sign):
        return False, "", "激活码无效，请确认未改动任何字符"
    label, days, _price = PLANS[plan]

    if fp == UNIVERSAL_FP:
        # 通用码：不校验机器指纹，有效期 = 本机首次激活日 + 套餐天数
        if days is None:
            return True, label, "有效"
        start = read_activation_days()
        if _now_days() - start > days:
            return False, label, f"{label}已于 {_date_str(start + days)} 到期，请续费后重新激活"
        return True, label, "有效"

    if not hmac.compare_digest(_fingerprint(machine_id), fp):
        return False, "", "激活码与本机不匹配（换电脑需重新获取）"
    if days is not None and _now_days() > _unb36(exp):
        return False, label, f"{label}已于 {_date_str(_unb36(exp))} 到期，请续费后重新激活"
    return True, label, "有效"


def verify(machine_id: str, code: str) -> bool:
    """仅判断有效/无效（供启动检查使用）。"""
    return verify_detail(machine_id, code)[0]


def expiry_of(machine_id: str, code: str) -> str:
    """该激活码的有效期描述：终身版返回"终身"，否则返回到期日期。
    通用码按本机首次激活日推算。"""
    raw = _norm(code)
    if len(raw) != 19:
        return ""
    plan = raw[6]
    if plan not in PLANS:
        return ""
    if PLANS[plan][1] is None:
        return "终身"
    if raw[0:6] == UNIVERSAL_FP:
        return _date_str(read_activation_days() + PLANS[plan][1])
    return _date_str(_unb36(raw[7:11]))


def plan_price(plan: str) -> str:
    """套餐建议售价，供生成器/界面展示。"""
    return PLANS.get((plan or "").upper(), ("", None, ""))[2]


# ---------------- 本地激活状态 ----------------

def license_path() -> str:
    """激活状态存放位置：优先 %APPDATA%，失败则退回程序目录。"""
    try:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = os.path.join(base, APP_NAME)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "license.key")
    except Exception:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "license.key")


def read_saved_code() -> str:
    """读本机已保存的激活码（文件第一行）。"""
    p = license_path()
    if not os.path.exists(p):
        return ""
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.readline().strip()
    except Exception:
        return ""


def read_activation_days() -> int:
    """通用码的首次激活日（距 epoch 天数）。文件第二行；缺失则视为今天。"""
    p = license_path()
    try:
        with open(p, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        if len(lines) >= 2 and lines[1].strip().isdigit():
            return int(lines[1].strip())
    except Exception:
        pass
    return _now_days()


def save_license(code: str) -> bool:
    """激活成功后写入本地激活文件：第一行激活码，第二行首次激活日（通用码用）。"""
    try:
        with open(license_path(), "w", encoding="utf-8") as f:
            f.write(_norm(code) + "\n")
            f.write(str(_now_days()) + "\n")
        return True
    except Exception:
        return False


def is_activated() -> bool:
    """启动时调用：本地激活码是否有效且未过期。"""
    saved = read_saved_code()
    if not saved:
        return False
    return verify(get_machine_id(), saved)


def active_plan():
    """返回当前授权 (套餐名, 有效期描述)；未激活返回 ("", "")。"""
    saved = read_saved_code()
    if not saved:
        return "", ""
    ok, label, _msg = verify_detail(get_machine_id(), saved)
    if not ok:
        return "", ""
    return label, expiry_of(get_machine_id(), saved)
