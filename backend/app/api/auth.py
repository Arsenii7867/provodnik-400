from fastapi import APIRouter, Request
from sqlalchemy import select

from app import auth, clock, ratelimit
from app.auth import Credentials, CurrentEmployee, employee_view
from app.db import Db
from app.errors import ApiError
from app.models import Employee
from app.schemas import DemoAccount, EmployeeOut, LoginRequest, LoginResponse, OkResponse
from app.seed import DEMO_ACCOUNTS
from app.services import action_log

router = APIRouter(prefix="/api/auth", tags=["Авторизация"])


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", summary="Вход по коду сотрудника и PIN", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Db):
    settings = request.app.state.settings
    address = client_address(request)
    now = clock.now()
    ratelimit.check(address, now, settings.login_rate_per_minute)
    employee = db.scalar(select(Employee).where(Employee.code == body.employee_code))
    if employee is None or not auth.verify_pin(employee, body.pin):
        # один ответ для неизвестного кода и неверного PIN: существование кода не раскрывается
        ratelimit.register_failure(address, now)
        raise ApiError(401, "pin_invalid", "Неверный код сотрудника или PIN")
    token, expires_at = auth.issue_token(db, employee, now, settings.token_ttl_hours)
    action_log.log(db, employee.id, "login", "employee", employee.code, {}, now)
    db.commit()
    return {"token": token, "expires_at": expires_at.isoformat(), "employee": employee_view(employee)}


@router.post("/logout", summary="Выход: токен отзывается", response_model=OkResponse)
def logout(credentials: Credentials, employee: CurrentEmployee, db: Db):
    auth.revoke_token(db, credentials.credentials)
    action_log.log(db, employee.id, "logout", "employee", employee.code, {}, clock.now())
    db.commit()
    return {"ok": True}


@router.get("/me", summary="Текущий сотрудник по токену", response_model=EmployeeOut)
def me(employee: CurrentEmployee):
    return employee_view(employee)


@router.get("/demo", summary="Демо-профили для экрана входа", response_model=list[DemoAccount])
def demo(request: Request, db: Db):
    if request.app.state.settings.app_env == "prod":
        return []
    notes = {account["code"]: account["note"] for account in DEMO_ACCOUNTS}
    rows = db.scalars(select(Employee).where(Employee.code.in_(list(notes))).order_by(Employee.code)).all()
    return [employee_view(employee) | {"note": notes[employee.code]} for employee in rows]
