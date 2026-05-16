import os
import asyncio
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.models.database import init_db
from app.routers import overview, deployments, incidents, errors, infrastructure
from app.workers.monitor import start_scheduler, run_all_checks
from app.workers.demo import seed_demo_deployments, seed_demo_historical_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("sre")

DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")
DASHBOARD_PASS = os.getenv("DASHBOARD_PASS", "admin")
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"

app = FastAPI(title="SRE Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Simple auth dependency
def check_auth(request: Request):
    if not AUTH_ENABLED:
        return True
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Basic "):
        import base64
        try:
            decoded = base64.b64decode(auth[6:]).decode()
            user, pwd = decoded.split(":", 1)
            if user == DASHBOARD_USER and pwd == DASHBOARD_PASS:
                return True
        except Exception:
            pass
    # Allow unauthenticated access for health/API endpoints used by frontend
    # In production, put behind VPN/reverse proxy auth
    return True


app.include_router(overview.router)
app.include_router(deployments.router)
app.include_router(incidents.router)
app.include_router(errors.router)
app.include_router(infrastructure.router)


@app.on_event("startup")
async def startup():
    logger.info("SRE Agent starting up...")
    await init_db()

    # Skip scheduler and initial checks in test mode
    TEST_MODE = os.getenv("TEST_MODE", "false").lower() == "true"
    if TEST_MODE:
        logger.info("Test mode: skipping scheduler and initial checks")
        return

    # Demo: deployments must exist before health_checks / user_errors (FK)
    if os.getenv("DEMO_MODE", "false").lower() == "true":
        logger.info("Demo mode enabled, seeding demo deployments and historical data...")
        try:
            await seed_demo_deployments()
            await seed_demo_historical_data()
        except Exception as e:
            logger.warning(f"Demo seed failed: {e}")

    # Run initial check in background so HTTP routes (e.g. /api/overview) are available immediately.
    logger.info("Scheduling initial monitoring check in background...")
    async def _initial_checks():
        try:
            await run_all_checks()
        except Exception as e:
            logger.error(f"Initial check failed: {e}")

    asyncio.create_task(_initial_checks())

    # Start background scheduler
    start_scheduler()
    logger.info("SRE Agent ready")


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "sre-agent-api"}


@app.get("/")
async def root():
    return {"service": "SRE Agent API", "docs": "/docs"}
