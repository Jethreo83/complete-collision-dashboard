"""One-off admin script: create test platform.person rows on STAGING only,
so csv_import_cli.py's full pipeline (customers -> vehicles -> jobs ->
costs) can be exercised end-to-end against the templates in
data/templates/. NOT for production use — see app/repository.py's
create_person_and_customer() docstring for why brand-new person creation
needs a privileged connection and is a known open architecture gap.

Usage: python scripts/_seed_test_people.py <ENV_VAR_NAME>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import cursor

PEOPLE = [
    ("Jane", "Doe", "jane.doe@example.com", "512-555-0101"),
    ("John", "Smith", "john.smith@example.com", "512-555-0102"),
]


def main():
    env_var = sys.argv[1]
    with cursor(env_var, autocommit=False) as cur:
        for first, last, email, phone in PEOPLE:
            cur.execute(
                "SELECT id FROM platform.person WHERE email_normalized = %s",
                (email.lower(),),
            )
            if cur.fetchone():
                print(f"SKIP (already exists): {email}")
                continue
            cur.execute(
                """
                INSERT INTO platform.person (first_name, last_name, email_normalized, phone_normalized, created_by)
                VALUES (%s, %s, %s, %s, 'seed_test_people_script')
                RETURNING id
                """,
                (first, last, email.lower(), phone),
            )
            print(f"CREATED: {email} -> person_id={cur.fetchone()['id']}")


if __name__ == "__main__":
    main()
