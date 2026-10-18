import pytest
from fastapi.testclient import TestClient
from app import ledger
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh():
    ledger.reset(6)


def post(key, src=0, dst=1, amount=100):
    return client.post("/transfers", json={"src": src, "dst": dst, "amount": amount},
                       headers={"Idempotency-Key": key})


def test_create_transfer_201_then_replay_200():
    assert post("k").status_code == 201
    r = post("k")
    assert r.status_code == 200 and r.json()["duplicate"] is True


def test_missing_idempotency_key_is_422():
    r = client.post("/transfers", json={"src": 0, "dst": 1, "amount": 5})
    assert r.status_code == 422


def test_insufficient_funds_is_409():
    assert post("big", amount=ledger.OPENING_BALANCE + 1).status_code == 409


def test_unknown_account_is_404_and_self_transfer_is_422():
    assert post("g", dst=99).status_code == 404
    assert post("s", src=2, dst=2).status_code == 422


def test_invariants_endpoint_reports_ok_after_activity():
    post("a"); post("b", src=2, dst=3)
    assert client.get("/invariants").json()["ok"] is True
