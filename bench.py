"""Load test the transfer function under N concurrent workers. Run it yourself and quote its output."""
import random, statistics, threading, time, uuid
from app import ledger


def bench(workers, per):
    ledger.reset(6)
    lat, lock = [], threading.Lock()

    def w():
        mine = []
        for _ in range(per):
            s, d = random.sample(range(6), 2)
            t = time.perf_counter()
            ledger.transfer(s, d, random.randint(1, 1000), str(uuid.uuid4()))
            mine.append(time.perf_counter() - t)
        with lock:
            lat.extend(mine)

    ts = [threading.Thread(target=w) for _ in range(workers)]
    t0 = time.perf_counter()
    [t.start() for t in ts]
    [t.join() for t in ts]
    dt = time.perf_counter() - t0
    lat.sort()
    n = len(lat)
    print(f"workers={workers:3d} transfers={n:5d} {n/dt:7.0f}/s p50={lat[n//2]*1000:6.1f}ms "
          f"p95={lat[int(n*.95)]*1000:6.1f}ms invariants_ok={ledger.invariants()['ok']}")


if __name__ == "__main__":
    for w in (1, 10, 50):
        bench(w, 2000 // w)
