"""认证 API:注册/登录/登出。"""
import random
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import config, ratelimit
from ..db import transaction
from ..services import auth as auth_svc
from .deps import get_conn

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _texts():
    return config.load_seed("texts.json")


class RegisterForm(BaseModel):
    username: str = ""
    password: str = ""
    f_name: str = ""
    l_name: str = ""
    sex: str = ""
    msg: str = ""
    dmes: str = ""
    com: str = ""


@router.post("/register")
def register(form: RegisterForm, request: Request, response: Response,
             conn=Depends(get_conn)):
    texts = _texts()
    # [安全] 按 IP 频控,防脚本批量占满名额
    ip = request.client.host if request.client else "?"
    if not ratelimit.allow(f"reg:ip:{ip}", limit=20, window_secs=3600):
        raise HTTPException(429, "注册过于频繁,请稍后再试")
    game = auth_svc.get_running_game(conn) or auth_svc.current_game(conn)
    try:
        data = auth_svc.validate_register(conn, game, form.model_dump(), texts)
    except auth_svc.RegisterError as e:
        msg = texts["register_errors"][e.key].format(**e.params)
        raise HTTPException(400, detail=dict(key=e.key, message=msg))
    try:
        with transaction(conn):
            # [FIX] 校验在事务外:取写锁后复查对局仍 running 且未截止,
            # 防校验与写入之间管理员开新局(旧局 abandoned)把玩家挂进死局
            g2 = conn.execute("SELECT status, forbidden_count FROM games WHERE id=?",
                              (game["id"],)).fetchone()
            if g2 is None or g2["status"] != "running" \
                    or g2["forbidden_count"] >= config.LIMIT * 3 + 1:
                raise auth_svc.RegisterError("closed")
            pid = auth_svc.create_player(conn, game, data, random.Random(), texts)
            token = auth_svc.create_session(conn, game["id"], pid)
    except auth_svc.RegisterError as e:
        msg = texts["register_errors"][e.key].format(**e.params)
        raise HTTPException(400, detail=dict(key=e.key, message=msg))
    except sqlite3.IntegrityError:
        # [FIX] 校验与写入不在同一事务:并发同名/同名同姓注册撞 UNIQUE → 友好提示
        raise HTTPException(400, detail=dict(
            key="dup", message=texts["register_errors"]["dup"]))
    response.set_cookie(auth_svc.SESSION_COOKIE, token, httponly=True,
                        samesite="lax", secure=config.COOKIE_SECURE)
    return dict(ok=True, intro=texts["intro"])


class LoginForm(BaseModel):
    username: str
    password: str


@router.post("/login")
def login(form: LoginForm, request: Request, response: Response, conn=Depends(get_conn)):
    texts = _texts()
    # [安全] 按 用户名+IP 双键失败锁定,阻断在线爆破
    ip = request.client.host if request.client else "?"
    keys = (f"login:u:{form.username}", f"login:ip:{ip}")
    if any(ratelimit.is_locked(k) for k in keys):
        raise HTTPException(429, "尝试次数过多,请稍后再试")
    with transaction(conn):
        token, player, err = auth_svc.login(conn, form.username, form.password)
    if err:
        if err == "no_game":
            raise HTTPException(400, detail=dict(key=err, message="游戏尚未开始,请等待管理员开局。"))
        if err in ("no_id", "wrong_pass"):
            for k in keys:
                ratelimit.record_fail(k, max_fails=5, lock_secs=600)
        msg = texts["messages"].get(err, err)
        raise HTTPException(401, detail=dict(key=err, message=msg))
    for k in keys:
        ratelimit.clear(k)
    # 会话(含死亡角色)一律下发:死亡角色登录后进入只读死亡画面
    response.set_cookie(auth_svc.SESSION_COOKIE, token, httponly=True,
                        samesite="lax", secure=config.COOKIE_SECURE)
    if player["hit"] <= 0 or player["status"] == "dead":
        # [FIX] 死亡登录原为 403 且不带 cookie——前端无法进入死亡画面;
        # 改为 200+dead 标记,由前端弹窗提示后跳转
        msg = texts["messages"]["already_dead"].format(
            death=player["death_type"] or "不明", msg=player["msg"])
        return dict(ok=True, dead=True, message=msg)
    return dict(ok=True)


@router.post("/logout")
def logout(request: Request, response: Response, conn=Depends(get_conn)):
    auth_svc.delete_session(conn, request.cookies.get(auth_svc.SESSION_COOKIE))
    response.delete_cookie(auth_svc.SESSION_COOKIE)
    return dict(ok=True)


@router.get("/whoami")
def whoami(request: Request, conn=Depends(get_conn)):
    s, player = auth_svc.session_player(conn, request.cookies.get(auth_svc.SESSION_COOKIE))
    if not s:
        raise HTTPException(401, "未登录")
    if player is None:
        return dict(ok=True, admin=True)
    return dict(ok=True, player=dict(
        id=player["id"], username=player["username"],
        f_name=player["f_name"], l_name=player["l_name"]))
