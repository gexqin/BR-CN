"""P8 数值公式黄金值测试(引擎级,固定 RNG)。

期望值逐条抄录自原版 Perl:
  命中 = 武器基础 + int(熟练/20) - (头伤 20)     (lib2.cgi TACTGET)
  伤害 = ((att_p×wk) − def_p)/2 + rand(0,that),×相性,保底 1(attack.cgi 87-96)
  升级 = exp >= level*9 + (level-1)*9            (attack.cgi LVUPCHK)
  wk   = 0.9/0.95/1.0/1.05/1.1/1.15              (attack.cgi 399-405)
  DRAIN mhit -= int(rand(mhit*0.2)+mhit*0.1)     (lib2.cgi DRAIN)
"""
import random

from app.engine import util
from app.engine.battle import damage, deftreat, tactget
from app import config


def test_prof_wk_table():
    assert util.prof_wk(0) == 0.9
    assert util.prof_wk(19) == 0.9
    assert util.prof_wk(20) == 0.95      # int(20/20)=1
    assert util.prof_wk(40) == 1.0
    assert util.prof_wk(60) == 1.05
    assert util.prof_wk(80) == 1.1
    assert util.prof_wk(100) == 1.15
    assert util.prof_wk(999) == 1.15     # 封顶


def test_next_exp():
    assert util.next_exp(1) == 9         # 1*9+0*9
    assert util.next_exp(2) == 27        # 2*9+1*9
    assert util.next_exp(3) == 45
    assert util.next_exp(4) == 63


def test_weapon_class():
    # [FIX] WNS 统一按刺系;空枪空弓按钝器(B 优先)
    assert util.weapon_class("WB") == "B"
    assert util.weapon_class("WP") == "P"
    assert util.weapon_class("WG") == "G"
    assert util.weapon_class("WGB") == "B"
    assert util.weapon_class("WAB") == "B"
    assert util.weapon_class("WA") == "A"
    assert util.weapon_class("WN") == "N"
    assert util.weapon_class("WS") == "S"
    assert util.weapon_class("WNS") == "S"
    assert util.weapon_class("WNSC") == "S"
    assert util.weapon_class("WC") == "C"
    assert util.weapon_class("WD") == "D"


def test_death_word():
    assert util.death_word_by_weapon("WN") == "斩杀"
    assert util.death_word_by_weapon("WA") == "射杀"
    assert util.death_word_by_weapon("WG") == "枪杀"
    assert util.death_word_by_weapon("WC") == "杀害"
    assert util.death_word_by_weapon("WD") == "爆杀"
    assert util.death_word_by_weapon("WS") == "刺杀"
    assert util.death_word_by_weapon("WB") == "殴杀"
    assert util.death_word_by_weapon("WGB") == "殴杀"    # 空枪当钝器
    assert util.death_word_by_weapon("WNS") == "刺杀"    # [FIX] 双属性统一刺


def _defender(body="", head="", acc=None):
    return dict(bou_code=body, bouh_code=head,
                items=([None] * 5 + [acc]) if acc else [None] * 6)


def test_deftreat_table():
    # 生效分支(对等原版)
    assert deftreat("WG", _defender(acc=dict(code="ADB", eff=5))) == 0.5
    assert deftreat("WG", _defender(head="DH")) == 1.5
    assert deftreat("WN", _defender(body="DBK")) == 0.5
    assert deftreat("WN", _defender(acc=dict(code="ADB", eff=5))) == 1.5
    assert deftreat("WB", _defender(head="DH")) == 0.5
    assert deftreat("WGB", _defender(head="DH")) == 0.5
    assert deftreat("WAB", _defender(head="DH")) == 0.5
    # [FIX] 原版死代码三分支按设计意图实现
    assert deftreat("WB", _defender(body="DBA")) == 1.5
    assert deftreat("WS", _defender(body="DBA")) == 0.5
    assert deftreat("WS", _defender(body="DBK")) == 1.5
    # 无相性 → 1.0
    assert deftreat("WP", _defender(body="DBN")) == 1.0
    assert deftreat("WD", _defender(head="DH")) == 1.0
    assert deftreat("WA", _defender(acc=dict(code="ADB", eff=5))) == 1.0


