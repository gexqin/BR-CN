"""P6 世界推进:禁区日界/滞留处决/黑客重置/胜负判定/注册截止。"""
import datetime
import json

import pytest


@pytest.fixture()
def world(client):
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    for uname, fname in (("w1", "玩一"), ("w2", "玩二")):
        client.post("/api/auth/register", json=dict(
            username=uname, password="pass1234", f_name=fname, l_name="家",
            sex="男生"))
    return client


def _login(client, username):
    client.cookies.clear()
    r = client.post("/api/auth/login", json=dict(username=username, password="pass1234"))
    assert r.status_code == 200, r.text


def _db():
    import app.config as config
    import app.db as db
    return db.connect(config.DB_PATH)


def test_day_tick_and_area_death(world):
    conn = _db()
    # 构造:禁区序 [0, 5, ...],明日推进后前 4 个变禁区;w2 放在地点 5,w1 放在
    # 安全区(顺序表第 5 位之后)——注意处决覆盖全部当前禁区,滞留分校也会死
    g = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()
    order = json.loads(g["forbidden_order"])
    order.remove(5)
    order.insert(1, 5)
    safe = order[5]
    yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    conn.execute("UPDATE games SET forbidden_order=?, last_tick_day=? WHERE id=?",
                 (json.dumps(order), yesterday, g["id"]))
    conn.execute("UPDATE players SET place=5 WHERE username='w2'")
    conn.execute("UPDATE players SET place=? WHERE username='w1'", (safe,))
    conn.execute("UPDATE games SET hack_active=1 WHERE id=?", (g["id"],))
    conn.commit()
    conn.close()

    _login(world, "w1")
    st = world.get("/api/game/state").json()   # 任意请求触发推进
    assert st["forbidden"]["names"][:2] == ["分校", "消防署"]
    assert st["forbidden"]["hacked"] is False   # 黑客标志日界重置

    conn = _db()
    w2 = conn.execute("SELECT status, death_type FROM players WHERE username='w2'").fetchone()
    g2 = conn.execute("SELECT forbidden_count FROM games WHERE id=?", (g["id"],)).fetchone()
    conn.close()
    assert g2["forbidden_count"] == 4
    assert w2["status"] == "dead" and w2["death_type"] == "禁区滞留"
    r = world.get("/api/news")
    assert any(n["kind"] == "DEATHAREA" for n in r.json())
    assert any(n["kind"] == "AREA" for n in r.json())


def test_victory(world):
    conn = _db()
    g = conn.execute("SELECT * FROM games ORDER BY id DESC LIMIT 1").fetchone()
    # 第 5 天(ar>10)且仅剩 w1 存活
    conn.execute("UPDATE games SET forbidden_count=11 WHERE id=?", (g["id"],))
    conn.execute("UPDATE players SET hit=0, status='dead' WHERE username='w2'")
    conn.commit()
    conn.close()
    _login(world, "w1")
    st = world.get("/api/game/state").json()
    assert st["view"] == "ending_win"
    conn = _db()
    g2 = conn.execute("SELECT * FROM games WHERE id=?", (g["id"],)).fetchone()
    w1 = conn.execute("SELECT status, win_flag FROM players WHERE username='w1'").fetchone()
    conn.close()
    assert g2["status"] == "finished_win"
    assert w1["status"] == "won" and w1["win_flag"] == 1
    r = world.get("/api/news")
    assert any(n["kind"] == "WINEND" for n in r.json())


def test_no_early_victory(world):
    """不足天数(ar<=10)时即使仅剩 1 人也不结束(对等原版 $battle_limit)。"""
    conn = _db()
    g = conn.execute("SELECT id FROM games ORDER BY id DESC LIMIT 1").fetchone()
    conn.execute("UPDATE games SET forbidden_count=5 WHERE id=?", (g["id"],))
    conn.execute("UPDATE players SET hit=0, status='dead' WHERE username='w2'")
    conn.commit()
    conn.close()
    _login(world, "w1")
    st = world.get("/api/game/state").json()
    assert st["view"] == "main"
    conn = _db()
    g2 = conn.execute("SELECT status FROM games WHERE id=?", (g["id"],)).fetchone()
    conn.close()
    assert g2["status"] == "running"


def test_registration_cutoff(world):
    conn = _db()
    g = conn.execute("SELECT id FROM games ORDER BY id DESC LIMIT 1").fetchone()
    conn.execute("UPDATE games SET forbidden_count=10 WHERE id=?", (g["id"],))
    conn.commit()
    conn.close()
    r = world.post("/api/auth/register", json=dict(
        username="late", password="pass1234", f_name="迟到", l_name="者", sex="男生"))
    assert r.status_code == 400
    assert r.json()["detail"]["key"] == "closed"
