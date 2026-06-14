import asyncio
import threading
from functools import lru_cache
from supabase import create_client, Client, ClientOptions
from app.config import get_settings

# Thread-local storage so each thread gets its own Supabase client,
# preventing HTTP/2 connection sharing issues under concurrent load.
_thread_local = threading.local()


def get_supabase() -> Client:
    """Return a thread-local Supabase client (avoids HTTP/2 connection conflicts)."""
    if not hasattr(_thread_local, "client"):
        settings = get_settings()
        _thread_local.client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _thread_local.client


async def db_fetch_one(table: str, filters: dict) -> dict | None:
    """Fetch a single row from a Supabase table."""
    client = get_supabase()

    def _query():
        q = client.table(table).select("*")
        for key, val in filters.items():
            q = q.eq(key, val)
        return q.limit(1).execute()

    result = await asyncio.to_thread(_query)
    return result.data[0] if result.data else None


async def db_fetch_many(
    table: str,
    filters: dict | None = None,
    order_by: str | None = None,
    limit: int | None = None,
    select: str = "*",
) -> list[dict]:
    """Fetch multiple rows from a Supabase table."""
    client = get_supabase()

    def _query():
        q = client.table(table).select(select)
        if filters:
            for key, val in filters.items():
                if isinstance(val, (list, tuple)):
                    q = q.in_(key, list(val))
                else:
                    q = q.eq(key, val)
        if order_by:
            desc = order_by.startswith("-")
            col = order_by.lstrip("-")
            q = q.order(col, desc=desc)
        if limit:
            q = q.limit(limit)
        return q.execute()

    result = await asyncio.to_thread(_query)
    return result.data or []


async def db_insert(table: str, data: dict) -> dict:
    """Insert a row and return the created row."""
    client = get_supabase()

    def _query():
        return client.table(table).insert(data).execute()

    result = await asyncio.to_thread(_query)
    return result.data[0]


async def db_update(table: str, filters: dict, data: dict) -> list[dict]:
    """Update rows matching filters and return updated rows."""
    client = get_supabase()

    def _query():
        q = client.table(table).update(data)
        for key, val in filters.items():
            q = q.eq(key, val)
        return q.execute()

    result = await asyncio.to_thread(_query)
    return result.data or []


async def db_upsert(table: str, data: dict, on_conflict: str) -> dict:
    """Upsert a row by conflict column and return the row."""
    client = get_supabase()

    def _query():
        return client.table(table).upsert(data, on_conflict=on_conflict).execute()

    result = await asyncio.to_thread(_query)
    return result.data[0]


async def db_delete(table: str, filters: dict) -> list[dict]:
    """Delete rows matching filters and return deleted rows."""
    import asyncio as _asyncio
    client = get_supabase()

    def _query():
        q = client.table(table).delete()
        for key, val in filters.items():
            q = q.eq(key, val)
        return q.execute()

    result = await _asyncio.to_thread(_query)
    return result.data or []


async def db_update_where(table: str, filters: dict, data: dict) -> list[dict]:
    """Update rows matching ALL filters. Alias for db_update with clearer semantics."""
    return await db_update(table, filters, data)


async def db_rpc(function_name: str, params: dict) -> any:
    """Call a Supabase RPC function."""
    client = get_supabase()

    def _query():
        return client.rpc(function_name, params).execute()

    result = await asyncio.to_thread(_query)
    return result.data
