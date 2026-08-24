"""P7 管理后台:登录/一览/处刑/备份/回滚一致性。"""
import pytest


@pytest.fixture()
def admin(client):
    # 先开新局+注册(玩家会话),最后以管理员登录(单 cookie jar)
    client.post("/api/admin/login", json=dict(password="790923"))
    client.post("/api/admin/new_game")
    client.post("/api/auth/register", json=dict(
        username="u1", password="pass1234", f_name="甲", l_name="员",
        sex="男生"))
    client.cookies.clear()
    client.post("/api/admin/login", json=dict(password="790923"))
    return client


def test_admin_flow(admin):
    # 错误密码
    r = admin.post("/api/admin/login", json=dict(password="wrong"))
    assert r.status_code == 401

    # 一览
    r = admin.get("/api/admin/players")
    assert r.status_code == 200
    players = r.json()["players"]
    assert any(p["username"] == "u1" for p in players)
    npc = [p for p in players if p["government"]]
    assert len(npc) == 4

    # 政府处刑
    u1 = [p for p in players if p["username"] == "u1"][0]
    r = admin.post("/api/admin/execute", json=dict(player_id=u1["id"],
                                                   message="违反规则"))
    assert r.status_code == 200
    r = admin.get("/api/admin/players")
    u1 = [p for p in r.json()["players"] if p["username"] == "u1"][0]
    assert u1["status"] == "dead" and u1["death"] == "政府处刑"
    # 新闻记录(直查 DB;管理会话无权访问玩家路由)
    import app.config as config
    import app.db as db
    conn = db.connect(config.DB_PATH)
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM news").fetchall()]
    conn.close()
    assert "DEATH4" in kinds


def test_backup_rollback(admin):
    import app.config as config
    import app.db as db
    r = admin.post("/api/admin/backup?label=before")
    assert r.status_code == 200
    bid = r.json()["backup_id"]

    # 破坏状态:处刑玩家 + 撒掉物品 + 改禁区数
    r = admin.get("/api/admin/players")
    u1 = [p for p in r.json()["players"] if p["username"] == "u1"][0]
    admin.post("/api/admin/execute", json=dict(player_id=u1["id"], message=""))
    conn = db.connect(config.DB_PATH)
    g = conn.execute("SELECT id FROM games ORDER BY id DESC LIMIT 1").fetchone()
    conn.execute("UPDATE games SET forbidden_count=9 WHERE id=?", (g["id"],))
    conn.execute("DELETE FROM area_items WHERE game_id=?", (g["id"],))
    conn.commit()
    before_players = conn.execute("SELECT COUNT(*) c FROM players WHERE game_id=?",
                                  (g["id"],)).fetchone()["c"]
    before_items = conn.execute("SELECT COUNT(*) c FROM area_items WHERE game_id=?",
                                (g["id"],)).fetchone()["c"]
    assert before_items == 0
    conn.close()

    # 回滚
    r = admin.post("/api/admin/rollback", json=dict(backup_id=bid))
    assert r.status_code == 200
    conn = db.connect(config.DB_PATH)
    g2 = conn.execute("SELECT forbidden_count FROM games WHERE id=?", (g["id"],)).fetchone()
    items = conn.execute("SELECT COUNT(*) c FROM area_items WHERE game_id=?",
                         (g["id"],)).fetchone()["c"]
    u1_row = conn.execute("SELECT hit FROM players WHERE username='u1'").fetchone()
    after_players = conn.execute("SELECT COUNT(*) c FROM players WHERE game_id=?",
                                 (g["id"],)).fetchone()["c"]
    conn.close()
    assert g2["forbidden_count"] == 1          # 回到备份时的值
    assert items > 0                            # 物品恢复
    assert u1_row["hit"] > 0                    # 玩家复活(回滚前被处刑)
    assert after_players == before_players      # 处刑不删行,回滚前后行数一致
