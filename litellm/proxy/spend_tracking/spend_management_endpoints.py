#### SPEND MANAGEMENT #####
import collections
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional

import fastapi
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
import asyncio
import json
from typing import AsyncGenerator

import litellm
from litellm._logging import verbose_proxy_logger
from litellm.proxy._types import *
from litellm.proxy._types import ProviderBudgetResponse, ProviderBudgetResponseObject
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.proxy.spend_tracking.spend_tracking_utils import (
    get_spend_by_team_and_customer,
)
from litellm.proxy.utils import handle_exception_on_proxy

# Import caching utilities for performance optimization
try:
    from litellm.proxy.cache.spend_cache import cached_endpoint, SpendCache
except ImportError:
    # Fallback if cache module is not available
    def cached_endpoint(endpoint_name: str, ttl_seconds: int = None):
        def decorator(func):
            return func
        return decorator

if TYPE_CHECKING:
    from litellm.proxy.proxy_server import PrismaClient
else:
    PrismaClient = Any

router = APIRouter()


@router.get(
    "/global/spend/models",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def global_spend_models(
    limit: int = fastapi.Query(default=10, description="Maximum number of models to return"),
):
    """
    Get top models by spend using materialized view for better performance.
    """
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    try:
        # Try to use materialized view first
        sql_query = """
            SELECT model, total_spend::FLOAT as total_spend 
            FROM "TopModelsBySpend" 
            ORDER BY total_spend DESC 
            LIMIT {};
        """.format(limit)
        
        response = await prisma_client.db.query_raw(query=sql_query)
        return response
        
    except Exception as e:
        # Fallback to regular aggregation if materialized view doesn't exist
        verbose_proxy_logger.warning(f"Materialized view not found, using fallback: {e}")
        
        sql_query = """
            SELECT 
                model,
                SUM(spend)::FLOAT as total_spend
            FROM "LiteLLM_DailyUserSpend"
            WHERE date >= CURRENT_DATE - INTERVAL '30 days'
                AND model IS NOT NULL
            GROUP BY model
            ORDER BY total_spend DESC
            LIMIT {};
        """.format(limit)
        
        response = await prisma_client.db.query_raw(query=sql_query)
        return response


@router.get(
    "/global/spend/keys",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def global_spend_keys(
    limit: int = fastapi.Query(default=10, description="Maximum number of keys to return"),
):
    """
    Get top API keys by spend using materialized view for better performance.
    """
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    try:
        # Try to use materialized view first
        sql_query = """
            SELECT api_key, total_spend::FLOAT as total_spend 
            FROM "TopKeysBySpend" 
            ORDER BY total_spend DESC 
            LIMIT {};
        """.format(limit)
        
        response = await prisma_client.db.query_raw(query=sql_query)
        return response
        
    except Exception as e:
        # Fallback to regular aggregation if materialized view doesn't exist
        verbose_proxy_logger.warning(f"Materialized view not found, using fallback: {e}")
        
        sql_query = """
            SELECT 
                api_key,
                SUM(spend)::FLOAT as total_spend
            FROM "LiteLLM_DailyUserSpend"
            WHERE date >= CURRENT_DATE - INTERVAL '30 days'
                AND api_key IS NOT NULL
            GROUP BY api_key
            ORDER BY total_spend DESC
            LIMIT {};
        """.format(limit)
        
        response = await prisma_client.db.query_raw(query=sql_query)
        return response


@router.get(
    "/global/spend/stream",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def stream_spend_data():
    """
    Stream real-time spend data updates using Server-Sent Events.
    This allows the UI to receive incremental updates without polling.
    """
    async def generate_spend_stream() -> AsyncGenerator[str, None]:
        from litellm.proxy.proxy_server import prisma_client
        
        if prisma_client is None:
            yield f"data: {json.dumps({'error': 'No database connected'})}\n\n"
            return
        
        try:
            # Send initial data
            initial_data = {
                'type': 'initial',
                'timestamp': datetime.now().isoformat(),
                'status': 'connected'
            }
            yield f"data: {json.dumps(initial_data)}\n\n"
            
            # Stream incremental updates every 5 seconds
            while True:
                try:
                    # Get latest spend summary
                    sql_query = """
                        SELECT 
                            COUNT(*) as total_requests,
                            SUM(spend)::FLOAT as total_spend,
                            COUNT(DISTINCT api_key) as unique_keys
                        FROM "LiteLLM_DailyUserSpend"
                        WHERE date = CURRENT_DATE;
                    """
                    
                    result = await prisma_client.db.query_raw(query=sql_query)
                    
                    update_data = {
                        'type': 'update',
                        'timestamp': datetime.now().isoformat(),
                        'data': result[0] if result else {},
                        'status': 'ok'
                    }
                    
                    yield f"data: {json.dumps(update_data)}\n\n"
                    
                except Exception as e:
                    error_data = {
                        'type': 'error',
                        'timestamp': datetime.now().isoformat(),
                        'error': str(e),
                        'status': 'error'
                    }
                    yield f"data: {json.dumps(error_data)}\n\n"
                
                await asyncio.sleep(5)  # Update every 5 seconds
                
        except asyncio.CancelledError:
            # Client disconnected
            yield f"data: {json.dumps({'type': 'disconnect', 'status': 'disconnected'})}\n\n"
    
    return StreamingResponse(
        generate_spend_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )


@router.get(
    "/global/spend/dashboard-summary",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
@cached_endpoint("dashboard_summary", ttl_seconds=300)  # Cache for 5 minutes
async def get_dashboard_summary(
    days: int = fastapi.Query(default=30, description="Number of days to aggregate"),
):
    """
    Get dashboard summary statistics for faster loading.
    Returns all key metrics in a single API call.
    """
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    try:
        # Get comprehensive dashboard summary in one query
        sql_query = """
            WITH daily_summary AS (
                SELECT 
                    date,
                    SUM(spend)::FLOAT as daily_spend,
                    SUM(api_requests) as daily_requests,
                    SUM(prompt_tokens + completion_tokens) as daily_tokens,
                    COUNT(DISTINCT api_key) as daily_unique_keys,
                    COUNT(DISTINCT user_id) as daily_unique_users
                FROM "LiteLLM_DailyUserSpend"
                WHERE date >= CURRENT_DATE - INTERVAL '{} days'
                GROUP BY date
            ),
            totals AS (
                SELECT 
                    SUM(daily_spend) as total_spend,
                    SUM(daily_requests) as total_requests,
                    SUM(daily_tokens) as total_tokens,
                    AVG(daily_spend) as avg_daily_spend,
                    AVG(daily_requests) as avg_daily_requests,
                    COUNT(DISTINCT daily_unique_keys) as total_unique_keys,
                    COUNT(DISTINCT daily_unique_users) as total_unique_users,
                    MAX(daily_spend) as peak_daily_spend,
                    MIN(daily_spend) as min_daily_spend
                FROM daily_summary
            ),
            current_month AS (
                SELECT 
                    SUM(spend)::FLOAT as monthly_spend,
                    SUM(api_requests) as monthly_requests
                FROM "LiteLLM_DailyUserSpend"
                WHERE date >= DATE_TRUNC('month', CURRENT_DATE)
            )
            SELECT 
                t.total_spend,
                t.total_requests,
                t.total_tokens,
                t.avg_daily_spend,
                t.avg_daily_requests,
                t.total_unique_keys,
                t.total_unique_users,
                t.peak_daily_spend,
                t.min_daily_spend,
                cm.monthly_spend,
                cm.monthly_requests,
                CURRENT_DATE as report_date
            FROM totals t, current_month cm;
        """.format(days)
        
        result = await prisma_client.db.query_raw(query=sql_query)
        
        if not result:
            return {
                "total_spend": 0,
                "total_requests": 0,
                "total_tokens": 0,
                "avg_daily_spend": 0,
                "avg_daily_requests": 0,
                "total_unique_keys": 0,
                "total_unique_users": 0,
                "monthly_spend": 0,
                "monthly_requests": 0,
                "period_days": days
            }
        
        summary = result[0]
        summary["period_days"] = days
        return summary
        
    except Exception as e:
        verbose_proxy_logger.error(f"Error in dashboard summary: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": str(e)})


@router.get(
    "/global/spend/activity-summary",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
@cached_endpoint("activity_summary", ttl_seconds=180)  # Cache for 3 minutes
async def get_activity_summary(
    days: int = fastapi.Query(default=30, description="Number of days for activity summary"),
):
    """
    Get aggregated activity summary for charts.
    Pre-calculates daily totals for faster chart rendering.
    """
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    try:
        # Get daily activity summary
        sql_query = """
            SELECT 
                date,
                SUM(api_requests) as api_requests,
                SUM(prompt_tokens + completion_tokens) as total_tokens,
                SUM(spend)::FLOAT as spend,
                COUNT(DISTINCT api_key) as unique_keys
            FROM "LiteLLM_DailyUserSpend"
            WHERE date >= CURRENT_DATE - INTERVAL '{} days'
            GROUP BY date
            ORDER BY date ASC;
        """.format(days)
        
        daily_data = await prisma_client.db.query_raw(query=sql_query)
        
        # Calculate summary totals
        total_requests = sum(row.get('api_requests', 0) for row in daily_data)
        total_tokens = sum(row.get('total_tokens', 0) for row in daily_data)
        total_spend = sum(row.get('spend', 0) for row in daily_data)
        
        return {
            "sum_api_requests": total_requests,
            "sum_total_tokens": total_tokens,
            "sum_spend": total_spend,
            "daily_data": daily_data,
            "period_days": days
        }
        
    except Exception as e:
        verbose_proxy_logger.error(f"Error in activity summary: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": str(e)})


@router.get(
    "/global/spend/teams-summary",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
@cached_endpoint("teams_summary", ttl_seconds=300)  # Cache for 5 minutes
async def get_teams_summary(
    days: int = fastapi.Query(default=30, description="Number of days for team summary"),
    limit: int = fastapi.Query(default=10, description="Number of top teams to return"),
):
    """
    Get aggregated team spend summary.
    """
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    try:
        # Get team spend summary
        sql_query = """
            SELECT 
                COALESCE(t.team_alias, dts.team_id, 'Unassigned') as team_name,
                dts.team_id,
                SUM(dts.spend)::FLOAT as total_spend,
                SUM(dts.api_requests) as total_requests,
                COUNT(DISTINCT dts.date) as active_days,
                AVG(dts.spend)::FLOAT as avg_daily_spend,
                MAX(dts.spend)::FLOAT as peak_daily_spend
            FROM "LiteLLM_DailyTeamSpend" dts
            LEFT JOIN "LiteLLM_TeamTable" t ON dts.team_id = t.team_id
            WHERE dts.date >= CURRENT_DATE - INTERVAL '{} days'
                AND dts.team_id IS NOT NULL
            GROUP BY t.team_alias, dts.team_id
            ORDER BY total_spend DESC
            LIMIT {};
        """.format(days, limit)
        
        teams_data = await prisma_client.db.query_raw(query=sql_query)
        
        # Format for UI consumption
        total_spend_per_team = [
            {
                "name": team.get("team_name", "Unknown"),
                "value": team.get("total_spend", 0),
                "team_id": team.get("team_id"),
                "total_requests": team.get("total_requests", 0),
                "active_days": team.get("active_days", 0),
                "avg_daily_spend": team.get("avg_daily_spend", 0),
                "peak_daily_spend": team.get("peak_daily_spend", 0)
            }
            for team in teams_data
        ]
        
        return {
            "total_spend_per_team": total_spend_per_team,
            "teams": [team["team_id"] for team in teams_data],
            "period_days": days
        }
        
    except Exception as e:
        verbose_proxy_logger.error(f"Error in teams summary: {str(e)}")
        raise HTTPException(status_code=500, detail={"error": str(e)})


@router.get(
    "/spend/keys",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def spend_key_fn():
    """
    View all keys created, ordered by spend

    Example Request:
    ```
    curl -X GET "http://0.0.0.0:8000/spend/keys" \
-H "Authorization: Bearer sk-1234"
    ```
    """

    from litellm.proxy.proxy_server import prisma_client

    try:
        if prisma_client is None:
            raise Exception(
                "Database not connected. Connect a database to your proxy - https://docs.litellm.ai/docs/simple_proxy#managing-auth---virtual-keys"
            )

        key_info = await prisma_client.get_data(table_name="key", query_type="find_all")
        return key_info

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(e)},
        )


@router.get(
    "/spend/users",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def spend_user_fn(
    user_id: Optional[str] = fastapi.Query(
        default=None,
        description="Get User Table row for user_id",
    ),
):
    """
    View all users created, ordered by spend

    Example Request:
    ```
    curl -X GET "http://0.0.0.0:8000/spend/users" \
-H "Authorization: Bearer sk-1234"
    ```

    View User Table row for user_id
    ```
    curl -X GET "http://0.0.0.0:8000/spend/users?user_id=1234" \
-H "Authorization: Bearer sk-1234"
    ```
    """
    from litellm.proxy.proxy_server import prisma_client

    try:
        if prisma_client is None:
            raise Exception(
                "Database not connected. Connect a database to your proxy - https://docs.litellm.ai/docs/simple_proxy#managing-auth---virtual-keys"
            )

        if user_id is not None:
            user_info = await prisma_client.get_data(
                table_name="user", query_type="find_unique", user_id=user_id
            )
            return [user_info]
        else:
            user_info = await prisma_client.get_data(
                table_name="user", query_type="find_all"
            )

        return user_info

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(e)},
        )


@router.get(
    "/spend/tags",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    responses={
        200: {"model": List[LiteLLM_SpendLogs]},
    },
)
async def view_spend_tags(
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time from which to start viewing key spend",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time till which to view key spend",
    ),
):
    """
    LiteLLM Enterprise - View Spend Per Request Tag

    Example Request:
    ```
    curl -X GET "http://0.0.0.0:8000/spend/tags" \
-H "Authorization: Bearer sk-1234"
    ```

    Spend with Start Date and End Date
    ```
    curl -X GET "http://0.0.0.0:8000/spend/tags?start_date=2022-01-01&end_date=2022-02-01" \
-H "Authorization: Bearer sk-1234"
    ```
    """

    try:
        from enterprise.utils import get_spend_by_tags
    except ImportError:
        raise Exception(
            "Trying to use Spend by Tags"
            + CommonProxyErrors.missing_enterprise_package_docker.value
        )
    from litellm.proxy.proxy_server import prisma_client

    try:
        if prisma_client is None:
            raise Exception(
                "Database not connected. Connect a database to your proxy - https://docs.litellm.ai/docs/simple_proxy#managing-auth---virtual-keys"
            )

        # run the following SQL query on prisma
        """
        SELECT
        jsonb_array_elements_text(request_tags) AS individual_request_tag,
        COUNT(*) AS log_count,
        SUM(spend) AS total_spend
        FROM "LiteLLM_SpendLogs"
        GROUP BY individual_request_tag;
        """
        response = await get_spend_by_tags(
            start_date=start_date, end_date=end_date, prisma_client=prisma_client
        )

        return response
    except Exception as e:
        if isinstance(e, HTTPException):
            raise ProxyException(
                message=getattr(e, "detail", f"/spend/tags Error({str(e)})"),
                type="internal_error",
                param=getattr(e, "param", "None"),
                code=getattr(e, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR),
            )
        elif isinstance(e, ProxyException):
            raise e
        raise ProxyException(
            message="/spend/tags Error" + str(e),
            type="internal_error",
            param=getattr(e, "param", "None"),
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


async def get_global_activity_internal_user(
    user_api_key_dict: UserAPIKeyAuth, start_date: datetime, end_date: datetime
):
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})

    user_id = user_api_key_dict.user_id
    if user_id is None:
        raise HTTPException(status_code=500, detail={"error": "No user_id found"})

    sql_query = """
    SELECT
        date_trunc('day', "startTime") AS date,
        COUNT(*) AS api_requests,
        SUM(total_tokens) AS total_tokens
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" BETWEEN $1::date AND $2::date + interval '1 day'
    AND "user" = $3
    GROUP BY date_trunc('day', "startTime")
    """
    db_response = await prisma_client.db.query_raw(
        sql_query, start_date, end_date, user_id
    )

    return db_response


