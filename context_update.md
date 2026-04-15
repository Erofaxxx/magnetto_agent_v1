# Context Update — Multi-Cabinet Architecture

## Краткое резюме изменений

1. У клиента **Magnetto** (девелопер) 4 рекламных кабинета Яндекс Директа. Раньше аналитика строилась только по первому кабинету — остальные 3 лежали в БД (таблицы `*_2`, `*_3`, `*_4`), но в витрины не попадали.
2. Созданы **20 таблиц-клонов** (по 4 на каждую из 5 исходных выгрузок) с добавленным полем `cabinet_name LowCardinality(String)`. Бэкфилл + Materialized View ловит новые INSERT-ы в источники.
3. **7 витрин** переписаны: вместо чтения одной таблицы — `UNION ALL` всех 4 клонов, везде добавлено поле `cabinet_name` и соответствующий `GROUP BY` / `JOIN` ключ.
4. Создана таблица **`project_cabinet_map`** — связывает slug проекта (из URL Метрики `/our-projects/[slug]`) с кабинетом. Позволяет джойнить visit-based витрины (которые не разделяются по кабинетам, т.к. счётчик Метрики общий) с direct-based витринами.
5. Visit-based витрины (dm_traffic_performance, dm_client_profile, dm_client_journey, dm_conversion_paths, dm_funnel_velocity, dm_step_goal_impact, dm_active_clients_scoring, dm_path_templates) **не изменились** — один счётчик Метрики, кабинеты на уровне визитов не разделяются.

---

## Таблица кабинетов

| cabinet_name          | ClientLogin в Директе             | Основной project_slug |
|-----------------------|-----------------------------------|-----------------------|
| `audit-magnetto-tab1` | `ksi-costura-urban-magnetto`      | `costura-town`        |
| `audit-magnetto-tab2` | `ksi-niti-magnetto`               | `niti`                |
| `audit-magnetto-tab3` | `ksi-rivayat-kongrada-magnetto`   | `rivayat`             |
| `audit-magnetto-tab4` | `ksi-origana-grinvich-magnetto`   | `origana`             |

Объём данных (для ориентира, период с 27.10.2025):
- tab1 ≈ 1.50M строк direct_custom_report
- tab2 ≈ 1.73M строк (последняя дата 17.03.2026 — кабинет, видимо, остановлен)
- tab3 ≈ 1.67M строк
- tab4 ≈ 1.54M строк

---

## Архитектура клонов

### Поток данных

```
ETL → magnetto.direct_custom_report       (кабинет 1 — исходная таблица)
         │
         ├─ (MV trigger on INSERT) ──▶ magnetto.direct_custom_report_cab1   + cabinet_name='audit-magnetto-tab1'
         │
ETL → magnetto.direct_custom_report_2     (кабинет 2)
         │
         ├─ (MV trigger on INSERT) ──▶ magnetto.direct_custom_report_cab2   + cabinet_name='audit-magnetto-tab2'
         │
ETL → magnetto.direct_custom_report_3     (кабинет 3)  ──▶ …_cab3
ETL → magnetto.direct_custom_report_4     (кабинет 4)  ──▶ …_cab4
                                                            │
                                                            ▼
                                 ┌──────────────── UNION ALL ────────────────┐
                                 │  dm_direct_performance / bad_keywords /   │
                                 │  bad_placements (витрины читают клоны)    │
                                 └───────────────────────────────────────────┘
```

### Список клонов (20 таблиц)

| Исходник               | Клоны (4 шт)                                                                                                  |
|------------------------|---------------------------------------------------------------------------------------------------------------|
| `direct_custom_report*`          | `direct_custom_report_cab1`, `_cab2`, `_cab3`, `_cab4`                                               |
| `direct_search_queries_goals*`   | `direct_search_queries_goals_cab1`, `_cab2`, `_cab3`, `_cab4`                                        |
| `campaigns_meta*`                | `campaigns_meta_cab1`, `_cab2`, `_cab3`, `_cab4`                                                     |
| `ad_groups_meta*`                | `ad_groups_meta_cab1`, `_cab2`, `_cab3`, `_cab4`                                                     |
| `ads_meta*`                      | `ads_meta_cab1`, `_cab2`, `_cab3`, `_cab4`                                                           |

