"""战斗系统:遭遇/先制/被袭/反击/负伤/防具相性/死亡/搜刮。

逐条对等 attack.cgi ATTACK/ATTACK1/ATTACK2/WEPTREAT/DEFTREAT/DEATH/DEATH2/WINGET。
[FIX] 相对原版:
1. ATTACK2 敌方命中判定误用玩家命中率($mei)→ 改用敌方 mei2;
2. 反击命中复用同一颗骰子 → 各掷新骰;
3. 敌方饰品防御因变量写错($ball += 而非 $ball2)从未生效 → 修正;
4. 负伤部位 rand(3) 永远掷不出"足" → rand(4);
5. DEFTREAT DBA/DBK 三分支引用未定义变量 → 按设计意图实现;
6. WNS 双属性武器统一按刺系参与相性判定(与熟练度/命中统一);
7. 击杀夺物菜单 GET_$i] 多余 "]"(原版不可用)→ 修复;
8. NPC 攻击饰品吸收查错变量($w_item[5] ↔ $item[5])→ 攻防双方对称实现。
"""
import datetime
import json

from .. import config
from . import util
from .ctx import MUTABLE_COLUMNS, Ctx
from .death import kill_player
from .items import CmdError
from .news import add_sense
from .util import weapon_class


# ---------- 数据载入/回写 ----------

def load_battle_target(ctx, target_id):
    row = ctx.conn.execute("SELECT * FROM players WHERE id=? AND game_id=?",
                           (target_id, ctx.game["id"])).fetchone()
    if row is None:
        raise CmdError("不正确的存取。")
    t = dict(row)
    if isinstance(t["items"], str):
        t["items"] = json.loads(t["items"])
    return t


def flush_target(ctx, target):
    cols = ", ".join(f"{c}=?" for c in MUTABLE_COLUMNS)
    vals = []
    for c in MUTABLE_COLUMNS:
        v = target[c]
        if c == "items":
            v = json.dumps(v, ensure_ascii=False)
        vals.append(v)
    ctx.conn.execute(f"UPDATE players SET {cols} WHERE id=?", (*vals, target["id"]))


# ---------- 战术计算(lib2.cgi TACTGET/TACTGET2) ----------

def tactget(p):
    """返回 dict(mei,weps,atp,dfp):命中率/射程/攻击倍率/防御倍率(所在区域修正)。"""
    cls = weapon_class(p["wep_code"])
    empty_ranged = cls in ("G", "A") and not p["wep_uses"]
    if cls == "B" and p["wep_name"] != "空手" or empty_ranged:
        eff_cls, mei_base = "WB", 80      # 钝器/空枪空弓
    else:
        eff_cls, mei_base = {
            "A": ("WA", 60), "C": ("WC", 70), "D": ("WD", 50), "G": ("WG", 50),
            "N": ("WN", 80), "S": ("WS", 80), "P": ("WP", 70),
        }.get(cls, ("WP", 70))
    prof = p[f"prof_{util.prof_key(eff_cls[1])}"]
    mei = mei_base + prof // config.BASE

    atp, dfp = 1.0, 1.0
    st = config.ARSTS[p["place"]]
    if st == "WU":
        atp += 0.2
    elif st == "WD":
        atp -= 0.2
    elif st == "DU":
        dfp += 0.2
    elif st == "DD":
        dfp -= 0.2
    if "腕" in (p["injuries"] or ""):
        atp -= 0.2
    if "头" in (p["injuries"] or ""):
        mei -= 20
    return dict(mei=mei, weps="S" if eff_cls in ("WB", "WN", "WS", "WP") else "L",
                atp=atp, dfp=dfp)


def attack_power(p, tact):
    """att_p:空枪/空弓攻击力按 watt/10(attack.cgi 49-53,浮点参与运算,
    仅状态栏显示取整)。"""
    cls = weapon_class(p["wep_code"])
    watt = p["wep_att"]
    if cls in ("G", "A") and not p["wep_uses"]:
        watt = watt / 10
    return (watt + p["att"]) * tact["atp"]


