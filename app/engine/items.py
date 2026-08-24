"""物品系统:拾取/使用/装备/丢弃/整理/合成/特殊物品。

逐条对等 lib/item.cgi / itemsei.cgi / itemgou.cgi / poison.cgi / hack.cgi / speaker.cgi。
[FIX] 原版 int(rand($#list)) off-by-one:拾取改为全列表均匀。
"""
from .. import config
from . import util
from .news import add_sense
from .death import kill_player


class CmdError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


# ---------- 拾取(ITEMGET) ----------

def itemget(ctx):
    """从当前区域物品池随机拾取 1 件。返回 True 表示有发现。"""
    rows = ctx.conn.execute(
        "SELECT * FROM area_items WHERE game_id=? AND place=?",
        (ctx.game["id"], ctx.player["place"])).fetchall()
    if not rows:
        ctx.log("这个区域已经什么都没有了吗????<BR>")
        return True
    # [FIX] 均匀抽取全列表(原版抽不到最后一行)
    work = ctx.rng.randrange(len(rows))
    row = rows[work]
    name, code, eff, uses = row["name"], row["code"], row["eff"], row["uses"]

    if code == "TO":    # 陷阱(触发即从池中移除)
        ctx.conn.execute("DELETE FROM area_items WHERE id=?", (row["id"],))
        result = util.rand_int(ctx.rng, eff // 2, eff - 1) if eff > 1 else eff // 2
        ctx.log(f"是陷阱！被事先设好的 {name} 弄伤，"
                f"受到了<span class=\"red\"><b>{result}点损害</b></span>！<BR>")
        ctx.player["hit"] -= result
        if ctx.player["hit"] <= 0:
            ctx.player["hit"] = 0
            _dead_line(ctx)
            kill_player(ctx.conn, ctx.game, ctx.player, ctx.now,
                        ctx.texts, ctx.rng, death_type=config.DEATH_WEAK)
            ctx.dead = True
        return True

    # 找空位或可堆叠位(0-4 背包;饰品位 5 不参与拾取——原版循环 0..4)
    slot = -1
    for i in range(5):
        it = ctx.item_at(i)
        if it is None:
            slot = i
            break
        if it["name"] == name and it["code"] == code and (
                "WC" in code or "TN" in code or "子弹" in name or "箭" in name):
            slot = i
            break

    if slot == -1:
        # 满包:物品留在区域池(对等原版:splice 仅在内存,满包分支不写回文件)
        ctx.log(f"发现了{name}。但是，背包已经装不下了。<BR>只好放弃了{name}???。<BR>")
        return True
    ctx.conn.execute("DELETE FROM area_items WHERE id=?", (row["id"],))

    sub = _pickup_hint(code)
    ctx.log(f"发现了{name}。{sub}<BR>")
    it = ctx.item_at(slot)
    if it is None:
        ctx.set_item(slot, name, code, eff, uses)
    elif ("子弹" in name) or ("箭" in name):
        it["eff"] += eff
    else:
        it["uses"] = (it["uses"] or 0) + (uses or 0)
    return True


def _pickup_hint(code):
    if "HH" in code:
        return "吃下去的话体力好像能恢复。"
    if "SH" in code or "SD" in code:
        return "吃下去的话精力和体力好像都能恢复。"
    if code.startswith("W"):
        return "这家伙好像能当武器用。"
    if code.startswith("D"):
        return "这家伙好像能当防具用。"
    if code.startswith("A"):
        return "这家伙好像可以佩戴在身上。"
    if "TN" in code:
        return "用这个好像能设置陷阱。"
    return "肯定能派上什么用场吧。"


# ---------- 使用/装备(ITEM) ----------

def use_item(ctx, slot):
    p = ctx.player
    it = ctx.item_at(slot)
    if it is None:
        raise CmdError(ctx.msg["bad_access"])
    name, code, eff, uses = it["name"], it["code"], it["eff"], it["uses"]

    def consume():
        if uses is None:      # ∞
            return
        uses2 = (it["uses"] or 0) - 1
        if uses2 <= 0:
            ctx.set_item(slot, None, "", 0, 0)
        else:
            it["uses"] = uses2

    if "SH" in code:      # 精力恢复
        ctx.log(f"使用了{name}。<BR>精力恢复了<BR>")
        p["sta"] = min(p["sta"] + eff, config.MAXSTA)
        consume()
    elif "HH" in code:    # 体力恢复
        ctx.log(f"使用了{name}。<BR>体力恢复了<BR>")
        p["hit"] = min(p["hit"] + eff, p["mhit"])
        consume()
    elif "SD" in code or "HD" in code:   # 有毒
        result = int(eff * 1.5) if code in ("SD2", "HD2") else eff
        p["hit"] -= result
        ctx.log(f"唔???糟糕！好像被掺进了毒物！<span class=\"red\"><b>{result}点损害</b></span>！<BR>")
        consume()
        if p["hit"] <= 0:
            p["hit"] = 0
            _dead_line(ctx)
            kill_player(ctx.conn, ctx.game, ctx.player, ctx.now,
                        ctx.texts, ctx.rng, death_type=config.DEATH_POISON)
            ctx.dead = True
    elif code.startswith("W"):     # 武器装备(与手中互换)
        ctx.log(f"装备了{name}。<BR>")
        old = (p["wep_name"], p["wep_code"], p["wep_att"], p["wep_uses"])
        p["wep_name"], p["wep_code"], p["wep_att"], p["wep_uses"] = name, code, eff, uses
        if old[0] != "空手":
            ctx.set_item(slot, *old)
        else:
            ctx.set_item(slot, None, "", 0, 0)
    elif "DB" in code:             # 身体防具
        ctx.log(f"把{name}穿在了身上。<BR>")
        old = (p["bou_name"], p["bou_code"], p["bou_def"], p["bou_uses"])
        p["bou_name"], p["bou_code"], p["bou_def"], p["bou_uses"] = name, code, eff, uses
        if old[0] != "内衣":
            ctx.set_item(slot, *old)
        else:
            ctx.set_item(slot, None, "", 0, 0)
    elif "DH" in code:             # 头部
        _equip_part(ctx, slot, "bouh", "头上")
    elif "DF" in code:             # 足部
        _equip_part(ctx, slot, "bouf", "脚上")
    elif "DA" in code:             # 腕部
        _equip_part(ctx, slot, "boua", "手腕上")
    elif code.startswith("A"):     # 饰品(装入 5 号位)
        ctx.log(f"把{name}佩戴上了。<BR>")
        old = ctx.item_at(5)
        ctx.set_item(5, name, code, eff, uses)
        if old is not None:
            ctx.set_item(slot, old["name"], old["code"], old["eff"], old["uses"])
        else:
            ctx.set_item(slot, None, "", 0, 0)
    elif code == "R1" or code == "R2":     # 雷达
        from .radar import build_radar
        ctx.view = "radar"
        ctx.extras["radar"] = build_radar(ctx, full=(code == "R2"))
    elif "TN" in code:             # 陷阱设置
        ctx.log(f"把{name}设成了陷阱。自己也得小心点???。<BR>")
        ctx.conn.execute(
            "INSERT INTO area_items(game_id, place, name, code, eff, uses, trap, "
            "owner_id, created_at) VALUES(?,?,?,?,?,?,1,?,?)",
            (ctx.game["id"], p["place"], name, "TO", eff, uses,
             p["id"], ctx.now))
        consume()
    elif name in ("磨刀石", "破布") and p["wep_code"] == "WN":
        p["wep_att"] = min(p["wep_att"] + eff, 30)
        ctx.log(f"使用了{name}。{p['wep_name']}的攻击力变成了 {p['wep_att']}。<BR>")
        consume()
    elif name == "缝纫工具" and p["bou_code"] == "DBN" and p["bou_name"] != "内衣":
        p["bou_uses"] = min((p["bou_uses"] or 0) + eff, 30)
        ctx.log(f"使用了{name}。{p['bou_name']}的耐久力变成了 {p['bou_uses']}。<BR>")
        consume()
    elif name == "子弹" and "G" in p["wep_code"]:
        up = _load_ammo(ctx, slot, eff)
        if "WGB" in p["wep_code"]:
            p["wep_code"] = p["wep_code"].replace("WGB", "WG")
        ctx.log(f"给{p['wep_name']}装填了{name}。<BR>{p['wep_name']}的使用次数提升了 {up}。<BR>")
    elif "箭" in name and "A" in p["wep_code"]:
        up = _load_ammo(ctx, slot, eff)
        if "WAB" in p["wep_code"]:
            p["wep_code"] = p["wep_code"].replace("WAB", "WA")
        ctx.log(f"用{name}给{p['wep_name']}补充完毕。<BR>{p['wep_name']}的使用次数提升了 {up}。<BR>")
    elif "电池" in name:
        _charge_laptop(ctx, slot)
    elif name == "程序解除钥匙":
        if p["place"] == 0:
            p["key_flag"] = 1
            ctx.log("用解除钥匙停止了程序。<br>颈环脱落了！<BR>")
            _trigger_ex_end(ctx)
        else:
            ctx.log("在这里使用也没有意义???。<BR>")
    else:
        ctx.log("这玩意是干什么用的呢???。<BR>")


def _equip_part(ctx, slot, prefix, where):
    p = ctx.player
    it = ctx.item_at(slot)
    ctx.log(f"把{it['name']}戴在了{where}。<BR>" if where != "脚上"
            else f"把{it['name']}穿在了脚上。<BR>")
    old_name = p[f"{prefix}_name"]
    old = (old_name, p[f"{prefix}_code"], p[f"{prefix}_def"], p[f"{prefix}_uses"])
    p[f"{prefix}_name"] = it["name"]
    p[f"{prefix}_code"] = it["code"]
    p[f"{prefix}_def"] = it["eff"]
    p[f"{prefix}_uses"] = it["uses"]
    if old_name:
        ctx.set_item(slot, *old)
    else:
        ctx.set_item(slot, None, "", 0, 0)


def _load_ammo(ctx, slot, eff):
    p = ctx.player
    cur = p["wep_uses"] or 0
    up = eff if cur + eff <= 6 else 6 - cur
    if up < 0:
        up = 0
    p["wep_uses"] = cur + up
    it = ctx.item_at(slot)
    it["eff"] -= up
    if it["eff"] <= 0:
        ctx.set_item(slot, None, "", 0, 0)
    return up


def _charge_laptop(ctx, slot):
    for i in range(5):
        it = ctx.item_at(i)
        if it and it["name"] == "笔记本电脑" and (it["uses"] or 0) < 5:
            it["uses"] = min((it["uses"] or 0) + ctx.item_at(slot)["eff"], 5)
            src = ctx.item_at(slot)
            src_uses = (src["uses"] or 0) - 1
            if src_uses <= 0:
                ctx.set_item(slot, None, "", 0, 0)
            else:
                src["uses"] = src_uses
            ctx.log(f"用{src['name'] if src else '电池'}给笔记本电脑充上了电。"
                    f"笔记本电脑的使用次数变成了 {it['uses']}。<BR>")
            return
    ctx.log("这玩意是干什么用的呢???。<BR>")


def _trigger_ex_end(ctx):
    """程序解除钥匙:全员逃生结局(EX_END)。"""
    from .news import add_news
    p = ctx.player
    ctx.conn.execute("UPDATE games SET status='finished_escape', end_reason='程序解除' "
                     "WHERE id=?", (ctx.game["id"],))
    ctx.game["status"] = "finished_escape"
    add_news(ctx.conn, ctx.game["id"], ctx.now, "EX_END", subject_id=p["id"],
             extra=dict(),
             text=f"{p['f_name']} {p['l_name']} 使程序紧急停止了！")
    ctx.view = "ending_escape"


def _dead_line(ctx):
    p = ctx.player
    ctx.log(f"<span class=\"red\"><b>{p['f_name']} {p['l_name']}"
            f"（{p['class_name']} {p['sex']}{p['class_no']}号）死亡了。</b></span><br>")


# ---------- 丢弃/卸下(ITEMDEL/WEPDEL/WEPDEL2) ----------

def drop_item(ctx, slot):
    it = ctx.item_at(slot)
    if it is None:
        raise CmdError(ctx.msg["bad_access"])
    ctx.log(f"丢掉了{it['name']}。<br>")
    ctx.conn.execute(
        "INSERT INTO area_items(game_id, place, name, code, eff, uses, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (ctx.game["id"], ctx.player["place"], it["name"], it["code"],
         it["eff"], it["uses"], ctx.now))
    ctx.set_item(slot, None, "", 0, 0)


