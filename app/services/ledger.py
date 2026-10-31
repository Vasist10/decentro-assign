from decimal import Decimal, ROUND_DOWN

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models import Expense, ExpenseSplit, Group, GroupMember, Settlement, User
from app.schemas.api import ExpenseCreate, GroupCreate, SettlementCreate, UserCreate

CENT = Decimal("0.01")


async def require_group(session: AsyncSession, group_id: int) -> Group:
    group = await session.get(Group, group_id)
    if not group:
        raise AppError(404, "Group not found")
    return group


async def lock_group(session: AsyncSession, group_id: int) -> Group:
    """Lock the group row to serialize membership and ledger writes on PostgreSQL."""
    group = await session.scalar(select(Group).where(Group.id == group_id).with_for_update())
    if not group:
        raise AppError(404, "Group not found")
    return group


async def create_user(session: AsyncSession, data: UserCreate) -> User:
    user = User(name=data.name)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.id))).all())


async def get_user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if not user:
        raise AppError(404, "User not found")
    return user


async def create_group(session: AsyncSession, data: GroupCreate) -> Group:
    group = Group(name=data.name)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group


async def list_groups(session: AsyncSession) -> list[Group]:
    return list((await session.scalars(select(Group).order_by(Group.id))).all())


async def add_member(session: AsyncSession, group_id: int, user_id: int) -> GroupMember:
    await lock_group(session, group_id)
    await get_user(session, user_id)
    existing = await session.scalar(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id))
    if existing:
        raise AppError(409, "User is already a member of this group")
    member = GroupMember(group_id=group_id, user_id=user_id)
    session.add(member)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(409, "User is already a member of this group") from exc
    await session.refresh(member)
    return member


async def list_members(session: AsyncSession, group_id: int) -> list[GroupMember]:
    await require_group(session, group_id)
    return list((await session.scalars(select(GroupMember).options(selectinload(GroupMember.user)).where(GroupMember.group_id == group_id).order_by(GroupMember.user_id))).all())


async def remove_member(session: AsyncSession, group_id: int, user_id: int) -> None:
    await lock_group(session, group_id)
    member = await session.scalar(select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id))
    if not member:
        raise AppError(404, "Group member not found")
    expense_link = await session.scalar(select(Expense.id).outerjoin(ExpenseSplit).where(Expense.group_id == group_id, (Expense.paid_by == user_id) | (ExpenseSplit.user_id == user_id)).limit(1))
    settlement_link = await session.scalar(select(Settlement.id).where(Settlement.group_id == group_id, (Settlement.paid_by == user_id) | (Settlement.paid_to == user_id)).limit(1))
    if expense_link or settlement_link:
        raise AppError(400, "Cannot remove a member referenced by historical expenses or settlements")
    await session.delete(member)
    await session.commit()


async def create_expense(session: AsyncSession, group_id: int, data: ExpenseCreate) -> Expense:
    await lock_group(session, group_id)
    members = list((await session.scalars(select(GroupMember).where(GroupMember.group_id == group_id).order_by(GroupMember.user_id))).all())
    if not members:
        raise AppError(400, "Cannot add an expense to a group with no members")
    member_ids = [m.user_id for m in members]
    if data.paid_by not in member_ids:
        raise AppError(400, "Expense payer must be a member of the group")
    amount = data.amount.quantize(CENT)
    base = (amount / len(member_ids)).quantize(CENT, rounding=ROUND_DOWN)
    remainder = int((amount - base * len(member_ids)) / CENT)
    shares = [base + (CENT if i < remainder else Decimal("0.00")) for i in range(len(member_ids))]
    expense = Expense(group_id=group_id, paid_by=data.paid_by, amount=amount, description=data.description, category=data.category)
    expense.splits = [ExpenseSplit(user_id=user_id, owed_amount=share) for user_id, share in zip(member_ids, shares)]
    session.add(expense)
    await session.commit()
    return await get_expense(session, expense.id)


async def expense_to_dict(expense: Expense) -> dict:
    return {"id": expense.id, "group_id": expense.group_id, "paid_by": expense.paid_by, "payer_name": expense.payer.name,
            "amount": expense.amount, "description": expense.description, "category": expense.category,
            "created_at": expense.created_at,
            "splits": [{"user_id": split.user_id, "user_name": split.user.name, "owed_amount": split.owed_amount} for split in expense.splits]}