У каждого клона есть MV-триггер с суффиксом `_mv` (например `direct_custom_report_cab1_mv`) — срабатывает при каждом `INSERT` в источник, **не** refreshable.

### Пример DDL клона

```sql
-- 1. Целевая таблица (клон + cabinet_name)
CREATE TABLE IF NOT EXISTS magnetto.direct_custom_report_cab1
ENGINE = MergeTree
ORDER BY (CampaignId, Date, AttributionModel)
SETTINGS index_granularity = 8192
AS SELECT *, '' AS cabinet_name FROM magnetto.direct_custom_report WHERE 0;

ALTER TABLE magnetto.direct_custom_report_cab1
    MODIFY COLUMN cabinet_name LowCardinality(String);

-- 2. MV-триггер на INSERT в источник
CREATE MATERIALIZED VIEW magnetto.direct_custom_report_cab1_mv
TO magnetto.direct_custom_report_cab1
AS SELECT *, 'audit-magnetto-tab1' AS cabinet_name
FROM magnetto.direct_custom_report;

-- 3. Бэкфилл существующих данных (разовый)
INSERT INTO magnetto.direct_custom_report_cab1
SELECT *, 'audit-magnetto-tab1' AS cabinet_name
FROM magnetto.direct_custom_report;
```

Для cab2/cab3/cab4 — аналогично, меняется только источник (`_2`/`_3`/`_4`) и значение `cabinet_name`.

---

## Обновлённые витрины (7 шт)

Во всех витринах добавлена колонка **`cabinet_name LowCardinality(String)`** (как правило — второй колонкой после ключа даты). Источник — `UNION ALL` 4 клонов вместо одной исходной таблицы.

### 1. `dm_direct_performance`

**Было:** `FROM magnetto.direct_custom_report`, `GROUP BY Date, CampaignId, AdGroupId, AdNetworkType`.
**Стало:** `FROM (UNION ALL 4 клонов)`, `GROUP BY Date, cabinet_name, CampaignId, AdGroupId, AdNetworkType`.

Колонка `cabinet_name` добавлена сразу после `date`.

```sql
-- Пример: клики/расход по кабинетам за последние 30 дней
SELECT
    cabinet_name,
    sum(clicks)      AS clicks,
    sum(cost)        AS cost,
    sum(leads_all)   AS leads,
    sum(order_paid)  AS orders
FROM magnetto.dm_direct_performance
WHERE date >= today() - 30
GROUP BY cabinet_name
ORDER BY cost DESC;
```

### 2. `campaigns_settings`

**Было:** `SELECT * FROM campaigns_meta WHERE loaded_at = (SELECT max(loaded_at) FROM campaigns_meta)` — один snapshot.
**Стало:** `UNION ALL` 4 клонов, **per-cabinet `max(loaded_at)`** — у каждого кабинета свой последний снимок.

```sql
SELECT * FROM magnetto.campaigns_meta_cab1 WHERE loaded_at = (SELECT max(loaded_at) FROM magnetto.campaigns_meta_cab1)
UNION ALL
SELECT * FROM magnetto.campaigns_meta_cab2 WHERE loaded_at = (SELECT max(loaded_at) FROM magnetto.campaigns_meta_cab2)
-- … cab3, cab4
```

```sql
-- Кол-во активных кампаний по кабинетам
SELECT cabinet_name, countIf(status = 'ENABLED') AS active, count() AS total
FROM magnetto.campaigns_settings
GROUP BY cabinet_name;
```

### 3. `adgroups_settings`

Аналогично `campaigns_settings`: источник — `ad_groups_meta_cab1..4`, per-cabinet `max(loaded_at)`. `cabinet_name` первой колонкой.

### 4. `ads_settings`

