"""P3 引擎测试:移动/探索/物品/整理/合成/特殊行动(API 级,容忍随机)。"""
import pytest


@pytest.fixture()
def game_client(client):
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    client.post("/api/auth/register", json=dict(
        username="p1", password="pass1234", f_name="一号", l_name="测试",
        sex="男生"))
    return client


def _cmd(client, cmd, **args):
    r = client.post("/api/game/command", json=dict(cmd=cmd, args=args))
    assert r.status_code == 200, r.text
    return r.json()


def _state(client):
    r = client.get("/api/game/state")
    assert r.status_code == 200
    return r.json()


def test_move_and_stamina(game_client):
    st = _state(game_client)
    assert st["place"]["index"] == 0
    # 分校是禁区,但移动出去合法;移动消耗耐力 8~12(田径部 5~9)
    track = st["player"]["club"] == "田径部"
    res = _cmd(game_client, "move", to=1)
    st = res["state"]
    assert st["place"]["index"] == 1
    lo, hi = (91, 95) if track else (88, 92)
    assert lo <= st["player"]["sta"] <= hi, f"club={st['player']['club']} sta={st['player']['sta']}"
    # 移动进当前禁区被拒([FIX]:原版可绕过)
    # 构造:把 1 号也设为禁区 —— 通过直接改库
    import app.config as config
    import app.db as db
    import json as jsonmod
    conn = db.connect(config.DB_PATH)
    g = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()
    order = jsonmod.loads(g["forbidden_order"])
    if 1 not in order[: g["forbidden_count"]]:
        # 把 1 插入禁区头部(仅测试)
        order.remove(1)
        order.insert(0, 1)
        conn.execute("UPDATE games SET forbidden_order=? WHERE id=?",
                     (jsonmod.dumps(order), g["id"]))
    conn.close()
    _cmd(game_client, "move", to=2)     # 先离开 1 号地
    res = _cmd(game_client, "move", to=1)
    assert "禁止地区" in res["log"]
    assert res["state"]["place"]["index"] == 2  # 未移动


def test_explore_pickup(game_client):
    # 分校禁止探索(对等原版菜单:分校无探索指令)
    r = game_client.post("/api/game/command", json=dict(cmd="explore", args={}))
    assert r.status_code == 400
    # 移动到有物品的区域后探索应能拾取
    _cmd(game_client, "move", to=2)
    found = False
    for _ in range(80):
        res = _cmd(game_client, "explore")
        if "发现了" in res["log"]:
            found = True
            break
    assert found


def test_food_use(game_client):
    # 使用面包(SH):耐力+20
    _cmd(game_client, "move", to=2)
    _cmd(game_client, "explore")
    st = _state(game_client)
    slot0 = st["player"]["items"][0]
    assert slot0["name"] == "面包"
    # 消耗耐力后使用
    for _ in range(3):
        _cmd(game_client, "explore")
    res = _cmd(game_client, "use_item", slot=0)
    assert "精力恢复" in res["log"] or "使用了面包" in res["log"]


def test_craft_chain(game_client):
    # 直接构造背包:轻油+肥料 → 火药
    import app.config as config
    import app.db as db
    import json
    conn = db.connect(config.DB_PATH)
    p = conn.execute("SELECT * FROM players WHERE username='p1'").fetchone()
    items = [None] * 6
    items[0] = dict(name="轻油", code="Y", eff=1, uses=1)
    items[1] = dict(name="肥料", code="Y", eff=1, uses=1)
    conn.execute("UPDATE players SET items=? WHERE id=?",
                 (json.dumps(items, ensure_ascii=False), p["id"]))
    conn.close()
    res = _cmd(game_client, "craft", a=0, b=1)
    assert "做出了火药" in res["log"], res["log"]
    names = [i["name"] for i in res["state"]["player"]["items"] if i]
    assert "火药" in names


def test_poison_and_check(game_client):
    import app.config as config
    import app.db as db
    import json
    conn = db.connect(config.DB_PATH)
    p = conn.execute("SELECT * FROM players WHERE username='p1'").fetchone()
    items = [None] * 6
    items[0] = dict(name="面包", code="SH", eff=20, uses=2)
    items[1] = dict(name="毒药", code="Y", eff=20, uses=1)
    conn.execute("UPDATE players SET items=?, club='料理研究部' WHERE id=?",
                 (json.dumps(items, ensure_ascii=False), p["id"]))
    conn.close()
    res = _cmd(game_client, "poison", slot=0)
    assert "掺入了毒物" in res["log"]
    it = res["state"]["player"]["items"][0]
    assert it["code"] == "SD2"   # 料理研究部特制毒
    res = _cmd(game_client, "check_poison", slot=0)
    assert "毒物" in res["log"]
    # 食用毒物致死 → DEATH1
    res = _cmd(game_client, "use_item", slot=0)
    st = _cmd(game_client, "move", to=1)  # 死后任何命令
    assert st["view"] in ("dead", "main")


def test_hack_and_speaker(game_client):
    import app.config as config
    import app.db as db
    import json
    conn = db.connect(config.DB_PATH)
    p = conn.execute("SELECT * FROM players WHERE username='p1'").fetchone()
    items = [None] * 6
    items[0] = dict(name="笔记本电脑", code="Y", eff=1, uses=5)
    items[1] = dict(name="携带式扩音器", code="Y", eff=1, uses=1)
    conn.execute("UPDATE players SET items=? WHERE id=?",
                 (json.dumps(items, ensure_ascii=False), p["id"]))
    conn.close()
    hacked = False
    for _ in range(40):
        r = game_client.post("/api/game/command", json=dict(cmd="hack", args={}))
        if r.status_code != 200:
            break    # 笔记本电脑损坏后无法继续
        res = r.json()
        if "禁止区域解除" in res["log"]:
            hacked = True
            break
        if res["view"] == "dead":    # 颈环引爆(1%)
            break
    if hacked:
        st = _state(game_client)
        assert st["forbidden"]["hacked"] or st["forbidden"]["names"] == []
    res = _cmd(game_client, "megaphone", speech="大家快逃")
    # 颈环引爆时跳过;单玩家局全灭后游戏终局,视图为 ending_*(而非 dead)
    if res["view"] not in ("dead", "ending_win", "ending_escape"):
        assert "好好传达到" in res["log"]


def test_radar(game_client):
    import app.config as config
    import app.db as db
    import json
    conn = db.connect(config.DB_PATH)
    p = conn.execute("SELECT * FROM players WHERE username='p1'").fetchone()
    items = [None] * 6
    items[0] = dict(name="雷达", code="R2", eff=1, uses=None)
    conn.execute("UPDATE players SET items=? WHERE id=?",
                 (json.dumps(items, ensure_ascii=False), p["id"]))
    conn.close()
    res = _cmd(game_client, "use_item", slot=0)
    assert res["view"] == "radar"
    assert "D06" in res["extras"]["radar"]["cells"]


def test_sleep_heal_cycle(game_client):
    _cmd(game_client, "move", to=2)
    res = _cmd(game_client, "sleep")
    st = _state(game_client)
    assert st["status"] == "sleeping"
    # 下一条命令结算恢复并唤醒(测试中即时执行,恢复 0~1 点)
    res = _cmd(game_client, "explore")
    assert res["state"]["status"] == "alive"
