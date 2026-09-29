"""Money with consequences: rent, lending, repaying. Debts live in relationships.debt_cents (actor owes target)."""
from __future__ import annotations

import sqlite3

from contracts.claim import Claim
from world.attention import QUIET, noticers, var
from world.claims import describe_claim, labels
from world.events import Change, ClaimSpec, EventSpec, MemorySpec
from world.helpers import RelDeltas, person
from world.intent import LEND_CENTS, Intent

RENT_CENTS = 600
ODD_JOBS_CENTS = 900  # what someone without a job scrapes together in a day


def arrears(conn: sqlite3.Connection, pid: str) -> int:
    return int(var(conn, f"arrears.{pid}", 0))


def rent_changes(conn: sqlite3.Connection, pid: str) -> list[Change]:
    """Overnight rent. What cannot be paid becomes arrears; money paid first clears old arrears."""
    if var(conn, f"arrears.{pid}", None) is None:
        return []  # a world without the economy
    p = person(conn, pid)
    money = p["money_cents"] + (0 if '"work"' in p["schedule"] else ODD_JOBS_CENTS)
    income = money - p["money_cents"]
    due = RENT_CENTS + arrears(conn, pid)
    paid = min(money, due)
    changes = [Change("person", pid, "money_cents", delta=income - paid)] if income - paid else []
    new_arrears = due - paid
    if new_arrears != arrears(conn, pid):
        changes.append(Change("var", f"arrears.{pid}", "value", delta=float(new_arrears - arrears(conn, pid))))
    return changes


def resolve_lend(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a, b = it.actor, it.target
    here = person(conn, a)["location_id"]
    names = labels(conn)
    lent = Claim(a, "lend", b)
    owes = Claim(b, "owe", a)
    deltas = RelDeltas()
    deltas.add(b, a, "affection", 0.1)
    deltas.add(b, a, "trust", 0.05)
    seen = noticers(conn, here, now, f"lend:{a}:{b}", QUIET, a, b)
    return EventSpec(
        timestamp=now, type="lend", trigger_type=trigger, location_id=here, importance=0.45,
        truth={"actor": a, "target": b, "amount_cents": LEND_CENTS, "reason": it.reason, "source": it.source},
        participants=[(a, "actor"), (b, "target")] + [(w, "witness") for w in seen],
        changes=[Change("person", a, "money_cents", delta=-LEND_CENTS), Change("person", b, "money_cents", delta=LEND_CENTS),
                 Change("relationship", f"{b}:{a}", "debt_cents", delta=LEND_CENTS)] + deltas.changes(conn),
        memories=[MemorySpec(p, describe_claim(lent, names), 1.0, claim=lent) for p in (a, b)]
        + [MemorySpec(p, describe_claim(owes, names), 1.0, claim=owes) for p in (a, b)]
        + [MemorySpec(w, describe_claim(lent, names), 0.6, claim=lent) for w in seen],
        claims=[ClaimSpec(lent), ClaimSpec(owes)],
    )


def resolve_repay(conn: sqlite3.Connection, it: Intent, now: int, trigger: str) -> EventSpec:
    a, b = it.actor, it.target
    here = person(conn, a)["location_id"]
    names = labels(conn)
    debt = conn.execute("SELECT debt_cents FROM relationships WHERE actor_id = ? AND target_id = ?", (a, b)).fetchone()[0]
    amount = min(debt, LEND_CENTS)
    paid = Claim(a, "repay", b)
    deltas = RelDeltas()
    deltas.add(b, a, "trust", 0.1)
    deltas.add(b, a, "affection", 0.05)
    return EventSpec(
        timestamp=now, type="repay", trigger_type=trigger, location_id=here, importance=0.4,
        truth={"actor": a, "target": b, "amount_cents": amount, "left_cents": debt - amount,
               "reason": it.reason, "source": it.source},
        participants=[(a, "actor"), (b, "target")],
        changes=[Change("person", a, "money_cents", delta=-amount), Change("person", b, "money_cents", delta=amount),
                 Change("relationship", f"{a}:{b}", "debt_cents", delta=-amount)] + deltas.changes(conn),
        memories=[MemorySpec(p, describe_claim(paid, names), 1.0, claim=paid) for p in (a, b)],
        claims=[ClaimSpec(paid)],
    )
