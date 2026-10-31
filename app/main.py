from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.core.database import Base, engine
from app.core.errors import AppError, app_error_handler, validation_error_handler
from app.models import Expense, ExpenseSplit, Group, GroupMember, Settlement, User
from app.api.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Compose waits for PostgreSQL; migrations are the canonical schema setup.
    yield


app = FastAPI(title="Decentro Expense Sharing Service", version="1.0.0", lifespan=lifespan)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
