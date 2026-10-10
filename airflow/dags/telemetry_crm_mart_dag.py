"""
DAG: Telemetry & CRM -> Analytics Mart (prosthetic_reports_mart)

Назначение:
  Ежедневный ETL-пайплайн для агрегации телеметрических данных
  из PostgreSQL и данных CRM в аналитическую витрину ClickHouse.

Источники:
  - PostgreSQL (telemetry): агрегаты датчиков протезов
  - CRM REST API: связки клиентов и протезов

Результат:
  - Запись денормализованных записей в ClickHouse (prosthetic_reports_mart)
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# ======================================================================
# Экспорт коннекторов (импортируются из airflow.providers)
# ======================================================================
from airflow.providers.clickhouse.hooks.clickhouse import ClickHouseHook
from airflow.providers.postgres.hooks.postgres import PostgresHook

# ======================================================================
# Параметры коннекторов (настраиваются в Airflow UI / airflow.cfg)
# ======================================================================
CLICKHOUSE_CONN_ID = "clickhouse_analytics"
POSTGRES_CONN_ID = "postgres_telemetry"
CRM_API_BASE_URL = "https://crm.bionicpro.internal/api/v1"
CRM_API_KEY = "{{ var.value crm_api_key }}"


# ======================================================================
# Задача 1: Извлечение агрегатов датчиков из PostgreSQL
# ======================================================================
def extract_telemetry(**context):
    """
    Извлекает агрегированные данные телеметрии за расчетные сутки
    из таблицы telemetry_daily_aggregates.

    Возвращает список словарей с полями:
        user_id, prosthetic_id, report_date,
        total_steps, active_time_seconds, battery_drain_avg, load_level_max
    """
    execution_date = context["execution_date"]
    target_date = execution_date.strftime("%Y-%m-%d")

    sql = """
        SELECT
            user_id,
            prosthetic_id,
            report_date,
            total_steps,
            active_time_seconds,
            battery_drain_avg,
            load_level_max
        FROM telemetry_daily_aggregates
        WHERE report_date = %(target_date)s
        ORDER BY user_id, prosthetic_id;
    """

    hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
    records = hook.get_records(sql, parameters={"target_date": target_date})

    column_names = [
        "user_id",
        "prosthetic_id",
        "report_date",
        "total_steps",
        "active_time_seconds",
        "battery_drain_avg",
        "load_level_max",
    ]

    telemetry_data = []
    for row in records:
        record = dict(zip(column_names, row))
        telemetry_data.append(record)

    # Передаём данные в следующий шаг через XCom
    ti = context["ti"]
    ti.xcom_push(key="telemetry_records", value=telemetry_data)

    print(f"[extract_telemetry] Извлечено {len(telemetry_data)} записей за {target_date}")
    return telemetry_data


# ======================================================================
# Задача 2: Извлечение связок клиентов и протезов из CRM (REST API)
# ======================================================================
def extract_crm(**context):
    """
    Запрашивает CRM REST API для получения списка клиентов
    и привязанных к ним протезов.

    Ожидаемый ответ API (JSON):
        [
            {
                "client_id": "c1",
                "client_name": "Иванов Иван Иванович",
                "contract_number": "CTR-2024-00142",
                "prostheses": [
                    {"prosthetic_id": "PRO-HIP-00742", "status": "active"}
                ]
            }
        ]

    Возвращает словарь: { prosthetic_id: { user_id, user_name, contract_number } }
    """
    import json
    import urllib.request
    import urllib.error

    url = f"{CRM_API_BASE_URL}/clients?include_prostheses=true"
    headers = {
        "Authorization": f"Bearer {CRM_API_KEY}",
        "Content-Type": "application/json",
    }

    request = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        raise RuntimeError(
            f"CRM API HTTP error {e.code}: {e.reason}. Body: {error_body}"
        )
    except Exception as e:
        raise RuntimeError(f"Ошибка запроса к CRM API: {e}")

    # Преобразуем плоский список клиентов в словарь по prosthetic_id
    crm_mapping = {}
    for client in data:
        client_id = client["client_id"]
        client_name = client["client_name"]
        contract_number = client["contract_number"]

        for prosthesis in client.get("prostheses", []):
            prosthetic_id = prosthesis["prosthetic_id"]
            crm_mapping[prosthetic_id] = {
                "user_id": client_id,
                "user_name": client_name,
                "contract_number": contract_number,
            }

    ti = context["ti"]
    ti.xcom_push(key="crm_mapping", value=crm_mapping)

    print(f"[extract_crm] Обработано {len(crm_mapping)} протезов из CRM")
    return crm_mapping


# ======================================================================
# Задача 3: Объединение данных в денормализованные записи
# ======================================================================
def transform_and_aggregate(**context):
    """
    Объединяет телеметрические данные с CRM-связками.

    На вход получает через XCom:
        - telemetry_records: список записей телеметрии
        - crm_mapping: словарь { prosthetic_id: crm_info }

    Возвращает список денормализованных записей для вставки в витрину:
        [
            {
                "user_id": ...,
                "user_name": ...,
                "contract_number": ...,
                "prosthetic_id": ...,
                "report_date": ...,
                "total_steps": ...,
                "active_time_seconds": ...,
                "battery_drain_avg": ...,
                "load_level_max": ...,
            },
            ...
        ]
    """
    ti = context["ti"]

    telemetry_records = ti.xcom_pull(task_ids="extract_telemetry", key="telemetry_records")
    crm_mapping = ti.xcom_pull(task_ids="extract_crm", key="crm_mapping")

    if not telemetry_records:
        print("[transform_and_aggregate] Нет телеметрических данных для обработки")
        ti.xcom_push(key="mart_records", value=[])
        return []

    mart_records = []
    for tel in telemetry_records:
        prosthetic_id = tel["prosthetic_id"]
        crm_info = crm_mapping.get(prosthetic_id)

        if crm_info is None:
            print(
                f"[transform_and_aggregate] Предупреждение: протез {prosthetic_id} "
                "не найден в CRM, запись пропущена"
            )
            continue

        record = {
            "user_id": tel["user_id"],
            "user_name": crm_info["user_name"],
            "contract_number": crm_info["contract_number"],
            "prosthetic_id": prosthetic_id,
            "report_date": tel["report_date"],
            "total_steps": tel["total_steps"],
            "active_time_seconds": tel["active_time_seconds"],
            "battery_drain_avg": tel["battery_drain_avg"],
            "load_level_max": tel["load_level_max"],
        }
        mart_records.append(record)

    ti.xcom_push(key="mart_records", value=mart_records)
    print(f"[transform_and_aggregate] Сформировано {len(mart_records)} записей для витрины")
    return mart_records


# ======================================================================
# Задача 4: Пакетная вставка в ClickHouse
# ======================================================================
def load_clickhouse(**context):
    """
    Выполняет пакетную вставку (Batch INSERT) денормализованных записей
    в таблицу prosthetic_reports_mart ClickHouse.

    Использует ClickHouseHook для подключения и execute() для INSERT.
    """
    ti = context["ti"]
    mart_records = ti.xcom_pull(task_ids="transform_and_aggregate", key="mart_records")

    if not mart_records:
        print("[load_clickhouse] Нет записей для загрузки")
        return

    clickhouse_hook = ClickHouseHook(clickhouse_conn_id=CLICKHOUSE_CONN_ID)
    conn = clickhouse_hook.get_conn()

    columns = [
        "user_id",
        "user_name",
        "contract_number",
        "prosthetic_id",
        "report_date",
        "total_steps",
        "active_time_seconds",
        "battery_drain_avg",
        "load_level_max",
        "created_at",
    ]

    values_template = (
        "%(user_id)s, %(user_name)s, %(contract_number)s, %(prosthetic_id)s, "
        "%(report_date)s, %(total_steps)s, %(active_time_seconds)s, "
        "%(battery_drain_avg)s, %(load_level_max)s, now()"
    )

    sql = f"INSERT INTO prosthetic_reports_mart ({', '.join(columns)}) VALUES {values_template}"

    # Форматируем записи для ClickHouse (убираем created_at из values_template, он по умолчанию)
    formatted_records = []
    for rec in mart_records:
        formatted_rec = dict(rec)
        formatted_rec["created_at"] = "now()"
        formatted_records.append(formatted_rec)

    conn.query(sql, formatted_records)

    print(f"[load_clickhouse] Загружено {len(formatted_records)} записей в ClickHouse")


# ======================================================================
# Определение DAG
# ======================================================================
default_args = {
    "owner": "bionicpro-analytics",
    "depends_on_past": False,
    "email_on_failure": True,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "start_date": datetime(2025, 1, 1),
}

with DAG(
    dag_id="telemetry_crm_mart_etl",
    default_args=default_args,
    description="ETL-пайплайн: телеметрия PostgreSQL + CRM -> витрина ClickHouse",
    schedule_interval="@daily",
    catchup=False,
    tags=["etl", "telemetry", "crm", "mart"],
    doc_md=__doc__,
) as dag:

    task_extract_telemetry = PythonOperator(
        task_id="extract_telemetry",
        python_callable=extract_telemetry,
        provide_context=True,
    )

    task_extract_crm = PythonOperator(
        task_id="extract_crm",
        python_callable=extract_crm,
        provide_context=True,
    )

    task_transform = PythonOperator(
        task_id="transform_and_aggregate",
        python_callable=transform_and_aggregate,
        provide_context=True,
    )

    task_load = PythonOperator(
        task_id="load_clickhouse",
        python_callable=load_clickhouse,
        provide_context=True,
    )

    # Порядок выполнения:
    # extract_telemetry и extract_crm выполняются параллельно,
    # затем transform_and_aggregate, затем load_clickhouse
    task_extract_telemetry >> task_transform
    task_extract_crm >> task_transform
    task_transform >> task_load