"""
Reporting API — бэкенд для витрины ClickHouse.
Безопасность: JWT-валидация через Keycloak JWKS, RBAC по user_id.
"""

import os
from datetime import date, datetime, timedelta
from typing import List, Optional

import httpx
from clickhouse_connect import create_client
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi import FastAPI, Header, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from jose import jwk, jwt
from jose import constants
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------
CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "reports-realm")

JWKS_URL = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs"

# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------
app = FastAPI(title="Reporting API")

# CORS — разрешаем запросы с фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Кэш JWKS ключей
# ---------------------------------------------------------------------------
_jwks_cache: Optional[dict] = None
_jwks_expiry: Optional[datetime] = None


async def _get_jwks_keys() -> dict:
    """Загружает публичные ключи JWKS из Keycloak с кэшированием на 1 час."""
    global _jwks_cache, _jwks_expiry
    now = datetime.utcnow()
    if _jwks_cache and _jwks_expiry and _jwks_expiry > now:
        return _jwks_cache

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(JWKS_URL)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_expiry = now + timedelta(hours=1)
        return _jwks_cache


def _jwk_to_pem(jwk_obj: dict) -> bytes:
    """Конвертирует JWK RSA ключ в PEM-формат."""
    import base64

    # Декодируем n и e из base64url
    n_bytes = base64.urlsafe_b64decode(jwk_obj["n"] + "==")
    e_bytes = base64.urlsafe_b64decode(jwk_obj["e"] + "==")

    # Конвертируем в int (big endian)
    n = int.from_bytes(n_bytes, byteorder="big")
    e = int.from_bytes(e_bytes, byteorder="big")

    # Создаём RSA публичный ключ через cryptography
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    public_numbers = RSAPublicNumbers(e, n)
    public_key = public_numbers.public_key()
    return public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo
    )


async def _verify_token(authorization: Optional[str]) -> dict:
    """
    Валидирует JWT-токен из заголовка Authorization.
    Возвращает decoded claims.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header is missing")

    parts = authorization.split()
    if len(parts) != 2 or parts[0] != "Bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header format")

    token = parts[1]

    try:
        # Декодируем заголовок без проверки, чтобы получить kid
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        algorithm = unverified_header.get("alg", "RS256")

        # Получаем JWKS ключи
        jwks = await _get_jwks_keys()
        
        # Находим ключ по kid
        keys = jwks.get("keys", [])
        target_jwk = None
        for key in keys:
            if kid and key.get("kid") == kid:
                target_jwk = key
                break
        if not target_jwk and keys:
            target_jwk = keys[0]

        if not target_jwk:
            raise HTTPException(status_code=401, detail="Unable to find public key for token")

        # Конвертируем JWK в PEM
        pem_key = _jwk_to_pem(target_jwk)

        # Валидируем токен
        decoded = jwt.decode(
            token,
            pem_key,
            algorithms=[algorithm],
            # issuer не валидируем, так как Keycloak использует http://localhost:8080
            # а API внутри Docker использует http://keycloak:8080
            # required_claims=["sub"],
        )
        return decoded

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Token validation failed: {str(e)}")


# ---------------------------------------------------------------------------
# Pydantic модели
# ---------------------------------------------------------------------------
class ReportRecord(BaseModel):
    user_id: str
    user_name: str
    contract_number: str
    prosthetic_id: str
    report_date: date
    total_steps: int
    active_time_seconds: int
    battery_drain_avg: float
    load_level_max: float
    created_at: datetime


class ReportResponse(BaseModel):
    records: List[ReportRecord]
    warning: Optional[str] = None


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------
@app.get("/health")
async def health_check():
    """Простой health-check эндпоинт."""
    return {"status": "ok"}


@app.get("/reports", response_model=ReportResponse)
async def get_reports(
    response: Response,
    date_from: Optional[date] = Query(None, description="Начальная дата периода (включительно)"),
    date_to: Optional[date] = Query(None, description="Конечная дата периода (включительно)"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """
    Получение отчётов по нагрузке на протезы.
    
    Безопасность:
    - Требуется JWT-токен в заголовке Authorization: Bearer <token>
    - Данные фильтруются строго по user_id из токена (RBAC)
    
    Валидация периода:
    - Запрос date_to >= сегодня возвращает предупреждение
    - Доступны только исторические данные (до вчерашнего дня включительно)
    """
    # 1. Валидация токена и извлечение user_id
    claims = await _verify_token(authorization)
    user_id = claims.get("preferred_username") or claims.get("sub")
    
    if not user_id:
        raise HTTPException(status_code=401, detail="Unable to extract user identity from token")

    # 2. Валидация и предупреждение о незакрытом периоде
    today = date.today()
    yesterday = today - timedelta(days=1)
    warning = None

    # Определяем максимальную доступную дату (вчера)
    max_available_date = yesterday

    # 3. Формирование запроса к ClickHouse (используем %(name)s для clickhouse-connect)
    query_parts = [
        "SELECT * FROM prosthetic_reports_mart",
        "WHERE user_id = %(user_id)s",
        "AND report_date <= %(max_date)s",
    ]
    query_params = {
        "user_id": user_id,
        "max_date": max_available_date,
    }

    # Добавляем фильтрацию по периоду если указан
    if date_from:
        query_parts.append("AND report_date >= %(date_from)s")
        query_params["date_from"] = date_from

    # Если date_to указан и >= сегодня — добавляем предупреждение
    if date_to:
        if date_to >= today:
            warning = (
                "Данные за текущий или незакрытый период ещё не рассчитаны Airflow. "
                "Доступны отчеты только до вчерашнего дня включительно."
            )
            # Корректируем date_to до вчерашнего дня
            query_parts.append("AND report_date <= %(date_to)s")
            query_params["date_to"] = max_available_date
        else:
            query_parts.append("AND report_date <= %(date_to)s")
            query_params["date_to"] = date_to

    query_parts.append("ORDER BY report_date DESC")

    query = " ".join(query_parts)

    # 4. Выполнение запроса к ClickHouse
    try:
        client = create_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
        )
        result = client.query(query, parameters=query_params)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ClickHouse query error: {str(e)}")

    # 5. Формирование ответа
    records = []
    # column_names — атрибут QueryResult для названий колонок
    col_names = result.column_names
    for row in result.result_rows:
        record_dict = dict(zip(col_names, row))
        records.append(ReportRecord(**record_dict))

    return ReportResponse(records=records, warning=warning)