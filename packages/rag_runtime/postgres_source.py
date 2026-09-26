"""Allowlisted PostgreSQL text capture, never used by question execution."""

import asyncio
import math
import weakref
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from .contracts import canonical, digest
from .errors import Problem
from .network import resolve_host

MAX_BYTES = 20 * 1024 * 1024
CONNECTION_SLOTS = weakref.WeakKeyDictionary()


def policies(config, approved):
    return [
        p
        for p in approved
        if p["host"].casefold() == config["host"].casefold()
        and p["port"] == config["port"]
        and p["database"] == config["database"]
        and p["schema"] in config["allowed_schemas"]
    ]


@asynccontextmanager
async def database(config, password, allowed_hosts):
    address = await resolve_host(config["host"], config["port"], allowed_hosts)
    params = dict(
        host=config["host"],
        hostaddr=address,
        port=config["port"],
        dbname=config["database"],
        user=config["username"],
        password=password,
        sslmode=config["ssl_mode"],
        connect_timeout=10,
        autocommit=True,
        row_factory=dict_row,
    )
    try:
        # Operation-owned pools close credentials/connections on completion or cancellation.
        async with (
            CONNECTION_SLOTS.setdefault(asyncio.get_running_loop(), asyncio.Semaphore(2)),
            AsyncConnectionPool(
                kwargs=params, min_size=0, max_size=2, open=False, timeout=10, reconnect_timeout=1
            ) as pool,
        ):
            async with pool.connection() as conn:
                async with conn.transaction():
                    await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    await conn.execute("SET LOCAL statement_timeout='30s'")
                    await conn.execute("SET LOCAL lock_timeout='5s'")
                    await conn.execute("SET LOCAL TIME ZONE 'UTC'")
                    await conn.execute("SET LOCAL DateStyle='ISO,YMD'")
                    role = await (
                        await conn.execute(
                            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                        )
                    ).fetchone()
                    if not role or any(role.values()):
                        raise Problem(
                            "READ_ONLY_ROLE_REQUIRED",
                            "Use a dedicated read-only database role without elevated role privileges.",
                        )
                    yield conn
    except (psycopg.Error, PoolTimeout) as exc:
        code = (
            "DATABASE_TIMEOUT"
            if isinstance(exc, (psycopg.errors.QueryCanceled, PoolTimeout))
            else "DATABASE_UNAVAILABLE"
        )
        raise Problem(
            code,
            "The approved database operation failed. Check the read-only role, TLS settings and database availability.",
        ) from None


async def relation(conn, policy):
    row = await (
        await conn.execute(
            "SELECT c.oid,c.relkind,has_table_privilege(c.oid,'INSERT,UPDATE,DELETE,TRUNCATE') AS writable FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s AND c.relkind IN ('r','p','v','m')",
            (policy["schema"], policy["relation"]),
        )
    ).fetchone()
    if not row:
        raise Problem("RELATION_UNAVAILABLE", "The approved table or view is unavailable.")
    if row["writable"]:
        raise Problem(
            "READ_ONLY_ROLE_REQUIRED",
            "The source role has write permissions on the selected relation. Use a read-only role.",
        )
    columns = await (
        await conn.execute(
            "SELECT attnum,attname AS name,format_type(atttypid,atttypmod) AS data_type,NOT attnotnull AS nullable,has_column_privilege(attrelid,attnum,'SELECT') AS selectable FROM pg_attribute WHERE attrelid=%s AND attnum>0 AND NOT attisdropped ORDER BY attnum",
            (row["oid"],),
        )
    ).fetchall()
    columns = [c for c in columns if c["name"] in policy["columns"] and c["selectable"]]
    if not columns:
        raise Problem("RELATION_UNAVAILABLE", "No approved columns can be read by this database role.")
    indexes = await (
        await conn.execute(
            "SELECT indkey::smallint[] AS keys,indnkeyatts FROM pg_index WHERE indrelid=%s AND indisunique AND indisvalid AND indpred IS NULL AND indexprs IS NULL ORDER BY indisprimary DESC,indexrelid",
            (row["oid"],),
        )
    ).fetchall()
    by_number = {c["attnum"]: c for c in columns}
    suggested = []
    for index in indexes:
        keys = index["keys"][: index["indnkeyatts"]]
        if all(k in by_number and not by_number[k]["nullable"] for k in keys):
            suggested = [by_number[k]["name"] for k in keys]
            break
    return dict(
        schema=policy["schema"],
        name=policy["relation"],
        kind="view" if row["relkind"] in {"v", "m"} else "table",
        columns=[{k: v for k, v in c.items() if k != "attnum"} for c in columns],
        suggested_key_columns=suggested,
    )


async def list_relations(config, password, allowed_hosts, approved):
    async with asyncio.timeout(45):
        async with database(config, password, allowed_hosts) as conn:
            return [await relation(conn, policy) for policy in policies(config, approved)]


def key_value(value):
    if (
        value is None
        or isinstance(value, (list, dict, bytes))
        or isinstance(value, float)
        and not math.isfinite(value)
    ):
        raise Problem("UNSTABLE_KEY", "Choose non-null scalar columns that uniquely identify each row.")
    return value if isinstance(value, (str, int, float, bool)) else str(value)


