"""死亡结算(对等原版 SAVE(hit=0)/LOGSAVE/尸体变体)。

player 参数必须是**可变 dict**(引擎内存态):本函数同时更新 dict 与数据库,
确保随后的 flush 不会用陈旧快照覆盖死亡状态(审查 #1/#2 的架构级修复)。
"""
from .. import config
from .news import add_news


def kill_player(conn, game, player, now, texts, rng, death_type="",
                killer=None):
    """置玩家于死亡并同步其内存 dict。

    原版保留整行记录(尸体含装备物品,供搜刮),此处对等:
    status='dead'、hit=0、掷定尸体描述变体、死亡禁注册计时、写新闻。
    """
    desc = rng.randrange(7)
    dead_by = killer["id"] if killer else None
    conn.execute(
        "UPDATE players SET hit=0, status='dead', death_type=?, death_time=?, "
        "corpse_desc=?, rest_since=NULL, no_reentry_until=?, dead_by=? WHERE id=?",
        (death_type, now, desc, now + config.DEATH_REENTRY_SECS,
         dead_by, player["id"]))
    # 同步内存 dict,防止调用方随后的 flush 回写陈旧存活状态
    player.update(hit=0, status="dead", death_type=death_type, death_time=now,
                  corpse_desc=desc, rest_since=None, dead_by=dead_by,
                  no_reentry_until=now + config.DEATH_REENTRY_SECS)

    name = f"{player['f_name']} {player['l_name']}"
    kind = "DEATH"
    if death_type == config.DEATH_POISON:
        kind = "DEATH1"
    elif killer is not None:
        kind = "DEATH2"
    elif death_type == config.DEATH_GOV:
        kind = "DEATH4"
    elif death_type == config.DEATH_AREA:
        kind = "DEATHAREA"

    if killer is not None:
        # death_type 已含"被XX(...)斩杀"完整短语,直接作为讣告主体
        add_news(conn, game["id"], now, kind, subject_id=player["id"],
                 opponent_id=killer["id"], extra=dict(death=death_type),
                 text=f"{name}({player['class_name']} {player['sex']}"
                      f"{player['class_no']}号){death_type}了。")
    else:
        reason = death_type or "死亡"
        add_news(conn, game["id"], now, kind, subject_id=player["id"],
                 extra=dict(death=death_type, dmes=player["dmes"]),
                 text=f"{name}({player['class_name']} {player['sex']}"
                      f"{player['class_no']}号)死亡了。({reason})")
