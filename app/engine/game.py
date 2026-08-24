"""命令处理管线与基础命令:移动/探索/睡眠/治疗/口癖变更(对等 battle.cgi)。

管线顺序:会话校验(API 层)→ 事务 → 惰性结算(禁区推进+恢复)→ 清交战锁 →
命令分发 → 胜负/结局检查 → 回写 → 提交。
"""
from .. import config
from . import events, items, util
from .ctx import Ctx
from .time_utils import (advance_world, forbidden_places, next_forbidden_places,
                         settle_rest, check_victory)


# 引擎统一命令错误类型(items 中抛出的 CmdError 与此处同一类,API 层统一捕获)
CmdError = items.CmdError


def run_command(conn, game, player_row, cmd, args, rng, now, texts):
    """执行一条命令(整条包在 BEGIN IMMEDIATE 事务内,对等原版全局锁)。"""
    conn.execute("BEGIN IMMEDIATE")
    # [FIX] 取得写锁后无条件重读 players 行:player_row 是事务外的陈旧快照,
    # 直接使用会在 flush 时覆盖并发提交的修改(丢伤害/变相回血)
    player_row = conn.execute("SELECT * FROM players WHERE id=?",
                              (player_row["id"],)).fetchone()
    if player_row is None:
        conn.execute("ROLLBACK")
        raise CmdError("角色不存在。")
    try:
        ctx = Ctx(conn, game, player_row, rng, now, texts)
        # 惰性结算:世界推进 + 个人恢复(主动交互唤醒)
        advance_world(conn, ctx.game, now, texts, rng)
        game_row = conn.execute("SELECT * FROM games WHERE id=?", (game["id"],)).fetchone()
        if game_row:
            ctx.game.update(dict(game_row))
        # 玩家可能在日界推进中被处决:重读行,防止陈旧快照"复活"(审查 #1)
        row = conn.execute("SELECT * FROM players WHERE id=?",
                           (ctx.player["id"],)).fetchone()
        if row is not None:
            ctx.player.update(dict(row))
            if isinstance(ctx.player["items"], str):
                import json as _json
                ctx.player["items"] = _json.loads(ctx.player["items"])
        if ctx.player["status"] == "dead" or ctx.player["hit"] <= 0:
            pass                    # 下方统一转 dead 视图
        else:
            wake = settle_rest(conn, ctx.player, now, texts)
            if wake:
                ctx.log(wake)

        # 游戏结束后命令只读(对等原版:结束后一切请求进结局页)
        if ctx.game["status"] != "running":
            ctx.view = ("ending_win"
                        if ctx.game["status"] == "finished_win"
                        else "ending_escape")
        elif ctx.player["status"] == "dead" or ctx.player["hit"] <= 0:
            ctx.view = "dead"
        else:
            # 清交战锁(对等 IDCHK 末尾 bid="")
            ctx.player["bid"] = None
            _dispatch(ctx, cmd, args)

        # 死亡/胜负检查
        if not ctx.dead and ctx.view == "main":
            check_victory(conn, ctx.game, now, texts, rng)

        # 玩家收件箱日志并入响应后清空(对等原版 SAVE 写空 log)
        inbox = ctx.player["log"] or ""
        ctx.player["log"] = ""
        # 兜底:flush 前强制死亡状态一致(防任何路径回写存活态)
        if ctx.player["hit"] <= 0 and ctx.player["status"] != "dead":
            ctx.player["status"] = "dead"
        ctx.flush()
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return dict(view=ctx.view, log=ctx.action_log, inbox=inbox, extras=ctx.extras)


def _slot(args, key):
    """槽位参数解析与白名单(0-4 背包;饰品位 5 不对用户命令开放)。"""
    try:
        v = int(args.get(key, -1))
    except (TypeError, ValueError):
        raise CmdError("不正确的存取。")
    if not (0 <= v <= 4):
        raise CmdError("不正确的存取。")
    return v


def _dispatch(ctx, cmd, args):
    args = args or {}
    p = ctx.player
    if cmd == "move":
        try:
            to = int(args.get("to", -1))
        except (TypeError, ValueError):
            raise CmdError(ctx.msg["bad_access"])
        return cmd_move(ctx, to)
    if cmd == "explore":
        # 分校无探索(黑客解除禁区后例外,对等原版菜单逻辑)
        if p["place"] == 0 and not ctx.game["hack_active"]:
            raise CmdError(ctx.msg["bad_access"])
        return cmd_explore(ctx)
    if cmd == "sleep":
        if p["place"] == 0:
            raise CmdError(ctx.msg["bad_access"])
        p["status"], p["rest_since"] = "sleeping", ctx.now
        ctx.log("稍微睡一会儿。<br>")
        return
    if cmd == "heal":
        if p["place"] == 0:
            raise CmdError(ctx.msg["bad_access"])
        p["status"], p["rest_since"] = "healing", ctx.now
        ctx.log("来治疗伤口吧。<br>")
        return
    if cmd == "use_item":
        return items.use_item(ctx, _slot(args, "slot"))
    if cmd == "drop_item":
        return items.drop_item(ctx, _slot(args, "slot"))
    if cmd == "drop_weapon":
        return items.drop_weapon(ctx)
    if cmd == "unequip_weapon":
        return items.unequip_weapon(ctx)
    if cmd == "sort_pack":
        return items.sort_items(ctx, _slot(args, "a"), _slot(args, "b"))
    if cmd == "craft":
        return items.craft(ctx, _slot(args, "a"), _slot(args, "b"))
    if cmd == "first_aid":
        return items.first_aid(ctx, args.get("part", ""))
    if cmd == "poison":
        return items.poison(ctx, _slot(args, "slot"))
    if cmd == "check_poison":
        return items.check_poison(ctx, _slot(args, "slot"))
    if cmd == "hack":
        return items.hack(ctx)
    if cmd == "megaphone":
        return items.megaphone(ctx, args.get("speech", ""))
    if cmd == "change_msg":
        # 玩家可控文本:转义后落库(对等原版 DECODE)
        p["msg"] = util.esc((args.get("msg") or "").strip()[:32])
        p["dmes"] = util.esc((args.get("dmes") or "").strip()[:32])
        p["com"] = util.esc((args.get("com") or "").strip()[:32])
        ctx.log("口癖变更完成。<br>")
        return
    if cmd == "attack":
        from .battle import cmd_attack
        return cmd_attack(ctx, args)
    if cmd == "loot":
        from .battle import cmd_loot
        return cmd_loot(ctx, args)
    raise CmdError(ctx.msg["bad_access"])