@router.get(
    "/global/activity",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    responses={
        200: {"model": List[LiteLLM_SpendLogs]},
    },
    include_in_schema=False,
)
async def get_global_activity(
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time from which to start viewing spend",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time till which to view spend",
    ),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    Get number of API Requests, total tokens through proxy

    {
        "daily_data": [
                const chartdata = [
                {
                date: 'Jan 22',
                api_requests: 10,
                total_tokens: 2000
                },
                {
                date: 'Jan 23',
                api_requests: 10,
                total_tokens: 12
                },
        ],
        "sum_api_requests": 20,
        "sum_total_tokens": 2012
    }
    """

    if start_date is None or end_date is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Please provide start_date and end_date"},
        )

    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

    from litellm.proxy.proxy_server import prisma_client

    try:
        if prisma_client is None:
            raise Exception(
                "Database not connected. Connect a database to your proxy - https://docs.litellm.ai/docs/simple_proxy#managing-auth---virtual-keys"
            )

        if (
            user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER
            or user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER_VIEW_ONLY
        ):
            db_response = await get_global_activity_internal_user(
                user_api_key_dict, start_date_obj, end_date_obj
            )
        else:
            sql_query = """
            SELECT
                date_trunc('day', "startTime") AS date,
                COUNT(*) AS api_requests,
                SUM(total_tokens) AS total_tokens
            FROM "LiteLLM_SpendLogs"
            WHERE "startTime" BETWEEN $1::date AND $2::date + interval '1 day'
            GROUP BY date_trunc('day', "startTime")
            """
            db_response = await prisma_client.db.query_raw(
                sql_query, start_date_obj, end_date_obj
            )

        if db_response is None:
            return []

        sum_api_requests = 0
        sum_total_tokens = 0
        daily_data = []
        for row in db_response:
            # cast date to datetime
            _date_obj = datetime.fromisoformat(row["date"])
            row["date"] = _date_obj.strftime("%b %d")

            daily_data.append(row)
            sum_api_requests += row.get("api_requests", 0)
            sum_total_tokens += row.get("total_tokens", 0)

        # sort daily_data by date
        daily_data = sorted(daily_data, key=lambda x: x["date"])

        data_to_return = {
            "daily_data": daily_data,
            "sum_api_requests": sum_api_requests,
            "sum_total_tokens": sum_total_tokens,
        }

        return data_to_return

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(e)},
        )


async def get_global_activity_model_internal_user(
    user_api_key_dict: UserAPIKeyAuth, start_date: datetime, end_date: datetime
):
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})

    user_id = user_api_key_dict.user_id
    if user_id is None:
        raise HTTPException(status_code=500, detail={"error": "No user_id found"})

    sql_query = """
    SELECT
        model_group,
        date_trunc('day', "startTime") AS date,
        COUNT(*) AS api_requests,
        SUM(total_tokens) AS total_tokens
    FROM "LiteLLM_SpendLogs"
    WHERE "startTime" BETWEEN $1::date AND $2::date + interval '1 day'
    AND "user" = $3
    GROUP BY model_group, date_trunc('day', "startTime")
    """
    db_response = await prisma_client.db.query_raw(
        sql_query, start_date, end_date, user_id
    )

    return db_response


@router.get(
    "/global/activity/model",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    responses={
        200: {"model": List[LiteLLM_SpendLogs]},
    },
    include_in_schema=False,
)
async def get_global_activity_model(
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time from which to start viewing spend",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time till which to view spend",
    ),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    Get number of API Requests, total tokens through proxy - Grouped by MODEL

    [
        {
            "model": "gpt-4",
            "daily_data": [
                    const chartdata = [
                    {
                    date: 'Jan 22',
                    api_requests: 10,
                    total_tokens: 2000
                    },
                    {
                    date: 'Jan 23',
                    api_requests: 10,
                    total_tokens: 12
                    },
            ],
            "sum_api_requests": 20,
            "sum_total_tokens": 2012

        },
        {
            "model": "azure/gpt-4-turbo",
            "daily_data": [
                    const chartdata = [
                    {
                    date: 'Jan 22',
                    api_requests: 10,
                    total_tokens: 2000
                    },
                    {
                    date: 'Jan 23',
                    api_requests: 10,
                    total_tokens: 12
                    },
            ],
            "sum_api_requests": 20,
            "sum_total_tokens": 2012

        },
    ]
    """

    if start_date is None or end_date is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Please provide start_date and end_date"},
        )

    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

    from litellm.proxy.proxy_server import prisma_client

    try:
        if prisma_client is None:
            raise Exception(
                "Database not connected. Connect a database to your proxy - https://docs.litellm.ai/docs/simple_proxy#managing-auth---virtual-keys"
            )

        if (
            user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER
            or user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER_VIEW_ONLY
        ):
            db_response = await get_global_activity_model_internal_user(
                user_api_key_dict, start_date_obj, end_date_obj
            )
        else:
            sql_query = """
            SELECT
                model_group,
                date_trunc('day', "startTime") AS date,
                COUNT(*) AS api_requests,
                SUM(total_tokens) AS total_tokens
            FROM "LiteLLM_SpendLogs"
            WHERE "startTime" BETWEEN $1::date AND $2::date + interval '1 day'
            GROUP BY model_group, date_trunc('day', "startTime")
            """
            db_response = await prisma_client.db.query_raw(
                sql_query, start_date_obj, end_date_obj
            )
        if db_response is None:
            return []

        model_ui_data: dict = (
            {}
        )  # {"gpt-4": {"daily_data": [], "sum_api_requests": 0, "sum_total_tokens": 0}}

        for row in db_response:
            _model = row["model_group"]
            if _model not in model_ui_data:
                model_ui_data[_model] = {
                    "daily_data": [],
                    "sum_api_requests": 0,
                    "sum_total_tokens": 0,
                }
            _date_obj = datetime.fromisoformat(row["date"])
            row["date"] = _date_obj.strftime("%b %d")

            model_ui_data[_model]["daily_data"].append(row)
            model_ui_data[_model]["sum_api_requests"] += row.get("api_requests", 0)
            model_ui_data[_model]["sum_total_tokens"] += row.get("total_tokens", 0)

        # sort mode ui data by sum_api_requests -> get top 10 models
        model_ui_data = dict(
            sorted(
                model_ui_data.items(),
                key=lambda x: x[1]["sum_api_requests"],
                reverse=True,
            )[:10]
        )

        response = []
        for model, data in model_ui_data.items():
            _sort_daily_data = sorted(data["daily_data"], key=lambda x: x["date"])

            response.append(
                {
                    "model": model,
                    "daily_data": _sort_daily_data,
                    "sum_api_requests": data["sum_api_requests"],
                    "sum_total_tokens": data["sum_total_tokens"],
                }
            )

        return response

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": str(e)},
        )


@router.get(
    "/global/activity/exceptions/deployment",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    responses={
        200: {"model": List[LiteLLM_SpendLogs]},
    },
    include_in_schema=False,
)
async def get_global_activity_exceptions_per_deployment(
    model_group: str = fastapi.Query(
        description="Filter by model group",
    ),
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time from which to start viewing spend",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time till which to view spend",
    ),
):
    """
    Get number of 429 errors - Grouped by deployment

    [
        {
            "deployment": "https://azure-us-east-1.openai.azure.com/",
            "daily_data": [
                    const chartdata = [
                    {
                    date: 'Jan 22',
                    num_rate_limit_exceptions: 10
                    },
                    {
                    date: 'Jan 23',
                    num_rate_limit_exceptions: 12
                    },
            ],
            "sum_num_rate_limit_exceptions": 20,

        },
        {
            "deployment": "https://azure-us-east-1.openai.azure.com/",
            "daily_data": [
                    const chartdata = [
                    {
                    date: 'Jan 22',
                    num_rate_limit_exceptions: 10,
                    },
                    {
                    date: 'Jan 23',
                    num_rate_limit_exceptions: 12
                    },
            ],
            "sum_num_rate_limit_exceptions": 20,

        },
    ]
    """

    if start_date is None or end_date is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Please provide start_date and end_date"},
        )

    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

    from litellm.proxy.proxy_server import prisma_client

    try:
        if prisma_client is None:
            raise Exception(
                "Database not connected. Connect a database to your proxy - https://docs.litellm.ai/docs/simple_proxy#managing-auth---virtual-keys"
            )

        sql_query = """
        SELECT
            api_base,
            date_trunc('day', "startTime")::date AS date,
            COUNT(*) AS num_rate_limit_exceptions
        FROM
            "LiteLLM_ErrorLogs"
        WHERE
            "startTime" >= $1::date
            AND "startTime" < ($2::date + INTERVAL '1 day')
            AND model_group = $3
            AND status_code = '429'
        GROUP BY
            api_base,
            date_trunc('day', "startTime")
        ORDER BY
            date;
        """
        db_response = await prisma_client.db.query_raw(
            sql_query, start_date_obj, end_date_obj, model_group
        )
        if db_response is None:
            return []

        model_ui_data: dict = (
            {}
        )  # {"gpt-4": {"daily_data": [], "sum_api_requests": 0, "sum_total_tokens": 0}}

        for row in db_response:
            _model = row["api_base"]
            if _model not in model_ui_data:
                model_ui_data[_model] = {
                    "daily_data": [],
                    "sum_num_rate_limit_exceptions": 0,
                }
            _date_obj = datetime.fromisoformat(row["date"])
            row["date"] = _date_obj.strftime("%b %d")

            model_ui_data[_model]["daily_data"].append(row)
            model_ui_data[_model]["sum_num_rate_limit_exceptions"] += row.get(
                "num_rate_limit_exceptions", 0
            )

        # sort mode ui data by sum_api_requests -> get top 10 models
        model_ui_data = dict(
            sorted(
                model_ui_data.items(),
                key=lambda x: x[1]["sum_num_rate_limit_exceptions"],
                reverse=True,
            )[:10]
        )

        response = []
        for model, data in model_ui_data.items():
            _sort_daily_data = sorted(data["daily_data"], key=lambda x: x["date"])

            response.append(
                {
                    "api_base": model,
                    "daily_data": _sort_daily_data,
                    "sum_num_rate_limit_exceptions": data[
                        "sum_num_rate_limit_exceptions"
                    ],
                }
            )

        return response

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": str(e)},
        )


