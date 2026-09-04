"""Apply/run a .sql file against a Postgres connection, printing:
  - every server NOTICE (RAISE NOTICE ... in DO blocks) as it arrives
  - every SELECT's result rows

This is deliberately more verbose than `psql -f` piping to a log, because
the whole point of verify_NNN.sql scripts in this repo's discipline is to
prove behavior by real query output, not by trusting a clean exit code.

Usage: uv run --with psycopg2-binary python scripts/run_sql.py <ENV_VAR_NAME> <sql_file> [--rollback]

Connection string is read from an environment variable name (never a
literal CLI arg) so it doesn't land in shell history / process list.
--rollback: run the whole file in a transaction and roll it back at the
end (useful for re-running a verify script against data left by a prior
run without accumulating test rows) -- NOT used for actual migrations,
only for verify scripts if desired.
"""
import os
import sys

import psycopg2
import psycopg2.extensions


def main():
    args = sys.argv[1:]
    rollback = "--rollback" in args
    args = [a for a in args if a != "--rollback"]
    if len(args) != 2:
        print("usage: run_sql.py <ENV_VAR_NAME_HOLDING_CONN_STRING> <sql_file> [--rollback]", file=sys.stderr)
        sys.exit(2)

    env_var_name, sql_file = args
    conn_string = os.environ.get(env_var_name)
    if not conn_string:
        print(f"Environment variable {env_var_name} is not set or empty", file=sys.stderr)
        sys.exit(2)

    with open(sql_file, "r", encoding="utf-8") as f:
        sql = f.read()

    conn = psycopg2.connect(conn_string)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            # psycopg2 supports multiple ;-separated statements (including
            # DO $$...$$ blocks) in a single execute() call as long as we
            # don't need per-statement result sets for statements *before*
            # the last one. To get output from every SELECT (verify
            # scripts have several), split top-level statements and run
            # each individually, tracking dollar-quoted blocks so we don't
            # split inside a DO $$ ... $$ body.
            for stmt in _split_statements(sql):
                if _is_empty_or_comment_only(stmt):
                    continue
                cur.execute(stmt)
                for notice in conn.notices:
                    print(notice.strip())
                conn.notices.clear()
                if cur.description:  # this statement returned rows
                    cols = [d[0] for d in cur.description]
                    print(" | ".join(cols))
                    for row in cur.fetchall():
                        print(" | ".join(str(v) for v in row))
        if rollback:
            conn.rollback()
            print(f"ROLLED BACK: {sql_file} (--rollback requested, no changes persisted)")
        else:
            conn.commit()
            print(f"COMMITTED: {sql_file}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _is_empty_or_comment_only(stmt: str) -> bool:
    """True if stmt has no executable SQL — blank, or only `--` comment
    lines (Postgres rejects a bare comment as an empty query)."""
    for line in stmt.splitlines():
        line = line.strip()
        if line and not line.startswith("--"):
            return False
    return True


def _split_statements(sql: str):
    """Split on top-level semicolons, respecting $$ ... $$ dollar-quoted
    bodies (Postgres DO blocks) and `--` line comments, so we don't split
    on a semicolon that's actually just punctuation inside a comment."""
    stmts = []
    buf = []
    in_dollar = False
    in_line_comment = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if not in_dollar and sql[i:i+2] == "--":
            in_line_comment = True
            buf.append("--")
            i += 2
            continue
        if sql[i:i+2] == "$$":
            in_dollar = not in_dollar
            buf.append("$$")
            i += 2
            continue
        if ch == ";" and not in_dollar:
            stmts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


if __name__ == "__main__":
    main()
