-- ============================================
-- DDL: Аналитическая витрина prosthetic_reports_mart
-- Движок: MergeTree
-- Назначение: Хранение агрегированных данных о нагрузке на протезы
-- ============================================

DROP TABLE IF EXISTS prosthetic_reports_mart;

CREATE TABLE prosthetic_reports_mart
(
    user_id String COMMENT 'Идентификатор пользователя',
    user_name String COMMENT 'Имя клиента из CRM',
    contract_number String COMMENT 'Номер договора из CRM',
    prosthetic_id String COMMENT 'Идентификатор протеза',
    report_date Date COMMENT 'Дата отчета',
    total_steps UInt32 COMMENT 'Число шагов за день',
    active_time_seconds UInt32 COMMENT 'Время активности в секундах',
    battery_drain_avg Float32 COMMENT 'Средний расход батареи (%)',
    load_level_max Float32 COMMENT 'Пиковая механическая нагрузка',
    created_at DateTime DEFAULT now() COMMENT 'Время сборки витрины'
)
ENGINE = MergeTree()
PRIMARY KEY (user_id, report_date)
ORDER BY (user_id, report_date)
SETTINGS index_granularity = 8192;

-- ============================================
-- Тестовые данные за закрытые дни (today()-1, today()-2)
-- Для пользователя 'prothetic1'
-- ============================================

INSERT INTO prosthetic_reports_mart
(
    user_id,
    user_name,
    contract_number,
    prosthetic_id,
    report_date,
    total_steps,
    active_time_seconds,
    battery_drain_avg,
    load_level_max,
    created_at
)
VALUES
(
    'prothetic1',
    'Иванов Иван Иванович',
    'CTR-2024-00142',
    'PRO-HIP-00742',
    toDate(now() - INTERVAL 2 DAY),
    8432,
    25800,
    12.5,
    78.3,
    now()
),
(
    'prothetic1',
    'Иванов Иван Иванович',
    'CTR-2024-00142',
    'PRO-HIP-00742',
    toDate(now() - INTERVAL 1 DAY),
    9105,
    28400,
    14.2,
    82.1,
    now()
);