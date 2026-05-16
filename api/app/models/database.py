import aiosqlite
import os
import logging
from pathlib import Path

logger = logging.getLogger("sre")

DB_PATH = os.getenv("DATABASE_PATH", "/data/sre.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS deployments (
    id TEXT PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    environment TEXT DEFAULT 'production',
    git_url TEXT,
    health_url TEXT,
    browser_url TEXT,
    expected_selector TEXT,
    tcp_checks TEXT,
    container_id TEXT,
    container_name TEXT,
    image TEXT,
    status TEXT DEFAULT 'unknown',
    last_check TEXT,
    probe_host_header TEXT,
    source TEXT DEFAULT 'docker',
    vhost_names TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id TEXT NOT NULL,
    check_type TEXT NOT NULL,
    status_code INTEGER,
    response_time_ms REAL,
    success INTEGER DEFAULT 0,
    error_message TEXT,
    checked_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
);

CREATE TABLE IF NOT EXISTS tcp_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id TEXT NOT NULL,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    success INTEGER DEFAULT 0,
    error_message TEXT,
    checked_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
);

CREATE TABLE IF NOT EXISTS browser_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id TEXT NOT NULL,
    url TEXT NOT NULL,
    status_code INTEGER,
    selector_found INTEGER DEFAULT 0,
    page_blank INTEGER DEFAULT 0,
    error_message TEXT,
    checked_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
);

CREATE TABLE IF NOT EXISTS container_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id TEXT NOT NULL,
    container_state TEXT,
    restart_count INTEGER DEFAULT 0,
    exit_code INTEGER,
    cpu_percent REAL,
    memory_usage_mb REAL,
    memory_limit_mb REAL,
    network_rx_bytes INTEGER,
    network_tx_bytes INTEGER,
    collected_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
);

CREATE TABLE IF NOT EXISTS vps_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT NOT NULL,
    os_name TEXT,
    kernel TEXT,
    docker_version TEXT,
    cpu_count INTEGER,
    memory_total_mb REAL,
    disk_total_gb REAL,
    disk_used_gb REAL,
    collected_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS docker_sizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id TEXT NOT NULL,
    images_mb REAL,
    containers_mb REAL,
    volumes_mb REAL,
    build_cache_mb REAL,
    collected_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS traefik_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id TEXT,
    method TEXT,
    path TEXT,
    status_code INTEGER,
    duration_ms REAL,
    upstream TEXT,
    remote_ip TEXT,
    logged_at TEXT,
    raw_line TEXT,
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
);

CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id TEXT,
    title TEXT NOT NULL,
    severity TEXT DEFAULT 'warning',
    status TEXT DEFAULT 'open',
    environment TEXT DEFAULT 'production',
    trigger_type TEXT,
    error_category TEXT,
    fingerprint TEXT,
    started_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT,
    suggested_fix TEXT,
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
);

CREATE TABLE IF NOT EXISTS incident_timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    message TEXT,
    occurred_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (incident_id) REFERENCES incidents(id)
);

CREATE TABLE IF NOT EXISTS user_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id TEXT,
    source TEXT DEFAULT 'traefik',
    path TEXT NOT NULL,
    method TEXT,
    status_code INTEGER NOT NULL,
    error_category TEXT,
    count INTEGER DEFAULT 1,
    first_seen TEXT DEFAULT (datetime('now')),
    last_seen TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (deployment_id) REFERENCES deployments(id)
);

CREATE TABLE IF NOT EXISTS log_ingest_state (
    source TEXT NOT NULL,
    file_path TEXT NOT NULL,
    offset INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (source, file_path)
);

CREATE INDEX IF NOT EXISTS idx_health_deployment ON health_checks(deployment_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_incident_deployment ON incidents(deployment_id);
CREATE INDEX IF NOT EXISTS idx_incident_fingerprint ON incidents(fingerprint, status);
CREATE INDEX IF NOT EXISTS idx_user_errors_path ON user_errors(path, status_code);
CREATE INDEX IF NOT EXISTS idx_traefik_logs_path ON traefik_logs(path, status_code);
"""


async def get_db() -> aiosqlite.Connection:
    Path(os.path.dirname(DB_PATH)).mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        await db.commit()
        logger.info("Database schema initialized")
        await migrate_deployments_schema(db)
        await db.commit()
    finally:
        await db.close()


async def migrate_deployments_schema(db: aiosqlite.Connection):
    """Add columns introduced after first release (SQLite has limited ALTER)."""
    cursor = await db.execute("PRAGMA table_info(deployments)")
    rows = await cursor.fetchall()
    colnames = {row[1] for row in rows}
    if "probe_host_header" not in colnames:
        await db.execute("ALTER TABLE deployments ADD COLUMN probe_host_header TEXT")
        logger.info("Migration: deployments.probe_host_header added")
    if "source" not in colnames:
        await db.execute("ALTER TABLE deployments ADD COLUMN source TEXT DEFAULT 'docker'")
        logger.info("Migration: deployments.source added")
    if "vhost_names" not in colnames:
        await db.execute("ALTER TABLE deployments ADD COLUMN vhost_names TEXT")
        logger.info("Migration: deployments.vhost_names added")

    cursor = await db.execute("PRAGMA table_info(user_errors)")
    rows = await cursor.fetchall()
    user_error_cols = {row[1] for row in rows}
    if "source" not in user_error_cols:
        await db.execute("ALTER TABLE user_errors ADD COLUMN source TEXT DEFAULT 'traefik'")
        logger.info("Migration: user_errors.source added")
    await db.execute("CREATE INDEX IF NOT EXISTS idx_user_errors_source ON user_errors(source)")


async def execute(query: str, params=(), commit: bool = True):
    db = await get_db()
    try:
        await db.execute(query, params)
        if commit:
            await db.commit()
    finally:
        await db.close()


async def execute_insert(query: str, params=()) -> int:
    """Run INSERT and return SQLite last_insert_rowid()."""
    db = await get_db()
    try:
        cursor = await db.execute(query, params)
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()


async def fetch_one(query: str, params=()):
    db = await get_db()
    try:
        cursor = await db.execute(query, params)
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()


async def fetch_all(query: str, params=()):
    db = await get_db()
    try:
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()
