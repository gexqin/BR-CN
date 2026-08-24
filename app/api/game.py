"""游戏 API:状态视图(命令分发在 P3 加入)。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import config
from ..db import transaction
from ..services import auth as auth_svc
from ..services import state as state_svc
from ..services import world as world_svc
from .deps import get_conn

router = APIRouter(prefix="/api", tags=["game"])


def _require_player(request: Request, conn):
    s, player = auth_svc.session_player(conn, request.cookies.get(auth_svc.SESSION_COOKIE))
    if not s or player is None:
        raise HTTPException(401, "未登录")
    return player


@router.get("/game/state")
def game_state(request: Request, conn=Depends(get_conn), since_id: int = 0):
    token = request.cookies.get(auth_svc.SESSION_COOKIE)
    state, err = state_svc.game_state(conn, token, since_id=since_id)
    if err:
        raise HTTPException(401, err.get("error", "未登录"))
    return state


class CommandForm(BaseModel):
    cmd: str
    args: dict = {}


@router.post("/game/command")
def game_command(form: CommandForm, request: Request, conn=Depends(get_conn)):
    import datetime
    import random

    from ..engine import game as engine
    player = _require_player(request, conn)
    game = conn.execute("SELECT * FROM games WHERE id=?", (player["game_id"],)).fetchone()
    texts = config.load_seed("texts.json")
    try:
        result = engine.run_command(conn, game, player, form.cmd, form.args,
                                    random.Random(), datetime.datetime.now().timestamp(),
                                    texts)
    except engine.CmdError as e:
        raise HTTPException(400, detail=dict(key="cmd_error", message=e.message))
    except (ValueError, IndexError, KeyError, TypeError) as e:
        # 参数类型/越界等防御性兜底(正常路径已在引擎内白名单化)
        raise HTTPException(400, detail=dict(key="cmd_error", message="不正确的存取。"))
    state, err = state_svc.game_state(conn, request.cookies.get(auth_svc.SESSION_COOKIE))
    result["state"] = state if not err else None
    return result


@router.get("/map")
def map_view(request: Request, conn=Depends(get_conn)):
    player = _require_player(request, conn)
    return world_svc.map_view(conn, player["game_id"])


@router.get("/news")
def news_view(request: Request, conn=Depends(get_conn), limit: int = 200):
    player = _require_player(request, conn)
    limit = max(1, min(limit, 500))
    return world_svc.news_view(conn, player["game_id"], limit)


@router.get("/rank")
def rank_view(request: Request, conn=Depends(get_conn)):
    player = _require_player(request, conn)
    return world_svc.rank_view(conn, player["game_id"])


@router.get("/rule")
def rule():
    with open(config.BASE_DIR + "/static/rule.htm", encoding="utf-8") as f:
        return dict(html=f.read())


@router.get("/texts")
def texts():
    """前端渲染所需公开文案(结局/引言等)。"""
    t = config.load_seed("texts.json")
    return dict(
        ending_win=t["ending_win"],
        ending_escape_others=t["ending_escape_others"],
        ending_escape_keyuser=t["ending_escape_keyuser"],
        home_intro=t["home_intro"],
        intro=t["intro"],
        messages=t["messages"],
    )
