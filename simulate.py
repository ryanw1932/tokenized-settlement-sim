"""Compare instant (real-time gross) vs batch (periodic net) settlement on the same workload.

Time is simulated: transfers arrive uniformly over a window; in batch mode each transfer waits
for the next batch boundary, then each bank pair is netted into at most one posted transfer.
"""
import argparse, random, statistics, uuid
from collections import defaultdict
from app import ledger


def workload(n, banks, window_s, seed):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        s, d = rng.sample(range(banks), 2)
        out.append((rng.uniform(0, window_s), s, d, rng.randint(1, 5000)))
    return sorted(out)


def run(mode, n, banks, window_s, interval_s, seed):
    ledger.reset(banks)
    wl = workload(n, banks, window_s, seed)
    lags, gross, moved = [], sum(a for *_, a in wl), 0
    if mode == "instant":
        for _, s, d, a in wl:
            ledger.transfer(s, d, a, str(uuid.uuid4()))
            lags.append(0.0)
        moved = gross
    else:
        batches = defaultdict(list)
        for t, s, d, a in wl:
            boundary = (int(t // interval_s) + 1) * interval_s
            lags.append(boundary - t)
            batches[boundary].append((s, d, a))
        for boundary in sorted(batches):
            net = defaultdict(int)
            for s, d, a in batches[boundary]:
                lo, hi = min(s, d), max(s, d)
                net[(lo, hi)] += a if s == lo else -a
            for (lo, hi), v in net.items():
                if v == 0:
                    continue
                s, d = (lo, hi) if v > 0 else (hi, lo)
                ledger.transfer(s, d, abs(v), str(uuid.uuid4()))
                moved += abs(v)
    inv = ledger.invariants()
    return {"mode": mode, "mean_lag_s": statistics.mean(lags), "max_lag_s": max(lags),
            "gross_value": gross, "value_moved": moved, "invariants_ok": inv["ok"]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--banks", type=int, default=6)
    ap.add_argument("--window", type=float, default=3600, help="simulated seconds of arrivals")
    ap.add_argument("--interval", type=float, default=900, help="batch interval (simulated s)")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    for mode in ("instant", "batch"):
        r = run(mode, a.n, a.banks, a.window, a.interval, a.seed)
        print(f"{r['mode']:8s} mean_lag={r['mean_lag_s']:7.1f}s max_lag={r['max_lag_s']:7.1f}s "
              f"gross={r['gross_value']} moved={r['value_moved']} invariants_ok={r['invariants_ok']}")
