# Tokenized Deposit Settlement Simulator

[![ci](https://github.com/ryanw1932/tokenized-settlement-sim/actions/workflows/ci.yml/badge.svg)](https://github.com/ryanw1932/tokenized-settlement-sim/actions/workflows/ci.yml)

A PostgreSQL double-entry ledger with a FastAPI front end, plus a simulator that compares
**instant (real-time gross)** settlement against **batch (periodic net)** settlement between banks.
This is a simulation with synthetic transfers, not a production system.

## Guarantees (and how each is enforced)

| Guarantee | Mechanism | Test |
|---|---|---|
| Atomic transfers | One transaction posts both ledger entries and both balance updates | `test_transfer_moves_money_and_balances_ledger` |
| Idempotent retries | `UNIQUE(idem_key)` + `ON CONFLICT DO NOTHING`; a replay returns the original result | `test_idempotent_replay_posts_once`, `test_concurrent_replays_of_one_key_post_once` |
| No overdrafts | Balance checked under `SELECT ... FOR UPDATE` row locks, plus `CHECK (balance >= 0)` | `test_overdraft_pressure_never_goes_negative` |
| No deadlocks | Both accounts are locked first, in ascending id order | `test_opposing_transfers_do_not_deadlock` |
| Ledger always balances | `/invariants` checks that entries sum to zero, balances match entries, and every posted transfer has two entries | all concurrency tests |

> **Design note:** locking must happen *before* inserting into `transfers`. The foreign keys make that
> insert take row locks on the accounts, so inserting first breaks the lock ordering and deadlocks under load.

## API

| Method | Path | Behavior |
|---|---|---|
| POST | `/transfers` | Requires an `Idempotency-Key` header. `201` on first post, `200` on replay, `409` on insufficient funds, `404` for an unknown account, `422` for invalid input |
| GET | `/accounts` | Current balances |
| GET | `/invariants` | Ledger consistency checks |
| POST | `/admin/reset` | Reset all accounts (simulation only) |

## Run it

```bash
docker compose up --build            # API on :8000, Postgres on :5432
```

Then, from another terminal (PowerShell shown):

```powershell
curl.exe -X POST http://localhost:8000/admin/reset
Invoke-RestMethod -Method Post -Uri http://localhost:8000/transfers `
  -Headers @{"Idempotency-Key"="abc"} -ContentType "application/json" `
  -Body '{"src":0,"dst":1,"amount":500}'
Invoke-RestMethod http://localhost:8000/invariants
```

Run the tests (with the compose `db` service running):

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ledger   # PowerShell: $env:DATABASE_URL = "..."
pip install -r requirements.txt
python -m pytest -q
```

## Experiments

```bash
python simulate.py   # instant vs batch settlement
python bench.py      # throughput and latency at 1, 10, and 50 concurrent workers
```

### Instant vs batch settlement

Seeded workload (seed 42): 2,000 transfers across 6 banks over a simulated hour, with 15-minute batches.

| Mode | Mean settlement lag | Value moved | Invariants |
|---|---|---|---|
| Instant (gross) | 0 s | 5,080,112 | OK |
| Batch (net) | 451.8 s | 816,578 (~16% of gross) | OK |

Netting reduces the value that has to move between banks by roughly 84% in this workload,
at the cost of a mean settlement delay of about 7.5 minutes.

### Concurrency benchmark

Measured on Docker Desktop for Windows, PostgreSQL 16, 6 accounts, 2,000 transfers per run.

| Workers | Transfers/sec | p95 latency | Invariants |
|---|---|---|---|
| 1 | 299 | 3.8 ms | OK |
| 10 | 60 | 304.1 ms | OK |
| 50 | 53 | 1197.0 ms | OK |

Throughput falls as concurrency rises. With only six accounts, transfers likely queue on hot row
locks, though I have not profiled beyond that. Docker networking on Windows adds latency to each
round trip too. Ledger invariants held at every concurrency level.