def unequip_weapon(ctx):
    p = ctx.player
    if p["wep_name"] == "空手":
        ctx.log(f"{p['l_name']}没有装备武器。<br>")
        return
    slot = ctx.first_empty(0, 4)
    if slot == -1:
        ctx.log("背包已经装不下了。<br>")
        return
    ctx.log(f"{p['wep_name']}已经取下来了。<br>")
    ctx.set_item(slot, p["wep_name"], p["wep_code"], p["wep_att"], p["wep_uses"])
    p["wep_name"], p["wep_code"], p["wep_att"], p["wep_uses"] = "空手", "WP", 0, None


def drop_weapon(ctx):
    p = ctx.player
    if p["wep_name"] == "空手":
        ctx.log(f"{p['l_name']}没有装备武器。<br>")
        return
    ctx.log(f"丢掉了{p['wep_name']}。<br>")
    ctx.conn.execute(
        "INSERT INTO area_items(game_id, place, name, code, eff, uses, created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (ctx.game["id"], p["place"], p["wep_name"], p["wep_code"],
         p["wep_att"], p["wep_uses"], ctx.now))
    p["wep_name"], p["wep_code"], p["wep_att"], p["wep_uses"] = "空手", "WP", 0, None


# ---------- 整理(ITEMSEIRI) ----------

