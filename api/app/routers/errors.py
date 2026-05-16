from fastapi import APIRouter
from app.models.database import fetch_all, fetch_one

router = APIRouter(prefix="/api", tags=["errors"])


@router.get("/errors")
async def list_errors():
    errors = await fetch_all(
        """SELECT hc.deployment_id, hc.check_type, hc.status_code, hc.error_message, hc.checked_at,
            d.slug as deployment_slug
        FROM health_checks hc
        LEFT JOIN deployments d ON hc.deployment_id = d.id
        WHERE hc.success = 0
        ORDER BY hc.checked_at DESC LIMIT 200"""
    )
    return errors


@router.get("/user-errors")
async def list_user_errors():
    errors = await fetch_all(
        """SELECT id, deployment_id, path, method, status_code, error_category, count, first_seen, last_seen
        FROM user_errors
        ORDER BY count DESC LIMIT 100"""
    )
    return errors


@router.get("/user-errors/summary")
async def user_errors_summary():
    top_paths = await fetch_all(
        """SELECT path, SUM(count) as total_count, error_category, status_code
        FROM user_errors
        GROUP BY path, status_code
        ORDER BY total_count DESC LIMIT 20"""
    )

    by_category = await fetch_all(
        """SELECT error_category, SUM(count) as total_count, COUNT(*) as distinct_errors
        FROM user_errors
        GROUP BY error_category
        ORDER BY total_count DESC"""
    )

    by_status = await fetch_all(
        """SELECT status_code, SUM(count) as total_count
        FROM user_errors
        GROUP BY status_code
        ORDER BY total_count DESC"""
    )

    return {
        "top_failing_paths": top_paths,
        "by_category": by_category,
        "by_status_code": by_status,
    }
