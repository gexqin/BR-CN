"""区域随机事件(对等 lib/event.cgi)。"""
from .. import config
from . import util
from .death import kill_player


def run_event(ctx):
    """返回 True=有事件(chksts OK)。dice=int(rand(5));<2 无事。"""
    p = ctx.player
    texts = ctx.texts
    dice = util.dice(ctx.rng, 5)
    if dice < 2:
        return False
    kind = texts["place_events"].get(str(p["place"]))
    if not kind:
        return False
    ev = texts["events"][kind]
    ctx.log(ev["intro"])
    if kind == "pond":
        # dice<=3 掉池:耐力 -int(rand(5)+5)+10 → 15~19
        if dice <= 3:
            damage = util.rand_int(ctx.rng, 5, 9) + 10
            ctx.log(ev["damage"].format(damage=damage))
            p["sta"] -= damage
            if p["sta"] <= 0:
                from .game import drain
                drain(ctx, "eve")
        else:
            ctx.log(ev["repel"])
        return True
    if dice == 2:      # 负伤
        part = ev["part"]
        p["injuries"] = (p["injuries"] or "").replace(part, "") + part
        ctx.log(ev["injury"])
    elif dice == 3:    # 伤害 5~9,可致死
        damage = util.rand_int(ctx.rng, 5, 9)
        ctx.log(ev["damage"].format(damage=damage))
        p["hit"] -= damage
        if p["hit"] <= 0:
            p["hit"] = 0
            ctx.log(f"<span class=\"red\"><b>{p['f_name']} {p['l_name']}"
                    f"（{p['class_name']} {p['sex']}{p['class_no']}号）已经死亡。</b></span><br>")
            kill_player(ctx.conn, ctx.game, ctx.player, ctx.now,
                        ctx.texts, ctx.rng, death_type=config.DEATH_WEAK)
            ctx.dead = True
    else:
        ctx.log(ev["repel"])
    return True