async def get_expense(session: AsyncSession, expense_id: int) -> Expense:
    stmt = select(Expense).options(selectinload(Expense.payer), selectinload(Expense.splits).selectinload(ExpenseSplit.user)).where(Expense.id == expense_id)
    expense = await session.scalar(stmt)
    if not expense:
        raise AppError(404, "Expense not found")
    return expense


async def list_expenses(session: AsyncSession, group_id: int, limit: int, offset: int) -> list[Expense]:
    await require_group(session, group_id)
    stmt = select(Expense).options(selectinload(Expense.payer), selectinload(Expense.splits).selectinload(ExpenseSplit.user)).where(Expense.group_id == group_id).order_by(Expense.created_at.desc(), Expense.id.desc()).limit(limit).offset(offset)
    return list((await session.scalars(stmt)).all())


async def calculate_balances(session: AsyncSession, group_id: int) -> tuple[list[dict], list[dict]]:
    await require_group(session, group_id)
    members = await list_members(session, group_id)
    balances = {m.user_id: Decimal("0.00") for m in members}
    names = {m.user_id: m.user.name for m in members}
    expenses = await session.scalars(select(Expense).options(selectinload(Expense.splits)).where(Expense.group_id == group_id))
    for expense in expenses:
        balances[expense.paid_by] += expense.amount
        for split in expense.splits:
            balances[split.user_id] -= split.owed_amount
    settlements = await session.scalars(select(Settlement).where(Settlement.group_id == group_id))
    for settlement in settlements:
        balances[settlement.paid_by] += settlement.amount
        balances[settlement.paid_to] -= settlement.amount
    balances = {user_id: amount.quantize(CENT) for user_id, amount in balances.items()}
    if sum(balances.values(), Decimal("0.00")) != Decimal("0.00"):
        raise AppError(500, "Ledger is unbalanced")
    debtors = [[uid, -amount] for uid, amount in balances.items() if amount < 0]
    creditors = [[uid, amount] for uid, amount in balances.items() if amount > 0]
    debts = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        transfer = min(debtors[i][1], creditors[j][1]).quantize(CENT)
        debts.append({"debtor_id": debtors[i][0], "debtor_name": names[debtors[i][0]], "creditor_id": creditors[j][0], "creditor_name": names[creditors[j][0]], "amount": transfer})
        debtors[i][1] -= transfer
        creditors[j][1] -= transfer
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    member_balances = [{"user_id": uid, "name": names[uid], "net_balance": value} for uid, value in balances.items()]
    return member_balances, debts


async def create_settlement(session: AsyncSession, group_id: int, data: SettlementCreate) -> Settlement:
    # The lock is shared with expense and membership writes, so validation sees
    # a stable ledger and member set through commit.
    await lock_group(session, group_id)
    if data.paid_by == data.paid_to:
        raise AppError(400, "Users cannot settle with themselves")
    members = {m.user_id for m in await list_members(session, group_id)}
    if data.paid_by not in members or data.paid_to not in members:
        raise AppError(400, "Both settlement participants must be group members")
    _, debts = await calculate_balances(session, group_id)
    owed = sum((d["amount"] for d in debts if d["debtor_id"] == data.paid_by and d["creditor_id"] == data.paid_to), Decimal("0.00"))
    amount = data.amount.quantize(CENT)
    if amount > owed:
        raise AppError(400, "Settlement exceeds the outstanding debt between these users")
    settlement = Settlement(group_id=group_id, paid_by=data.paid_by, paid_to=data.paid_to, amount=amount)
    session.add(settlement)
    await session.commit()
    await session.refresh(settlement)
    return settlement


async def settlement_suggestions(session: AsyncSession, group_id: int) -> list[dict]:
    members, _ = await calculate_balances(session, group_id)
    names = {m["user_id"]: m["name"] for m in members}
    debtors = [[m["user_id"], -m["net_balance"]] for m in members if m["net_balance"] < 0]
    creditors = [[m["user_id"], m["net_balance"]] for m in members if m["net_balance"] > 0]
    suggestions = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        amount = min(debtors[i][1], creditors[j][1]).quantize(CENT)
        if amount > 0:
            suggestions.append({"paid_by": debtors[i][0], "payer_name": names[debtors[i][0]], "paid_to": creditors[j][0], "receiver_name": names[creditors[j][0]], "amount": amount})
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    return suggestions
