"""引擎通用工具:武器码归类、熟练度、随机数、HTML 转义。

武器码归类规则(对等原版字母包含匹配,顺序经 [FIX] 调整):
  原版 WNS(双属性刀)命中率按斩、熟练度增长按刺,不一致;统一按刺系。
  空枪/空弓(WGB/WAB)按钝器 B 处理,与原版一致(B 优先于 G/A)。
  [FIX] WSB(铲类)原版按 B(钝器);WNS/WNSC 特判为 S(刺)。
"""
import random

from .. import config

# 归类优先级:B(殴,含空枪空弓/WSB) → A(弓) → C(投) → D(爆) → G(枪) → S(刺) → N(斩) → P(空手)
_CLASS_ORDER = ["B", "A", "C", "D", "G", "S", "N", "P"]


def esc(text) -> str:
    """玩家可控文本的 HTML 转义(对等原版 DECODE 的 &<>" 过滤)。

    所有进入日志 HTML 的玩家输入(dengon/speech/msg/dmes/com)必须先过此处。
    """
    # [FIX] 补单引号:当前模板均为双引号属性,但演进出单引号属性时防属性逃逸
    return (str(text or "")
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;")
            .replace("'", "&#39;"))


def weapon_class(code: str) -> str:
    """武器种类码 → 单字母类别。"""
    code = code or ""
    if code.startswith("WNS"):    # [FIX] 双属性刀统一刺系
        return "S"
    for ch in _CLASS_ORDER:
        if ch in code:
            return ch
    return "P"


def prof_key(cls: str) -> str:
    return config.WEAPON_KINDS["W" + cls]["prof"]


def prof_wk(value: int) -> float:
    """熟练度 → 攻击倍率(0.9~1.15)。"""
    return config.PROF_WK[min(value // config.BASE, len(config.PROF_WK) - 1)]


def rand_int(rng: random.Random, lo: int, hi: int) -> int:
    """[lo, hi] 闭区间均匀(对等 Perl int(rand(n))+m)。"""
    return rng.randint(lo, hi)


def dice(rng: random.Random, n: int) -> int:
    """int(rand(n)) → [0, n-1]。"""
    return rng.randrange(n)


def death_word_by_weapon(code: str) -> str:
    """击杀武器 → 死因词(attack.cgi 判定序)。空枪/空弓按 B 类 → 殴杀。"""
    cls = weapon_class(code)
    for letter, word in config.DEATH_WORD_ORDER:
        if letter == cls:
            return word
    return config.DEATH_WORD_DEFAULT


def next_exp(level: int) -> int:
    """升级所需经验(原版 level*9+(level-1)*9)。"""
    return level * config.BASEEXP + (level - 1) * config.BASEEXP
