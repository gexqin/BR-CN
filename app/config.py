"""游戏常量 —— 对等移植自原版 br.cgi(全部数值单一事实来源)。

原版行号以注释标注;与原版不同之处(即 bug 修复)以 [FIX] 标注并记录于 BUGFIXES.md。
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEDS_DIR = os.path.join(BASE_DIR, "seeds")

VER = "V02.00"                      # 原 br.cgi:19 为 V01.16;v2 重写后独立演进
GAME_TITLE = f"■ BATTLE ROYALE ■({VER})"
DB_PATH = os.environ.get("BR_DB", os.path.join(BASE_DIR, "brcn.db"))

# --- 班级/人数(br.cgi:86-91) ---
CLASSES = ["3年A组", "3年B组", "3年C组", "3年D组", "3年E组",
           "3年F组", "3年G组", "3年H组", "3年I组", "3年J组"]
CLMAX = 5          # 班级数
MANMAX = 21        # 每班每性别最大人数
MAXMEM = CLMAX * MANMAX * 2   # 最大注册数 210

# --- 地点(br.cgi:94-106) ---
PLACE = ["分校", "北之岬", "北村住宅街", "北村公所", "邮局", "消防署",
         "观音堂", "清水池", "西村神社", "旅馆废墟",
         "山岳地带", "隧道", "西村住宅街", "寺庙", "废弃学校", "南村神社",
         "森林地带", "源二郎池", "南村住宅街", "诊疗所",
         "灯塔", "南之岬"]
AREA = ["D-6", "A-2", "B-4", "C-3", "C-4", "C-5", "C-6", "D-3", "E-2", "E-4",
        "E-5", "E-7", "F-2", "F-9", "G-3", "G-6", "H-4", "H-6", "I-6", "I-7",
        "I-10", "J-6"]

# 区域状态:WU 攻击增 WD 攻击减 DU 防御增 DD 防御减 SU 发现增 SD 发现减
# [FIX] 原版 br.cgi:100-102 使用 AU/AD,而判定代码(TACTGET/TACTGET2)只匹配
# WU/WD,导致观音堂/旅馆废墟/废弃学校/南村住宅街的攻击修正从未生效。
# 此处统一为 WU/WD,使 4 个地点的攻击修正真实生效。
ARSTS = ["SU", "DD", "DU", "SU", "SD", "SU",
         "WU", "SU", "SD", "WD",
         "SU", "DD", "DU", "SD", "WD", "SD",
         "SD", "SD", "WU", "SU",
         "DU", "SU"]

# --- 数值常量(br.cgi:139-163) ---
BASEEXP = 9         # 升级基准:exp >= level*9+(level-1)*9
BASE = 20           # 熟练度基准:每 20 点 = 1 级
BATTLE_LIMIT = 3    # 最短举办天数:ar > battle_limit*3+1=10 才能决出优胜
LIMIT = 3           # 报名截止天数:ar >= limit*3+1=10 停止注册
MAXSTA = 100        # 耐力上限
OKYU_STA = 70       # 应急治疗消耗耐力
DOKUMI_STA = 30     # 验毒消耗耐力
KAIFUKU_TIME = 6    # 睡眠:每 6 秒恢复 1 耐力
KAIFUKU_RATE = 2    # 治疗:体力恢复 = 耐力恢复 / 2(即每 12 秒 1 HP)
DEATH_REENTRY_SECS = 2 * 60 * 60   # [FIX] 死亡后 2 小时禁注册(原版 cookie 恒写 0 从未生效)

# 遭遇/发现概率(battle.cgi SEARCH2 / lib2.cgi TACTGET)
ENCOUNTER_RATE = 6      # dice1 <= 5 → 60% 进入遇敌检索(chkpnt 基准)
CHKPNT = 7              # 发现率基准(10 进制,SU +2 / SD -2;原版 5,调高搜刮手感)
CHKPNT2 = 5             # 先制率基准(dice3 <= 5 → 60% 先制)
CORPSE_FIND_RATE = 8    # dice4 >= 8 → 20% 发现尸体(原版 9=10%,调高)
SENSE_GUNSHOT_SECS = 15 # 枪声/悲鸣可见时长
SENSE_SCREAM_SECS = 15
SENSE_ANNOUNCE_SECS = 30  # 扩音器广播可见时长

# 反击率(attack.cgi:rand(10) < 5)
COUNTER_RATE = 5

# 陷阱伤害:int(rand(eff/2)+eff/2)(item.cgi)
# 弹药装填上限 6;磨刀石/缝纫工具上限 30

# --- 武器类别参数(attack.cgi WEPTREAT / lib2.cgi TACTGET) ---
# mei=命中率基础 wkind=熟练度字段名 weps=射程(S 近战/L 远程)
# kega=负伤率(%) parts=可负伤部位 hakai=武器破坏率(%)
WEAPON_KINDS = {
    # code前缀: (mei, weps, kega, parts, hakai, prof_key)
    "WB": dict(mei=80, weps="S", kega=15, parts=["头", "腕"], hakai=3, prof="wb"),
    "WP": dict(mei=70, weps="S", kega=0,  parts=[],           hakai=0, prof="wp"),
    "WG": dict(mei=50, weps="L", kega=25, parts=["头", "腕", "腹", "足"], hakai=3, prof="wg"),
    "WA": dict(mei=60, weps="L", kega=20, parts=["头", "腕", "腹", "足"], hakai=3, prof="wa"),
    "WN": dict(mei=80, weps="S", kega=25, parts=["头", "腕", "腹", "足"], hakai=3, prof="wn"),
    "WS": dict(mei=80, weps="S", kega=25, parts=["头", "腕", "腹", "足"], hakai=3, prof="ws"),
    "WC": dict(mei=70, weps="L", kega=15, parts=["头", "腕"], hakai=0, prof="wc"),
    "WD": dict(mei=50, weps="L", kega=15, parts=["头", "腕", "腹", "足"], hakai=0, prof="wd"),
}
# [FIX] 原版 WNS(双属性刀)命中率按斩(wn)、熟练度增长按刺(ws),两者不一致;
# 统一按刺系(ws)计算命中率(WEAPON_KINDS 按最长前缀匹配,WS 优先于 WN)。

# 熟练度倍率 wk:int(prof/BASE) → 系数(attack.cgi:399-405)
PROF_WK = [0.9, 0.95, 1.0, 1.05, 1.1, 1.15]   # 索引 min(int(p/BASE), 5)

# 空枪/空弓(WGB/WAB 或 弹药为 0)按钝器处理:mei=80/S 系/att 取 int(watt/10)

# --- 防具相性 DEFTREAT(attack.cgi)[FIX] ---
# 原版 DBA/DBK 三条分支引用未定义变量 $b_kind_b 永不生效;此处按设计意图实现。
# 键: (攻击武器前缀, 防具码包含) → 伤害倍率
DEFTREAT = [
    (("WG",), "ADB", 0.5),   # 枪 → 防弹背心/杂志:减伤
    (("WG",), "DH", 1.5),    # 枪 → 头盔:增伤
    (("WN",), "DBK", 0.5),   # 斩 → 锁子甲:减伤
    (("WN",), "ADB", 1.5),   # 斩 → 防弹饰品:增伤
    (("WB", "WGB", "WAB"), "DH", 0.5),        # 殴系(含空枪空弓) → 头盔:减伤
    (("WB", "WGB", "WAB"), "DBA", 1.5),       # [FIX] 殴 → 铠甲:增伤
    (("WS",), "DBA", 0.5),   # [FIX] 刺 → 铠甲:减伤
    (("WS",), "DBK", 1.5),   # [FIX] 刺 → 锁子甲:增伤
]

# --- 死因词(attack.cgi WEPTREAT/LOGSAVE 判定序) ---
# 按武器码与弹药状态映射;顺序:斩 N → 弓 A(有箭) → 枪 G(有弹) → 投 C →
# 爆 D → 刺 S → 殴 B/空枪空弓 → 兜底"杀害"
DEATH_WORD_ORDER = [
    ("N", "斩杀"), ("A", "射杀"), ("G", "枪杀"), ("C", "杀害"),
    ("D", "爆杀"), ("S", "刺杀"), ("B", "殴杀"),
]
DEATH_WORD_DEFAULT = "杀害"
DEATH_POISON = "毒物摄入"
DEATH_WEAK = "衰弱死"       # DRAIN 耐力耗尽致死
DEATH_AREA = "禁区滞留"
DEATH_GOV = "政府处刑"      # 管理员处刑 / 黑客大失败颈环引爆

# --- 社团(regist.cgi CLUBMAKE,int rand(11)) ---
CLUBS = [
    ("弓道部", "wa"), ("射击部", "wg"), ("空手部", "wb"), ("篮球部", "wc"),
    ("科学部", "wd"), ("击剑部", "ws"), ("剑道部", "wn"), ("相扑部", "wp"),
    ("田径部", None), ("料理研究部", None), ("个人电脑部", None),
]

# --- 合成配方(lib/gousei_tbl.cgi) ---
RECIPES = [
    # (素材1, 素材2, 产物名, 产物码, 效果, 耐久/数量)
    ("轻油", "肥料", "火药", "Y", 1, 1),
    ("汽油", "空瓶", "燃烧瓶", "WD", 15, 1),
    ("雷管", "火药", "炸弹", "WD", 60, 1),
    ("火药", "导火索", "黄色炸药", "WD", 15, 6),
    ("喷雾罐", "打火机", "简易火焰喷射器", "WD", 10, 8),
    ("手机", "苹果电脑", "笔记本电脑", "Y", 1, 1),
]

# --- 黑客(hack.cgi) ---
HACK_BONUS_PC_CLUB = 5   # 个人电脑部 dice1 <= 5(60%);他人 dice1 <= 0(10%)
HACK_BONUS_OTHER = 0
HACK_BREAK_ROLL = 9      # dice1 >= 9(10%):笔记本电脑损坏
HACK_NECK_ROLL = 9       # 损坏后再掷 dice2 >= 9(10%):颈环爆死

# --- 耐力消耗(battle.cgi MOVE/SEARCH,int rand(5)+N) ---
STA_MOVE = 8       # 基础移动 8~12
STA_MOVE_TRACK = 5   # 田径部 5~9
STA_MOVE_FOOT = 13   # 足伤 13~17
STA_SEARCH = 18      # 探索 18~22
STA_SEARCH_TRACK = 13  # 田径部 13~17
STA_SEARCH_FOOT = 23  # 足伤 23~27

# --- NPC(admin.cgi DATARESET,政府系) ---
NPC_GOV_ATT = 40      # rand(10)+40
NPC_GOV_HIT = 80      # rand(30)+80
NPC_GOV_LEVEL = 10
NPC_GOV_PROF = 60     # 全熟练度 60(等级 3)
BOSS_CLASS = "班主任"
ZAKO_CLASS = "士兵"

ADMIN_USER = os.environ.get("BR_ADMIN_USER", "admin")
# [安全] 管理密码无默认值:未设置 BR_ADMIN_PASS 时管理登录整体禁用
ADMIN_PASSWORD = os.environ.get("BR_ADMIN_PASS")
# [安全] HTTPS 部署时置 1,会话 cookie 追加 Secure 属性
COOKIE_SECURE = os.environ.get("BR_COOKIE_SECURE", "").lower() in ("1", "true", "yes")


def load_seed(name):
    with open(os.path.join(SEEDS_DIR, name), encoding="utf-8") as f:
        return json.load(f)
