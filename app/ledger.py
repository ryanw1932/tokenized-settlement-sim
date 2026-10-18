"""Double-entry settlement ledger on PostgreSQL.

Guarantees:
  * Atomic: a transfer posts both entries and both balance updates, or nothing.
  * Idempotent: replaying the same idempotency key never posts twice.
  * No overdrafts: balances are checked while holding row locks (and by a CHECK constraint).
  * Deadlock-free: the two accounts of a transfer are always locked in ascending id order.
"""
import uuid
import psycopg2
from .db import DSN, pool

OPENING_BALANCE = 1_000_000

SCHEMA = """
DROP TABLE IF EXISTS entries, transfers, accounts CASCADE;
CREATE TABLE accounts(
    id INT PRIMARY KEY,
    bank TEXT NOT NULL,
    opening BIGINT NOT NULL,
    balance BIGINT NOT NULL CHECK (balance >= 0));
CREATE TABLE transfers(
    id UUID PRIMARY KEY,
    idem_key TEXT UNIQUE NOT NULL,
    src INT NOT NULL REFERENCES accounts(id),
    dst INT NOT NULL REFERENCES accounts(id),
    amount BIGINT NOT NULL CHECK (amount > 0),
    status TEXT NOT NULL CHECK (status IN ('pending','posted','rejected')),
    CHECK (src <> dst));
CREATE TABLE entries(
    id BIGSERIAL PRIMARY KEY,
    transfer_id UUID NOT NULL REFERENCES transfers(id),
    account_id INT NOT NULL REFERENCES accounts(id),
    amount BIGINT NOT NULL);
"""


def reset(n_banks: int = 6, opening: int = OPENING_BALANCE) -> None:
    conn = psycopg2.connect(DSN)
    with conn, conn.cursor() as c:
        c.execute(SCHEMA)
        for i in range(n_banks):
            c.execute("INSERT INTO accounts VALUES (%s,%s,%s,%s)", (i, f"bank{i}", opening, opening))
    conn.close()


def transfer(src: int, dst: int, amount: int, idem_key: str) -> dict:
    """Post a transfer. Returns {"transfer_id", "status", "duplicate"}.
    status is 'posted' or 'rejected' (insufficient funds)."""
    if src == dst or amount <= 0:
        raise ValueError("src must differ from dst and amount must be positive")
    p = pool()
    conn = p.getconn()
    try:
        with conn, conn.cursor() as c:
            # Lock both accounts FIRST, in ascending id order. Inserting into `transfers`
            # takes FK row locks on the accounts, so doing that earlier would break the
            # lock ordering and allow deadlocks.
            first, second = sorted((src, dst))
            c.execute(
                "SELECT id, balance FROM accounts WHERE id IN (%s,%s) ORDER BY id FOR UPDATE",
                (first, second),
            )
            balances = dict(c.fetchall())
            if src not in balances or dst not in balances:
                raise LookupError("unknown account")
            tid = str(uuid.uuid4())
            c.execute(
                """INSERT INTO transfers VALUES (%s,%s,%s,%s,%s,'pending')
                   ON CONFLICT (idem_key) DO NOTHING RETURNING id""",
                (tid, idem_key, src, dst, amount),
            )
            if c.fetchone() is None:  # replay: report the original outcome
                c.execute("SELECT id, status FROM transfers WHERE idem_key=%s", (idem_key,))
                oid, status = c.fetchone()
                return {"transfer_id": str(oid), "status": status, "duplicate": True}
            if balances[src] < amount:
                c.execute("UPDATE transfers SET status='rejected' WHERE id=%s", (tid,))
                return {"transfer_id": tid, "status": "rejected", "duplicate": False}
            c.execute("UPDATE accounts SET balance=balance-%s WHERE id=%s", (amount, src))
            c.execute("UPDATE accounts SET balance=balance+%s WHERE id=%s", (amount, dst))
            c.execute(
                "INSERT INTO entries(transfer_id,account_id,amount) VALUES (%s,%s,%s),(%s,%s,%s)",
                (tid, src, -amount, tid, dst, amount),
            )
            c.execute("UPDATE transfers SET status='posted' WHERE id=%s", (tid,))
            return {"transfer_id": tid, "status": "posted", "duplicate": False}
    finally:
        p.putconn(conn)


def balances() -> dict:
    conn = psycopg2.connect(DSN)
    with conn.cursor() as c:
        c.execute("SELECT id, bank, balance FROM accounts ORDER BY id")
        rows = c.fetchall()
    conn.close()
    return {r[0]: {"bank": r[1], "balance": r[2]} for r in rows}


def invariants() -> dict:
    """Checks that must hold at all times. All values should be zero / True."""
    conn = psycopg2.connect(DSN)
    with conn.cursor() as c:
        c.execute("SELECT COALESCE(SUM(amount),0) FROM entries")
        net_entries = int(c.fetchone()[0])
        c.execute("SELECT COUNT(*) FROM accounts WHERE balance < 0")
        negative = c.fetchone()[0]
        c.execute(
            """SELECT COUNT(*) FROM accounts a WHERE a.balance - a.opening !=
               COALESCE((SELECT SUM(amount) FROM entries e WHERE e.account_id = a.id), 0)"""
        )
        drift = c.fetchone()[0]
        c.execute(
            """SELECT COUNT(*) FROM transfers t WHERE t.status='posted'
               AND (SELECT COUNT(*) FROM entries e WHERE e.transfer_id=t.id) != 2"""
        )
        broken = c.fetchone()[0]
    conn.close()
    return {
        "entries_sum_to_zero": net_entries == 0,
        "negative_accounts": negative,
        "balance_drift_accounts": drift,
        "posted_without_two_entries": broken,
        "ok": net_entries == 0 and negative == 0 and drift == 0 and broken == 0,
    }