def defense_power(p, tact):
    """def_p:裸防御+四部位防具+AD 饰品。[FIX] 对称计算双方(原版敌方饰品无效)。"""
    ball = p["deff"] + p["bou_def"] + p["bouh_def"] + p["bouf_def"] + p["boua_def"]
    acc = p["items"][5] if p["items"] else None
    if acc and "AD" in acc["code"]:
        ball += acc["eff"]
    return ball * tact["dfp"]


# ---------- 遭遇(battle.cgi SEARCH2 敌人支) ----------

def candidates(ctx):
    """同地点、非本人、且未与我交战锁定的其他角色(含尸体)。随机排序。

    排除条件为候选者 bid==我(对等原版 $w_bid ne $id):被我打过、
    对方尚未行动(其 bid 在行动时清除)的角色不会重复出现。
    """
    rows = ctx.conn.execute(
        "SELECT id, bid FROM players WHERE game_id=? AND place=? AND id!=?",
        (ctx.game["id"], ctx.player["place"], ctx.player["id"])).fetchall()
    ids = [r["id"] for r in rows if r["bid"] != ctx.player["id"]]
    ctx.rng.shuffle(ids)
    return ids


def try_encounter(ctx, chkpnt):
    """遇敌检索。返回 'found' 或 None。"""
    for tid in candidates(ctx):
        t = load_battle_target(ctx, tid)
        dice2 = util.dice(ctx.rng, 10)
        if dice2 * 1.0 >= chkpnt:
            continue
        if t["hit"] > 0:
            dice3 = util.dice(ctx.rng, 10)
            if dice3 <= config.CHKPNT2:      # 先制
                ctx.log(f"{t['f_name']} {t['l_name']}"
                        f"（{t['class_name']} {t['sex']}{t['class_no']}号）被你发现了！<br>")
                ctx.log(f"{t['f_name']} {t['l_name']}　对你的接近没有丝毫察觉。<br>")
                ctx.view = "battle"
                ctx.extras["battle"] = _battle_menu(ctx.player, t)
                return "found"
            # 被奇袭:互设交战锁后立即结算(ATTACK2)
            ctx.player["bid"] = t["id"]
            t["bid"] = ctx.player["id"]
            ctx.log(f"{t['f_name']} {t['l_name']}"
                    f"（{t['class_name']} {t['sex']}{t['class_no']}号）突然袭了过来！<br>")
            resolve_exchange(ctx, t, player_first=False, dengon="")
            flush_target(ctx, t)
            return "found"
        # 尸体:[FIX] 仅 dice4==9(10%)进入检索;原 `>` 与常量 9 恒假 → 100% 发现
        dice4 = util.dice(ctx.rng, 10)
        if dice4 < config.CORPSE_FIND_RATE:
            continue
        if not _corpse_has_loot(t):
            continue
        t["corpse_found"] = 1
        t["found_by"] = ctx.player["id"]
        flush_target(ctx, t)
        _corpse_discover(ctx, t)
        return "found"
    return None


def _corpse_has_loot(t):
    if t["wep_name"] != "空手" or t["bou_name"] != "内衣":
        return True
    for prefix in ("bouh", "bouf", "boua"):
        if t[f"{prefix}_name"]:
            return True
    return any(i for i in t["items"])


def _corpse_discover(ctx, t):
    texts = ctx.texts
    ctx.log(texts["messages"]["corpse_found"].format(
        f_name=t["f_name"], l_name=t["l_name"]))
    desc_table = texts["corpse"]
    desc = texts["corpse_default"]
    for key, variants in desc_table.items():
        if key in (t["death_type"] or ""):
            desc = variants[t["corpse_desc"] or 0]
            break
    ctx.log(desc + "<br>")
    ctx.log(texts["messages"]["corpse_tail"])
    ctx.view = "loot"
    ctx.extras["loot"] = _loot_menu(ctx.player, t)


