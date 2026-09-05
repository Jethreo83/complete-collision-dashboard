"""Email/phone normalization for platform.person matching.

Local copy of the same logic Elektrica built for the identical problem
(app/normalize.py in elektrica-dashboard-ref, verified live there). Per
ADR-001's own extraction rule ("_shared is extracted only when a second
real consumer exists"), Elektrica's docstring explicitly names Complete
Collision as flagged-but-not-yet-a-real-consumer: this module's own
match_or_create_and_link_customer() (below/app/repository.py) is the
second real consumer that note was waiting for. NOT promoting to a
shared `platform.*` helper in this pass -- that is a cross-repo
refactor decision for Jed, not something either bot should do solo by
just deleting the other's copy. Flagged here as the trigger condition
now being met, not acted on unilaterally.

platform.match_or_create_person()'s exact-match step does a literal
string-equality comparison against platform.person.email_normalized/
phone_normalized, which are already normalized AT REST -- but nothing
upstream of that call normalized an INCOMING value before this module
existed for Collision. Without it, `Jane@Example.com` or a phone with
dashes/parens would silently fail to match an existing
`jane@example.com`/digits-only row and create a duplicate
platform.person -- exactly the previous behavior of
create_person_and_customer()'s inline `email.strip().lower()` (no phone
normalization at all), which this module supersedes for the new
match_or_create_and_link_customer() path.

IMPORTANT -- phone format is UNCONFIRMED against real data, same caveat
Elektrica's copy carries: this module normalizes phone to DIGITS ONLY
(strip everything but 0-9), no US country-code stripping. If Jed's
actual convention differs, this function is the one place to fix it --
flagged for his review, not silently assumed correct.
"""
from __future__ import annotations

import re
from typing import Optional


def normalize_email(email: Optional[str]) -> Optional[str]:
    """Lowercase + strip whitespace. Returns None for falsy/blank input
    (never an empty string) so callers can pass the result straight to
    platform.match_or_create_person()'s nullable p_email_normalized
    argument without an extra falsy check."""
    if email is None:
        return None
    cleaned = email.strip().lower()
    return cleaned or None


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """Strip everything but digits. Returns None for falsy/blank input or
    input with no digits at all. Does NOT strip a US country code -- see
    module docstring for why (unconfirmed against real data)."""
    if phone is None:
        return None
    digits = re.sub(r"\D", "", phone)
    return digits or None