async def capture(
    config, password, allowed_hosts, approved, selection, *, preview=False, max_bytes=MAX_BYTES
):
    policy = next(
        (
            p
            for p in policies(config, approved)
            if p["schema"] == selection["schema"] and p["relation"] == selection["relation"]
        ),
        None,
    )
    if policy is None:
        raise Problem("RELATION_DENIED", "The owner has not approved this relation and its columns.")
    keys, texts = selection["key_columns"], selection["text_columns"]
    requested = keys + texts + ([selection["updated_at_column"]] if selection["updated_at_column"] else [])
    if (
        len(set(keys)) != len(keys)
        or len(set(texts)) != len(texts)
        or not set(requested) <= set(policy["columns"])
    ):
        raise Problem("COLUMN_DENIED", "Choose distinct columns from the owner-approved selection.")
    rows, skipped, truncated, total = [], 0, False, 0
    ordering = "Ascending database order: " + ", ".join(keys)
    async with asyncio.timeout(45):
        async with database(config, password, allowed_hosts) as conn:
            info = await relation(conn, policy)
            if not set(requested) <= {c["name"] for c in info["columns"]}:
                raise Problem("COLUMN_DENIED", "The database role cannot read the requested columns.")
            table = sql.Identifier(selection["schema"], selection["relation"])
            key_list = sql.SQL(",").join(map(sql.Identifier, keys))
            nulls = sql.SQL(" OR ").join(sql.SQL("{} IS NULL").format(sql.Identifier(k)) for k in keys)
            invalid = await (
                await conn.execute(
                    sql.SQL("SELECT 1 FROM {} GROUP BY {} HAVING count(*)>1 OR {} LIMIT 1").format(
                        table, key_list, nulls
                    )
                )
            ).fetchone()
            if invalid:
                raise Problem("UNSTABLE_KEY", "The selected key columns contain nulls or duplicate values.")
            raw_size = sql.SQL("+").join(
                sql.SQL("coalesce(octet_length({}::text),0)").format(sql.Identifier(t)) for t in texts
            )
            # Check each row's byte size on the server before returning potentially huge text values.
            fields = [
                sql.SQL("{} AS {}").format(sql.Identifier(k), sql.Identifier(f"k{i}"))
                for i, k in enumerate(keys)
            ]
            fields += [
                sql.SQL("CASE WHEN ({}) <= {} THEN {}::text ELSE NULL END AS {}").format(
                    raw_size, sql.Literal(max_bytes), sql.Identifier(t), sql.Identifier(f"t{i}")
                )
                for i, t in enumerate(texts)
            ]
            fields.append(sql.SQL("({}) AS raw_size").format(raw_size))
            if selection["updated_at_column"]:
                fields.append(
                    sql.SQL("{}::text AS updated_at").format(sql.Identifier(selection["updated_at_column"]))
                )
            limit = min(selection["max_rows"], 5) if preview else selection["max_rows"]
            async with conn.cursor(name="text_snapshot") as cur:
                await cur.execute(
                    sql.SQL("SELECT {} FROM {} ORDER BY {} LIMIT {}").format(
                        sql.SQL(",").join(fields), table, key_list, sql.Literal(selection["max_rows"] + 1)
                    )
                )
                scanned = 0
                while batch := await cur.fetchmany(1):
                    row = batch[0]
                    if scanned >= selection["max_rows"] or (preview and len(rows) >= limit):
                        truncated = True
                        break
                    scanned += 1
                    if row["raw_size"] > max_bytes:
                        truncated = True
                        break
                    values = {key: row[f"t{i}"] for i, key in enumerate(texts)}
                    if not any(v is not None and v.strip() for v in values.values()):
                        skipped += 1
                        continue
                    key = {name: key_value(row[f"k{i}"]) for i, name in enumerate(keys)}
                    if len(canonical(key)) > 65536:
                        raise Problem("UNSTABLE_KEY", "The selected record key is too large.")
                    text = "\n".join(
                        f"{name}: {value if value is not None else 'NULL'}" for name, value in values.items()
                    )
                    record = dict(key=key, values=values, text=text, updated_at=row.get("updated_at"))
                    size = len(canonical(record))
                    if total + size > max_bytes:
                        truncated = True
                        break
                    rows.append(record)
                    total += size
    if preview:
        return dict(
            rows=[dict(key=r["key"], text=r["text"][:8000]) for r in rows],
            truncated=truncated or any(len(r["text"]) > 8000 for r in rows),
            ordering=ordering,
        )
    if not rows:
        raise Problem(
            "EMPTY_SNAPSHOT",
            "No text records fit this selection. Choose populated text columns or narrower records.",
        )
    raw = dict(
        format="postgres_snapshot_v1",
        relation=f"{selection['schema']}.{selection['relation']}",
        key_columns=keys,
        text_columns=texts,
        captured_at=datetime.now(timezone.utc).isoformat(),
        rows=rows,
        skipped_empty_records=skipped,
        truncated=truncated,
        ordering=ordering,
    )
    text, segments = "", []
    for row in rows:
        start = len(text)
        text += row["text"] + "\n\n"
        segments.append(
            dict(
                start=start,
                end=len(text),
                page=None,
                relation=raw["relation"],
                record_key=row["key"],
                updated_at=row["updated_at"],
            )
        )
    parsed = dict(
        text=text,
        segments=segments,
        parser="postgres_snapshot",
        parser_revision="1",
        sha256=digest(canonical(raw)),
        warnings=["Snapshot truncated in stable key order."] if truncated else [],
    )
    return dict(raw=raw, parsed=parsed)
