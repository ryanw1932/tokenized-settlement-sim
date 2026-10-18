# Tokenized Deposit Settlement Simulator

A PostgreSQL double-entry ledger with a FastAPI front end, plus a simulator that compares
**instant (real-time gross)** settlement against **batch (periodic net)** settlement between banks.

## Guarantees (and how each is enforced)

| Guarantee | Mechanism | Test |
|---|---|---|
| Atomic transfers | One transaction posts both ledger entries and both balance updates | `test_transfer_moves_money_and_balances_ledger` |
| Idempotent retries | `UNIQUE(idem_key)` + `ON CONFLICT DO NOTHING`; replay returns the original result | `test_idempotent_replay_posts_once`, `test_concurrent_replays_of_one_key_post_once` |
| No overdrafts | Balance checked under `SELECT ... FOR UPDATE` row locks, plus `CHECK (balance >= 0)` | `test_overdraft_pressure_never_goes_negative` |
| No deadlocks | Both accounts locked first, in ascending id order | `test_opposing_transfers_do_not_deadlock` |
| Ledger always balances | `/invariants` checks entries sum to zero, balances match entries, every posted transfer has 2 entries | all concurrency tests |

> Design note: locking must happen *before* inserting into `transfers`. The foreign keys make that
> insert take row locks on the accounts, so inserting first breaks lock ordering and deadlocks under load.

## Run it

```bash
docker compose up --build            # API on :8000, Postgres on :5432
curl -X POST localhost:8000/admin/reset
curl -X POST localhost:8000/transfers -H 'Idempotency-Key: abc' \
     -H 'Content-Type: application/json' -d '{"src":0,"dst":1,"amount":500}'
curl localhost:8000/invariants
```

Without Docker: start Postgres, `export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ledger`,
then `pip install -r requirements.txt && pytest -q`.

## Experiments

```bash
python simulate.py   # instant vs batch: settlement lag vs value actually moved
python bench.py      # throughput and latency at 1, 10, 50 concurrent workers
```

Record your own results here after running on your machine:

| Workers | Transfers/sec | p95 latency | Invariants |
|---|---|---|---|
| 1 | | | |
| 10 | | | |
| 50 | | | |

Expect throughput to fall and p95 to rise as workers increase: with only 6 accounts, transfers queue on hot row locks.