@router.get(
    "/global/activity/exceptions",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    responses={
        200: {"model": List[LiteLLM_SpendLogs]},
    },
    include_in_schema=False,
)
async def get_global_activity_exceptions(
    model_group: str = fastapi.Query(
        description="Filter by model group",
    ),
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time from which to start viewing spend",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time till which to view spend",
    ),
):
    """
    Get number of API Requests, total tokens through proxy

    {
        "daily_data": [
                const chartdata = [
                {
                date: 'Jan 22',
                num_rate_limit_exceptions: 10,
                },
                {
                date: 'Jan 23',
                num_rate_limit_exceptions: 10,
                },
        ],
        "sum_api_exceptions": 20,
    }
    """

    if start_date is None or end_date is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Please provide start_date and end_date"},
        )

    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

    from litellm.proxy.proxy_server import prisma_client

    try:
        if prisma_client is None:
            raise Exception(
                "Database not connected. Connect a database to your proxy - https://docs.litellm.ai/docs/simple_proxy#managing-auth---virtual-keys"
            )

        sql_query = """
        SELECT
            date_trunc('day', "startTime")::date AS date,
            COUNT(*) AS num_rate_limit_exceptions
        FROM
            "LiteLLM_ErrorLogs"
        WHERE
            "startTime" >= $1::date
            AND "startTime" < ($2::date + INTERVAL '1 day')
            AND model_group = $3
            AND status_code = '429'
        GROUP BY
            date_trunc('day', "startTime")
        ORDER BY
            date;
        """
        db_response = await prisma_client.db.query_raw(
            sql_query, start_date_obj, end_date_obj, model_group
        )

        if db_response is None:
            return []

        sum_num_rate_limit_exceptions = 0
        daily_data = []
        for row in db_response:
            # cast date to datetime
            _date_obj = datetime.fromisoformat(row["date"])
            row["date"] = _date_obj.strftime("%b %d")

            daily_data.append(row)
            sum_num_rate_limit_exceptions += row.get("num_rate_limit_exceptions", 0)

        # sort daily_data by date
        daily_data = sorted(daily_data, key=lambda x: x["date"])

        data_to_return = {
            "daily_data": daily_data,
            "sum_num_rate_limit_exceptions": sum_num_rate_limit_exceptions,
        }

        return data_to_return

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(e)},
        )