Аналогично: источник — `ads_meta_cab1..4`, per-cabinet `max(loaded_at)`. `cabinet_name` первой колонкой.

### 5. `bad_keywords`

Сложный CTE со взвешенным `goal_score` и медианами. Изменения:
- CTE `src` — `UNION ALL` 4 клонов
- Во всех `GROUP BY` добавлен `cabinet_name`
- В CTE `medians` (per-campaign медианы `goal_score_rate` / `roas`) — **`GROUP BY cabinet_name, CampaignId, ad_network_type`** (раньше без cabinet_name)
- В `JOIN` `agg` ↔ `medians` добавлено условие `a.cabinet_name = m.cabinet_name`

```sql
-- Топ-20 красных ключей по кабинету tab2
SELECT Criterion, CampaignName, clicks, cost, goal_score_rate, roas, zone_status
FROM magnetto.bad_keywords
WHERE cabinet_name = 'audit-magnetto-tab2'
  AND zone_status = 'red'
  AND report_date = (SELECT max(report_date) FROM magnetto.bad_keywords)
ORDER BY cost DESC
LIMIT 20;
```

### 6. `bad_placements`

Аналогично `bad_keywords`:
- CTE `src` — `UNION ALL` 4 клонов
- CTE `max_dates` — **per-cabinet `max(Date)`** (окно 60 дней считается от последней даты КАЖДОГО кабинета, а не глобально)
- CTE `benchmarks` — `GROUP BY cabinet_name, CampaignId`
- JOIN-ы включают `cabinet_name`

### 7. `bad_queries`

Источник — `direct_search_queries_goals_cab1..4`. Во всех CTE (`agg_raw`, `agg`, `benchmarks`, `scored`) присутствует `cabinet_name` в GROUP BY / SELECT / JOIN.

```sql
-- Хронические красные запросы по всем кабинетам
SELECT cabinet_name, Query, CampaignName, clicks, cost, goal_score_rate, zone_reason
FROM magnetto.bad_queries
WHERE zone_status = 'red'
  AND is_chronic = 1
  AND report_date = (SELECT max(report_date) FROM magnetto.bad_queries)
ORDER BY cabinet_name, cost DESC;
```

---

## `project_cabinet_map` — маппинг slug → кабинет

Статическая таблица (обновляется вручную), связывает slug проекта из URL Метрики (`/our-projects/[slug]`) с рекламным кабинетом.

### Схема

```sql
CREATE TABLE magnetto.project_cabinet_map
(
    project_slug   String,
    cabinet_name   LowCardinality(String),   -- '' если кросс-кабинетный
    is_primary     UInt8,                    -- 1 = основной, 0 = слабая связь / требует подтверждения
    note           String
)
ENGINE = MergeTree
ORDER BY project_slug;
```

### Данные

| project_slug        | cabinet_name          | is_primary | Note                                 |
|---------------------|-----------------------|-----------:|--------------------------------------|
| `costura-town`      | `audit-magnetto-tab1` | 1 | ksi-costura-urban-magnetto              |
| `niti`              | `audit-magnetto-tab2` | 1 | ksi-niti-magnetto                       |
| `rivayat`           | `audit-magnetto-tab3` | 1 | ksi-rivayat-kongrada-magnetto           |
| `origana`           | `audit-magnetto-tab4` | 1 | ksi-origana-grinvich-magnetto           |
| `grinvich`          | `audit-magnetto-tab4` | 0 | предположительно origana/grinvich       |
| `glavnye-roli`      | `audit-magnetto-tab2` | 0 | доминирует tab2, требует подтверждения  |
| `zhivi-na-portovoj` | `audit-magnetto-tab2` | 0 | единичные данные                        |
| `altura`            | `audit-magnetto-tab2` | 0 | единичные данные                        |
| `odette`            | `audit-magnetto-tab2` | 0 | единичные данные                        |
| `zk-1712`           | `''`                  | 0 | cross-cabinet: равномерно по всем 4     |

### Источник `last_project` в `dm_client_profile`

