# Проектная работа: Архитектура BionicPRO (Спринт 9)

Комплексная модернизация архитектуры IT-системы компании BionicPRO:
1. Защита аутентификации и персональных данных: переход с Authorization Code Grant на PKCE, проектирование трансграничной федерации удостоверений (Federated Identity / IdP).
2. Аналитическая платформа и витрина отчетов: построение ETL-пайплайна на Apache Airflow, консолидация телеметрии и данных CRM в ClickHouse, разработка защищенного Reporting API с проверкой владения данными (RBAC/ABAC).

---

## Навигация по заданиям и артефактам

### [Задание 1. Повышение безопасности системы](./task-1/)
- **Задача 1. Архитектура управления учетными данными:**
  - Диаграмма C4 (Container): [`schemas/task1_c4_identity.drawio`](./schemas/)
  - Описание архитектурного решения (трансграничная федерация IdP без трансграничной передачи ПДн/медданных, защита access/refresh токенов): [`task-1/solution.md`](./task-1/solution.md)
- **Задача 2. Реализация PKCE Flow:**
  - Конфигурация клиента Keycloak (`pkce-code-challenge-method: S256`): [`keycloak/realm-export.json`](./keycloak/realm-export.json)
  - Реализация генерации verifier/challenge и обмена в SPA: [`frontend/src/`](./frontend/src/)

### [Задание 2. Сервис отчётов и аналитический контур](./task-2/)
- **Задача 1. Архитектура подготовки и получения отчетов:**
  - Диаграмма C4 (ETL + OLAP + API): [`schemas/task2_c4_analytics.drawio`](./schemas/)
- **Задача 2. Airflow DAG и витрина в OLAP:**
  - Реализация пайплайна: [`task-2/airflow/dags/`](./task-2/)
  - DDL схемы витрины ClickHouse (агрегация телеметрии + CRM): [`task-2/clickhouse/`](./task-2/)
- **Задачи 3–4. Backend Reporting API и авторизация:**
  - Исходный код API (`/reports`): [`task-2/api/`](./task-2/)
  - Ограничение доступа: валидация токена Keycloak, выдача данных строго по текущему пользователю.
- **Задача 5. Интерфейс выгрузки отчетов (UI):**
  - Кнопка получения отчета с блокировкой неавторизованных запросов и валидацией периода: [`frontend/src/components/ReportPage.tsx`](./frontend/src/components/ReportPage.tsx)

---

## Кроссплатформенная инструкция по запуску (Windows / macOS)

### Требования
- Docker Desktop с поддержкой Compose v2.
- Свободные порты: `3000` (UI), `8080` (Keycloak), `5433` (Keycloak DB), `8000` (API), `8123` (ClickHouse), `8081` (Airflow).

### Запуск инфраструктуры

1. Клонирование и переход в проект:
   ```bash
   git clone [https://github.com/lelik-bolek/architecture-bionicpro.git](https://github.com/lelik-bolek/architecture-bionicpro.git)
   cd architecture-bionicpro

```

2. Запуск контейнеров:
```bash
docker compose up -d --build

```
3. Доступные сервисы:
* **Frontend UI**: [http://localhost:3000](http://localhost:3000)
* **Keycloak Console**: [http://localhost:8080](http://localhost:8080) (`admin` / `admin`)
* **Airflow Web UI**: [http://localhost:8081](http://localhost:8081) (`admin` / `admin`)
* **Reporting API**: [http://localhost:8000/docs](http://localhost:8000/docs)

```