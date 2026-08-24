#!/usr/bin/env python3
"""启动:python3 run.py [端口]"""
import os
import sys

import uvicorn

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
if not os.environ.get("BR_ADMIN_PASS"):
    print("[警告] 未设置 BR_ADMIN_PASS:管理后台登录已禁用。"
          "局域网/公网部署请务必配置。", file=sys.stderr)
uvicorn.run("app.main:app", host="0.0.0.0", port=port)