def sort_items(ctx, a, b):
    ia, ib = ctx.item_at(a), ctx.item_at(b)
    if ia is None or ib is None:
        raise CmdError(ctx.msg["bad_access"])
    ctx.log("整理物品。<br>")
    same_name = ia["name"] == ib["name"]
    if a == b:
        ctx.log(f"重新放好了{ia['name']}。<br>")
    elif same_name and ia["eff"] == ib["eff"] and \
            ("HH" in ia["code"] or "HD" in ia["code"]) and \
            ("HH" in ib["code"] or "HD" in ib["code"]):
        _merge_food(ctx, a, b, "HD")
    elif same_name and ia["eff"] == ib["eff"] and \
            ("SH" in ia["code"] or "SD" in ia["code"]) and \
            ("SH" in ib["code"] or "SD" in ib["code"]):
        _merge_food(ctx, a, b, "SD")
    elif same_name and ia["code"] == ib["code"] and (
            "WC" in ia["code"] or "WD" in ia["code"] or "毒药" in ia["name"]):
        ia["uses"] = (ia["uses"] or 0) + (ib["uses"] or 0)
        ctx.set_item(b, None, "", 0, 0)
        ctx.log(f"把{ia['name']}整理好了。<br>")
    elif same_name and ia["code"] == ib["code"] and ia["code"] == "Y" and \
            ("子弹" in ia["name"] or "箭" in ia["name"]):
        ia["eff"] += ib["eff"]
        ctx.set_item(b, None, "", 0, 0)
        ctx.log(f"把{ia['name']}整理好了。<br>")
    else:
        ctx.log(f"{ia['name']}和{ib['name']}没办法整理在一起。<br>")