def _battle_menu(p, t):
    """先制攻击菜单(对等 lib2.cgi COMMAND BATTLE0)。"""
    options = []
    code = p["wep_code"]
    cls = weapon_class(code)
    ammo = p["wep_uses"]
    label = {"WB": "殴", "WP": "殴", "WG": "击", "WA": "射", "WN": "斩",
             "WS": "刺", "WC": "投", "WD": "投"}
    profs = dict(wn=p["prof_wn"], wp=p["prof_wp"], wa=p["prof_wa"], wg=p["prof_wg"],
                 wc=p["prof_wc"], wd=p["prof_wd"], wb=p["prof_wb"], ws=p["prof_ws"])
    if cls in ("G", "A") and not ammo:
        options.append(("殴", profs["wb"]))
    else:
        options.append((label.get("W" + cls, "殴"), profs[util.prof_key(cls)]))
    return dict(target=dict(id=t["id"], name=f"{t['f_name']} {t['l_name']}",
                            class_name=t["class_name"], sex=t["sex"],
                            class_no=t["class_no"]),
                options=options)


def _loot_menu(p, t):
    """搜刮菜单(对等 BATTLE2/DEATHGET;[FIX] GET_$i] 修复)。"""
    slots = []
    if t["wep_name"] != "空手":
        slots.append(dict(slot="weapon", name=t["wep_name"], eff=t["wep_att"],
                          uses=t["wep_uses"]))
    if t["bou_name"] != "内衣":
        slots.append(dict(slot="body", name=t["bou_name"], eff=t["bou_def"],
                          uses=t["bou_uses"]))
    for key, label in (("bouh", "头"), ("bouf", "足"), ("boua", "腕")):
        if t[f"{key}_name"]:
            slots.append(dict(slot=key, name=t[f"{key}_name"],
                              eff=t[f"{key}_def"], uses=t[f"{key}_uses"]))
    for i, it in enumerate(t["items"]):
        if it:
            slots.append(dict(slot=i, name=it["name"], eff=it["eff"], uses=it["uses"]))
    return dict(target=dict(id=t["id"], name=f"{t['f_name']} {t['l_name']}"),
                slots=slots)


# ---------- 武器处理(attack.cgi WEPTREAT) ----------

_VERB = {
    "WB": "朝{d}打了过去！", "WP": "朝{d}一拳打了过去！", "WA": "瞄准{d}射了出去！",
    "WC": "朝{d}扔了过去！", "WD": "朝{d}扔了过去！", "WG": "瞄准{d}射击！",
    "WN": "朝{d}斩了过去！", "WS": "朝{d}刺了过去！",
}

_INJURY_PARTS = {
    "WB": (15, "头腕"), "WA": (20, "头腕腹足"), "WC": (15, "头腕"),
    "WD": (15, "头腕足"), "WG": (25, "头腕腹足"), "WN": (25, "头腕腹足"),
    "WS": (25, "头腕腹足"), "WP": (0, ""),
}


