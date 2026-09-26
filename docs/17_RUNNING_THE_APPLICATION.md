# Running the application

Operational instructions are being completed alongside the implementation. See `IMPLEMENTATION_STATUS.md` for actual verification coverage.

## PostgreSQL text sources

The playground's own database and a source database are separate connections. Source connections require `RAG_MASTER_KEY`, an external Fernet key, and exact owner-controlled destination and relation policies in `.env`. Generate the key using the command in `.env.example`; back it up separately from PostgreSQL.

For example:

```dotenv
RAG_DATABASE_HOST_ALLOWLIST=["db.internal"]
RAG_DATABASE_RELATION_ALLOWLIST=[{"host":"db.internal","port":5432,"database":"knowledge","schema":"public","relation":"articles","columns":["id","body"]}]
```

Prepare a dedicated role in that source database. Set its password securely using your database administration tool, then grant only the required access:

```sql
CREATE ROLE rag_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
GRANT CONNECT ON DATABASE knowledge TO rag_reader;
GRANT USAGE ON SCHEMA public TO rag_reader;
GRANT SELECT (id, body) ON public.articles TO rag_reader;
```

The role must not inherit write privileges on the selected relation. Only explicitly approved relations and columns appear in the browser. Approve views only after reviewing the functions they call. Use `verify-full` TLS for remote sources and configure the PostgreSQL client trust roots on the server. `disable` is available for an intentional local development connection.

Connect through the source panel, inspect the allowed relation, choose non-null unique key columns and text columns, then preview or capture. A read-only repeatable-read transaction freezes at most 10,000 rows and 20 MiB of selected text. The interface discloses truncated captures. Queries read this frozen source and never reconnect. Refresh creates a new source and corpus revision; previous runs retain their old snapshot. Deleting a connection removes credentials while retaining already captured sources.