def _merge_food(ctx, a, b, poison_code):
    """同类食物合并(对等 itemsei.cgi):耐久相加,任一侧有毒则整堆带毒(D2 优先)。"""
    ia, ib = ctx.item_at(a), ctx.item_at(b)
    ia["uses"] = (ia["uses"] or 0) + (ib["uses"] or 0)
    codes = {ia["code"], ib["code"]}
    base = "H" if poison_code == "HD" else "S"
    if f"{base}D2" in codes:
        ia["code"] = f"{base}D2"
    elif f"{base}D" in codes:
        ia["code"] = f"{base}D"
    else:
        ia["code"] = f"{base}H"
    ctx.set_item(b, None, "", 0, 0)
    ctx.log(f"把{ia['name']}整理好了。<br>")


# ---------- 合成(ITEMGOUSEI) ----------

def craft(ctx, a, b):
    ia, ib = ctx.item_at(a), ctx.item_at(b)
    if ia is None or ib is None:
        raise CmdError(ctx.msg["bad_access"])

    # 产物落位:素材单发/∞ 落素材位;防具素材落防具位;否则空位
    def armor(code):
        return any(x in code for x in ("DB", "DH", "DF", "DA"))

    j = -1
    if (ia["uses"] in (1, None)) or armor(ia["code"]):
        j = a
    elif (ib["uses"] in (1, None)) or armor(ib["code"]):
        j = b
    else:
        j = ctx.first_empty(0, 4)

    if j == -1:
        ctx.log("背包已经装不下了。<br>")
        return
    ctx.log("合成物品。<br>")
    if a == b or ia["name"] == ib["name"]:
        ctx.log(f"端详了一下{ia['name']}。<br>")
        return

    recipe = None
    for m1, m2, pname, pcode, peff, puses in config.RECIPES:
        if {ia["name"], ib["name"]} == {m1, m2}:
            recipe = (pname, pcode, peff, puses)
            break
    if recipe is None:
        ctx.log(f"{ia['name']}和{ib['name']}没办法组合起来。<br>")
        return
    pname, pcode, peff, puses = recipe
    ctx.log(f"用{ia['name']}和{ib['name']}做出了{pname}！<BR>")
    ctx.set_item(j, pname, pcode, peff, puses)

    # 素材消耗(对等原版 ITEMCOUNT):产物落在素材位则只耗另一位;
    # 防具素材整体消失,其余耐久-1
    def consume(slot):
        it = ctx.item_at(slot)
        if it is None:
            return
        if armor(it["code"]):
            ctx.set_item(slot, None, "", 0, 0)
        else:
            it["uses"] = (it["uses"] or 1) - 1
            if it["uses"] <= 0:
                ctx.set_item(slot, None, "", 0, 0)

    if a == j:
        consume(b)
    elif b == j:
        consume(a)
    else:
        consume(a)
        consume(b)


