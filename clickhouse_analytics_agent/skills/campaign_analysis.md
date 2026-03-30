# Скилл: Аналитика каналов и кампаний

Активируется при вопросах про: источники трафика, каналы, кампании, UTM, конверсию,
откуда приходят лиды, first touch, last touch, путь клиента, качество трафика.

---

## Доступные данные

**Расходы на рекламу отсутствуют** — нет витрины с ad spend.
Метрики CPC, CPM, CPA, ROAS рассчитать **невозможно**. Не пытаться их считать.

**Выручки в прямом виде нет** — компания не e-commerce. Финальная метрика — `has_crm_paid` (оплаченная сделка).

Доступны: трафик, конверсия в лид, конверсия в сделку по каналам, пути клиентов.

---

## Какую витрину использовать

| Задача | Витрина |
|--------|---------|
| Трафик по каналу: визиты, отказы, глубина, динамика по дням | `dm_traffic_performance` |
| Лиды по каналу (по дням, воронка) | `dm_traffic_performance` (goal_314553735) |
| First touch и last touch атрибуция лидов | `dm_client_profile` |
| Полный путь клиента до лида, мультитач | `dm_conversion_paths` |
| Конкретный визит конверсии, last touch по сессии | `dm_client_journey` (is_converting_visit = 1) |

---

## dm_traffic_performance — трафик и лиды по дням

### Основные поля
| Поле | Описание |
|------|----------|
| `date` | Дата |
| `project_slug` | Проект ЖК или `'site'` |
| `utm_source` | Источник трафика |
| `utm_medium` | Тип трафика |
| `utm_campaign` | Кампания |
| `traffic_source` | Тип трафика из Метрики: `ad`, `organic`, `direct`, `referral` и др. |
| `device_category` | Устройство: `desktop`, `mobile`, `tablet` |
| `region_city` | Город |
| `visits` | Визиты |
| `new_users` | Новые пользователи |
| `bounces` | Отказы (1 страница) |
| `total_duration_sec` | Суммарное время на сайте (сек) |
| `total_page_views` | Просмотры страниц |
| `goal_314553735` | Все лиды — magnetto (главная цель конверсии) |
| `goal_402733217` | Мусорный трафик (спам/боты) |

### ⚠️ Правила работы с dm_traffic_performance

- **Пустой `utm_source`** — не органика. Использовать `traffic_source` для определения: `organic`, `direct`, `ad`, `undefined`.
- **Спам:** при расчёте CR всегда фильтровать `WHERE goal_402733217 = 0` или исключать строки с ненулевым значением этого поля.
- **CR считать в запросе:** `goal_314553735 / visits * 100`.

### Трафик и качество по каналу

```sql
SELECT
    utm_source,
    traffic_source,
    sum(visits)                                              AS visits,
    sum(new_users)                                          AS new_users,
    round(sum(bounces) / sum(visits) * 100, 1)              AS bounce_rate_pct,
    round(sum(total_duration_sec) / sum(visits) / 60, 1)    AS avg_duration_min,
    round(sum(total_page_views) / sum(visits), 1)           AS avg_pageviews,
    sum(goal_314553735)                                     AS leads,
    round(sum(goal_314553735) / sum(visits) * 100, 2)       AS cr_lead_pct
FROM magnetto.dm_traffic_performance
WHERE date >= today() - 30
  AND goal_402733217 = 0   -- фильтр спама
GROUP BY utm_source, traffic_source
ORDER BY leads DESC
```

### Динамика по дням

```sql
SELECT
    date,
    utm_source,
    sum(visits) AS visits,
    sum(goal_314553735) AS leads
FROM magnetto.dm_traffic_performance
WHERE date >= today() - 30
  AND goal_402733217 = 0
GROUP BY date, utm_source
ORDER BY date, visits DESC
```

### Лиды по проектам и каналам

```sql
SELECT
    project_slug,
    utm_source,
    sum(visits)         AS visits,
    sum(goal_314553735) AS leads,
    round(sum(goal_314553735) / sum(visits) * 100, 2) AS cr_pct
FROM magnetto.dm_traffic_performance
WHERE date >= today() - 30
  AND project_slug != 'site'   -- только страницы ЖК
  AND goal_402733217 = 0
GROUP BY project_slug, utm_source
ORDER BY leads DESC
```

