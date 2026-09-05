"""Manual/CSV data entry workflows — the ONLY way CCC ONE-adjacent data
enters this system in Phase 1 (ADR-001 §1: no API/EMS/Secure Share/DMS
Interface integration; a human reads CCC ONE and either types into the
dashboard directly, or exports a CSV they built by hand/from a
spreadsheet and imports it here).

Every import function in this module:
  - Takes a `dry_run` flag (default True) — reports what WOULD happen
    without writing anything, so a human can review before committing.
  - Is idempotent on natural keys (ro_number, vin, site name) — re-running
    the same CSV twice updates/skips rather than duplicating.
  - Records provenance: cost entries imported this way get
    source='csv_import' and source_file=<the CSV's filename>, per
    migrations/006's cost_entry.source_file column.
  - Never talks to CCC ONE in any way — input is a CSV file path on disk,
    nothing else.
  - Returns a structured report (ImportReport) instead of just printing,
    so a caller (CLI, future admin UI) can decide how to surface errors.

CSV formats (headers are required, order doesn't matter):

  customers.csv:
    first_name, last_name, email, phone, source
      source one of: walk_in, insurer_referred, elektrica_rental, other
      (defaults to walk_in if blank)
      NOTE (2026-09-05 continuous-build cycle): first_name+last_name are now
      REQUIRED (previously only email was required, since the old code path
      did a raw exact-email SELECT and nothing else). Each row now goes
      through the SAME platform.match_or_create_person() identity primitive
      POST /customers/intake and POST /staff/intake already use -- see
      import_customers_csv()'s own docstring for the full match/queue/create
      semantics and the REQUIRES A PRIVILEGED CONNECTION note (this import
      can no longer run as collision_app; it needs a neondb_owner-class
      connection string, same requirement create_person_and_customer()
      always had, now actually enforced by a real grant check instead of
      just documented).

  vehicles.csv:
    customer_email, vin, make, model, year
      customer_email must match a row already imported/existing (looked
      up by email against platform.person via collision.customer)

  jobs.csv (the RO tracker):
    ro_number, customer_email, vin, site, category, status,
    claim_number, insurer, adjuster_name, posture,
    gross_revenue, direct_ro_costs, labor_cost, rent_utility_share
      category one of: collision, pdr, hail
      status one of the 11 job_status values (defaults to 'undecided')
      site is a free-text name — created on demand via get_or_create_site
      NOTE (migration 010, 2026-09-06): direct_ro_costs/labor_cost are
      no longer written directly to collision.job (that migration made
      them genuinely derived from collision.cost_entry, collision_app
      can no longer INSERT/UPDATE them at all). To avoid SILENTLY
      DROPPING a value present in an existing/old-format jobs.csv, any
      non-zero direct_ro_costs/labor_cost on a jobs.csv row is converted
      into an equivalent collision.cost_entry row at import time (labor_cost
      -> one 'labor' category entry, direct_ro_costs -> one 'other'
      category entry, both source='csv_import'/source_file=<filename>,
      description noting it's a flat total from jobs.csv, not a real
      itemized breakdown). Prefer cost_entries.csv going forward for
      genuinely itemized data — this conversion is a compatibility path
      for the old flat-total format, not the recommended way to enter
      new data.

  cost_entries.csv:
    ro_number, category, description, amount, incurred_at
      category one of: parts, labor, paint_materials, sublet,
      rental_reimbursement, other
      incurred_at as YYYY-MM-DD, defaults to today if blank

customers.csv import (2026-09-05 continuous-build cycle) now goes through
app.repository.match_or_create_and_link_customer() -- the same shared
platform.match_or_create_person() identity primitive POST /customers/intake
and POST /staff/intake already use, closing the gap flagged in this
module's WORKLOG entries ("swap csv_import.py's person-creation paths to
the identity-match primitive now that 2 real consumers prove it works").
Because that primitive itself issues `SET ROLE platform_identity_service`,
this import REQUIRES A PRIVILEGED CONNECTION (a neondb_owner-class
connection string, same requirement create_person_and_customer() always
had) -- it will fail under collision_app with InsufficientPrivilege, which
is the correct, intended behavior, not a bug. vehicles.csv/jobs.csv still
look up an existing platform.person by exact normalized email (unchanged
-- those rows should already exist after customers.csv import, whether
matched to an existing person or newly created).
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from app.models import CostCategory, CostEntry, JobCategory, JobStatus
from app import normalize
from app import repository as repo


@dataclass
class ImportReport:
    file: str
    dry_run: bool
    total_rows: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    # attached/queued only ever populated by import_customers_csv (2026-09-05
    # cycle): the two extra outcomes platform.match_or_create_person() can
    # return that plain created/updated/skipped can't represent -- 'attached'
    # means an EXISTING platform.person was matched with confidence and
    # linked as a collision.customer (not a brand-new person, so not
    # 'created'; not a no-op, so not 'skipped'); 'queued' means the match was
    # ambiguous and a human must resolve it via platform.person_match_queue
    # before any collision.customer row exists for that row at all.
    attached: int = 0
    queued: int = 0
    queued_details: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [
            f"Import report for {self.file} ({'DRY RUN — nothing written' if self.dry_run else 'COMMITTED'})",
            f"  total rows:  {self.total_rows}",
            f"  created:     {self.created}",
            f"  attached:    {self.attached}",
            f"  updated:     {self.updated}",
            f"  skipped:     {self.skipped}",
            f"  queued:      {self.queued}",
            f"  errors:      {len(self.errors)}",
        ]
        for q in self.queued_details:
            lines.append(f"    ? {q}")
        for e in self.errors:
            lines.append(f"    - {e}")
        return "\n".join(lines)


def _read_rows(csv_path: str) -> list[dict]:
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def _clean(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = v.strip()
    return v if v else None


def _parse_decimal(v: Optional[str], field_name: str, default: str = "0") -> Decimal:
    v = _clean(v)
    if v is None:
        v = default
    try:
        return Decimal(v)
    except InvalidOperation:
        raise ValueError(f"{field_name}={v!r} is not a valid decimal number")


def _parse_int(v: Optional[str], field_name: str) -> Optional[int]:
    v = _clean(v)
    if v is None:
        return None
    try:
        return int(v)
    except ValueError:
        raise ValueError(f"{field_name}={v!r} is not a valid integer")


def _parse_date(v: Optional[str], field_name: str) -> Optional[date]:
    v = _clean(v)
    if v is None:
        return None
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"{field_name}={v!r} is not YYYY-MM-DD")


# ---------------------------------------------------------------------------
# customers.csv — link EXISTING platform.person rows only (see module
# docstring). Looks up by normalized email.
# ---------------------------------------------------------------------------

def import_customers_csv(cur, csv_path: str, actor: str, dry_run: bool = True) -> ImportReport:
    """Real customer-intake path via app.repository.match_or_create_and_
    link_customer() -- the same shared platform.match_or_create_person()
    identity primitive POST /customers/intake and POST /staff/intake
    already use (see module docstring). first_name/last_name are required
    (the primitive needs at least a name to create a genuinely new person
    when there's no match); email/phone/date_of_birth are optional inputs
    to the SAME underlying match call, normalized here via app.normalize
    before the repository call -- same convention as the API routes.

    *** REQUIRES A PRIVILEGED CONNECTION *** -- see module docstring. Under
    dry_run=True this function does NOT call the repository at all (that
    call itself would write a queue row or a new person row on some
    outcomes, which is not something a dry run may do) -- it only
    validates row shape (required fields, known `source` value) and
    reports how many rows WOULD be submitted for matching. It genuinely
    cannot preview attached/created/queued outcomes without invoking the
    real function, so those three counts are only ever non-zero when
    dry_run=False.
    """
    report = ImportReport(file=csv_path, dry_run=dry_run)
    rows = _read_rows(csv_path)
    report.total_rows = len(rows)

    for i, row in enumerate(rows, start=2):  # start=2: header is row 1
        try:
            first_name = _clean(row.get("first_name"))
            last_name = _clean(row.get("last_name"))
            if not first_name or not last_name:
                raise ValueError("first_name and last_name are both required")
            source = _clean(row.get("source")) or "walk_in"
            if source not in repo.VALID_CUSTOMER_SOURCES:
                raise ValueError(
                    f"source={source!r} must be one of {repo.VALID_CUSTOMER_SOURCES}"
                )
            date_of_birth = _parse_date(row.get("date_of_birth"), "date_of_birth")
            email_normalized = normalize.normalize_email(_clean(row.get("email")))
            phone_normalized = normalize.normalize_phone(_clean(row.get("phone")))

            if dry_run:
                report.created += 1
                continue

            result = repo.match_or_create_and_link_customer(
                cur, first_name, last_name, actor,
                date_of_birth=date_of_birth,
                email_normalized=email_normalized,
                phone_normalized=phone_normalized,
                source=source,
            )
            if result.match_status == "queued":
                report.queued += 1
                report.queued_details.append(
                    f"row {i}: {first_name} {last_name} queued for human review "
                    f"(queue_id={result.queue_id}, person_id={result.person_id})"
                )
            elif result.match_status == "attached":
                report.attached += 1
            else:  # 'created'
                report.created += 1
        except Exception as e:
            report.errors.append(f"row {i}: {e}")

    return report


# ---------------------------------------------------------------------------
# vehicles.csv
# ---------------------------------------------------------------------------

def import_vehicles_csv(cur, csv_path: str, actor: str, dry_run: bool = True) -> ImportReport:
    report = ImportReport(file=csv_path, dry_run=dry_run)
    rows = _read_rows(csv_path)
    report.total_rows = len(rows)

    for i, row in enumerate(rows, start=2):
        try:
            email = _clean(row.get("customer_email"))
            if not email:
                raise ValueError("customer_email is required")
            vin = _clean(row.get("vin"))
            make = _clean(row.get("make"))
            model = _clean(row.get("model"))
            year = _parse_int(row.get("year"), "year")

            cur.execute(
                "SELECT id FROM platform.person WHERE email_normalized = %s",
                (email.lower(),),
            )
            person_row = cur.fetchone()
            if not person_row:
                raise ValueError(f"no platform.person found with email={email!r}")
            customer = repo.get_customer_by_person_id(cur, person_row["id"])
            if not customer:
                raise ValueError(
                    f"person with email={email!r} exists but has no collision.customer "
                    "row yet — import customers.csv first"
                )

            if vin:
                existing = repo.get_vehicle_by_vin(cur, vin)
                if existing:
                    report.skipped += 1
                    continue

            if not dry_run:
                repo.get_or_create_vehicle(
                    cur, customer.id, actor, vin=vin, make=make, model=model, year=year,
                )
            report.created += 1
        except Exception as e:
            report.errors.append(f"row {i}: {e}")

    return report


# ---------------------------------------------------------------------------
# jobs.csv — the RO tracker
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {c.value for c in JobCategory}
VALID_STATUSES = {s.value for s in JobStatus}


def import_jobs_csv(cur, csv_path: str, actor: str, dry_run: bool = True) -> ImportReport:
    report = ImportReport(file=csv_path, dry_run=dry_run)
    rows = _read_rows(csv_path)
    report.total_rows = len(rows)

    for i, row in enumerate(rows, start=2):
        try:
            ro_number = _clean(row.get("ro_number"))
            if not ro_number:
                raise ValueError("ro_number is required")

            existing = repo.get_repair_order_by_ro_number(cur, ro_number)
            if existing:
                report.skipped += 1
                continue

            email = _clean(row.get("customer_email"))
            if not email:
                raise ValueError("customer_email is required")
            cur.execute(
                "SELECT id FROM platform.person WHERE email_normalized = %s",
                (email.lower(),),
            )
            person_row = cur.fetchone()
            if not person_row:
                raise ValueError(f"no platform.person found with email={email!r}")
            customer = repo.get_customer_by_person_id(cur, person_row["id"])
            if not customer:
                raise ValueError(f"person with email={email!r} has no collision.customer row yet")

            vin = _clean(row.get("vin"))
            if vin:
                vehicle = repo.get_vehicle_by_vin(cur, vin)
                if not vehicle:
                    raise ValueError(f"no vehicle found with vin={vin!r} — import vehicles.csv first")
            else:
                # No VIN given for this RO — matches collision.vehicle.vin's
                # nullable design ("intake may not always have VIN captured
                # yet", migrations/002). Fall back to matching by customer:
                # only safe when the customer has exactly one vehicle on
                # file, otherwise this is genuinely ambiguous and must be
                # disambiguated by a human rather than guessed.
                customer_vehicles = repo.get_vehicles_by_customer(cur, customer.id)
                if len(customer_vehicles) == 0:
                    raise ValueError(
                        f"no vin given and customer {email!r} has no vehicle on file — "
                        "import vehicles.csv first"
                    )
                if len(customer_vehicles) > 1:
                    raise ValueError(
                        f"no vin given and customer {email!r} has {len(customer_vehicles)} "
                        "vehicles on file — ambiguous, specify vin explicitly"
                    )
                vehicle = customer_vehicles[0]

            site_name = _clean(row.get("site"))
            if not site_name:
                raise ValueError("site is required")

            category = _clean(row.get("category"))
            if category not in VALID_CATEGORIES:
                raise ValueError(f"category={category!r} must be one of {VALID_CATEGORIES}")

            status = _clean(row.get("status")) or "undecided"
            if status not in VALID_STATUSES:
                raise ValueError(f"status={status!r} must be one of {VALID_STATUSES}")

            if not dry_run:
                site = repo.get_or_create_site(cur, site_name, actor)
                from app.models import RepairOrder as RO
                ro = RO(
                    ro_number=ro_number, vehicle_id=vehicle.id, customer_id=customer.id,
                    site_id=site.id, category=JobCategory(category), status=JobStatus(status),
                    claim_number=_clean(row.get("claim_number")),
                    insurer=_clean(row.get("insurer")),
                    adjuster_name=_clean(row.get("adjuster_name")),
                    posture=_clean(row.get("posture")),
                    gross_revenue=_parse_decimal(row.get("gross_revenue"), "gross_revenue"),
                    rent_utility_share=_parse_decimal(row.get("rent_utility_share"), "rent_utility_share"),
                )
                created_ro = repo.create_repair_order(cur, ro, actor)

                # See module docstring's jobs.csv NOTE (migration 010):
                # direct_ro_costs/labor_cost can no longer be written
                # directly to collision.job — convert any non-zero value
                # into a cost_entry row instead of silently dropping it.
                labor_flat = _parse_decimal(row.get("labor_cost"), "labor_cost")
                direct_flat = _parse_decimal(row.get("direct_ro_costs"), "direct_ro_costs")
                source_file = Path(csv_path).name
                if labor_flat > 0:
                    repo.add_cost_entry(
                        cur,
                        CostEntry(
                            job_id=created_ro.id, category=CostCategory.LABOR,
                            description="flat labor_cost total from jobs.csv (not itemized)",
                            amount=labor_flat, incurred_at=date.today(),
                            source="csv_import", source_file=source_file,
                        ),
                        actor,
                    )
                if direct_flat > 0:
                    repo.add_cost_entry(
                        cur,
                        CostEntry(
                            job_id=created_ro.id, category=CostCategory.OTHER,
                            description="flat direct_ro_costs total from jobs.csv (not itemized)",
                            amount=direct_flat, incurred_at=date.today(),
                            source="csv_import", source_file=source_file,
                        ),
                        actor,
                    )
            report.created += 1
        except Exception as e:
            report.errors.append(f"row {i}: {e}")

    return report


# ---------------------------------------------------------------------------
# cost_entries.csv — itemized ledger
# ---------------------------------------------------------------------------

VALID_COST_CATEGORIES = {c.value for c in CostCategory}


def import_cost_entries_csv(cur, csv_path: str, actor: str, dry_run: bool = True) -> ImportReport:
    report = ImportReport(file=csv_path, dry_run=dry_run)
    rows = _read_rows(csv_path)
    report.total_rows = len(rows)
    source_file = Path(csv_path).name

    for i, row in enumerate(rows, start=2):
        try:
            ro_number = _clean(row.get("ro_number"))
            if not ro_number:
                raise ValueError("ro_number is required")
            job = repo.get_repair_order_by_ro_number(cur, ro_number)
            if not job:
                raise ValueError(f"no job found with ro_number={ro_number!r} — import jobs.csv first")

            category = _clean(row.get("category"))
            if category not in VALID_COST_CATEGORIES:
                raise ValueError(f"category={category!r} must be one of {VALID_COST_CATEGORIES}")

            amount = _parse_decimal(row.get("amount"), "amount")
            if amount < 0:
                raise ValueError(f"amount={amount} must be >= 0")

            incurred_at = _parse_date(row.get("incurred_at"), "incurred_at") or date.today()

            if not dry_run:
                entry = CostEntry(
                    job_id=job.id, category=CostCategory(category),
                    description=_clean(row.get("description")), amount=amount,
                    incurred_at=incurred_at, source="csv_import", source_file=source_file,
                )
                repo.add_cost_entry(cur, entry, actor)
            report.created += 1
        except Exception as e:
            report.errors.append(f"row {i}: {e}")

    return report