def weptreat(ctx, attacker, defender, is_pc_attacker, ind):
    """一次挥击的武器处理。直接结算:熟练度+1、枪声日志、防御方防具代伤。
    返回 (wk, hakaiinf, kega_text, weapon_destroyed, defender_injury):
    后两项为"命中才生效"的待定结果(对等原版 wep_2/w_inf_2)。
    """
    a_name = attacker["l_name"]
    d_name = defender["l_name"]
    cls = weapon_class(attacker["wep_code"])
    empty_ranged = cls in ("G", "A") and not attacker["wep_uses"]
    if (cls == "B" and attacker["wep_name"] != "空手") or empty_ranged:
        eff = "WB"
    else:
        eff = "W" + cls
    verb = _VERB.get(eff, "朝{d}打了过去！").format(d=d_name)
    ctx.log(f"{a_name}的{ind}！用{attacker['wep_name']}{verb}")

    prof_col = f"prof_{util.prof_key(eff[1])}"
    attacker[prof_col] = attacker[prof_col] + 1
    wk = util.prof_wk(attacker[prof_col])

    if eff == "WG":    # 枪声
        add_sense(ctx.conn, ctx.game["id"], ctx.now,
                  ctx.now + config.SENSE_GUNSHOT_SECS, "place", attacker["place"],
                  "gunshot", attacker["id"], defender["id"])

    kega, parts = _INJURY_PARTS[eff]
    hakai = 3 if eff in ("WB", "WA", "WG", "WN", "WS") else 0

    # 武器破坏(命中才应用)
    destroyed = util.dice(ctx.rng, 100) < hakai and attacker["wep_name"] != "空手"
    hakaiinf = "武器打坏了！" if destroyed else ""

    # 负伤判定([FIX] rand(4) 使"足"可出现)
    injury = None
    kega_text = ""
    if util.dice(ctx.rng, 100) < kega:
        part = ["头", "腕", "腹", "足"][util.dice(ctx.rng, 4)]
        if part in parts:
            # 防具代伤(直接生效)
            acc = defender["items"][5] if defender["items"] else None
            if part == "腹" and ((acc and "AD" in acc["code"]) or "DB" in defender["bou_code"]):
                if acc and "AD" in acc["code"]:
                    # [FIX] uses=None(∞)不扣减(原 `(x or 0)-1` 会把 ∞ 一次耗尽)
                    if acc["uses"] is not None:
                        acc["uses"] -= 1
                        if acc["uses"] <= 0:
                            defender["items"][5] = None
                else:
                    defender["bou_uses"] = (defender["bou_uses"] or 0) - 1 \
                        if defender["bou_uses"] is not None else None
                    if defender["bou_uses"] is not None and defender["bou_uses"] <= 0:
                        defender.update(bou_name="内衣", bou_code="DN",
                                        bou_def=0, bou_uses=None)
            elif part == "头" and "DH" in defender["bouh_code"]:
                defender["bouh_uses"] = (defender["bouh_uses"] or 0) - 1
                if defender["bouh_uses"] <= 0:
                    defender.update(bouh_name="", bouh_code="", bouh_def=0, bouh_uses=None)
            elif part == "足" and "DF" in defender["bouf_code"]:
                defender["bouf_uses"] = (defender["bouf_uses"] or 0) - 1
                if defender["bouf_uses"] <= 0:
                    defender.update(bouf_name="", bouf_code="", bouf_def=0, bouf_uses=None)
            elif part == "腕" and "DA" in defender["boua_code"]:
                defender["boua_uses"] = (defender["boua_uses"] or 0) - 1
                if defender["boua_uses"] <= 0:
                    defender.update(boua_name="", boua_code="", boua_def=0, boua_uses=None)
            else:
                injury = part
                kega_text = f"{part}部受伤"
    return wk, hakaiinf, kega_text, destroyed, injury


# ---------- 防具相性(attack.cgi DEFTREAT;[FIX] 死代码分支实现) ----------

def deftreat(attack_code, defender):
    """伤害倍率 pnt(按武器码判定,对等原版 eq 匹配;空枪空弓按 B 类)。"""
    cls = weapon_class(attack_code)
    acc = defender["items"][5] if defender["items"] else None
    acc_code = acc["code"] if acc else ""
    head = defender["bouh_code"]
    body = defender["bou_code"]
    if cls == "G":
        if acc_code == "ADB":
            return 0.5
        if head == "DH":
            return 1.5
    elif cls == "N":
        if body == "DBK":
            return 0.5
        if acc_code == "ADB":
            return 1.5
    elif cls == "B":
        if head == "DH":
            return 0.5
        if body == "DBA":       # [FIX] 原版 $b_kind_b 未定义
            return 1.5
    elif cls == "S":
        if body == "DBA":       # [FIX]
            return 0.5
        if body == "DBK":       # [FIX]
            return 1.5
    return 1.0


# ---------- 弹药/损耗(attack.cgi 167-173) ----------

