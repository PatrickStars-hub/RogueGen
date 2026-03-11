import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.sessions import router as sessions_router
from api.history import router as history_router
from config import settings
from db.session_store import init_db
from graph.builder import init_graph, cleanup_graph

# 确保静态资源目录存在
_STATIC_ART_DIR = Path(__file__).parent / settings.ART_OUTPUT_DIR
_STATIC_ART_DIR.mkdir(parents=True, exist_ok=True)
_STATIC_GAMES_DIR = Path(__file__).parent / "static" / "games"
_STATIC_GAMES_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_graph()
    yield
    await cleanup_graph()


app = FastAPI(
    title="Roguelike Game Generator API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://localhost:8765"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录，前端可通过 /static/art/{session_id}/{filename} 访问生成的图片
app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(sessions_router)
app.include_router(history_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "roguelike-generator"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
