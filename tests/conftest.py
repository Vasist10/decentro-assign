import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base, get_session
from app.main import app


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    @event.listens_for(engine.sync_engine, "connect")
    def enable_sqlite_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as test_client:
        test_client.test_sessionmaker = sessions
        yield test_client
    app.dependency_overrides.clear()
    await engine.dispose()


async def make_group(client, names=("Rahul", "Ankit", "Mohit")):
    users = [(await client.post("/users", json={"name": name})).json() for name in names]
    group = (await client.post("/groups", json={"name": "Trip"})).json()
    for user in users:
        await client.post(f"/groups/{group['id']}/members", params={"user_id": user["id"]})
    return group, users
