"""P2 冒烟:开局 → 注册×2 → 登录 → state/map/news/rank。"""


def _new_game(client):
    r = client.post("/api/admin/login", json=dict(password="790923"))
    assert r.status_code == 200, r.text
    r = client.post("/api/admin/new_game")
    assert r.status_code == 200, r.text
    return r.json()["game_id"]


def _register(client, username, f_name="测试", l_name=None, sex="男生"):
    form = dict(username=username, password="pass1234", f_name=f_name,
                l_name=l_name or username, sex=sex, msg="口癖", dmes="遗言", com="座右铭")
    r = client.post("/api/auth/register", json=form)
    assert r.status_code == 200, r.text
    return r.json()


def test_register_login_state(client):
    _new_game(client)
    # 半角姓名应被拒
    r = client.post("/api/auth/register", json=dict(
        username="alice", password="pass1234", f_name="Bob", l_name="测试", sex="女生"))
    assert r.status_code == 400 and r.json()["detail"]["key"] == "f_name_half"
    # 合法注册
    r = client.post("/api/auth/register", json=dict(
        username="alice", password="pass1234", f_name="爱丽丝", l_name="测试",
        sex="女生"))
    assert r.status_code == 200, r.text
    assert "登陆完成" in r.json()["intro"] or "教室" in r.json()["intro"]

    # 登录
    client.cookies.clear()
    r = client.post("/api/auth/login", json=dict(username="alice", password="wrong"))
    assert r.status_code == 401
    r = client.post("/api/auth/login", json=dict(username="alice", password="pass1234"))
    assert r.status_code == 200, r.text

    # 状态
    r = client.get("/api/game/state")
    assert r.status_code == 200, r.text
    st = r.json()
    assert st["view"] == "main"
    assert st["player"]["hit"] >= 30 and st["player"]["mhit"] >= 30
    assert st["player"]["sta"] == 100
    assert st["place"]["name"] == "分校"
    assert st["forbidden"]["names"] == ["分校"]
    assert st["alive"] >= 1
    assert len(st["player"]["items"]) == 6
    assert st["player"]["items"][0]["name"] == "面包"

    # 地图
    r = client.get("/api/map")
    assert r.status_code == 200
    m = r.json()
    assert m["cells"]["D06"]["name"] == "分校"
    assert m["cells"]["D06"]["state"] == "forbidden"
    assert m["cells"]["A02"]["name"] == "北之岬"

    # 新闻(NEWGAME + ENTRY)
    r = client.get("/api/news")
    assert r.status_code == 200
    kinds = [n["kind"] for n in r.json()]
    assert "NEWGAME" in kinds and "ENTRY" in kinds

    # 排行
    r = client.get("/api/rank")
    assert r.status_code == 200
    rk = r.json()
    assert rk["alive"] >= 1
    assert any(m["username"] if "username" in m else m["f_name"] == "爱丽丝"
               for m in rk["members"])


def test_register_validations(client):
    _new_game(client)
    ok = dict(username="bob1", password="pass1234", f_name="张", l_name="三", sex="男生")
    # 同 ID 重复
    assert client.post("/api/auth/register", json=ok).status_code == 200
    r = client.post("/api/auth/register", json=ok)
    assert r.status_code == 400 and r.json()["detail"]["key"] == "dup"
    # 半角姓名
    r = client.post("/api/auth/register", json=dict(ok, username="bob2", f_name="ABC"))
    assert r.status_code == 400 and r.json()["detail"]["key"] == "f_name_half"
    # 姓名过长(>4 字符,[FIX] 按字符数)
    r = client.post("/api/auth/register", json=dict(ok, username="bob2", f_name="张王小李赵"))
    assert r.status_code == 400 and r.json()["detail"]["key"] == "f_name_len"
    # 4 字符姓名应通过(原版字节判定下会误拒)
    r = client.post("/api/auth/register", json=dict(ok, username="bob2", f_name="张王", l_name="小李"))
    assert r.status_code == 200, r.text
    # ID=密码
    r = client.post("/api/auth/register", json=dict(ok, username="bob3", password="bob3", f_name="赵", l_name="六"))
    assert r.status_code == 400 and r.json()["detail"]["key"] == "id_eq_pw"


def test_npc_seeded(client):
    _new_game(client)
    _register(client, "npccheck", f_name="检查", l_name="员")
    import app.config as config
    import app.db as db
    conn = db.connect(config.DB_PATH)
    npcs = conn.execute("SELECT * FROM players WHERE is_npc=1").fetchall()
    assert len(npcs) == 4
    boss = [n for n in npcs if n["class_name"] == "班主任"]
    assert len(boss) == 1
    import json
    items = json.loads(boss[0]["items"])
    assert any(i and i["name"] == "程序解除钥匙" for i in items)
    conn.close()