# ---------- 移动/探索(battle.cgi MOVE/SEARCH/SEARCH2) ----------

def cmd_move(ctx, to):
    p = ctx.player
    if not (0 <= to < len(config.PLACE)) or to == p["place"]:
        raise CmdError(ctx.msg["bad_access"])
    forbidden = forbidden_places(ctx.game)
    nxt = next_forbidden_places(ctx.game)
    # [FIX] 先检查目的地是否当前禁区(原版"下次禁区"分支跳过此检查)
    if to in forbidden:
        ctx.log(ctx.msg["move_forbidden"].format(place=config.PLACE[to]))
        return
    if to in nxt:
        ctx.log(ctx.msg["move_arrive_next_forbidden"].format(
            place=config.PLACE[to], arinfo=ctx.texts["arinfo"][to]))
    else:
        ctx.log(ctx.msg["move_arrive"].format(
            place=config.PLACE[to], arinfo=ctx.texts["arinfo"][to]))
    p["place"] = to
    _spend_sta_move(ctx)
    if not ctx.dead:
        search2(ctx, is_search=False)


def cmd_explore(ctx):
    p = ctx.player
    ctx.log(ctx.msg["search_start"].format(name=p["l_name"]))
    _spend_sta_search(ctx)
    if not ctx.dead:
        found = search2(ctx, is_search=True)
        if not found:
            ctx.log(ctx.msg["search_nothing"])


def _spend_sta_move(ctx):
    p = ctx.player
    if "足" in (p["injuries"] or ""):
        p["sta"] -= util.rand_int(ctx.rng, config.STA_MOVE_FOOT, config.STA_MOVE_FOOT + 4)
    elif p["club"] == "田径部":
        p["sta"] -= util.rand_int(ctx.rng, config.STA_MOVE_TRACK, config.STA_MOVE_TRACK + 4)
    else:
        p["sta"] -= util.rand_int(ctx.rng, config.STA_MOVE, config.STA_MOVE + 4)
    if p["sta"] <= 0:
        drain(ctx, "mov")


def _spend_sta_search(ctx):
    p = ctx.player
    if "足" in (p["injuries"] or ""):
        p["sta"] -= util.rand_int(ctx.rng, config.STA_SEARCH_FOOT, config.STA_SEARCH_FOOT + 4)
    elif p["club"] == "田径部":
        p["sta"] -= util.rand_int(ctx.rng, config.STA_SEARCH_TRACK, config.STA_SEARCH_TRACK + 4)
    else:
        p["sta"] -= util.rand_int(ctx.rng, config.STA_SEARCH, config.STA_SEARCH + 4)
    if p["sta"] <= 0:
        drain(ctx, "mov")


def search2(ctx, is_search):
    """遭遇引擎(battle.cgi SEARCH2)。返回 True=有发现。"""
    # 区域发现率(原版 chkpnt:SU+2/SD-2)
    chkpnt = config.CHKPNT
    st = config.ARSTS[ctx.player["place"]]
    if st == "SU":
        chkpnt += 2
    elif st == "SD":
        chkpnt -= 2

    dice1 = util.dice(ctx.rng, 10)
    if dice1 <= config.ENCOUNTER_RATE - 1:      # 60%: 遇敌检索
        from .battle import try_encounter
        result = try_encounter(ctx, chkpnt)
        if result == "found":
            return True
        ctx.log(ctx.msg["sense_people"])
        return False
    dice2 = util.dice(ctx.rng, 10)
    if dice2 < chkpnt and is_search:            # 物品发现
        return items.itemget(ctx)
    return events.run_event(ctx)


# ---------- 耐力耗尽(lib2.cgi DRAIN) ----------

def drain(ctx, mode):
    p = ctx.player
    ctx.log(ctx.msg["drain"].format(name=p["l_name"]))
    p["sta"] = config.MAXSTA
    dhit = int(ctx.rng.random() * (p["mhit"] * 0.2) + p["mhit"] * 0.1) or 1
    p["mhit"] -= dhit
    if p["mhit"] <= 0:
        p["mhit"] = 0
        p["hit"] = 0
        ctx.log(ctx.msg["dead_line"].format(
            f_name=p["f_name"], l_name=p["l_name"], cl=p["class_name"],
            sex=p["sex"], no=p["class_no"]))
        from .death import kill_player
        kill_player(ctx.conn, ctx.game, ctx.player, ctx.now,
                    ctx.texts, ctx.rng, death_type=config.DEATH_WEAK)
        ctx.dead = True
    elif p["hit"] > p["mhit"]:
        p["hit"] = p["mhit"]