def test_damage_formula_golden():
    """伤害黄金值:att_p=30, wk=1.0, def_p=10 → 基础 20,伤害 ∈ [10,20]。"""

    class RngCtx:
        def __init__(self, seed):
            self.rng = random.Random(seed)

    for _ in range(200):
        result = damage(RngCtx(42), 30.0, 1.0, 10.0, 1.0)
        assert 10 <= result <= 20, result
    # def_p ≥ att_p×wk 时保底 1
    assert damage(RngCtx(1), 10.0, 1.0, 50.0, 1.0) == 1
    # 相性 0.5:基础 20 → [5,10]
    for _ in range(100):
        r = damage(RngCtx(7), 30.0, 1.0, 10.0, 0.5)
        assert 5 <= r <= 10


def test_tactget_accuracy():
    """命中率 = 基础 + int(熟练/20);头伤 -20;腕伤攻击-0.2。"""
    p = dict(wep_code="WN", wep_uses=None, prof_wn=45, injuries="", place=2,  # DU
             wep_att=20, wep_name="柴刀", att=10)
    t = tactget(p)
    assert t["mei"] == 80 + 2        # int(45/20)=2
    assert t["weps"] == "S"
    assert t["dfp"] == 1.2           # DU 防御增
    p["injuries"] = "头"
    assert tactget(p)["mei"] == 80 + 2 - 20
    p["injuries"] = "腕"
    t2 = tactget(p)
    assert abs(t2["atp"] - 0.8) < 1e-9


def test_drain_range():
    """DRAIN:mhit 100 → 减少 int(rand(20)+10) ∈ [10,29]。"""
    from app.engine.ctx import Ctx
    import datetime
    texts = config.load_seed("texts.json")
    conn = None
    # drain 只操作 dict,无需 conn
    class FakeCtx:
        pass
    from app.engine import game as engine
    ctx = FakeCtx()
    ctx.rng = random.Random(3)
    ctx.msg = texts["messages"]
    ctx.dead = False
    ctx.log = lambda *_: None
    p = dict(l_name="测", mhit=100, hit=100, sta=0,
             f_name="试", class_name="3年A组", sex="男生", class_no=1, id=1)
    ctx.player = p
    engine.drain(ctx, "com")
    assert p["sta"] == 100
    assert 71 <= p["mhit"] <= 90     # 100 - [10,29]
    assert 0 < p["mhit"]


def test_sta_cost_ranges():
    """移动 8~12 / 探索 18~22(基础);DRAIN 在耗尽时触发。"""
    assert config.STA_MOVE == 8 and config.STA_MOVE + 4 == 12
    assert config.STA_SEARCH == 18 and config.STA_SEARCH + 4 == 22
    assert config.STA_MOVE_TRACK == 5
    assert config.STA_SEARCH_FOOT == 23


def test_seed_counts():
    """种子对等:44 武器/19 私物/4 NPC/22 地点/7×8 尸体描述。"""
    weapons = config.load_seed("weapons.json")
    personal = config.load_seed("personal_items.json")
    npcs = config.load_seed("npcs.json")
    texts = config.load_seed("texts.json")
    assert len(weapons) == 44
    assert len(personal) == 19
    assert len(npcs) == 4
    assert len(texts["arinfo"]) == 22
    assert all(len(v) == 7 for v in texts["corpse"].values())
    names = {w["name"] for w in weapons}
    assert "日本刀" in names and "乌兹9mm冲锋枪" in names
    # 私物含合成素材 手机/雷管
    pn = {i["name"] for i in personal}
    assert "手机" in pn and "雷管" in pn