@router.get(
    "/global/spend/provider",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
    responses={
        200: {"model": List[LiteLLM_SpendLogs]},
    },
)
async def get_global_spend_provider(
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time from which to start viewing spend",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time till which to view spend",
    ),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    Get breakdown of spend per provider
    [
        {
            "provider": "Azure OpenAI",
            "spend": 20
        },
        {
            "provider": "OpenAI",
            "spend": 10
        },
        {
            "provider": "VertexAI",
            "spend": 30
        }
    ]
    """
    from collections import defaultdict

    if start_date is None or end_date is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Please provide start_date and end_date"},
        )

    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

    from litellm.proxy.proxy_server import llm_router, prisma_client

    try:
        if prisma_client is None:
            raise Exception(
                "Database not connected. Connect a database to your proxy - https://docs.litellm.ai/docs/simple_proxy#managing-auth---virtual-keys"
            )

        if (
            user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER
            or user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER_VIEW_ONLY
        ):
            user_id = user_api_key_dict.user_id
            if user_id is None:
                raise HTTPException(
                    status_code=400, detail={"error": "No user_id found"}
                )

            sql_query = """
            SELECT
            model_id,
            SUM(spend) AS spend
            FROM "LiteLLM_SpendLogs"
            WHERE "startTime" BETWEEN $1::date AND $2::date 
            AND length(model_id) > 0
            AND "user" = $3
            GROUP BY model_id
            """
            db_response = await prisma_client.db.query_raw(
                sql_query, start_date_obj, end_date_obj, user_id
            )
        else:
            sql_query = """
            SELECT
            model_id,
            SUM(spend) AS spend
            FROM "LiteLLM_SpendLogs"
            WHERE "startTime" BETWEEN $1::date AND $2::date AND length(model_id) > 0
            GROUP BY model_id
            """
            db_response = await prisma_client.db.query_raw(
                sql_query, start_date_obj, end_date_obj
            )

        if db_response is None:
            return []

        ###################################
        # Convert model_id -> to Provider #
        ###################################

        # we use the in memory router for this
        ui_response = []
        provider_spend_mapping: defaultdict = defaultdict(int)
        for row in db_response:
            _model_id = row["model_id"]
            _provider = "Unknown"
            if llm_router is not None:
                _deployment = llm_router.get_deployment(model_id=_model_id)
                if _deployment is not None:
                    try:
                        _, _provider, _, _ = litellm.get_llm_provider(
                            model=_deployment.litellm_params.model,
                            custom_llm_provider=_deployment.litellm_params.custom_llm_provider,
                            api_base=_deployment.litellm_params.api_base,
                            litellm_params=_deployment.litellm_params,
                        )
                        provider_spend_mapping[_provider] += row["spend"]
                    except Exception:
                        pass

        for provider, spend in provider_spend_mapping.items():
            ui_response.append({"provider": provider, "spend": spend})

        return ui_response

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(e)},
        )


@router.get(
    "/global/spend/report",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    responses={
        200: {"model": List[LiteLLM_SpendLogs]},
    },
)
async def get_global_spend_report(
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time from which to start viewing spend",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time till which to view spend",
    ),
    group_by: Optional[Literal["team", "customer", "api_key"]] = fastapi.Query(
        default="team",
        description="Group spend by internal team or customer or api_key",
    ),
    api_key: Optional[str] = fastapi.Query(
        default=None,
        description="View spend for a specific api_key. Example api_key='sk-1234",
    ),
    internal_user_id: Optional[str] = fastapi.Query(
        default=None,
        description="View spend for a specific internal_user_id. Example internal_user_id='1234",
    ),
    team_id: Optional[str] = fastapi.Query(
        default=None,
        description="View spend for a specific team_id. Example team_id='1234",
    ),
    customer_id: Optional[str] = fastapi.Query(
        default=None,
        description="View spend for a specific customer_id. Example customer_id='1234. Can be used in conjunction with team_id as well.",
    ),
):
    """
    Get Daily Spend per Team, based on specific startTime and endTime. Per team, view usage by each key, model
    [
        {
            "group-by-day": "2024-05-10",
            "teams": [
                {
                    "team_name": "team-1"
                    "spend": 10,
                    "keys": [
                        "key": "1213",
                        "usage": {
                            "model-1": {
                                    "cost": 12.50,
                                    "input_tokens": 1000,
                                    "output_tokens": 5000,
                                    "requests": 100
                                },
                                "audio-modelname1": {
                                "cost": 25.50,
                                "seconds": 25,
                                "requests": 50
                        },
                        }
                    }
            ]
        ]
    }
    """
    if start_date is None or end_date is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "Please provide start_date and end_date"},
        )

    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

    from litellm.proxy.proxy_server import premium_user, prisma_client

    try:
        if prisma_client is None:
            raise Exception(
                "Database not connected. Connect a database to your proxy - https://docs.litellm.ai/docs/simple_proxy#managing-auth---virtual-keys"
            )

        if premium_user is not True:
            verbose_proxy_logger.debug("accessing /spend/report but not a premium user")
            raise ValueError(
                "/spend/report endpoint " + CommonProxyErrors.not_premium_user.value
            )
        if api_key is not None:
            verbose_proxy_logger.debug("Getting /spend for api_key: %s", api_key)
            if api_key.startswith("sk-"):
                api_key = hash_token(token=api_key)
            sql_query = """
                WITH SpendByModelApiKey AS (
                    SELECT
                        sl.api_key,
                        sl.model,
                        SUM(sl.spend) AS model_cost,
                        SUM(sl.prompt_tokens) AS model_input_tokens,
                        SUM(sl.completion_tokens) AS model_output_tokens
                    FROM
                        "LiteLLM_SpendLogs" sl
                    WHERE
                        sl."startTime" BETWEEN $1::date AND $2::date AND sl.api_key = $3
                    GROUP BY
                        sl.api_key,
                        sl.model
                )
                SELECT
                    api_key,
                    SUM(model_cost) AS total_cost,
                    SUM(model_input_tokens) AS total_input_tokens,
                    SUM(model_output_tokens) AS total_output_tokens,
                    jsonb_agg(jsonb_build_object(
                        'model', model,
                        'total_cost', model_cost,
                        'total_input_tokens', model_input_tokens,
                        'total_output_tokens', model_output_tokens
                    )) AS model_details
                FROM
                    SpendByModelApiKey
                GROUP BY
                    api_key
                ORDER BY
                    total_cost DESC;
            """
            db_response = await prisma_client.db.query_raw(
                sql_query, start_date_obj, end_date_obj, api_key
            )
            if db_response is None:
                return []

            return db_response
        elif internal_user_id is not None:
            verbose_proxy_logger.debug(
                "Getting /spend for internal_user_id: %s", internal_user_id
            )
            sql_query = """
                WITH SpendByModelApiKey AS (
                    SELECT
                        sl.api_key,
                        sl.model,
                        SUM(sl.spend) AS model_cost,
                        SUM(sl.prompt_tokens) AS model_input_tokens,
                        SUM(sl.completion_tokens) AS model_output_tokens
                    FROM
                        "LiteLLM_SpendLogs" sl
                    WHERE
                        sl."startTime" BETWEEN $1::date AND $2::date AND sl.user = $3
                    GROUP BY
                        sl.api_key,
                        sl.model
                )
                SELECT
                    api_key,
                    SUM(model_cost) AS total_cost,
                    SUM(model_input_tokens) AS total_input_tokens,
                    SUM(model_output_tokens) AS total_output_tokens,
                    jsonb_agg(jsonb_build_object(
                        'model', model,
                        'total_cost', model_cost,
                        'total_input_tokens', model_input_tokens,
                        'total_output_tokens', model_output_tokens
                    )) AS model_details
                FROM
                    SpendByModelApiKey
                GROUP BY
                    api_key
                ORDER BY
                    total_cost DESC;
            """
            db_response = await prisma_client.db.query_raw(
                sql_query, start_date_obj, end_date_obj, internal_user_id
            )
            if db_response is None:
                return []

            return db_response
        elif team_id is not None and customer_id is not None:
            return await get_spend_by_team_and_customer(
                start_date_obj, end_date_obj, team_id, customer_id, prisma_client
            )
        if group_by == "team":
            # first get data from spend logs -> SpendByModelApiKey
            # then read data from "SpendByModelApiKey" to format the response obj
            sql_query = """

            WITH SpendByModelApiKey AS (
                SELECT
                    date_trunc('day', sl."startTime") AS group_by_day,
                    COALESCE(tt.team_alias, 'Unassigned Team') AS team_name,
                    sl.model,
                    sl.api_key,
                    SUM(sl.spend) AS model_api_spend,
                    SUM(sl.total_tokens) AS model_api_tokens
                FROM 
                    "LiteLLM_SpendLogs" sl
                LEFT JOIN 
                    "LiteLLM_TeamTable" tt 
                ON 
                    sl.team_id = tt.team_id
                WHERE
                    sl."startTime" BETWEEN $1::date AND $2::date
                GROUP BY
                    date_trunc('day', sl."startTime"),
                    tt.team_alias,
                    sl.model,
                    sl.api_key
            )
                SELECT
                    group_by_day,
                    jsonb_agg(jsonb_build_object(
                        'team_name', team_name,
                        'total_spend', total_spend,
                        'metadata', metadata
                    )) AS teams
                FROM (
                    SELECT
                        group_by_day,
                        team_name,
                        SUM(model_api_spend) AS total_spend,
                        jsonb_agg(jsonb_build_object(
                            'model', model,
                            'api_key', api_key,
                            'spend', model_api_spend,
                            'total_tokens', model_api_tokens
                        )) AS metadata
                    FROM 
                        SpendByModelApiKey
                    GROUP BY
                        group_by_day,
                        team_name
                ) AS aggregated
                GROUP BY
                    group_by_day
                ORDER BY
                    group_by_day;
                """

            db_response = await prisma_client.db.query_raw(
                sql_query, start_date_obj, end_date_obj
            )
            if db_response is None:
                return []

            return db_response

        elif group_by == "customer":
            sql_query = """

            WITH SpendByModelApiKey AS (
                SELECT
                    date_trunc('day', sl."startTime") AS group_by_day,
                    sl.end_user AS customer,
                    sl.model,
                    sl.api_key,
                    SUM(sl.spend) AS model_api_spend,
                    SUM(sl.total_tokens) AS model_api_tokens
                FROM
                    "LiteLLM_SpendLogs" sl
                WHERE
                    sl."startTime" BETWEEN $1::date AND $2::date
                GROUP BY
                    date_trunc('day', sl."startTime"),
                    customer,
                    sl.model,
                    sl.api_key
            )
            SELECT
                group_by_day,
                jsonb_agg(jsonb_build_object(
                    'customer', customer,
                    'total_spend', total_spend,
                    'metadata', metadata
                )) AS customers
            FROM
                (
                    SELECT
                        group_by_day,
                        customer,
                        SUM(model_api_spend) AS total_spend,
                        jsonb_agg(jsonb_build_object(
                            'model', model,
                            'api_key', api_key,
                            'spend', model_api_spend,
                            'total_tokens', model_api_tokens
                        )) AS metadata
                    FROM
                        SpendByModelApiKey
                    GROUP BY
                        group_by_day,
                        customer
                ) AS aggregated
            GROUP BY
                group_by_day
            ORDER BY
                group_by_day;
                """

            db_response = await prisma_client.db.query_raw(
                sql_query, start_date_obj, end_date_obj
            )
            if db_response is None:
                return []

            return db_response
        elif group_by == "api_key":
            sql_query = """
                WITH SpendByModelApiKey AS (
                    SELECT
                        sl.api_key,
                        sl.model,
                        SUM(sl.spend) AS model_cost,
                        SUM(sl.prompt_tokens) AS model_input_tokens,
                        SUM(sl.completion_tokens) AS model_output_tokens
                    FROM
                        "LiteLLM_SpendLogs" sl
                    WHERE
                        sl."startTime" BETWEEN $1::date AND $2::date
                    GROUP BY
                        sl.api_key,
                        sl.model
                )
                SELECT
                    api_key,
                    SUM(model_cost) AS total_cost,
                    SUM(model_input_tokens) AS total_input_tokens,
                    SUM(model_output_tokens) AS total_output_tokens,
                    jsonb_agg(jsonb_build_object(
                        'model', model,
                        'total_cost', model_cost,
                        'total_input_tokens', model_input_tokens,
                        'total_output_tokens', model_output_tokens
                    )) AS model_details
                FROM
                    SpendByModelApiKey
                GROUP BY
                    api_key
                ORDER BY
                    total_cost DESC;
            """
            db_response = await prisma_client.db.query_raw(
                sql_query, start_date_obj, end_date_obj
            )
            if db_response is None:
                return []

            return db_response

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": str(e)},
        )


@router.get(
    "/global/spend/all_tag_names",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
    responses={
        200: {"model": List[LiteLLM_SpendLogs]},
    },
)
@cached_endpoint("tag_names", ttl_seconds=30*60)  # Cache for 30 minutes
async def global_get_all_tag_names():
    try:
        from litellm.proxy.proxy_server import prisma_client

        if prisma_client is None:
            raise Exception(
                "Database not connected. Connect a database to your proxy - https://docs.litellm.ai/docs/simple_proxy#managing-auth---virtual-keys"
            )

        # Use the daily tag spend table instead of raw SpendLogs for better performance
        sql_query = """
        SELECT DISTINCT tag AS individual_request_tag
        FROM "LiteLLM_DailyTagSpend"
        WHERE tag IS NOT NULL;
        """

        db_response = await prisma_client.db.query_raw(sql_query)
        if db_response is None:
            return []

        _tag_names = []
        for row in db_response:
            _tag_names.append(row.get("individual_request_tag"))

        return {"tag_names": _tag_names}

    except Exception as e:
        if isinstance(e, HTTPException):
            raise ProxyException(
                message=getattr(e, "detail", f"/spend/all_tag_names Error({str(e)})"),
                type="internal_error",
                param=getattr(e, "param", "None"),
                code=getattr(e, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR),
            )
        elif isinstance(e, ProxyException):
            raise e
        raise ProxyException(
            message="/spend/all_tag_names Error" + str(e),
            type="internal_error",
            param=getattr(e, "param", "None"),
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get(
    "/global/spend/tags",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    responses={
        200: {"model": List[LiteLLM_SpendLogs]},
    },
)
async def global_view_spend_tags(
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time from which to start viewing key spend",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time till which to view key spend",
    ),
    tags: Optional[str] = fastapi.Query(
        default=None,
        description="comman separated tags to filter on",
    ),
    limit: int = fastapi.Query(default=100, description="Maximum number of results to return"),
    offset: int = fastapi.Query(default=0, description="Number of results to skip"),
):
    """
    LiteLLM Enterprise - View Spend Per Request Tag. Used by LiteLLM UI

    Example Request:
    ```
    curl -X GET "http://0.0.0.0:4000/spend/tags" \
-H "Authorization: Bearer sk-1234"
    ```

    Spend with Start Date and End Date
    ```
    curl -X GET "http://0.0.0.0:4000/spend/tags?start_date=2022-01-01&end_date=2022-02-01" \
-H "Authorization: Bearer sk-1234"
    ```
    """
    import traceback

    from litellm.proxy.proxy_server import prisma_client

    try:
        if prisma_client is None:
            raise Exception(
                "Database not connected. Connect a database to your proxy - https://docs.litellm.ai/docs/simple_proxy#managing-auth---virtual-keys"
            )

        if end_date is None or start_date is None:
            raise ProxyException(
                message="Please provide start_date and end_date",
                type="bad_request",
                param=None,
                code=status.HTTP_400_BAD_REQUEST,
            )
        response = await ui_get_spend_by_tags(
            start_date=start_date,
            end_date=end_date,
            tags_str=tags,
            prisma_client=prisma_client,
        )

        return response
    except Exception as e:
        error_trace = traceback.format_exc()
        error_str = str(e) + "\n" + error_trace
        if isinstance(e, HTTPException):
            raise ProxyException(
                message=getattr(e, "detail", f"/spend/tags Error({error_str})"),
                type="internal_error",
                param=getattr(e, "param", "None"),
                code=getattr(e, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR),
            )
        elif isinstance(e, ProxyException):
            raise e
        raise ProxyException(
            message="/spend/tags Error" + error_str,
            type="internal_error",
            param=getattr(e, "param", "None"),
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


async def _get_spend_report_for_time_range(
    start_date: str,
    end_date: str,
):
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        verbose_proxy_logger.error(
            "Database not connected. Connect a database to your proxy for weekly, monthly spend reports"
        )
        return None

    try:
        sql_query = """
        SELECT
            t.team_alias,
            SUM(s.spend) AS total_spend
        FROM
            "LiteLLM_SpendLogs" s
        LEFT JOIN
            "LiteLLM_TeamTable" t ON s.team_id = t.team_id
        WHERE
            s."startTime"::DATE >= $1::date AND s."startTime"::DATE <= $2::date
        GROUP BY
            t.team_alias
        ORDER BY
            total_spend DESC;
        """
        response = await prisma_client.db.query_raw(sql_query, start_date, end_date)

        # get spend per tag for today
        sql_query = """
        SELECT 
        jsonb_array_elements_text(request_tags) AS individual_request_tag,
        SUM(spend) AS total_spend
        FROM "LiteLLM_SpendLogs"
        WHERE "startTime"::DATE >= $1::date AND "startTime"::DATE <= $2::date
        GROUP BY individual_request_tag
        ORDER BY total_spend DESC;
        """

        spend_per_tag = await prisma_client.db.query_raw(
            sql_query, start_date, end_date
        )

        return response, spend_per_tag
    except Exception as e:
        verbose_proxy_logger.error(
            "Exception in _get_daily_spend_reports {}".format(str(e))
        )


@router.post(
    "/spend/calculate",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    responses={
        200: {
            "cost": {
                "description": "The calculated cost",
                "example": 0.0,
                "type": "float",
            }
        }
    },
)
async def calculate_spend(request: SpendCalculateRequest):
    """
    Accepts all the params of completion_cost.

    Calculate spend **before** making call:

    Note: If you see a spend of $0.0 you need to set custom_pricing for your model: https://docs.litellm.ai/docs/proxy/custom_pricing

    ```
    curl --location 'http://localhost:4000/spend/calculate'
    --header 'Authorization: Bearer sk-1234'
    --header 'Content-Type: application/json'
    --data '{
        "model": "anthropic.claude-v2",
        "messages": [{"role": "user", "content": "Hey, how'''s it going?"}]
    }'
    ```

    Calculate spend **after** making call:

    ```
    curl --location 'http://localhost:4000/spend/calculate'
    --header 'Authorization: Bearer sk-1234'
    --header 'Content-Type: application/json'
    --data '{
        "completion_response": {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-3.5-turbo-0125",
            "system_fingerprint": "fp_44709d6fcb",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello there, how may I assist you today?"
                },
                "logprobs": null,
                "finish_reason": "stop"
            }]
            "usage": {
                "prompt_tokens": 9,
                "completion_tokens": 12,
                "total_tokens": 21
            }
        }
    }'
    ```
    """
    try:
        from litellm import completion_cost
        from litellm.cost_calculator import CostPerToken
        from litellm.proxy.proxy_server import llm_router

        _cost = None
        if request.model is not None:
            if request.messages is None:
                raise HTTPException(
                    status_code=400,
                    detail="Bad Request - messages must be provided if 'model' is provided",
                )

            # check if model in llm_router
            _model_in_llm_router = None
            cost_per_token: Optional[CostPerToken] = None
            if llm_router is not None:
                if (
                    llm_router.model_group_alias is not None
                    and request.model in llm_router.model_group_alias
                ):
                    # lookup alias in llm_router
                    _model_group_name = llm_router.model_group_alias[request.model]
                    for model in llm_router.model_list:
                        if model.get("model_name") == _model_group_name:
                            _model_in_llm_router = model

                else:
                    # no model_group aliases set -> try finding model in llm_router
                    # find model in llm_router
                    for model in llm_router.model_list:
                        if model.get("model_name") == request.model:
                            _model_in_llm_router = model

            """
            3 cases for /spend/calculate

            1. user passes model, and model is defined on litellm config.yaml or in DB. use info on config or in DB in this case
            2. user passes model, and model is not defined on litellm config.yaml or in DB. Pass model as is to litellm.completion_cost
            3. user passes completion_response
            
            """
            if _model_in_llm_router is not None:
                _litellm_params = _model_in_llm_router.get("litellm_params")
                _litellm_model_name = _litellm_params.get("model")
                input_cost_per_token = _litellm_params.get("input_cost_per_token")
                output_cost_per_token = _litellm_params.get("output_cost_per_token")
                if (
                    input_cost_per_token is not None
                    or output_cost_per_token is not None
                ):
                    cost_per_token = CostPerToken(
                        input_cost_per_token=input_cost_per_token,
                        output_cost_per_token=output_cost_per_token,
                    )

                _cost = completion_cost(
                    model=_litellm_model_name,
                    messages=request.messages,
                    custom_cost_per_token=cost_per_token,
                )
            else:
                _cost = completion_cost(model=request.model, messages=request.messages)
        elif request.completion_response is not None:
            _completion_response = litellm.ModelResponse(**request.completion_response)
            _cost = completion_cost(completion_response=_completion_response)
        else:
            raise HTTPException(
                status_code=400,
                detail="Bad Request - Either 'model' or 'completion_response' must be provided",
            )
        return {"cost": _cost}
    except Exception as e:
        if isinstance(e, HTTPException):
            raise ProxyException(
                message=getattr(e, "detail", str(e)),
                type=getattr(e, "type", "None"),
                param=getattr(e, "param", "None"),
                code=getattr(e, "status_code", status.HTTP_400_BAD_REQUEST),
            )
        error_msg = f"{str(e)}"
        raise ProxyException(
            message=getattr(e, "message", error_msg),
            type=getattr(e, "type", "None"),
            param=getattr(e, "param", "None"),
            code=getattr(e, "status_code", 500),
        )


@router.get(
    "/spend/logs/ui",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
    responses={
        200: {"model": List[LiteLLM_SpendLogs]},
    },
)
async def ui_view_spend_logs(  # noqa: PLR0915
    api_key: Optional[str] = fastapi.Query(
        default=None,
        description="Get spend logs based on api key",
    ),
    user_id: Optional[str] = fastapi.Query(
        default=None,
        description="Get spend logs based on user_id",
    ),
    request_id: Optional[str] = fastapi.Query(
        default=None,
        description="request_id to get spend logs for specific request_id",
    ),
    team_id: Optional[str] = fastapi.Query(
        default=None,
        description="Filter spend logs by team_id",
    ),
    min_spend: Optional[float] = fastapi.Query(
        default=None,
        description="Filter logs with spend greater than or equal to this value",
    ),
    max_spend: Optional[float] = fastapi.Query(
        default=None,
        description="Filter logs with spend less than or equal to this value",
    ),
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time from which to start viewing key spend",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time till which to view key spend",
    ),
    page: int = fastapi.Query(
        default=1, description="Page number for pagination", ge=1
    ),
    page_size: int = fastapi.Query(
        default=50, description="Number of items per page", ge=1, le=100
    ),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
    status_filter: Optional[str] = fastapi.Query(
        default=None, description="Filter logs by status (e.g., success, failure)"
    ),
    model: Optional[str] = fastapi.Query(
        default=None, description="Filter logs by model"
    ),
):
    """
    View spend logs for UI with pagination support

    Returns:
        {
            "data": List[LiteLLM_SpendLogs],  # Paginated spend logs
            "total": int,                      # Total number of records
            "page": int,                       # Current page number
            "page_size": int,                  # Number of items per page
            "total_pages": int                 # Total number of pages
        }
    """
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise ProxyException(
            message="Prisma Client is not initialized",
            type="internal_error",
            param="None",
            code=status.HTTP_401_UNAUTHORIZED,
        )

    if start_date is None or end_date is None:
        raise ProxyException(
            message="Start date and end date are required",
            type="bad_request",
            param="None",
            code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        # Convert the date strings to datetime objects
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )

        # Convert to ISO format strings for Prisma
        start_date_iso = start_date_obj.isoformat()  # Already in UTC, no need to add Z
        end_date_iso = end_date_obj.isoformat()  # Already in UTC, no need to add Z

        # Build where conditions
        where_conditions: dict[str, Any] = {
            "startTime": {"gte": start_date_iso, "lte": end_date_iso},
        }

        if team_id is not None:
            where_conditions["team_id"] = team_id

        status_condition = _build_status_filter_condition(status_filter)
        if status_condition:
            where_conditions.update(status_condition)

        if api_key is not None:
            where_conditions["api_key"] = api_key

        if user_id is not None:
            where_conditions["user"] = user_id

        if request_id is not None:
            where_conditions["request_id"] = request_id

        if model is not None:
            where_conditions["model"] = model

        if min_spend is not None or max_spend is not None:
            where_conditions["spend"] = {}
            if min_spend is not None:
                where_conditions["spend"]["gte"] = min_spend
            if max_spend is not None:
                where_conditions["spend"]["lte"] = max_spend
        # Calculate skip value for pagination
        skip = (page - 1) * page_size

        # Get total count of records
        total_records = await prisma_client.db.litellm_spendlogs.count(
            where=where_conditions,
        )

        # Get paginated data
        data = await prisma_client.db.litellm_spendlogs.find_many(
            where=where_conditions,
            order={
                "startTime": "desc",
            },
            skip=skip,
            take=page_size,
        )

        # Calculate total pages
        total_pages = (total_records + page_size - 1) // page_size

        verbose_proxy_logger.debug("data= %s", json.dumps(data, indent=4, default=str))

        return {
            "data": data,
            "total": total_records,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }
    except Exception as e:
        verbose_proxy_logger.exception(f"Error in ui_view_spend_logs: {e}")
        raise handle_exception_on_proxy(e)


@lru_cache(maxsize=128)
@router.get(
    "/spend/logs/ui/{request_id}",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def ui_view_request_response_for_request_id(
    request_id: str,
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time from which to start viewing key spend",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time till which to view key spend",
    ),
):
    """
    View request / response for a specific request_id

    - goes through all callbacks, checks if any of them have a @property -> has_request_response_payload
    - if so, it will return the request and response payload
    """
    custom_loggers = (
        litellm.logging_callback_manager.get_active_additional_logging_utils_from_custom_logger()
    )
    start_date_obj: Optional[datetime] = None
    end_date_obj: Optional[datetime] = None
    if start_date is not None:
        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
    if end_date is not None:
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )

    for custom_logger in custom_loggers:
        payload = await custom_logger.get_request_response_payload(
            request_id=request_id,
            start_time_utc=start_date_obj,
            end_time_utc=end_date_obj,
        )
        if payload is not None:
            return payload

    return None


@router.get(
    "/spend/logs",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    responses={
        200: {"model": List[LiteLLM_SpendLogs]},
    },
)
async def view_spend_logs(  # noqa: PLR0915
    api_key: Optional[str] = fastapi.Query(
        default=None,
        description="Get spend logs based on api key",
    ),
    user_id: Optional[str] = fastapi.Query(
        default=None,
        description="Get spend logs based on user_id",
    ),
    request_id: Optional[str] = fastapi.Query(
        default=None,
        description="request_id to get spend logs for specific request_id. If none passed then pass spend logs for all requests",
    ),
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time from which to start viewing key spend",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time till which to view key spend",
    ),
    summarize: bool = fastapi.Query(
        default=True,
        description="When start_date and end_date are provided, summarize=true returns aggregated data by date (legacy behavior), summarize=false returns filtered individual logs",
    ),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    View all spend logs, if request_id is provided, only logs for that request_id will be returned

    When start_date and end_date are provided:
    - summarize=true (default): Returns aggregated spend data grouped by date (maintains backward compatibility)
    - summarize=false: Returns filtered individual log entries within the date range

    Example Request for all logs
    ```
    curl -X GET "http://0.0.0.0:8000/spend/logs" \
-H "Authorization: Bearer sk-1234"
    ```

    Example Request for specific request_id
    ```
    curl -X GET "http://0.0.0.0:8000/spend/logs?request_id=chatcmpl-6dcb2540-d3d7-4e49-bb27-291f863f112e" \
-H "Authorization: Bearer sk-1234"
    ```

    Example Request for specific api_key
    ```
    curl -X GET "http://0.0.0.0:8000/spend/logs?api_key=sk-Fn8Ej39NkBQmUagFEoUWPQ" \
-H "Authorization: Bearer sk-1234"
    ```

    Example Request for specific user_id
    ```
    curl -X GET "http://0.0.0.0:8000/spend/logs?user_id=ishaan@berri.ai" \
-H "Authorization: Bearer sk-1234"
    ```

    Example Request for date range with individual logs (unsummarized)
    ```
    curl -X GET "http://0.0.0.0:8000/spend/logs?start_date=2024-01-01&end_date=2024-01-02&summarize=false" \
-H "Authorization: Bearer sk-1234"
    ```
    """
    from litellm.proxy.proxy_server import prisma_client

    if (
        user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER
        or user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER_VIEW_ONLY
    ):
        user_id = user_api_key_dict.user_id

    try:
        verbose_proxy_logger.debug("inside view_spend_logs")
        if prisma_client is None:
            raise Exception(
                "Database not connected. Connect a database to your proxy - https://docs.litellm.ai/docs/simple_proxy#managing-auth---virtual-keys"
            )
        spend_logs = []
        if (
            start_date is not None
            and isinstance(start_date, str)
            and end_date is not None
            and isinstance(end_date, str)
        ):
            # Convert the date strings to datetime objects
            start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
            end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")

            filter_query = {
                "startTime": {
                    "gte": start_date_obj,  # Greater than or equal to Start Date
                    "lte": end_date_obj,  # Less than or equal to End Date
                }
            }

            if api_key is not None and isinstance(api_key, str):
                filter_query["api_key"] = api_key  # type: ignore
            elif request_id is not None and isinstance(request_id, str):
                filter_query["request_id"] = request_id  # type: ignore
            elif user_id is not None and isinstance(user_id, str):
                filter_query["user"] = user_id  # type: ignore

            # Check if user wants unsummarized data
            if not summarize:
                # Return filtered individual log entries (similar to UI endpoint)
                data = await prisma_client.db.litellm_spendlogs.find_many(
                    where=filter_query,  # type: ignore
                    order={
                        "startTime": "desc",
                    },
                )
                return data

            # Legacy behavior: return summarized data (when summarize=true)
            # SQL query
            response = await prisma_client.db.litellm_spendlogs.group_by(
                by=["api_key", "user", "model", "startTime"],
                where=filter_query,  # type: ignore
                sum={
                    "spend": True,
                },
            )

            if (
                isinstance(response, list)
                and len(response) > 0
                and isinstance(response[0], dict)
            ):
                result: dict = {}
                for record in response:
                    dt_object = datetime.strptime(str(record["startTime"]), "%Y-%m-%dT%H:%M:%S.%fZ")  # type: ignore
                    date = dt_object.date()
                    if date not in result:
                        result[date] = {"users": {}, "models": {}}
                    api_key = record["api_key"]  # type: ignore
                    user_id = record["user"]  # type: ignore
                    model = record["model"]  # type: ignore
                    result[date]["spend"] = result[date].get("spend", 0) + record.get(
                        "_sum", {}
                    ).get("spend", 0)
                    result[date][api_key] = result[date].get(api_key, 0) + record.get(
                        "_sum", {}
                    ).get("spend", 0)
                    result[date]["users"][user_id] = result[date]["users"].get(
                        user_id, 0
                    ) + record.get("_sum", {}).get("spend", 0)
                    result[date]["models"][model] = result[date]["models"].get(
                        model, 0
                    ) + record.get("_sum", {}).get("spend", 0)
                return_list = []
                final_date = None
                for k, v in sorted(result.items()):
                    return_list.append({**v, "startTime": k})
                    final_date = k

                end_date_date = end_date_obj.date()
                if final_date is not None and final_date < end_date_date:
                    current_date = final_date + timedelta(days=1)
                    while current_date <= end_date_date:
                        # Represent current_date as string because original response has it this way
                        return_list.append(
                            {
                                "startTime": current_date,
                                "spend": 0,
                                "users": {},
                                "models": {},
                            }
                        )  # If no data, will stay as zero
                        current_date += timedelta(days=1)  # Move on to the next day

                return return_list

            return response

        elif api_key is not None and isinstance(api_key, str):
            if api_key.startswith("sk-"):
                hashed_token = prisma_client.hash_token(token=api_key)
            else:
                hashed_token = api_key
            spend_log = await prisma_client.get_data(
                table_name="spend",
                query_type="find_all",
                key_val={"key": "api_key", "value": hashed_token},
            )
            if isinstance(spend_log, list):
                return spend_log
            else:
                return [spend_log]
        elif request_id is not None:
            spend_log = await prisma_client.get_data(
                table_name="spend",
                query_type="find_unique",
                key_val={"key": "request_id", "value": request_id},
            )
            return [spend_log]
        elif user_id is not None:
            spend_log = await prisma_client.get_data(
                table_name="spend",
                query_type="find_all",
                key_val={"key": "user", "value": user_id},
            )
            if isinstance(spend_log, list):
                return spend_log
            else:
                return [spend_log]
        else:
            spend_logs = await prisma_client.get_data(
                table_name="spend", query_type="find_all"
            )

            return spend_logs

        return None

    except Exception as e:
        if isinstance(e, HTTPException):
            raise ProxyException(
                message=getattr(e, "detail", f"/spend/logs Error({str(e)})"),
                type="internal_error",
                param=getattr(e, "param", "None"),
                code=getattr(e, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR),
            )
        elif isinstance(e, ProxyException):
            raise e
        raise ProxyException(
            message="/spend/logs Error" + str(e),
            type="internal_error",
            param=getattr(e, "param", "None"),
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post(
    "/global/spend/reset",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
)
async def global_spend_reset():
    """
    ADMIN ONLY / MASTER KEY Only Endpoint

    Globally reset spend for All API Keys and Teams, maintain LiteLLM_SpendLogs

    1. LiteLLM_SpendLogs will maintain the logs on spend, no data gets deleted from there
    2. LiteLLM_VerificationTokens spend will be set = 0
    3. LiteLLM_TeamTable spend will be set = 0

    """
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise ProxyException(
            message="Prisma Client is not initialized",
            type="internal_error",
            param="None",
            code=status.HTTP_401_UNAUTHORIZED,
        )

    await prisma_client.db.litellm_verificationtoken.update_many(
        data={"spend": 0.0}, where={}
    )
    await prisma_client.db.litellm_teamtable.update_many(data={"spend": 0.0}, where={})

    return {
        "message": "Spend for all API Keys and Teams reset successfully",
        "status": "success",
    }


@router.post(
    "/global/spend/refresh",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def global_spend_refresh():
    """
    ADMIN ONLY / MASTER KEY Only Endpoint

    Globally refresh spend MonthlyGlobalSpend view
    """
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise ProxyException(
            message="Prisma Client is not initialized",
            type="internal_error",
            param="None",
            code=status.HTTP_401_UNAUTHORIZED,
        )

    ## RESET GLOBAL SPEND VIEW ###
    async def is_materialized_global_spend_view() -> bool:
        """
        Return True if materialized view exists

        Else False
        """
        sql_query = """
        SELECT relname, relkind
        FROM pg_class
        WHERE relname = 'MonthlyGlobalSpend';            
        """
        try:
            resp = await prisma_client.db.query_raw(sql_query)

            return resp[0]["relkind"] == "m"
        except Exception:
            return False

    view_exists = await is_materialized_global_spend_view()

    if view_exists:
        # refresh materialized view
        sql_query = """
        REFRESH MATERIALIZED VIEW "MonthlyGlobalSpend";    
        """
        try:
            from litellm.proxy._types import CommonProxyErrors
            from litellm.proxy.proxy_server import proxy_logging_obj
            from litellm.proxy.utils import PrismaClient

            db_url = os.getenv("DATABASE_URL")
            if db_url is None:
                raise Exception(CommonProxyErrors.db_not_connected_error.value)
            new_client = PrismaClient(
                database_url=db_url,
                proxy_logging_obj=proxy_logging_obj,
                http_client={
                    "timeout": 6000,
                },
            )
            await new_client.db.connect()
            await new_client.db.query_raw(sql_query)
            verbose_proxy_logger.info("MonthlyGlobalSpend view refreshed")
            return {
                "message": "MonthlyGlobalSpend view refreshed",
                "status": "success",
            }

        except Exception as e:
            verbose_proxy_logger.exception(
                "Failed to refresh materialized view - {}".format(str(e))
            )
            return {
                "message": "Failed to refresh materialized view",
                "status": "failure",
            }


async def global_spend_for_internal_user(
    api_key: Optional[str] = None,
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise ProxyException(
            message="Prisma Client is not initialized",
            type="internal_error",
            param="None",
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    try:
        user_id = user_api_key_dict.user_id
        if user_id is None:
            raise ValueError("/global/spend/logs Error: User ID is None")
        if api_key is not None:
            sql_query = """
                SELECT * FROM "MonthlyGlobalSpendPerUserPerKey"
                WHERE "api_key" = $1 AND "user" = $2
                ORDER BY "date";
                """

            response = await prisma_client.db.query_raw(sql_query, api_key, user_id)

            return response

        sql_query = """SELECT * FROM "MonthlyGlobalSpendPerUserPerKey"  WHERE "user" = $1 ORDER BY "date";"""

        response = await prisma_client.db.query_raw(sql_query, user_id)

        return response
    except Exception as e:
        verbose_proxy_logger.error(f"/global/spend/logs Error: {str(e)}")
        raise e


@router.get(
    "/global/spend/logs",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def global_spend_logs(
    api_key: Optional[str] = fastapi.Query(
        default=None,
        description="API Key to get global spend (spend per day for last 30d). Admin-only endpoint",
    ),
    limit: int = fastapi.Query(default=100, description="Maximum number of results to return"),
    offset: int = fastapi.Query(default=0, description="Number of results to skip"),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    [BETA] This is a beta endpoint. It will change.

    Use this to get global spend (spend per day for last 30d). Admin-only endpoint

    More efficient implementation of /spend/logs, by creating a view over the spend logs table.
    """
    import traceback

    from litellm.integrations.prometheus_helpers.prometheus_api import (
        get_daily_spend_from_prometheus,
        is_prometheus_connected,
    )
    from litellm.proxy.proxy_server import prisma_client

    try:
        if prisma_client is None:
            raise ProxyException(
                message="Prisma Client is not initialized",
                type="internal_error",
                param="None",
                code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if (
            user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER
            or user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER_VIEW_ONLY
        ):
            response = await global_spend_for_internal_user(
                api_key=api_key, user_api_key_dict=user_api_key_dict
            )

            return response

        prometheus_api_enabled = is_prometheus_connected()

        if prometheus_api_enabled:
            response = await get_daily_spend_from_prometheus(api_key=api_key)
            return response
        else:
            if api_key is None:
                sql_query = """SELECT * FROM "MonthlyGlobalSpend" ORDER BY "date";"""

                response = await prisma_client.db.query_raw(query=sql_query)

                return response
            else:
                sql_query = """
                    SELECT * FROM "MonthlyGlobalSpendPerKey"
                    WHERE "api_key" = $1
                    ORDER BY "date";
                    """

                response = await prisma_client.db.query_raw(sql_query, api_key)

                return response

    except Exception as e:
        error_trace = traceback.format_exc()
        error_str = str(e) + "\n" + error_trace
        verbose_proxy_logger.error(f"/global/spend/logs Error: {error_str}")
        if isinstance(e, HTTPException):
            raise ProxyException(
                message=getattr(e, "detail", f"/global/spend/logs Error({error_str})"),
                type="internal_error",
                param=getattr(e, "param", "None"),
                code=getattr(e, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR),
            )
        elif isinstance(e, ProxyException):
            raise e
        raise ProxyException(
            message="/global/spend/logs Error" + error_str,
            type="internal_error",
            param=getattr(e, "param", "None"),
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get(
    "/global/spend",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def global_spend():
    """
    [BETA] This is a beta endpoint. It will change.

    View total spend across all proxy keys
    """
    import traceback

    from litellm.proxy.proxy_server import prisma_client

    try:
        total_spend = 0.0

        if prisma_client is None:
            raise HTTPException(status_code=500, detail={"error": "No db connected"})
        sql_query = """SELECT SUM(spend) as total_spend FROM "MonthlyGlobalSpend";"""
        response = await prisma_client.db.query_raw(query=sql_query)
        if response is not None:
            if isinstance(response, list) and len(response) > 0:
                total_spend = response[0].get("total_spend", 0.0)

        return {"spend": total_spend, "max_budget": litellm.max_budget}
    except Exception as e:
        error_trace = traceback.format_exc()
        error_str = str(e) + "\n" + error_trace
        if isinstance(e, HTTPException):
            raise ProxyException(
                message=getattr(e, "detail", f"/global/spend Error({error_str})"),
                type="internal_error",
                param=getattr(e, "param", "None"),
                code=getattr(e, "status_code", status.HTTP_500_INTERNAL_SERVER_ERROR),
            )
        elif isinstance(e, ProxyException):
            raise e
        raise ProxyException(
            message="/global/spend Error" + error_str,
            type="internal_error",
            param=getattr(e, "param", "None"),
            code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


async def global_spend_key_internal_user(
    user_api_key_dict: UserAPIKeyAuth, limit: int = 10
):
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})

    user_id = user_api_key_dict.user_id
    if user_id is None:
        raise HTTPException(status_code=500, detail={"error": "No user_id found"})

    sql_query = """
            WITH top_api_keys AS (
            SELECT 
                api_key,
                SUM(spend) as total_spend
            FROM 
                "LiteLLM_SpendLogs"
            WHERE 
                "user" = $1
            GROUP BY 
                api_key
            ORDER BY 
                total_spend DESC
            LIMIT $2  -- Adjust this number to get more or fewer top keys
        )
        SELECT 
            t.api_key,
            t.total_spend,
            v.key_alias,
            v.key_name
        FROM 
            top_api_keys t
        LEFT JOIN 
            "LiteLLM_VerificationToken" v ON t.api_key = v.token
        ORDER BY 
            t.total_spend DESC;
    
    """

    response = await prisma_client.db.query_raw(sql_query, user_id, limit)

    return response


@router.get(
    "/global/spend/keys",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def global_spend_keys(
    limit: int = fastapi.Query(
        default=None,
        description="Number of keys to get. Will return Top 'n' keys.",
    ),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    [BETA] This is a beta endpoint. It will change.

    Use this to get the top 'n' keys with the highest spend, ordered by spend.
    """
    from litellm.proxy.proxy_server import prisma_client

    if (
        user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER
        or user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER_VIEW_ONLY
    ):
        response = await global_spend_key_internal_user(
            user_api_key_dict=user_api_key_dict
        )

        return response
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    sql_query = """SELECT * FROM "Last30dKeysBySpend";"""

    if limit is None:
        response = await prisma_client.db.query_raw(sql_query)
        return response
    try:
        limit = int(limit)
        if limit < 1:
            raise ValueError("Limit must be greater than 0")
        sql_query = """SELECT * FROM "Last30dKeysBySpend" LIMIT $1 ;"""
        response = await prisma_client.db.query_raw(sql_query, limit)
    except ValueError as e:
        raise HTTPException(
            status_code=422, detail={"error": f"Invalid limit: {limit}, error: {e}"}
        ) from e

    return response


@router.get(
    "/global/spend/teams",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def global_spend_per_team(
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time from which to start viewing team spend",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="Time till which to view team spend",
    ),
    limit: int = fastapi.Query(default=100, description="Maximum number of results to return"),
    offset: int = fastapi.Query(default=0, description="Number of results to skip")
):
    """
    [BETA] This is a beta endpoint. It will change.

    Use this to get daily spend, grouped by `team_id` and `date`
    """
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    # Use date filters if provided, otherwise default to last 30 days
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND dts.date >= '{start_date}' AND dts.date <= '{end_date}'"
    else:
        date_filter = "AND dts.date >= CURRENT_DATE - INTERVAL '30 days'"
    
    # Use pre-aggregated daily team spend table for much better performance
    sql_query = f"""
        SELECT
            COALESCE(t.team_alias, 'Unassigned') as team_alias,
            dts.date AS spend_date,
            SUM(dts.spend) AS total_spend
        FROM
            "LiteLLM_DailyTeamSpend" dts
        LEFT JOIN
            "LiteLLM_TeamTable" t ON dts.team_id = t.team_id
        WHERE
            1=1
            {date_filter}
        GROUP BY
            t.team_alias,
            dts.date
        ORDER BY
            spend_date DESC
        LIMIT {limit} OFFSET {offset};
        """
    response = await prisma_client.db.query_raw(query=sql_query)

    # transform the response for the Admin UI
    spend_by_date = {}
    team_aliases = set()
    total_spend_per_team = {}
    for row in response:
        row_date = row["spend_date"]
        if row_date is None:
            continue
        team_alias = row["team_alias"]
        if team_alias is None:
            team_alias = "Unassigned"
        team_aliases.add(team_alias)
        if row_date in spend_by_date:
            # get the team_id for this entry
            # get the spend for this entry
            spend = row["total_spend"]
            spend = round(spend, 2)
            current_date_entries = spend_by_date[row_date]
            current_date_entries[team_alias] = spend
        else:
            spend = row["total_spend"]
            spend = round(spend, 2)
            spend_by_date[row_date] = {team_alias: spend}

        if team_alias in total_spend_per_team:
            total_spend_per_team[team_alias] += spend
        else:
            total_spend_per_team[team_alias] = spend

    total_spend_per_team_ui = []
    # order the elements in total_spend_per_team by spend
    total_spend_per_team = dict(
        sorted(total_spend_per_team.items(), key=lambda item: item[1], reverse=True)
    )
    for team_id in total_spend_per_team:
        # only add first 10 elements to total_spend_per_team_ui
        if len(total_spend_per_team_ui) >= 10:
            break
        if team_id is None:
            team_id = "Unassigned"
        total_spend_per_team_ui.append(
            {"team_id": team_id, "total_spend": total_spend_per_team[team_id]}
        )

    # sort spend_by_date by it's key (which is a date)

    response_data = []
    for key in spend_by_date:
        value = spend_by_date[key]
        response_data.append({"date": key, **value})

    return {
        "daily_spend": response_data,
        "teams": list(team_aliases),
        "total_spend_per_team": total_spend_per_team_ui,
    }


@router.get(
    "/global/all_end_users",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def global_view_all_end_users():
    """
    [BETA] This is a beta endpoint. It will change.

    Use this to just get all the unique `end_users`
    """
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})

    sql_query = """
    SELECT DISTINCT end_user FROM "LiteLLM_SpendLogs"
    """

    db_response = await prisma_client.db.query_raw(query=sql_query)
    if db_response is None:
        return []

    _end_users = []
    for row in db_response:
        _end_users.append(row["end_user"])

    return {"end_users": _end_users}


@router.post(
    "/global/spend/end_users",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def global_spend_end_users(data: Optional[GlobalEndUsersSpend] = None):
    """
    [BETA] This is a beta endpoint. It will change.

    Use this to get the top 'n' keys with the highest spend, ordered by spend.
    """
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})

    """
    Gets the top 100 end-users for a given api key
    """
    startTime = None
    endTime = None
    selected_api_key = None
    if data is not None:
        startTime = data.startTime
        endTime = data.endTime
        selected_api_key = data.api_key

    startTime = startTime or datetime.now() - timedelta(days=30)
    endTime = endTime or datetime.now()

    sql_query = """
SELECT end_user, COUNT(*) AS total_count, SUM(spend) AS total_spend
FROM "LiteLLM_SpendLogs"
WHERE "startTime" >= $1::timestamp
  AND "startTime" < $2::timestamp
  AND (
    CASE
      WHEN $3::TEXT IS NULL THEN TRUE
      ELSE api_key = $3
    END
  )
GROUP BY end_user
ORDER BY total_spend DESC
LIMIT 100
    """
    response = await prisma_client.db.query_raw(
        sql_query, startTime, endTime, selected_api_key
    )

    return response


async def global_spend_models_internal_user(
    user_api_key_dict: UserAPIKeyAuth, limit: int = 10
):
    from litellm.proxy.proxy_server import prisma_client

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})

    user_id = user_api_key_dict.user_id
    if user_id is None:
        raise HTTPException(status_code=500, detail={"error": "No user_id found"})

    sql_query = """
        SELECT 
            model,
            SUM(spend) as total_spend,
            SUM(total_tokens) as total_tokens
        FROM 
            "LiteLLM_SpendLogs"
        WHERE 
            "user" = $1
        GROUP BY 
            model
        ORDER BY 
            total_spend DESC
        LIMIT $2;
    """

    response = await prisma_client.db.query_raw(sql_query, user_id, limit)

    return response


@router.get(
    "/global/spend/models",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
)
async def global_spend_models(
    limit: int = fastapi.Query(
        default=10,
        description="Number of models to get. Will return Top 'n' models.",
    ),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    [BETA] This is a beta endpoint. It will change.

    Use this to get the top 'n' models with the highest spend, ordered by spend.
    """
    from litellm.proxy.proxy_server import prisma_client

    if (
        user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER
        or user_api_key_dict.user_role == LitellmUserRoles.INTERNAL_USER_VIEW_ONLY
    ):
        response = await global_spend_models_internal_user(
            user_api_key_dict=user_api_key_dict, limit=limit
        )
        return response

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})

    sql_query = """SELECT * FROM "Last30dModelsBySpend" LIMIT $1 ;"""

    response = await prisma_client.db.query_raw(sql_query, int(limit))

    return response


@router.get("/provider/budgets", response_model=ProviderBudgetResponse)
async def provider_budgets() -> ProviderBudgetResponse:
    """
    Provider Budget Routing - Get Budget, Spend Details https://docs.litellm.ai/docs/proxy/provider_budget_routing

    Use this endpoint to check current budget, spend and budget reset time for a provider

    Example Request

    ```bash
    curl -X GET http://localhost:4000/provider/budgets \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer sk-1234"
    ```

    Example Response

    ```json
    {
        "providers": {
            "openai": {
                "budget_limit": 1e-12,
                "time_period": "1d",
                "spend": 0.0,
                "budget_reset_at": null
            },
            "azure": {
                "budget_limit": 100.0,
                "time_period": "1d",
                "spend": 0.0,
                "budget_reset_at": null
            },
            "anthropic": {
                "budget_limit": 100.0,
                "time_period": "10d",
                "spend": 0.0,
                "budget_reset_at": null
            },
            "vertex_ai": {
                "budget_limit": 100.0,
                "time_period": "12d",
                "spend": 0.0,
                "budget_reset_at": null
            }
        }
    }
    ```

    """
    from litellm.proxy.proxy_server import llm_router

    try:
        if llm_router is None:
            raise HTTPException(
                status_code=500, detail={"error": "No llm_router found"}
            )

        provider_budget_config = llm_router.provider_budget_config
        if provider_budget_config is None:
            raise ValueError(
                "No provider budget config found. Please set a provider budget config in the router settings. https://docs.litellm.ai/docs/proxy/provider_budget_routing"
            )

        provider_budget_response_dict: Dict[str, ProviderBudgetResponseObject] = {}
        for _provider, _budget_info in provider_budget_config.items():
            if llm_router.router_budget_logger is None:
                raise ValueError("No router budget logger found")
            _provider_spend = (
                await llm_router.router_budget_logger._get_current_provider_spend(
                    _provider
                )
                or 0.0
            )
            _provider_budget_ttl = await llm_router.router_budget_logger._get_current_provider_budget_reset_at(
                _provider
            )
            provider_budget_response_object = ProviderBudgetResponseObject(
                budget_limit=_budget_info.max_budget,
                time_period=_budget_info.budget_duration,
                spend=_provider_spend,
                budget_reset_at=_provider_budget_ttl,
            )
            provider_budget_response_dict[_provider] = provider_budget_response_object
        return ProviderBudgetResponse(providers=provider_budget_response_dict)
    except Exception as e:
        verbose_proxy_logger.exception(
            "/provider/budgets: Exception occured - {}".format(str(e))
        )
        raise handle_exception_on_proxy(e)


async def get_spend_by_tags(
    prisma_client: PrismaClient, start_date=None, end_date=None
):
    response = await prisma_client.db.query_raw(
        """
        SELECT
        jsonb_array_elements_text(request_tags) AS individual_request_tag,
        COUNT(*) AS log_count,
        SUM(spend) AS total_spend
        FROM "LiteLLM_SpendLogs"
        GROUP BY individual_request_tag;
        """
    )

    return response


async def ui_get_spend_by_tags(
    start_date: str,
    end_date: str,
    prisma_client: Optional[PrismaClient] = None,
    tags_str: Optional[str] = None,
):
    """
    Should cover 2 cases:
    1. When user is getting spend for all_tags. "all_tags" in tags_list
    2. When user is getting spend for specific tags.
    """

    # tags_str is a list of strings csv of tags
    # tags_str = tag1,tag2,tag3
    # convert to list if it's not None
    tags_list: Optional[List[str]] = None
    if tags_str is not None and len(tags_str) > 0:
        tags_list = tags_str.split(",")

    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})

    response = None
    if tags_list is None or (isinstance(tags_list, list) and "all-tags" in tags_list):
        # Get spend for all tags
        sql_query = """
        SELECT
            individual_request_tag,
            spend_date,
            log_count,
            total_spend
        FROM "DailyTagSpend"
        WHERE spend_date >= $1::date AND spend_date <= $2::date
        ORDER BY total_spend DESC;
        """
        response = await prisma_client.db.query_raw(
            sql_query,
            start_date,
            end_date,
        )
    else:
        # filter by tags list
        sql_query = """
        SELECT
            individual_request_tag,
            SUM(log_count) AS log_count,
            SUM(total_spend) AS total_spend
        FROM "DailyTagSpend"
        WHERE spend_date >= $1::date AND spend_date <= $2::date
          AND individual_request_tag = ANY($3::text[])
        GROUP BY individual_request_tag
        ORDER BY total_spend DESC;
        """
        response = await prisma_client.db.query_raw(
            sql_query,
            start_date,
            end_date,
            tags_list,
        )

    # print("tags - spend")
    # print(response)
    # Bar Chart 1 - Spend per tag - Top 10 tags by spend
    total_spend_per_tag: collections.defaultdict = collections.defaultdict(float)
    total_requests_per_tag: collections.defaultdict = collections.defaultdict(int)
    for row in response:
        tag_name = row["individual_request_tag"]
        tag_spend = row["total_spend"]

        total_spend_per_tag[tag_name] += tag_spend
        total_requests_per_tag[tag_name] += row["log_count"]

    sorted_tags = sorted(total_spend_per_tag.items(), key=lambda x: x[1], reverse=True)
    # convert to ui format
    ui_tags = []
    for tag in sorted_tags:
        current_spend = tag[1]
        if current_spend is not None and isinstance(current_spend, float):
            current_spend = round(current_spend, 4)
        ui_tags.append(
            {
                "name": tag[0],
                "spend": current_spend,
                "log_count": total_requests_per_tag[tag[0]],
            }
        )

    return {"spend_per_tag": ui_tags}


@router.get(
    "/spend/logs/session/ui",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
    responses={
        200: {"model": List[LiteLLM_SpendLogs]},
    },
)
@router.get(
    "/global/dashboard/summary",
    tags=["Budget & Spend Tracking"],
    dependencies=[Depends(user_api_key_auth)],
    include_in_schema=False,
    responses={
        200: {"model": Dict},
    },
)
@cached_endpoint("dashboard_summary", ttl_seconds=5*60)  # Cache for 5 minutes
async def get_dashboard_summary(
    start_date: Optional[str] = fastapi.Query(
        default=None,
        description="Start date for data (YYYY-MM-DD)",
    ),
    end_date: Optional[str] = fastapi.Query(
        default=None,
        description="End date for data (YYYY-MM-DD)",
    ),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    Consolidated endpoint that returns all dashboard data in a single request.
    This reduces the number of API calls from the frontend for better performance.
    """
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    # Set default date range if not provided (last 30 days)
    if not start_date or not end_date:
        from datetime import datetime, timedelta
        end_dt = datetime.utcnow().date()
        start_dt = end_dt - timedelta(days=30)
        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = end_dt.strftime("%Y-%m-%d")
    
    try:
        # Execute all queries in parallel for better performance
        queries = {}
        
        # Monthly spend summary - use existing view
        queries["monthly_spend"] = prisma_client.db.query_raw(
            'SELECT * FROM "MonthlyGlobalSpend" ORDER BY "date" LIMIT 30'
        )
        
        # Top keys - use aggregated data
        queries["top_keys"] = prisma_client.db.query_raw("""
            SELECT 
                vt.key_alias,
                vt.token as api_key,
                SUM(dus.spend) as total_spend
            FROM "LiteLLM_DailyUserSpend" dus
            LEFT JOIN "LiteLLM_VerificationToken" vt ON dus.api_key = vt.token
            WHERE dus.date >= $1 AND dus.date <= $2
            GROUP BY vt.key_alias, vt.token
            ORDER BY total_spend DESC
            LIMIT 5
        """, start_date, end_date)
        
        # Top models - use aggregated data  
        queries["top_models"] = prisma_client.db.query_raw("""
            SELECT 
                model,
                SUM(spend) as total_spend
            FROM "LiteLLM_DailyUserSpend"
            WHERE date >= $1 AND date <= $2 AND model IS NOT NULL
            GROUP BY model
            ORDER BY total_spend DESC
            LIMIT 5
        """, start_date, end_date)
        
        # Provider spend breakdown
        queries["provider_spend"] = prisma_client.db.query_raw("""
            SELECT 
                custom_llm_provider as provider,
                SUM(spend) as spend
            FROM "LiteLLM_DailyUserSpend"
            WHERE date >= $1 AND date <= $2 AND custom_llm_provider IS NOT NULL
            GROUP BY custom_llm_provider
            ORDER BY spend DESC
        """, start_date, end_date)
        
        # Global activity summary
        queries["global_activity"] = prisma_client.db.query_raw("""
            SELECT 
                date,
                SUM(api_requests) as api_requests,
                SUM(prompt_tokens + completion_tokens) as total_tokens
            FROM "LiteLLM_DailyUserSpend"
            WHERE date >= $1 AND date <= $2
            GROUP BY date
            ORDER BY date DESC
        """, start_date, end_date)
        
        # Admin-only data
        if (user_api_key_dict.user_role == "Admin" or 
            user_api_key_dict.user_role == "Admin Viewer"):
            
            # Team spend data
            queries["team_spend"] = prisma_client.db.query_raw("""
                SELECT 
                    COALESCE(tt.team_alias, 'Unassigned') as team_alias,
                    dts.date,
                    SUM(dts.spend) as total_spend
                FROM "LiteLLM_DailyTeamSpend" dts
                LEFT JOIN "LiteLLM_TeamTable" tt ON dts.team_id = tt.team_id
                WHERE dts.date >= $1 AND dts.date <= $2
                GROUP BY tt.team_alias, dts.date
                ORDER BY dts.date DESC
            """, start_date, end_date)
            
            # Tag names for dropdown
            queries["tag_names"] = prisma_client.db.query_raw("""
                SELECT DISTINCT tag as tag_name
                FROM "LiteLLM_DailyTagSpend"
                WHERE tag IS NOT NULL
                LIMIT 100
            """)
        
        # Execute all queries in parallel
        results = {}
        for key, query_future in queries.items():
            try:
                results[key] = await query_future
            except Exception as e:
                verbose_proxy_logger.error(f"Error in dashboard query {key}: {e}")
                results[key] = []
        
        # Process and format the results
        dashboard_data = {
            "monthly_spend": results.get("monthly_spend", []),
            "top_keys": [
                {
                    "key": (row.get("key_alias") or row.get("api_key", "")[:10]),
                    "api_key": row.get("api_key", ""),
                    "key_alias": row.get("key_alias"),
                    "spend": float(row.get("total_spend", 0))
                }
                for row in results.get("top_keys", [])
            ],
            "top_models": [
                {
                    "key": row.get("model", ""),
                    "spend": float(row.get("total_spend", 0))
                }
                for row in results.get("top_models", [])
            ],
            "provider_spend": [
                {
                    "provider": row.get("provider", ""),
                    "spend": float(row.get("spend", 0))
                }
                for row in results.get("provider_spend", [])
            ],
            "global_activity": {
                "daily_data": [
                    {
                        "date": str(row.get("date", "")),
                        "api_requests": int(row.get("api_requests", 0)),
                        "total_tokens": int(row.get("total_tokens", 0))
                    }
                    for row in results.get("global_activity", [])
                ],
                "sum_api_requests": sum(int(row.get("api_requests", 0)) for row in results.get("global_activity", [])),
                "sum_total_tokens": sum(int(row.get("total_tokens", 0)) for row in results.get("global_activity", []))
            }
        }
        
        # Add admin-only data if available
        if "team_spend" in results:
            dashboard_data["team_spend"] = results["team_spend"]
        if "tag_names" in results:
            dashboard_data["tag_names"] = [row.get("tag_name") for row in results["tag_names"]]
        
        return dashboard_data
        
    except Exception as e:
        verbose_proxy_logger.error(f"Dashboard summary error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": str(e)}
        )


async def ui_view_session_spend_logs(
    session_id: str = fastapi.Query(
        description="Get all spend logs for a particular session",
    ),
    user_api_key_dict: UserAPIKeyAuth = Depends(user_api_key_auth),
):
    """
    Get all spend logs for a particular session
    """
    from litellm.proxy.proxy_server import prisma_client

    try:
        if prisma_client is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database not connected",
            )

        # Build query conditions
        where_conditions = {"session_id": session_id}
        # Query the database
        result = await prisma_client.db.litellm_spendlogs.find_many(
            where=where_conditions, order={"startTime": "asc"}
        )
        return result
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(e),
            )


# Individual metric endpoints for parallel loading
@router.get("/global/metrics/total-requests")
async def get_total_requests(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total API requests for the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT SUM(api_requests) as total_requests
        FROM "LiteLLM_DailyUserSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {"total_requests": result[0]["total_requests"] or 0}


@router.get("/global/metrics/successful-requests")
async def get_successful_requests(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total successful API requests for the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT SUM(successful_requests) as successful_requests
        FROM "LiteLLM_DailyUserSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {"successful_requests": result[0]["successful_requests"] or 0}


@router.get("/global/metrics/failed-requests")
async def get_failed_requests(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total failed API requests for the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT SUM(failed_requests) as failed_requests
        FROM "LiteLLM_DailyUserSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {"failed_requests": result[0]["failed_requests"] or 0}


@router.get("/global/metrics/total-tokens")
async def get_total_tokens(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total tokens (prompt + completion) for the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT 
            SUM(prompt_tokens + completion_tokens) as total_tokens,
            SUM(prompt_tokens) as prompt_tokens,
            SUM(completion_tokens) as completion_tokens
        FROM "LiteLLM_DailyUserSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {
        "total_tokens": result[0]["total_tokens"] or 0,
        "prompt_tokens": result[0]["prompt_tokens"] or 0,
        "completion_tokens": result[0]["completion_tokens"] or 0
    }


@router.get("/global/metrics/total-spend")
async def get_total_spend(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total spend for the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT SUM(spend) as total_spend
        FROM "LiteLLM_DailyUserSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {"total_spend": result[0]["total_spend"] or 0}


@router.get("/global/metrics/average-cost-per-request")
async def get_average_cost_per_request(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get average cost per request for the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT 
            SUM(spend) as total_spend,
            SUM(api_requests) as total_requests,
            CASE 
                WHEN SUM(api_requests) > 0 THEN SUM(spend) / SUM(api_requests)
                ELSE 0
            END as average_cost_per_request
        FROM "LiteLLM_DailyUserSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {
        "average_cost_per_request": result[0]["average_cost_per_request"] or 0,
        "total_spend": result[0]["total_spend"] or 0,
        "total_requests": result[0]["total_requests"] or 0
    }


# Team-specific metric endpoints
@router.get("/teams/metrics/total-requests")
async def get_team_total_requests(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total API requests for teams in the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT SUM(api_requests) as total_requests
        FROM "LiteLLM_DailyTeamSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {"total_requests": result[0]["total_requests"] or 0}


@router.get("/teams/metrics/successful-requests")
async def get_team_successful_requests(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total successful API requests for teams in the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT SUM(successful_requests) as successful_requests
        FROM "LiteLLM_DailyTeamSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {"successful_requests": result[0]["successful_requests"] or 0}


@router.get("/teams/metrics/failed-requests")
async def get_team_failed_requests(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total failed API requests for teams in the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT SUM(failed_requests) as failed_requests
        FROM "LiteLLM_DailyTeamSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {"failed_requests": result[0]["failed_requests"] or 0}


@router.get("/teams/metrics/total-tokens")
async def get_team_total_tokens(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total tokens for teams in the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT 
            SUM(prompt_tokens + completion_tokens) as total_tokens,
            SUM(prompt_tokens) as prompt_tokens,
            SUM(completion_tokens) as completion_tokens
        FROM "LiteLLM_DailyTeamSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {
        "total_tokens": result[0]["total_tokens"] or 0,
        "prompt_tokens": result[0]["prompt_tokens"] or 0,
        "completion_tokens": result[0]["completion_tokens"] or 0
    }


@router.get("/teams/metrics/total-spend")
async def get_team_total_spend(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total spend for teams in the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT SUM(spend) as total_spend
        FROM "LiteLLM_DailyTeamSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {"total_spend": result[0]["total_spend"] or 0}


@router.get("/teams/metrics/average-cost-per-request")
async def get_team_average_cost_per_request(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get average cost per request for teams in the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT 
            SUM(spend) as total_spend,
            SUM(api_requests) as total_requests,
            CASE 
                WHEN SUM(api_requests) > 0 THEN SUM(spend) / SUM(api_requests)
                ELSE 0
            END as average_cost_per_request
        FROM "LiteLLM_DailyTeamSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {
        "average_cost_per_request": result[0]["average_cost_per_request"] or 0,
        "total_spend": result[0]["total_spend"] or 0,
        "total_requests": result[0]["total_requests"] or 0
    }


# Tag-specific metric endpoints
@router.get("/tags/metrics/total-requests")
async def get_tag_total_requests(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total API requests for tags in the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT SUM(api_requests) as total_requests
        FROM "LiteLLM_DailyTagSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {"total_requests": result[0]["total_requests"] or 0}


@router.get("/tags/metrics/successful-requests")
async def get_tag_successful_requests(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total successful API requests for tags in the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT SUM(successful_requests) as successful_requests
        FROM "LiteLLM_DailyTagSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {"successful_requests": result[0]["successful_requests"] or 0}


@router.get("/tags/metrics/failed-requests")
async def get_tag_failed_requests(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total failed API requests for tags in the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT SUM(failed_requests) as failed_requests
        FROM "LiteLLM_DailyTagSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {"failed_requests": result[0]["failed_requests"] or 0}


@router.get("/tags/metrics/total-tokens")
async def get_tag_total_tokens(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total tokens for tags in the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT 
            SUM(prompt_tokens + completion_tokens) as total_tokens,
            SUM(prompt_tokens) as prompt_tokens,
            SUM(completion_tokens) as completion_tokens
        FROM "LiteLLM_DailyTagSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {
        "total_tokens": result[0]["total_tokens"] or 0,
        "prompt_tokens": result[0]["prompt_tokens"] or 0,
        "completion_tokens": result[0]["completion_tokens"] or 0
    }


@router.get("/tags/metrics/total-spend")
async def get_tag_total_spend(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get total spend for tags in the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT SUM(spend) as total_spend
        FROM "LiteLLM_DailyTagSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {"total_spend": result[0]["total_spend"] or 0}


@router.get("/tags/metrics/average-cost-per-request")
async def get_tag_average_cost_per_request(
    start_date: Optional[str] = fastapi.Query(default=None),
    end_date: Optional[str] = fastapi.Query(default=None),
):
    """Get average cost per request for tags in the date range"""
    from litellm.proxy.proxy_server import prisma_client
    
    if prisma_client is None:
        raise HTTPException(status_code=500, detail={"error": "No db connected"})
    
    date_filter = ""
    if start_date and end_date:
        date_filter = f"AND date >= '{start_date}' AND date <= '{end_date}'"
    else:
        date_filter = "AND date >= CURRENT_DATE - INTERVAL '30 days'"
    
    sql_query = f"""
        SELECT 
            SUM(spend) as total_spend,
            SUM(api_requests) as total_requests,
            CASE 
                WHEN SUM(api_requests) > 0 THEN SUM(spend) / SUM(api_requests)
                ELSE 0
            END as average_cost_per_request
        FROM "LiteLLM_DailyTagSpend"
        WHERE 1=1 {date_filter}
    """
    
    result = await prisma_client.db.query_raw(query=sql_query)
    return {
        "average_cost_per_request": result[0]["average_cost_per_request"] or 0,
        "total_spend": result[0]["total_spend"] or 0,
        "total_requests": result[0]["total_requests"] or 0
    }


def _build_status_filter_condition(status_filter: Optional[str]) -> Dict[str, Any]:
    """
    Helper function to build the status filter condition for database queries.

    Args:
        status_filter (Optional[str]): The status to filter by. Can be "success" or "failure".

    Returns:
        Dict[str, Any]: A dictionary containing the status filter condition.
    """
    if status_filter is None:
        return {}

    if status_filter == "success":
        return {"OR": [{"status": {"equals": "success"}}, {"status": None}]}
    else:
        return {"status": {"equals": status_filter}}
