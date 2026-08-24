"""新闻/日志写入(对等原版 lib.cgi LOGSAVE + news.cgi 渲染)。"""
import json


def add_news(conn, game_id, at, kind, subject_id=None, opponent_id=None,
             extra=None, text=""):
    conn.execute(
        "INSERT INTO news(game_id, at, kind, subject_id, opponent_id, extra, text) "
        "VALUES(?,?,?,?,?,?,?)",
        (game_id, at, kind, subject_id, opponent_id,
         json.dumps(extra or {}, ensure_ascii=False), text))


def add_sense(conn, game_id, at, expire_at, scope, place, kind, player_id,
              target_id=None, message=None):
    conn.execute(
        "INSERT INTO sense_logs(game_id, at, expire_at, scope, place, kind, "
        "player_id, target_id, message) VALUES(?,?,?,?,?,?,?,?,?)",
        (game_id, at, expire_at, scope, place, kind, player_id, target_id, message))