def weapon_consume(ctx, p):
    """攻击后的武器损耗:枪弓弹药-1;投掷/爆武器-1(尽则空手);
    含 N 的斩系(含 WNS 双属性刀)20% 卷刃 1~2(attack.cgi 167-173)。"""
    code = p["wep_code"]
    cls = weapon_class(code)
    if cls in ("G", "A") and p["wep_uses"]:
        p["wep_uses"] -= 1
    elif cls in ("C", "D"):
        uses = (p["wep_uses"] or 0) - 1
        if uses <= 0:
            p.update(wep_name="空手", wep_code="WP", wep_att=0, wep_uses=None)
        else:
            p["wep_uses"] = uses
    elif "N" in code and util.dice(ctx.rng, 5) == 0:
        p["wep_att"] -= util.rand_int(ctx.rng, 1, 2)
        if p["wep_att"] <= 0:
            p.update(wep_name="空手", wep_code="WP", wep_att=0, wep_uses=None)


def _apply_destroyed(p):
    p.update(wep_name="空手", wep_code="WP", wep_att=0, wep_uses=None)


def _add_injury(p, part):
    inf = (p["injuries"] or "")
    p["injuries"] = inf.replace(part, "") + part


# ---------- 伤害公式 ----------

def damage(ctx, att_p, wk, def_p, pnt):
    """(att_p×wk − def_p)/2 + rand(0,that),再乘 pnt,保底 1。"""
    result = (att_p * wk) - def_p
    result /= 2
    result += ctx.rng.random() * result if result > 0 else 0
    result = int(result * pnt)
    return max(result, 1)


# ---------- 敌方离线恢复(attack.cgi EN_KAIFUKU:每分钟 1 耐力 / 每 2 分钟 1HP) ----------

def en_kaifuku(ctx, t):
    if t["rest_since"] is None:
        return
    up = int((ctx.now - t["rest_since"]) / 60)
    if "腹" in (t["injuries"] or ""):
        up = int(up / 2)
    if t["status"] == "sleeping":
        t["sta"] = min(t["sta"] + up, config.MAXSTA)
        t["rest_since"] = ctx.now
    elif t["status"] == "healing":
        t["hit"] = min(t["hit"] + int(up / 2), t["mhit"])
        t["rest_since"] = ctx.now


# ---------- 交战解算(ATTACK1/ATTACK2) ----------

def _stamp():
    return datetime.datetime.now().strftime("%H:%M:%S")