# ---------- 应急治疗(OUKYU) ----------

def first_aid(ctx, part):
    p = ctx.player
    if part not in ("头", "腕", "腹", "足") or part not in (p["injuries"] or ""):
        raise CmdError(ctx.msg["bad_access"])
    p["injuries"] = (p["injuries"] or "").replace(part, "")
    ctx.log("应急治疗完成。<br>")
    p["sta"] -= config.OKYU_STA
    if p["sta"] <= 0:
        from .game import drain
        drain(ctx, "com")


# ---------- 投毒/验毒(poison.cgi) ----------

def poison(ctx, slot):
    p = ctx.player
    poison_slot = -1
    for i in range(5):
        it = ctx.item_at(i)
        if it and it["name"] == "毒药":
            poison_slot = i
            break
    target = ctx.item_at(slot)
    if target is None or poison_slot == -1 or not any(
            x in target["code"] for x in ("SH", "HH", "SD", "HD")):
        raise CmdError(ctx.msg["bad_access"])
    po = ctx.item_at(poison_slot)
    # [FIX] uses=None(∞)不扣减(原 `(x or 0)-1` 会把 ∞ 毒药一次耗尽)
    if po["uses"] is not None:
        po["uses"] -= 1
        if po["uses"] <= 0:
            ctx.set_item(poison_slot, None, "", 0, 0)
    ctx.log(f"往{target['name']}里掺入了毒物。小心别自己吃下去???。<br>")
    base = "H" if target["code"].startswith("H") else "S"
    if p["club"] == "料理研究部":
        target["code"] = f"{base}D2"
    elif target["code"] in ("SH", "HH"):
        # 已有毒(SD/HD/D2)保持原状(对等原版正则只匹配 SH/HH)
        target["code"] = f"{base}D"


