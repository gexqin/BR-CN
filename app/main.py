"""FastAPI 入口:路由注册、静态前端、DB 初始化。"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .api import admin, auth, game


@asynccontextmanager
async def lifespan(_app):
    db.init_db()
    yield


app = FastAPI(title="BATTLE ROYALE CN v2", version=config.VER, lifespan=lifespan)

app.include_router(auth.router)
app.include_router(game.router)
app.include_router(admin.router)

STATIC = os.path.join(config.BASE_DIR, "static")
app.mount("/static", StaticFiles(directory=STATIC, html=True), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC, "index.html"))