def resolve_exchange(ctx, target, player_first, dengon):
    """一次完整交战:先手攻击 → (存活则)反击。写双方状态与日志。"""
    p = ctx.player
    t = target
    p_tact = tactget(p)
    t_tact = tactget(t)
    att_p = attack_power(p, p_tact)
    def_p = defense_power(p, p_tact)
    att_n = attack_power(t, t_tact)
    def_n = defense_power(t, t_tact)
    en_kaifuku(ctx, t)

    p["bid"] = t["id"]
    t["bid"] = p["id"]

    if dengon:
        dengon = util.esc(dengon.strip()[:64])
        ctx.log(f"<span class=\"lime\"><b>{p['f_name']} {p['l_name']}"
                f"（{p['class_name']} {p['sex']}{p['class_no']}号）「{dengon}」</b></span><br>")
        t["log"] += (f"<span class=\"lime\"><b>{_stamp()} {p['f_name']} {p['l_name']}"
                     f"（{p['class_name']} {p['sex']}{p['class_no']}号）「{dengon}」</b></span><br>")

    def swing(attacker, defender, tact_a, att_val, def_val, ind):
        """一次攻击。返回 (hit, result, kega_text, hakaiinf, injury, destroyed)。"""
        is_pc = attacker is p
        wk, hakaiinf, kega_text, destroyed, injury = weptreat(
            ctx, attacker, defender, is_pc, ind)
        # [FIX] 命中方用攻击方自身命中率(原版 ATTACK2 敌方误用玩家 mei)
        mei = tact_a["mei"]
        if util.dice(ctx.rng, 100) < mei:
            pnt = deftreat(attacker["wep_code"], defender)
            result = damage(ctx, att_val, wk, def_val, pnt)
            ctx.log(f"<span class=\"red\"><b>{result}损害 {hakaiinf} {kega_text}</b></span>！<br>")
            if destroyed:
                _apply_destroyed(attacker)
            if injury:
                _add_injury(defender, injury)
            return True, result, kega_text, hakaiinf, injury, destroyed
        ctx.log("但是、就差一点，被躲开了！" + (f"{hakaiinf}" if hakaiinf else "") + "<br>")
        return False, 0, "", hakaiinf, None, False

    def after_swing(attacker):
        weapon_consume(ctx, attacker)

    report = dict(p_att=0, p_taken=0)
    if player_first:
        first_atk, first_def = p, t
        first_tact, first_attv, first_defv = p_tact, att_p, def_n
        second_atk, second_tact, second_attv, second_defv = t, t_tact, att_n, def_p
        first_ind, second_ind = "攻击", "反击"
    else:
        first_atk, first_def = t, p
        first_tact, first_attv, first_defv = t_tact, att_n, def_p
        second_atk, second_tact, second_attv, second_defv = p, p_tact, att_p, def_n
        first_ind, second_ind = "攻击", "反击"

    # 先手
    hit, result, kega, hakai, injury, _ = swing(
        first_atk, first_def, first_tact, first_attv, first_defv, first_ind)
    if hit:
        first_def["hit"] -= result
        btai = first_def["bou_uses"]
        if btai is not None:
            first_def["bou_uses"] = btai - 1
            if first_def["bou_uses"] <= 0:
                first_def.update(bou_name="内衣", bou_code="DN", bou_def=0, bou_uses=None)
        first_atk["exp"] += 1
        if first_atk is p:
            report["p_att"] = result
        else:
            report["p_taken"] = result
    after_swing(first_atk)

    first_dead = first_def["hit"] <= 0
    if first_dead:
        _resolve_death(ctx, first_atk, first_def)
        _lvup_check(ctx, p)
        _lvup_check(ctx, t)
        return report

    # 反击意愿(50%)且射程相同
    if util.dice(ctx.rng, 10) < config.COUNTER_RATE:
        defender2 = p if second_atk is t else t
        if p_tact["weps"] == t_tact["weps"]:
            hit2, result2, kega2, hakai2, injury2, _ = swing(
                second_atk, defender2,
                second_tact, second_attv, second_defv, second_ind)
            if hit2:
                defender2["hit"] -= result2
                btai = defender2["bou_uses"]
                if btai is not None:
                    defender2["bou_uses"] = btai - 1
                    if defender2["bou_uses"] <= 0:
                        defender2.update(bou_name="内衣", bou_code="DN",
                                         bou_def=0, bou_uses=None)
                second_atk["exp"] += 1
                if second_atk is p:
                    report["p_att"] = result2
                else:
                    report["p_taken"] = result2
            after_swing(second_atk)
            if defender2["hit"] <= 0:
                _resolve_death(ctx, second_atk, defender2)
            else:
                ctx.log(f"{defender2['l_name']} 逃走了。<br>")
        else:
            ctx.log(f"{second_atk['l_name']} 不能反击！<br>")
            ctx.log(f"{second_atk['l_name']} 逃走了。<br>")
    else:
        ctx.log(f"{first_def['l_name']} 逃走了。<br>")

    # 战报写入双方日志
    line = (f"<span class=\"yellow\"><b>{_stamp()} 战斗：{p['f_name']} {p['l_name']}"
            f"（{p['class_name']} {p['sex']}{p['class_no']}号） "
            f"攻:{report['p_att']} 被:{report['p_taken']}</b></span><br>")
    t["log"] += line
    _blog_ck(t)
    _lvup_check(ctx, p)
    _lvup_check(ctx, t)
    return report


def _blog_ck(t):
    """战斗日志超长自动删除(原版 >2000 字节;UTF-8 下按 2000 字符)。"""
    if len(t["log"]) > 2000:
        t["log"] = (f"<span class=\"yellow\"><b>{_stamp()} 战斗日志已自动删除。</b>"
                    f"</span><br>")