Поле `last_project` — это вычисленный slug из `startURL` последнего визита (часть URL после `/our-projects/`). Это единственный мост между visit-based аналитикой (Метрика общая) и кабинетной (Директ разделён).

### Как джойнить

```sql
-- Скоринг клиентов с привязкой к кабинету
SELECT
    s.client_id,
    s.priority,
    s.lift_score,
    s.last_project,
    coalesce(m.cabinet_name, 'unknown') AS cabinet_name,
    m.is_primary
FROM magnetto.dm_active_clients_scoring AS s
LEFT JOIN magnetto.project_cabinet_map AS m
    ON s.last_project = m.project_slug
   AND m.is_primary = 1;        -- только достоверные маппинги
```

**Важно:**
- Для `last_project IN ('costura-town','niti','rivayat','origana')` маппинг однозначный (`is_primary=1`).
- Для `zk-1712` и проектов с `is_primary=0` достоверного cabinet нет. Либо фильтруй `is_primary=1`, либо возвращай `''/unknown`.
- Встречаются числовые `last_project` ('29', '30', '31' и т.п.) — это старые URL-структуры без slug-а. В маппинге их нет.

---

## Не изменялось (visits-based витрины)

Следующие витрины **остались без поля `cabinet_name`** и читают напрямую из `visits_all_fields` (Метрика):

- `dm_traffic_performance` — per-source трафик и конверсии
- `dm_client_profile` — профиль клиента (поле `last_project` — мост к кабинетам)
- `dm_client_journey` — визиты клиента по порядку
- `dm_conversion_paths` — пути конверсии
- `dm_funnel_velocity` — скорость прохождения воронки
- `dm_step_goal_impact` — lift целей по шагам
- `dm_active_clients_scoring` — скоринг активных неконвертированных клиентов
- `dm_path_templates` — шаблоны путей

**Почему:** у Magnetto один общий счётчик Яндекс Метрики на все 4 проекта — на уровне визита нельзя определить, с какого рекламного кабинета пришёл пользователь (можно только косвенно через `last_project` + `project_cabinet_map`, и то только для визитов с URL `/our-projects/[slug]`).

Если нужно разбить визиты по кабинетам — **джойни через `last_project`**, отдавая отчёт в том, что часть визитов останется без кабинета.

---

## Примеры SQL для типовых задач агента

### Сравнение кабинетов за период (клики / лиды / CPL)

```sql
SELECT
    cabinet_name,
    sum(clicks)                                          AS clicks,
    round(sum(cost))                                     AS cost,
    sum(leads_all)                                       AS leads,
    sum(order_created)                                   AS crm_created,
    sum(order_paid)                                      AS crm_paid,
    round(sum(cost) / nullIf(sum(leads_all), 0))         AS cpl,
    round(sum(cost) / nullIf(sum(order_paid), 0))        AS cac_paid
FROM magnetto.dm_direct_performance
WHERE date BETWEEN today() - 30 AND today()
GROUP BY cabinet_name
ORDER BY cost DESC;
```

### Топ «плохих» ключей по конкретному кабинету

```sql
SELECT
    Criterion,
    CampaignName,
    clicks,
    round(cost)           AS cost,
    round(goal_score_rate, 2) AS gsr,
    round(roas, 2)        AS roas,
    bid_zone,
    zone_status
FROM magnetto.bad_keywords
WHERE cabinet_name = 'audit-magnetto-tab3'
  AND zone_status IN ('red', 'yellow')
  AND report_date = (SELECT max(report_date) FROM magnetto.bad_keywords)
ORDER BY cost DESC
LIMIT 50;
```

### Скоринг клиентов, разбитый по кабинетам

```sql
SELECT
    coalesce(m.cabinet_name, 'unmapped') AS cabinet_name,
    s.priority,
    count()                              AS clients,
    round(avg(s.lift_score), 1)          AS avg_lift
FROM magnetto.dm_active_clients_scoring AS s
LEFT JOIN magnetto.project_cabinet_map AS m
    ON s.last_project = m.project_slug AND m.is_primary = 1
GROUP BY cabinet_name, s.priority
ORDER BY cabinet_name, s.priority;
```

