"""CLI entry point for CSV data-entry workflows (Phase 1's manual/CSV
entry path — see app/csv_import.py's module docstring for full format
docs and the CCC ONE license rationale).

Usage:
  python scripts/csv_import_cli.py <ENV_VAR_NAME> customers <path/to/customers.csv> [--commit]
  python scripts/csv_import_cli.py <ENV_VAR_NAME> vehicles <path/to/vehicles.csv> [--commit]
  python scripts/csv_import_cli.py <ENV_VAR_NAME> jobs <path/to/jobs.csv> [--commit]
  python scripts/csv_import_cli.py <ENV_VAR_NAME> costs <path/to/cost_entries.csv> [--commit]

Connection string is read from the named environment variable (never a
literal CLI arg), same discipline as scripts/run_sql.py. --commit is
required to actually write; without it, every import runs as a dry run
and reports what WOULD happen.

--actor NAME sets created_by/updated_by (defaults to the OS username via
getpass.getuser() if not given — always overridable, since "who did this
CSV import" is meaningful audit-trail information, not boilerplate).
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import csv_import
from app.db import cursor


IMPORTERS = {
    "customers": csv_import.import_customers_csv,
    "vehicles": csv_import.import_vehicles_csv,
    "jobs": csv_import.import_jobs_csv,
    "costs": csv_import.import_cost_entries_csv,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("env_var", help="Environment variable name holding the DB connection string")
    parser.add_argument("kind", choices=sorted(IMPORTERS.keys()))
    parser.add_argument("csv_path")
    parser.add_argument("--commit", action="store_true", help="Actually write. Without this, dry-run only.")
    parser.add_argument("--actor", default=None, help="created_by/updated_by value (defaults to OS username)")
    args = parser.parse_args()

    actor = args.actor or getpass.getuser()
    importer = IMPORTERS[args.kind]

    with cursor(args.env_var, autocommit=False) as cur:
        report = importer(cur, args.csv_path, actor, dry_run=not args.commit)

    print(report.summary())
    sys.exit(0 if report.ok() else 1)


if __name__ == "__main__":
    main()