def _lvup_check(ctx, p):
    if p["hit"] > 0 and p["exp"] >= util.next_exp(p["level"]):
        p["mhit"] += ctx.rng.randint(7, 9)
        p["att"] += ctx.rng.randint(2, 4)
        p["deff"] += ctx.rng.randint(2, 4)
        p["level"] += 1
        if p is ctx.player:
            ctx.log("等级上升了。<br>")
        else:
            p["log"] += "等级上升了。<br>"


def _resolve_death(ctx, killer, victim):
    """战斗死亡(killer 杀 victim;双方均可能是玩家或对手)。"""
    p = ctx.player
    t = victim if victim is not p else None
    victim_name = f"{victim['f_name']} {victim['l_name']}"
    killer["kill"] += 1
    victim["corpse_desc"] = ctx.rng.randrange(7)
    ctx.log(f"<span class=\"red\"><b>{victim_name}（{victim['class_name']} "
            f"{victim['sex']}{victim['class_no']}号）已经死亡。</b></span><br>")
    if victim is not p and len(victim["dmes"] or "") > 1:
        ctx.log(f"<span class=\"yellow\"><b>{victim_name}『{util.esc(victim['dmes'])}』</b></span><br>")
    if killer is p and len(p["msg"] or "") > 1:
        ctx.log(f"<span class=\"lime\"><b>{p['f_name']} {p['l_name']}『{util.esc(p['msg'])}』</b></span><br>")
    # 悲鸣感知(案发现场)
    add_sense(ctx.conn, ctx.game["id"], ctx.now,
              ctx.now + config.SENSE_SCREAM_SECS, "place", victim["place"],
              "scream", victim["id"], killer["id"])
    # 死因词(按凶器);凶手为政府系时死因不带班级(对等 lib.cgi:101-104)
    word = util.death_word_by_weapon(killer["wep_code"])
    if killer["is_government"]:
        phrase = f"被{killer['f_name']} {killer['l_name']}{word}"
    else:
        phrase = (f"被{killer['f_name']} {killer['l_name']}"
                  f"（{killer['class_name']} {killer['sex']}{killer['class_no']}号）{word}")
    kill_player(ctx.conn, ctx.game, victim, ctx.now, ctx.texts, ctx.rng,
                death_type=phrase, killer=killer)
    if victim is p:
        ctx.dead = True
        ctx.view = "dead"
    else:
        # 击杀者可搜刮一次(对等原版 BATTLE2;w_bid 置空)
        victim["bid"] = None
        victim["found_by"] = killer["id"]
        victim["corpse_found"] = 0
        ctx.view = "loot"
        ctx.extras["loot"] = _loot_menu(ctx.player, victim)


# ---------- 命令入口 ----------

def cmd_attack(ctx, args):
    """玩家先制攻击(ATTACK1)/逃亡(RUNAWAY)。"""
    if args.get("run"):
        ctx.log(f"{ctx.player['l_name']} 飞快的逃走了。<br>")
        return
    try:
        target_id = int(args.get("target_id", 0))
    except (TypeError, ValueError):
        raise CmdError("不正确的存取。")
    t = load_battle_target(ctx, target_id)
    if t["bid"] == ctx.player["id"] and t["hit"] > 0:
        raise CmdError("不正确的存取。")
    if t["place"] != ctx.player["place"]:
        ctx.log(f"{t['f_name']} {t['l_name']}（{t['class_name']} {t['sex']}"
                f"{t['class_no']}号）逃走了！<br>")
        return
    if t["hit"] <= 0 and t["status"] == "dead":
        # 对尸体"攻击"→ 搜刮视图(需同地,上面已校验):
        # 已发现(corpse_found)、无主尸体(无击杀者)或击杀者/发现者本人可进;
        # [FIX] 其余未发现尸体不可凭 target_id 直接进入(对等原版 ATTACK1 拒绝死靶)
        if t["corpse_found"] or t["found_by"] is None \
                or t["found_by"] == ctx.player["id"]:
            _corpse_discover(ctx, t)
            flush_target(ctx, t)
            return
        raise CmdError("不正确的存取。")
    ctx.log(f"{t['f_name']} {t['l_name']}（{t['class_name']} {t['sex']}"
            f"{t['class_no']}号）战斗开始！<br>")
    resolve_exchange(ctx, t, player_first=True, dengon=args.get("dengon", ""))
    flush_target(ctx, t)


