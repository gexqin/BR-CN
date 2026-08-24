"""审查修复回归测试:死亡一致性/XSS 转义/远程搜刮/参数白名单/结束封锁。"""
import json

import pytest


@pytest.fixture()
def game2p(client):
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    for uname, fname, sex in (("k1", "杀", "男生"), ("v1", "被", "女生")):
        client.post("/api/auth/register", json=dict(
            username=uname, password="pass1234", f_name=fname, l_name="方",
            sex=sex, msg="<img src=x onerror=alert(1)>",
            dmes="<script>alert(2)</script>", com=""))
    return client


def _login(client, username):
    client.cookies.clear()
    r = client.post("/api/auth/login", json=dict(username=username, password="pass1234"))
    assert r.status_code == 200, r.text


def _cmd(client, cmd, **args):
    r = client.post("/api/game/command", json=dict(cmd=cmd, args=args))
    assert r.status_code == 200, r.text
    return r.json()


def _db():
    import app.config as config
    import app.db as db
    return db.connect(config.DB_PATH)


def _setup(place=2, hp=30):
    conn = _db()
    for uname in ("k1", "v1"):
        conn.execute(
            "UPDATE players SET place=?, hit=?, mhit=? WHERE username=?",
            (place, hp, hp, uname))
    conn.commit()
    conn.close()


def test_death_state_consistent_after_kill(game2p):
    """审查 #2 复现回归:击杀后尸体的 status/death_type 必须正确落库。"""
    _setup(hp=10)
    _login(game2p, "k1")
    dead = False
    for _ in range(80):
        res = _cmd(game2p, "explore")
        if res["view"] == "battle":
            tid = res["extras"]["battle"]["target"]["id"]
            for _ in range(40):
                res = _cmd(game2p, "attack", target_id=tid)
                if res["view"] in ("loot", "dead"):
                    break
                _login(game2p, "v1")
                _cmd(game2p, "change_msg", msg="x")
                _login(game2p, "k1")
            break
        if res["view"] in ("dead", "loot"):
            break
        if "突然袭了过来" in res["log"]:
            # 被袭路径由 v1 侧验证:直接查库
            break
    conn = _db()
    rows = {r["username"]: dict(r) for r in conn.execute(
        "SELECT username, hit, status, death_type FROM players "
        "WHERE username IN ('k1','v1')").fetchall()}
    conn.close()
    someone_dead = [r for r in rows.values() if r["hit"] <= 0]
    for r in someone_dead:
        assert r["status"] == "dead", f"{r} 死亡状态被回写覆盖"
        assert r["death_type"], f"{r} 死因丢失"


def test_area_execution_not_revived_by_own_command(game2p):
    """审查 #1 复现回归:玩家在禁区处决后,其本人下一条命令不得复活自己。"""
    import datetime
    conn = _db()
    g = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()
    order = json.loads(g["forbidden_order"])
    victim_zone = order[1]        # 次日新增禁区
    safe = order[5]
    yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    conn.execute("UPDATE games SET last_tick_day=? WHERE id=?", (yesterday, g["id"]))
    conn.execute("UPDATE players SET place=?, status='sleeping', rest_since=? "
                 "WHERE username='v1'", (victim_zone, datetime.datetime.now().timestamp() - 60))
    conn.execute("UPDATE players SET place=? WHERE username='k1'", (safe,))
    conn.commit()
    conn.close()
    _login(game2p, "v1")
    st = game2p.get("/api/game/state").json()   # 触发日界 → v1 被处决
    assert st["view"] == "dead"
    conn = _db()
    v1 = conn.execute("SELECT hit, status, death_type FROM players "
                      "WHERE username='v1'").fetchone()
    conn.close()
    assert v1["status"] == "dead" and v1["death_type"] == "禁区滞留"


def test_xss_escaped(game2p):
    """dengon/speech/msg/dmes 转义:日志中不得出现可执行的原始标签。"""
    _setup(hp=500)
    _login(game2p, "k1")
    for _ in range(80):
        res = _cmd(game2p, "explore")
        if res["view"] == "battle":
            tid = res["extras"]["battle"]["target"]["id"]
            res = _cmd(game2p, "attack", target_id=tid,
                       dengon="<img src=x onerror=alert(1)>")
            assert "<img" not in res["log"], "dengon 未转义"
            assert "&lt;img" in res["log"]
            break
        if res["view"] in ("dead", "loot"):
            break
    # 扩音器
    conn = _db()
    k1 = conn.execute("SELECT id FROM players WHERE username='k1'").fetchone()
    items = [None] * 6
    items[0] = dict(name="携带式扩音器", code="Y", eff=1, uses=1)
    conn.execute("UPDATE players SET items=? WHERE id=?",
                 (json.dumps(items), k1["id"]))
    conn.commit()
    conn.close()
    res = _cmd(game2p, "megaphone", speech="<b>bold</b>")
    assert "<b>bold</b>" not in json.dumps(res, ensure_ascii=False) or \
        "&lt;b&gt;" in res["log"]
    # 注册时的口癖/遗言落库已转义
    conn = _db()
    v1 = conn.execute("SELECT msg, dmes FROM players WHERE username='v1'").fetchone()
    conn.close()
    assert "<img" not in v1["msg"] and "<script" not in v1["dmes"]


def test_remote_loot_blocked(game2p):
    """审查 #3:跨地点搜刮/攻击尸体必须拒绝。"""
    conn = _db()
    ids = {r["username"]: r["id"] for r in conn.execute(
        "SELECT username, id FROM players WHERE username IN ('k1','v1')").fetchall()}
    conn.execute("UPDATE players SET place=2, hit=0, status='dead', corpse_found=1, "
                 "found_by=NULL, bid=NULL WHERE username='v1'")
    # 清空 k1 背包(避免满包分支提前返回 200)
    conn.execute("UPDATE players SET place=9, items=? WHERE username='k1'",
                 (json.dumps([None] * 6),))
    conn.commit()
    conn.close()
    _login(game2p, "k1")
    r = game2p.post("/api/game/command", json=dict(
        cmd="loot", args=dict(target_id=ids["v1"], slot="0")))
    assert r.status_code == 400, "远程搜刮未被拒绝"


def test_param_whitelist(game2p):
    _login(game2p, "k1")
    # slot 越界/负数/非数字 → 400(而非 500)
    for slot in (5, -1, 99, "abc"):
        r = game2p.post("/api/game/command",
                        json=dict(cmd="use_item", args=dict(slot=slot)))
        assert r.status_code == 400, f"slot={slot} 未被白名单拦截"
    # 未持有扩音器 → 400
    r = game2p.post("/api/game/command",
                    json=dict(cmd="megaphone", args=dict(speech="hi")))
    assert r.status_code == 400


def test_commands_blocked_after_finish(game2p):
    conn = _db()
    g = conn.execute("SELECT id FROM games ORDER BY id DESC LIMIT 1").fetchone()
    conn.execute("UPDATE games SET status='finished_escape' WHERE id=?", (g["id"],))
    conn.commit()
    conn.close()
    _login(game2p, "k1")
    res = _cmd(game2p, "move", to=2)
    assert res["view"] == "ending_escape"
    conn = _db()
    p = conn.execute("SELECT place FROM players WHERE username='k1'").fetchone()
    conn.close()
    assert p["place"] == 0, "游戏结束后命令仍生效"
