"""P5 特殊系统:EX 钥匙链(杀班主任→夺钥匙→分校解除)/陷阱/扩音器广播感知。"""
import json

import pytest


@pytest.fixture()
def hero(client):
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    client.post("/api/auth/register", json=dict(
        username="hero", password="pass1234", f_name="英雄", l_name="者",
        sex="男生", msg="", dmes="", com=""))
    return client


def _cmd(client, cmd, **args):
    r = client.post("/api/game/command", json=dict(cmd=cmd, args=args))
    assert r.status_code == 200, r.text
    return r.json()


def _db():
    import app.config as config
    import app.db as db
    return db.connect(config.DB_PATH)


def test_trap_place_and_trigger(hero):
    conn = _db()
    p = conn.execute("SELECT id FROM players WHERE username='hero'").fetchone()
    items = [None] * 6
    items[0] = dict(name="捕鼠夹", code="TN", eff=10, uses=2)
    conn.execute("UPDATE players SET place=3, items=? WHERE id=?",
                 (json.dumps(items), p["id"]))
    conn.close()
    res = _cmd(hero, "use_item", slot=0)     # 设置陷阱
    assert "设成了陷阱" in res["log"]
    res = _cmd(hero, "use_item", slot=0)     # 第二个也设上
    conn = _db()
    n = conn.execute("SELECT COUNT(*) c FROM area_items WHERE game_id=1 AND place=3 "
                     "AND trap=1").fetchone()["c"]
    conn.close()
    assert n >= 1
    # 反复探索直到踩中自己的陷阱(或拾取其他物品)
    triggered = False
    for _ in range(120):
        res = _cmd(hero, "explore")
        if "是陷阱！" in res["log"]:
            triggered = True
            break
    # 捕鼠夹在公所(地点3)投放池中本有 TO,触发概率高
    assert triggered


def test_megaphone_broadcast(hero):
    # 第二个玩家接收广播
    hero.cookies.clear()
    hero.post("/api/auth/register", json=dict(
        username="byst", password="pass1234", f_name="路人", l_name="甲",
        sex="女生"))
    hero.cookies.clear()
    hero.post("/api/auth/login", json=dict(username="hero", password="pass1234"))
    conn = _db()
    p = conn.execute("SELECT id FROM players WHERE username='hero'").fetchone()
    items = [None] * 6
    items[0] = dict(name="携带式扩音器", code="Y", eff=1, uses=1)
    conn.execute("UPDATE players SET items=? WHERE id=?",
                 (json.dumps(items), p["id"]))
    conn.close()
    res = _cmd(hero, "megaphone", speech="全体注意,立刻集合")
    assert "好好传达到" in res["log"]
    # 路人立即登录应看到广播(30 秒内)
    hero.cookies.clear()
    hero.post("/api/auth/login", json=dict(username="byst", password="pass1234"))
    st = hero.get("/api/game/state").json()
    assert "全体注意" in (st["log"] or ""), st["log"]


def test_ex_key_chain(hero):
    """EX 逃生路线:黑客解除禁区(模拟成功)→ 分校杀班主任 → 夺钥匙 → 解除程序。

    分校自开局即为禁区(原版设计),返回分校必须先黑客解除。
    """
    conn = _db()
    hero_row = conn.execute("SELECT id FROM players WHERE username='hero'").fetchone()
    boss = conn.execute(
        "SELECT id FROM players WHERE class_name='班主任'").fetchone()
    items = [None] * 6
    # 英雄持日本刀;班主任 1HP/徒手(避免被袭致死),士兵移离分校
    conn.execute(
        "UPDATE players SET wep_name='日本刀', wep_code='WNS', wep_att=25, "
        "wep_uses=NULL, items=? WHERE id=?",
        (json.dumps(items), hero_row["id"]))
    conn.execute("UPDATE players SET hit=1, mhit=1, att=0, deff=0 WHERE id=?",
                 (boss["id"],))
    conn.execute("UPDATE players SET place=1 WHERE class_name='士兵'")
    # 模拟黑客成功:禁区解除
    conn.execute("UPDATE games SET hack_active=1")
    conn.commit()
    conn.close()

    # 分校探索(黑客解除后允许)直到遭遇班主任;NPC 不行动,测试中代其解锁
    killed = False
    for _ in range(80):
        res = _cmd(hero, "explore")
        if res["view"] == "battle":
            tid = res["extras"]["battle"]["target"]["id"]
            res = _cmd(hero, "attack", target_id=tid)
            if res["view"] == "loot":
                killed = True
                break
        if res["view"] == "loot":     # 被袭反杀
            killed = True
            break
        if res["view"] == "dead":
            break
        # 模拟 NPC 行动(清其交战锁),保证循环可继续
        conn = _db()
        conn.execute("UPDATE players SET bid=NULL WHERE id=?", (boss["id"],))
        conn.commit()
        conn.close()
    assert killed, "未能击杀班主任"

    # 夺取钥匙
    slots = res["extras"]["loot"]["slots"]
    key_slot = [s for s in slots if s["name"] == "程序解除钥匙"]
    assert key_slot, f"战利品中无钥匙:{slots}"
    tid = res["extras"]["loot"]["target"]["id"]
    res = _cmd(hero, "loot", target_id=tid, slot=str(key_slot[0]["slot"]))
    assert "得到了程序解除钥匙" in res["log"]

    # 分校使用钥匙 → EX 结局
    res = _cmd(hero, "use_item", slot=0)
    assert "停止了程序" in res["log"]
    st = hero.get("/api/game/state").json()
    assert st["view"] == "ending_escape"
    conn = _db()
    g = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert g["status"] == "finished_escape"
    r = hero.get("/api/news")
    assert any(n["kind"] == "EX_END" for n in r.json())
