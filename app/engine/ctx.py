"""命令上下文:一次命令的完整状态载入/回写。

player 为 dict(行快照),处理器直接修改,管线结束时 flush() 回写全部可变列。
items 为 6 格列表(0-4 背包、5 饰品,对等原版 item[0..5])。
"""
import json

MUTABLE_COLUMNS = [
    "att", "deff", "hit", "mhit", "level", "exp", "kill",
    "prof_wn", "prof_wp", "prof_wa", "prof_wg", "prof_we", "prof_wc",
    "prof_wd", "prof_wb", "prof_wf", "prof_ws",
    "wep_name", "wep_code", "wep_att", "wep_uses",
    "bou_name", "bou_code", "bou_def", "bou_uses",
    "bouh_name", "bouh_code", "bouh_def", "bouh_uses",
    "bouf_name", "bouf_code", "bouf_def", "bouf_uses",
    "boua_name", "boua_code", "boua_def", "boua_uses",
    "items", "place", "sta", "status", "injuries", "death_type", "death_time",
    "dead_by", "corpse_found", "found_by", "rest_since", "bid", "log", "msg",
    "dmes", "com", "corpse_desc", "win_flag", "key_flag",
]


class Ctx:
    def __init__(self, conn, game, player_row, rng, now, texts):
        self.conn = conn
        self.game = dict(game)
        self.player = dict(player_row)
        if isinstance(self.player["items"], str):
            self.player["items"] = json.loads(self.player["items"])
        self.rng = rng
        self.now = now
        self.texts = texts
        self.msg = texts["messages"]
        self.action_log = ""      # 本次命令的瞬时日志(不落库)
        self.view = "main"        # 响应视图(main|radar|dead|ending_*)
        self.extras = {}          # 视图附加数据(雷达地图等)
        self.dead = False         # 本命令中死亡

    # ---- 日志 ----
    def log(self, html):
        self.action_log += html

    # ---- 背包(6 格) ----
    def items(self):
        return self.player["items"]

    def set_item(self, i, name, code, eff, uses):
        items = self.player["items"]
        if name is None:
            items[i] = None
        else:
            items[i] = dict(name=name, code=code, eff=eff, uses=uses)

    def item_at(self, i):
        it = self.player["items"][i]
        return it  # None 或 dict

    def first_empty(self, lo=0, hi=5):
        for i in range(lo, hi + 1):
            if self.player["items"][i] is None:
                return i
        return -1

    # ---- 快照 ----
    def snapshot_player(self):
        return dict(self.player)

    def flush(self):
        cols = ", ".join(f"{c}=?" for c in MUTABLE_COLUMNS)
        vals = []
        for c in MUTABLE_COLUMNS:
            v = self.player[c]
            if c == "items":
                v = json.dumps(v, ensure_ascii=False)
            vals.append(v)
        self.conn.execute(f"UPDATE players SET {cols} WHERE id=?", (*vals, self.player["id"]))