def cmd_loot(ctx, args):
    """搜刮/夺装(WINGET;[FIX] GET_$i])。仅限同地目标(对等原版 BB_CK)。"""
    p = ctx.player
    try:
        target_id = int(args.get("target_id", 0))
    except (TypeError, ValueError):
        raise CmdError("不正确的存取。")
    slot = args.get("slot", "")
    t = load_battle_target(ctx, target_id)
    # 背包需有空位
    if ctx.first_empty(0, 4) == -1:
        ctx.log("没办法再携带更多物品了。<br>")
        return
    if t["id"] == p["id"]:
        ctx.log("试着抢夺了自己的物品。<br>真是空虚???。<br>")
        return
    # 同地校验(审查 #3:防远程搜刮)
    if t["place"] != p["place"]:
        raise CmdError("不正确的存取。")
    # 对等原版 WINGET:活着 或 (bid 指向我且非"已发现"尸体=我已搜刮过一次) → 拒绝
    if t["hit"] > 0 or (t["bid"] == p["id"] and not t["corpse_found"]):
        ctx.log(f"强烈地念叨着想要{t['f_name']}的那件物品。<br>真是空虚???。<br>")
        return
    # [FIX] 与 cmd_attack 的死靶守卫对称:未发现且非击杀者的尸体不可直接搜刮,
    # 否则可凭枚举 target_id 绕过尸体发现掷骰(无击杀者尸体 corpse_found
    # 恒可进,对等 cmd_attack)
    if not (t["corpse_found"] or t["found_by"] is None
            or t["found_by"] == p["id"]):
        raise CmdError("不正确的存取。")

    got = None
    if slot == "weapon":
        got = dict(name=t["wep_name"], code=t["wep_code"], eff=t["wep_att"],
                   uses=t["wep_uses"])
        t.update(wep_name="空手", wep_code="WP", wep_att=0, wep_uses=None)
    elif slot == "body":
        got = dict(name=t["bou_name"], code=t["bou_code"], eff=t["bou_def"],
                   uses=t["bou_uses"])
        t.update(bou_name="内衣", bou_code="DN", bou_def=0, bou_uses=None)
    elif slot in ("bouh", "bouf", "boua"):
        got = dict(name=t[f"{slot}_name"], code=t[f"{slot}_code"],
                   eff=t[f"{slot}_def"], uses=t[f"{slot}_uses"])
        t.update({f"{slot}_name": "", f"{slot}_code": "",
                  f"{slot}_def": 0, f"{slot}_uses": None})
    else:
        try:
            idx = int(slot)
        except (TypeError, ValueError):
            raise CmdError("不正确的存取。")
        if not (0 <= idx < 6):
            raise CmdError("不正确的存取。")
        it = t["items"][idx]
        if it is None:
            ctx.log("放弃了拾取。<br>")
            t["bid"] = p["id"]
            flush_target(ctx, t)
            return
        got = it
        t["items"][idx] = None

    # [FIX] 空槽守卫(对等原版 WINGET:空/空手/内衣 放弃拾取,不生成垃圾物品)
    if got["name"] in ("空手", "内衣", ""):
        ctx.log("放弃了拾取。<br>")
        t["bid"] = p["id"]
        flush_target(ctx, t)
        return

    dest = ctx.first_empty(0, 4)
    ctx.set_item(dest, got["name"], got["code"], got["eff"], got["uses"])
    ctx.log(f"{p['l_name']} 得到了{got['name']}。<br>")
    t["bid"] = p["id"]      # 标记:非发现者尸体仅可搜刮一件(对等原版)
    flush_target(ctx, t)
    ctx.view = "main"