### Расход по кабинетам за неделю с динамикой день-в-день

```sql
SELECT
    date,
    cabinet_name,
    round(sum(cost)) AS cost,
    sum(clicks)      AS clicks
FROM magnetto.dm_direct_performance
WHERE date >= today() - 7
GROUP BY date, cabinet_name
ORDER BY date, cabinet_name;
```

### Найти кабинет, в котором конкретная кампания

```sql
SELECT cabinet_name, campaign_id, campaign_name, status, state
FROM magnetto.campaigns_settings
WHERE campaign_name ILIKE '%rivayat%';
```

### Красные плейсменты РСЯ по кабинету

```sql
SELECT
    Placement,
    CampaignName,
    round(cost)                  AS cost,
    clicks,
    round(bounce_rate, 1)        AS bounce_rate,
    round(goal_score_rate, 2)    AS gsr,
    zone_reason
FROM magnetto.bad_placements
WHERE cabinet_name = 'audit-magnetto-tab1'
  AND zone_status = 'red'
  AND report_date = (SELECT max(report_date) FROM magnetto.bad_placements)
ORDER BY cost DESC
LIMIT 30;
```

### Свести direct-показатели с поведенческими по проекту

```sql
WITH direct AS (
    SELECT cabinet_name, sum(cost) AS cost, sum(leads_all) AS leads
    FROM magnetto.dm_direct_performance
    WHERE date >= today() - 30
    GROUP BY cabinet_name
),
behavior AS (
    SELECT
        m.cabinet_name,
        countIf(s.priority = 'hot')  AS hot_clients,
        countIf(s.priority = 'warm') AS warm_clients
    FROM magnetto.dm_active_clients_scoring AS s
    INNER JOIN magnetto.project_cabinet_map AS m
        ON s.last_project = m.project_slug AND m.is_primary = 1
    GROUP BY m.cabinet_name
)
SELECT
    d.cabinet_name,
    d.cost,
    d.leads,
    coalesce(b.hot_clients, 0)  AS hot,
    coalesce(b.warm_clients, 0) AS warm
FROM direct AS d
LEFT JOIN behavior AS b ON d.cabinet_name = b.cabinet_name
ORDER BY d.cost DESC;
```

---

## Шпаргалка по выбору источника

| Задача                                       | Таблица                                | Фильтр по кабинету                       |
|----------------------------------------------|----------------------------------------|------------------------------------------|
| Расходы/клики/лиды Директа                   | `dm_direct_performance`                | `WHERE cabinet_name = ...`               |
| Настройки кампаний                           | `campaigns_settings`                   | `WHERE cabinet_name = ...`               |
| Настройки групп / ключи / автотаргетинг      | `adgroups_settings`                    | `WHERE cabinet_name = ...`               |
| Настройки объявлений / креативы              | `ads_settings`                         | `WHERE cabinet_name = ...`               |
| Плохие ключи                                 | `bad_keywords`                         | `WHERE cabinet_name = ...`               |
| Плохие плейсменты РСЯ                        | `bad_placements`                       | `WHERE cabinet_name = ...`               |
| Плохие поисковые запросы                     | `bad_queries`                          | `WHERE cabinet_name = ...`               |
| Трафик из всех источников (не только Директ) | `dm_traffic_performance`               | нет — общий Метрика-счётчик              |
| Профиль клиента                              | `dm_client_profile`                    | через `last_project` + map               |
| Скоринг / рекомендации                       | `dm_active_clients_scoring`            | через `last_project` + map               |
| Воронка / lift целей                         | `dm_funnel_velocity`, `dm_step_goal_impact` | нет — одинаково для всех           |

**Правило:** если витрина имеет колонку `cabinet_name` — всегда фильтруй по ней явно. Если колонки нет — это общеметрический слой, пытаться разделить по кабинетам можно только через `last_project` → `project_cabinet_map`, и то с потерей части визитов.
