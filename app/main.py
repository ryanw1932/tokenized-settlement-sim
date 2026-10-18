from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field
from . import ledger

app = FastAPI(title="Tokenized Deposit Settlement Simulator")


class TransferIn(BaseModel):
    src: int
    dst: int
    amount: int = Field(gt=0)


@app.post("/transfers", status_code=201)
def create_transfer(body: TransferIn, response: Response, idempotency_key: str = Header(...)):
    if body.src == body.dst:
        raise HTTPException(422, "src and dst must differ")
    try:
        result = ledger.transfer(body.src, body.dst, body.amount, idempotency_key)
    except LookupError:
        raise HTTPException(404, "unknown account")
    if result["duplicate"]:
        response.status_code = 200
    elif result["status"] == "rejected":
        raise HTTPException(409, "insufficient funds")
    return result


@app.get("/accounts")
def accounts():
    return ledger.balances()


@app.get("/invariants")
def invariants():
    return ledger.invariants()


@app.post("/admin/reset")
def reset(n_banks: int = 6):
    ledger.reset(n_banks)
    return {"reset": True, "banks": n_banks}
