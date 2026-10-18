import random, threading, uuid
import pytest
from app import ledger


@pytest.fixture(autouse=True)
def fresh():
    ledger.reset(6)


def run_workers(workers, per, banks=6, amount=lambda: random.randint(1, 5000)):
    results, lock = [], threading.Lock()

    def w():
        for _ in range(per):
            s, d = random.sample(range(banks), 2)
            r = ledger.transfer(s, d, amount(), str(uuid.uuid4()))
            with lock:
                results.append(r["status"])

    ts = [threading.Thread(target=w) for _ in range(workers)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    return results


def test_transfer_moves_money_and_balances_ledger():
    r = ledger.transfer(0, 1, 500, "k1")
    assert r["status"] == "posted" and not r["duplicate"]
    b = ledger.balances()
    assert b[0]["balance"] == ledger.OPENING_BALANCE - 500
    assert b[1]["balance"] == ledger.OPENING_BALANCE + 500
    assert ledger.invariants()["ok"]


def test_idempotent_replay_posts_once():
    first = ledger.transfer(0, 1, 500, "same")
    again = ledger.transfer(0, 1, 500, "same")
    assert again["duplicate"] and again["transfer_id"] == first["transfer_id"]
    assert ledger.balances()[0]["balance"] == ledger.OPENING_BALANCE - 500


def test_concurrent_replays_of_one_key_post_once():
    out, lock = [], threading.Lock()

    def go():
        r = ledger.transfer(0, 1, 100, "race")
        with lock:
            out.append(r)

    ts = [threading.Thread(target=go) for _ in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sum(1 for r in out if not r["duplicate"]) == 1
    assert ledger.balances()[0]["balance"] == ledger.OPENING_BALANCE - 100


def test_insufficient_funds_rejected_and_leaves_balances_alone():
    r = ledger.transfer(0, 1, ledger.OPENING_BALANCE + 1, "big")
    assert r["status"] == "rejected"
    assert ledger.balances()[0]["balance"] == ledger.OPENING_BALANCE
    assert ledger.invariants()["ok"]


def test_rejects_self_transfer_and_nonpositive_amount():
    with pytest.raises(ValueError):
        ledger.transfer(1, 1, 10, "self")
    with pytest.raises(ValueError):
        ledger.transfer(0, 1, 0, "zero")


def test_unknown_account():
    with pytest.raises(LookupError):
        ledger.transfer(0, 99, 10, "ghost")


def test_50_threads_2000_transfers_hold_invariants():
    run_workers(50, 40)
    assert ledger.invariants()["ok"]


def test_overdraft_pressure_never_goes_negative():
    ledger.reset(6, opening=10_000)
    res = run_workers(50, 40, amount=lambda: 900)
    inv = ledger.invariants()
    assert inv["negative_accounts"] == 0 and inv["ok"]
    assert "rejected" in res  # contention actually triggered rejections


def test_opposing_transfers_do_not_deadlock():
    done = []

    def ab(src, dst, tag):
        for i in range(200):
            ledger.transfer(src, dst, 1, f"{tag}{i}")
        done.append(tag)

    ts = [threading.Thread(target=ab, args=(0, 1, "a")), threading.Thread(target=ab, args=(1, 0, "b"))]
    [t.start() for t in ts]
    [t.join(timeout=30) for t in ts]
    assert sorted(done) == ["a", "b"] and ledger.invariants()["ok"]
