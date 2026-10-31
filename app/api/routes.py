from fastapi import APIRouter, Body, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import AppError
from app.models import GroupMember
from app.schemas.api import (BalancesOut, ExpenseCreate, ExpenseOut, ExpensePage, GroupCreate, GroupOut, MemberCreate,
                             MemberOut, SettlementCreate, SettlementOut, SuggestionsOut, UserCreate, UserOut)
from app.services import ledger

router = APIRouter()


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def post_user(data: UserCreate, session: AsyncSession = Depends(get_session)):
    return await ledger.create_user(session, data)


@router.get("/users", response_model=list[UserOut])
async def get_users(session: AsyncSession = Depends(get_session)):
    return await ledger.list_users(session)


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: int, session: AsyncSession = Depends(get_session)):
    return await ledger.get_user(session, user_id)


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def post_group(data: GroupCreate, session: AsyncSession = Depends(get_session)):
    return await ledger.create_group(session, data)


@router.get("/groups", response_model=list[GroupOut])
async def get_groups(session: AsyncSession = Depends(get_session)):
    return await ledger.list_groups(session)


@router.post("/groups/{group_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def post_member(group_id: int, data: MemberCreate | None = Body(default=None), user_id: int | None = Query(default=None, gt=0), session: AsyncSession = Depends(get_session)):
    user_id = data.user_id if data else user_id
    if user_id is None:
        raise AppError(422, "Provide user_id in the request body")
    member = await ledger.add_member(session, group_id, user_id)
    await session.refresh(member, attribute_names=["user"])
    return {"id": member.user.id, "name": member.user.name, "joined_at": member.joined_at}


@router.get("/groups/{group_id}/members", response_model=list[MemberOut])
async def get_members(group_id: int, session: AsyncSession = Depends(get_session)):
    members = await ledger.list_members(session, group_id)
    return [{"id": m.user.id, "name": m.user.name, "joined_at": m.joined_at} for m in members]


@router.delete("/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_member(group_id: int, user_id: int, session: AsyncSession = Depends(get_session)):
    await ledger.remove_member(session, group_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/groups/{group_id}/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
async def post_expense(group_id: int, data: ExpenseCreate, session: AsyncSession = Depends(get_session)):
    return await ledger.expense_to_dict(await ledger.create_expense(session, group_id, data))


@router.get("/groups/{group_id}/expenses", response_model=ExpensePage)
async def get_expenses(group_id: int, limit: int = Query(default=50, ge=1, le=100), offset: int = Query(default=0, ge=0), session: AsyncSession = Depends(get_session)):
    expenses = await ledger.list_expenses(session, group_id, limit, offset)
    return {"items": [await ledger.expense_to_dict(e) for e in expenses], "limit": limit, "offset": offset}


@router.get("/expenses/{expense_id}", response_model=ExpenseOut)
async def get_expense(expense_id: int, session: AsyncSession = Depends(get_session)):
    return await ledger.expense_to_dict(await ledger.get_expense(session, expense_id))


@router.get("/groups/{group_id}/balances", response_model=BalancesOut)
async def get_balances(group_id: int, session: AsyncSession = Depends(get_session)):
    members, debts = await ledger.calculate_balances(session, group_id)
    return {"group_id": group_id, "members": members, "debts": debts}


@router.get("/groups/{group_id}/settlement-suggestions", response_model=SuggestionsOut)
async def get_suggestions(group_id: int, session: AsyncSession = Depends(get_session)):
    return {"group_id": group_id, "suggestions": await ledger.settlement_suggestions(session, group_id)}


@router.post("/groups/{group_id}/settlements", response_model=SettlementOut, status_code=status.HTTP_201_CREATED)
async def post_settlement(group_id: int, data: SettlementCreate, session: AsyncSession = Depends(get_session)):
    return await ledger.create_settlement(session, group_id, data)