def check_poison(ctx, slot):
    p = ctx.player
    if p["club"] != "料理研究部":
        raise CmdError(ctx.msg["bad_access"])
    it = ctx.item_at(slot)
    if it is None or not any(x in it["code"] for x in ("SH", "HH", "SD", "HD")):
        raise CmdError(ctx.msg["bad_access"])
    if it["code"] in ("SH", "HH"):
        ctx.log(f"嗯？ {it['name']} 好像吃下去是安全的???。<br>")
    else:
        ctx.log(f"嗯？ {it['name']} 好像被掺入了毒物???。<br>")
    p["sta"] -= config.DOKUMI_STA
    if p["sta"] <= 0:
        from .game import drain
        drain(ctx, "com")


# ---------- 黑客(hack.cgi) ----------

def hack(ctx):
    p = ctx.player
    laptop = -1
    for i in range(5):
        it = ctx.item_at(i)
        if it and it["name"] == "笔记本电脑" and (it["uses"] or 0) >= 1:
            laptop = i
            break
    if laptop == -1:
        raise CmdError(ctx.msg["bad_access"])
    bonus = config.HACK_BONUS_PC_CLUB if "电脑" in (p["club"] or "") else config.HACK_BONUS_OTHER
    dice1 = util.dice(ctx.rng, 10)
    dice2 = util.dice(ctx.rng, 10)
    if dice1 <= bonus:
        ctx.conn.execute("UPDATE games SET hack_active=1 WHERE id=?", (ctx.game["id"],))
        ctx.game["hack_active"] = 1
        ctx.log("黑客程序成功！所有的禁止区域解除！！<BR>")
    else:
        ctx.log("黑客程序成功?<BR>")
    if dice1 >= config.HACK_BREAK_ROLL:     # 器材损坏
        ctx.set_item(laptop, None, "", 0, 0)
        ctx.log("糟糕！器材坏掉了。<BR>")
        if dice2 >= config.HACK_NECK_ROLL:  # 颈环引爆
            p["hit"] = 0
            _dead_line(ctx)
            kill_player(ctx.conn, ctx.game, ctx.player, ctx.now,
                        ctx.texts, ctx.rng, death_type=config.DEATH_GOV)
            add_sense(ctx.conn, ctx.game["id"], ctx.now,
                      ctx.now + config.SENSE_SCREAM_SECS, "place", p["place"],
                      "scream", p["id"], None)
            ctx.dead = True
    else:
        it = ctx.item_at(laptop)
        it["uses"] = (it["uses"] or 0) - 1
        if it["uses"] <= 0:
            ctx.log("笔记本电脑的电池没有电了，无法使用。<BR>")


# ---------- 扩音器(speaker.cgi) ----------

def megaphone(ctx, speech):
    p = ctx.player
    # 需实际持有扩音器(审查 M-1:原版仅靠菜单隐藏,API 层必须校验)
    has_speaker = any(it and it["name"] == "携带式扩音器"
                      for it in ctx.player["items"][:5])
    if not has_speaker:
        raise CmdError(ctx.msg["bad_access"])
    speech = util.esc((speech or "").strip()[:50])
    if not speech:
        raise CmdError("请输入广播内容。")
    ctx.log(f" {speech}<BR>")
    ctx.log(" 有没有好好传达到呢？<BR>")
    name = f"{p['f_name']} {p['l_name']}"
    add_sense(ctx.conn, ctx.game["id"], ctx.now,
              ctx.now + config.SENSE_ANNOUNCE_SECS, "island", p["place"],
              "announce", p["id"], None,
              message=f"{config.PLACE[p['place']]}|{name}|{speech}")
