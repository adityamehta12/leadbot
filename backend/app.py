import asyncio
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import BUSINESS_COLOR, BUSINESS_NAME, DATABASE_URL, GREETING, PORT
from db import dispose_engine
from redis_client import close_redis
from routers import auth, calendar, chat, config, dashboard, leads
from services.webhook_service import webhook_retry_loop


def _run_migrations():
    """Run Alembic migrations on startup if DATABASE_URL is set."""
    if not DATABASE_URL:
        return
    try:
        from alembic import command
        from alembic.config import Config
        alembic_cfg = Config(str(pathlib.Path(__file__).resolve().parent / "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", DATABASE_URL.replace("+asyncpg", ""))
        command.upgrade(alembic_cfg, "head")
        print("Migrations complete.")
    except Exception as e:
        print(f"Migration warning: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Run migrations on startup
    _run_migrations()
    # Startup: launch background webhook retry loop
    retry_task = None
    if DATABASE_URL:
        retry_task = asyncio.create_task(webhook_retry_loop())
    yield
    # Shutdown
    if retry_task:
        retry_task.cancel()
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    application = FastAPI(lifespan=lifespan)

    # ── CORS ─────────────────────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Templates ────────────────────────────────────────────
    _app_dir = pathlib.Path(__file__).resolve().parent
    templates = Jinja2Templates(directory=str(_app_dir / "templates"))
    application.state.templates = templates

    # ── Static files ─────────────────────────────────────────
    STATIC_DIR = _app_dir / "static" if (_app_dir / "static").is_dir() else _app_dir.parent / "static"
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Also mount dashboard static files
    DASH_STATIC = _app_dir / "static" / "dashboard"
    if DASH_STATIC.is_dir():
        # Already covered by /static mount above
        pass

    # ── Routers ──────────────────────────────────────────────
    application.include_router(chat.router)
    application.include_router(config.router)
    application.include_router(auth.router)
    application.include_router(leads.router)
    application.include_router(calendar.router)
    application.include_router(dashboard.router)

    # ── Health check ─────────────────────────────────────────
    @application.get("/api/health")
    def health_check():
        return {"status": "ok"}

    # ── Legacy config endpoint (no tenant_id = default) ──────
    @application.get("/api/config")
    def get_config():
        return {
            "business_name": BUSINESS_NAME,
            "color": BUSINESS_COLOR,
            "greeting": GREETING,
        }

    # ── Demo page ────────────────────────────────────────────
    @application.get("/")
    def serve_demo():
        return FileResponse(str(STATIC_DIR / "demo.html"))

    return application


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
