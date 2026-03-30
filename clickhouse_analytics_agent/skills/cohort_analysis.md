## Skill: Когортный анализ

**База данных:** `magnetto`
**Компания:** застройщик (не e-commerce). Продукт один — недвижимость.
**Конверсия:** лид (goal 314553735), финал — сделка (has_crm_paid).

### Ключевые таблицы

- **dm_client_profile** — сводный портрет клиента: first_visit_date, has_lead, first_lead_date, days_to_first_lead, has_crm_paid, crm_paid_date
- **dm_client_journey** — каждая сессия клиента: visit_number, date, utm_source, has_lead, has_crm_paid, is_converting_visit

Важно: `dm_traffic_performance` считает ВСЕ визиты включая анонимные (clientID = 0).
Клиентские витрины содержат только clientID > 0. Разница = анонимные сессии. Это норма.

---

### Когортирование по месяцу первого визита

```sql
-- Размер когорт по месяцу первого визита:
SELECT
    toStartOfMonth(first_visit_date) AS cohort_month,
    count() AS cohort_size,
    countIf(has_lead = 1) AS converted_to_lead,
    round(countIf(has_lead = 1) / count() * 100, 1) AS lead_cr_pct,
    countIf(has_crm_paid = 1) AS closed_deals,
    round(countIf(has_crm_paid = 1) / count() * 100, 2) AS deal_cr_pct
FROM magnetto.dm_client_profile
GROUP BY cohort_month
ORDER BY cohort_month
```

---

### Retention: возвраты на сайт по когортам

```sql
-- Количество клиентов из когорты, вернувшихся в месяц T+N:
WITH cohorts AS (
    SELECT
        client_id,
        toStartOfMonth(first_visit_date) AS cohort_month
    FROM magnetto.dm_client_profile
),
visits AS (
    SELECT
        j.client_id,
        c.cohort_month,
        toStartOfMonth(j.date) AS activity_month,
        dateDiff('month', c.cohort_month, toStartOfMonth(j.date)) AS months_since_first
    FROM magnetto.dm_client_journey j
    JOIN cohorts c ON j.client_id = c.client_id
)
SELECT
    cohort_month,
    months_since_first,
    count(DISTINCT client_id) AS active_clients
FROM visits
WHERE months_since_first >= 0
GROUP BY cohort_month, months_since_first
ORDER BY cohort_month, months_since_first
```

```python
# Retention rate = вернувшиеся в месяц T+N / размер когорты
pivot = df.pivot_table(
    index='cohort_month',
    columns='months_since_first',
    values='active_clients',
    aggfunc='sum'
)
# Первый столбец (0) = размер когорты
cohort_sizes = pivot[0]
retention = pivot.divide(cohort_sizes, axis=0) * 100
result = retention.round(1).to_markdown()
```

---

### Цикл сделки: сколько дней от первого визита до лида

```sql
-- Распределение по дням от первого визита до лида:
SELECT
    multiIf(
        days_to_first_lead = 0, '0 (день в день)',
        days_to_first_lead <= 7, '1–7 дней',
        days_to_first_lead <= 30, '8–30 дней',
        days_to_first_lead <= 90, '31–90 дней',
        '90+ дней'
    ) AS bucket,
    count() AS clients,
    round(count() / SUM(count()) OVER () * 100, 1) AS pct
FROM magnetto.dm_client_profile
WHERE has_lead = 1
  AND days_to_first_lead >= 0
GROUP BY bucket
ORDER BY min(days_to_first_lead)
```

```sql
-- Средний цикл по каналу первого касания:
SELECT
    first_utm_source,
    first_traffic_source,
    count() AS leads,
    round(avg(days_to_first_lead)) AS avg_days_to_lead,
    median(days_to_first_lead) AS median_days_to_lead,
    countIf(has_crm_paid = 1) AS closed_deals
FROM magnetto.dm_client_profile
WHERE has_lead = 1
  AND days_to_first_lead >= 0
GROUP BY first_utm_source, first_traffic_source
HAVING leads >= 5
ORDER BY leads DESC
```

---

### Когорты по каналу привлечения

```sql
-- Конверсия в лид по каналу + месяцу первого визита:
SELECT
    toStartOfMonth(first_visit_date) AS cohort_month,
    first_traffic_source,
    count() AS clients,
    countIf(has_lead = 1) AS leads,
    round(countIf(has_lead = 1) / count() * 100, 1) AS cr_lead_pct,
    countIf(has_crm_paid = 1) AS deals
FROM magnetto.dm_client_profile
GROUP BY cohort_month, first_traffic_source
HAVING clients >= 10
ORDER BY cohort_month, clients DESC
```

---

### Глубина прогрева: сколько визитов до лида

```sql
-- На каком по счёту визите клиент оставляет лид:
SELECT
    visit_number,
    count() AS converting_sessions,
    round(count() / SUM(count()) OVER () * 100, 1) AS pct_of_all_leads
FROM magnetto.dm_client_journey
WHERE is_converting_visit = 1
GROUP BY visit_number
ORDER BY visit_number
LIMIT 20
```

```sql
-- Среднее количество визитов до лида по когортам первого визита:
SELECT
    toStartOfMonth(p.first_visit_date) AS cohort_month,
    round(avg(j.visit_number)) AS avg_visit_at_lead,
    round(avg(p.days_to_first_lead)) AS avg_days_to_lead,
    count() AS leads
FROM magnetto.dm_client_journey j
JOIN magnetto.dm_client_profile p ON j.client_id = p.client_id
WHERE j.is_converting_visit = 1
  AND p.days_to_first_lead >= 0
GROUP BY cohort_month
ORDER BY cohort_month
```

---

### Клиенты, дошедшие до сделки

```sql
-- Профиль клиентов с оплаченной сделкой:
SELECT
    first_traffic_source,
    first_utm_source,
    count() AS deals,
    round(avg(days_to_first_lead)) AS avg_days_to_lead,
    round(avg(total_visits)) AS avg_visits,
    round(avg(projects_count)) AS avg_projects_viewed,
    round(avg(dateDiff('day', first_lead_date, crm_paid_date))) AS avg_days_lead_to_deal
FROM magnetto.dm_client_profile
WHERE has_crm_paid = 1
  AND first_lead_date != '1970-01-01'
  AND crm_paid_date != '1970-01-01'
GROUP BY first_traffic_source, first_utm_source
HAVING deals >= 3
ORDER BY deals DESC
```

---

### Интерпретация

- Для недвижимости цикл 30–180 дней от первого визита до лида — норма. Не сравнивать с e-commerce.
- Когорты молодше 3 месяцев ещё «созревают» — их conversion rate будет расти. Всегда указывать возраст когорты.
- `has_crm_paid = 1` — финальный KPI. Небольшое n (единицы сделок) — предупреждай о ненадёжности.
- `first_lead_date = '1970-01-01'` означает «лида не было». Всегда фильтровать при анализе цикла.
- При сравнении когорт сравнивай когорты одинакового возраста (одинаковое число месяцев наблюдения).