---

## dm_client_profile — first touch / last touch атрибуция лидов

Единственная витрина с атрибуцией на уровне клиента.

### Ключевые поля для атрибуции
| Поле | Описание |
|------|----------|
| `client_id` | ID клиента |
| `first_visit_date` | Дата первого визита |
| `first_traffic_source` | Тип трафика первого визита |
| `first_utm_source` | UTM Source первого визита (first touch) |
| `first_utm_medium` | UTM Medium первого визита |
| `first_utm_campaign` | UTM Campaign первого визита |
| `last_traffic_source` | Тип трафика последнего визита |
| `last_utm_source` | UTM Source последнего визита (last touch) |
| `last_utm_campaign` | UTM Campaign последнего визита |
| `has_lead` | 1 = хотя бы один лид |
| `first_lead_date` | Дата первого лида |
| `days_to_first_lead` | Дней от первого визита до лида |
| `has_crm_paid` | 1 = сделка оплачена (финальный KPI) |
| `total_visits` | Всего визитов клиента |

### First touch: откуда приходят те, кто оставил лид

```sql
SELECT
    first_utm_source,
    first_traffic_source,
    count() AS total_clients,
    countIf(has_lead = 1) AS leads,
    round(countIf(has_lead = 1) / count() * 100, 2) AS cr_to_lead_pct,
    countIf(has_crm_paid = 1) AS deals
FROM magnetto.dm_client_profile
GROUP BY first_utm_source, first_traffic_source
HAVING total_clients >= 10
ORDER BY leads DESC
```

### Last touch: с какого канала клиент пришёл перед лидом

Для last-touch атрибуции лидов используй `dm_client_journey` с `is_converting_visit = 1`.

```sql
-- Канал конвертирующей сессии (last touch по факту лида):
SELECT
    utm_source,
    traffic_source,
    count() AS converting_sessions,
    round(count() / SUM(count()) OVER () * 100, 1) AS pct
FROM magnetto.dm_client_journey
WHERE is_converting_visit = 1
GROUP BY utm_source, traffic_source
ORDER BY converting_sessions DESC
```

### Матрица first touch vs last touch

```sql
SELECT
    p.first_utm_source   AS first_touch,
    j.utm_source         AS last_touch,
    count() AS leads
FROM magnetto.dm_client_journey j
JOIN magnetto.dm_client_profile p ON j.client_id = p.client_id
WHERE j.is_converting_visit = 1
GROUP BY first_touch, last_touch
ORDER BY leads DESC
LIMIT 20
```

### Цикл сделки по каналу

```sql
SELECT
    first_utm_source,
    first_traffic_source,
    count() AS leads,
    round(avg(days_to_first_lead)) AS avg_days_to_lead,
    median(days_to_first_lead) AS median_days,
    round(avg(total_visits)) AS avg_visits_before_lead,
    countIf(has_crm_paid = 1) AS deals
FROM magnetto.dm_client_profile
WHERE has_lead = 1
  AND days_to_first_lead >= 0
GROUP BY first_utm_source, first_traffic_source
HAVING leads >= 5
ORDER BY leads DESC
```

---

## Правила интерпретации

- **Нет расходов** → не считать CPC, CPM, CPA, ROAS. Если пользователь просит ROAS — объяснить, что данных по расходам нет.
- **Малые выборки** → при n < 5 лидов/сделок ставить ⚠️ и предупреждать о ненадёжности.
- **Период** → всегда указывать сравниваемые периоды явно.
- **dm_traffic_performance** считает сессии. **dm_client_profile** считает уникальных клиентов. Не складывать leads из обеих таблиц — это может быть один и тот же клиент.
- **`project_slug = 'site'`** — большая часть трафика входит через главную, это норма.
- **Пустой `utm_source`** в dm_traffic_performance — не органика. Смотреть `traffic_source`.
- **`has_crm_paid`** — единственный финансовый KPI. Сделок мало (недвижимость, долгий цикл) — интерпретировать осторожно.
