from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from app.models import GroupMember, Settlement

from tests.conftest import make_group


@pytest.mark.asyncio
async def test_user_validation_and_group_membership(client):
    invalid = await client.post("/users", json={"name": "  "})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["message"] == "Request validation failed"
    group, users = await make_group(client, ("A", "B"))
    assert len((await client.get(f"/groups/{group['id']}/members")).json()) == 2
    assert (await client.post(f"/groups/{group['id']}/members", params={"user_id": users[0]["id"]})).status_code == 409


@pytest.mark.asyncio
async def test_equal_split_and_cent_rounding(client):
    group, users = await make_group(client)
    response = await client.post(f"/groups/{group['id']}/expenses", json={"paid_by": users[0]["id"], "amount": "10.00", "description": "Dinner"})
    assert response.status_code == 201
    assert [s["owed_amount"] for s in response.json()["splits"]] == ["3.34", "3.33", "3.33"]
    assert (await client.post(f"/groups/{group['id']}/expenses", json={"paid_by": users[0]["id"], "amount": "0", "description": "bad"})).status_code == 422
    assert (await client.post(f"/groups/{group['id']}/expenses", json={"paid_by": 999, "amount": "5", "description": "bad"})).status_code == 400


@pytest.mark.asyncio
async def test_balances_settlement_and_smart_suggestions(client):
    group, users = await make_group(client)
    # Rahul covers 1200 equally: Rahul owes nothing net and the other two owe 400 each.
    result = await client.post(f"/groups/{group['id']}/expenses", json={"paid_by": users[0]["id"], "amount": "1200.00", "description": "Dinner"})
    assert result.status_code == 201
    balances = (await client.get(f"/groups/{group['id']}/balances")).json()
    assert sum(Decimal(m["net_balance"]) for m in balances["members"]) == 0
    assert sorted(s["amount"] for s in (await client.get(f"/groups/{group['id']}/settlement-suggestions")).json()["suggestions"]) == ["400.00", "400.00"]
    settlement = await client.post(f"/groups/{group['id']}/settlements", json={"paid_by": users[1]["id"], "paid_to": users[0]["id"], "amount": "400.00"})
    assert settlement.status_code == 201
    overpayment = await client.post(f"/groups/{group['id']}/settlements", json={"paid_by": users[1]["id"], "paid_to": users[0]["id"], "amount": "0.01"})
    assert overpayment.status_code == 400
    updated = (await client.get(f"/groups/{group['id']}/balances")).json()
    assert len(updated["debts"]) == 1 and updated["debts"][0]["debtor_id"] == users[2]["id"]


@pytest.mark.asyncio
async def test_balances_net_multiple_expenses_and_payers(client):
    group, users = await make_group(client, ("A", "B", "C", "D"))
    for payer, amount in ((users[0], "12.00"), (users[1], "8.00")):
        response = await client.post(f"/groups/{group['id']}/expenses", json={"paid_by": payer["id"], "amount": amount, "description": "Shared"})
        assert response.status_code == 201
    balances = (await client.get(f"/groups/{group['id']}/balances")).json()
    assert {entry["user_id"]: entry["net_balance"] for entry in balances["members"]} == {
        users[0]["id"]: "7.00", users[1]["id"]: "3.00", users[2]["id"]: "-5.00", users[3]["id"]: "-5.00"
    }
    suggestions = (await client.get(f"/groups/{group['id']}/settlement-suggestions")).json()["suggestions"]
    assert sum((Decimal(item["amount"]) for item in suggestions), Decimal("0.00")) == Decimal("10.00")
    assert all(item["paid_by"] != item["paid_to"] for item in suggestions)


@pytest.mark.asyncio
async def test_sqlite_test_database_enforces_foreign_keys(client):
    sessions = client.test_sessionmaker
    async with sessions() as session:
        session.add(GroupMember(group_id=99999, user_id=99999))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_database_rejects_nonpositive_settlement_amount(client):
    group, users = await make_group(client, ("A", "B"))
    async with client.test_sessionmaker() as session:
        session.add(Settlement(group_id=group["id"], paid_by=users[0]["id"], paid_to=users[1]["id"], amount=Decimal("0.00")))
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_single_member_and_history_blocks_removal(client):
    group, users = await make_group(client, ("Solo",))
    created = await client.post(f"/groups/{group['id']}/expenses", json={"paid_by": users[0]["id"], "amount": "5.01", "description": "Coffee"})
    assert created.status_code == 201
    assert (await client.get(f"/groups/{group['id']}/balances")).json()["debts"] == []
    assert (await client.delete(f"/groups/{group['id']}/members/{users[0]['id']}")).status_code == 400


@pytest.mark.asyncio
async def test_nonexistent_group_and_pagination(client):
    assert (await client.get("/groups/777/expenses")).status_code == 404
    assert (await client.post("/groups/777/expenses", json={"paid_by": 1, "amount": "1", "description": "x"})).status_code == 404
    group, users = await make_group(client, ("A",))
    await client.post(f"/groups/{group['id']}/expenses", json={"paid_by": users[0]["id"], "amount": "1", "description": "x"})
    page = (await client.get(f"/groups/{group['id']}/expenses?limit=1&offset=0")).json()
    assert len(page["items"]) == 1


@pytest.mark.asyncio
async def test_empty_group_rejects_expense_and_user_listing(client):
    user = await client.post("/users", json={"name": "A"})
    assert user.status_code == 201
    assert len((await client.get("/users")).json()) == 1
    group = await client.post("/groups", json={"name": "Empty"})
    assert group.status_code == 201
    result = await client.post(f"/groups/{group.json()['id']}/expenses", json={"paid_by": user.json()["id"], "amount": "2.00", "description": "No members"})
    assert result.status_code == 400


@pytest.mark.asyncio
async def test_fully_settled_balances_have_no_suggestions(client):
    group, users = await make_group(client)
    await client.post(f"/groups/{group['id']}/expenses", json={"paid_by": users[0]["id"], "amount": "12.00", "description": "Shared"})
    for debtor in users[1:]:
        settlement = await client.post(f"/groups/{group['id']}/settlements", json={"paid_by": debtor["id"], "paid_to": users[0]["id"], "amount": "4.00"})
        assert settlement.status_code == 201
    balances = (await client.get(f"/groups/{group['id']}/balances")).json()
    assert all(item["net_balance"] == "0.00" for item in balances["members"])
    assert (await client.get(f"/groups/{group['id']}/settlement-suggestions")).json()["suggestions"] == []
