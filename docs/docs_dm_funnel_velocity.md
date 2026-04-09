# dm_funnel_velocity

## Назначение

Скорость прохождения воронки по недельным когортам: от первого визита до лида, от лида до CRM-сделки, от сделки до оплаты. Показывает, как быстро клиенты проходят каждый этап и какой процент доходит до следующей стадии.

## Источник данных

`magnetto.dm_client_profile` (профиль клиента: даты первого визита, лида, сделки, оплаты).

## Обновление

REFRESH EVERY 1 DAY OFFSET 5 HOUR (после dm_client_profile, которая обновляется в OFFSET 4 HOUR).

## Важно

Витрина учитывает ВСЕ источники трафика (organic, direct, referral, ad и т.д.), а не только платный. Это нужно помнить при интерпретации — конверсия отражает общую картину сайта, а не только эффективность рекламы.

## Структура таблицы

| Поле | Тип | Описание |
|------|-----|----------|
| cohort_week | Date | Понедельник недели первого визита (когорта) |
| cohort_age_days | UInt16 | Возраст когорты в днях (на момент рефреша) |
| new_clients | UInt32 | Всего уникальных клиентов в когорте |
| clients_with_lead | UInt32 | Дошли до стадии "лид" |
| lead_rate_pct | Float32 | % клиентов с лидом от new_clients |
| avg_days_to_lead | Float32 | Среднее кол-во дней от первого визита до лида |
| median_days_to_lead | Float32 | Медиана дней до лида |
| clients_with_crm | UInt32 | Дошли до CRM: Заказ создан |
| crm_rate_from_lead_pct | Float32 | % CRM-сделок от лидов |
| avg_days_lead_to_crm | Float32 | Среднее дней от лида до CRM-сделки |
| clients_paid | UInt32 | Дошли до CRM: Заказ оплачен |
| paid_rate_from_crm_pct | Float32 | % оплат от CRM-сделок |
| snapshot_date | Date | Дата последнего рефреша |

ORDER BY: cohort_week

## Логика воронки

```
new_clients → (lead_rate_pct%) → clients_with_lead → (crm_rate_from_lead_pct%) → clients_with_crm → (paid_rate_from_crm_pct%) → clients_paid
```

Каждая стадия привязана к цели Метрики:
- Лид = цель 314553735 (Все лиды magnetto)
- CRM-сделка = цель 332069613 (CRM: Заказ создан)
- Оплата = цель 332069614 (CRM: Заказ оплачен)

## Сценарии использования для AI-агента

### 1. Общая скорость воронки

**Когда спрашивают**: "Сколько времени уходит от первого визита до сделки?", "Какой цикл продаж?", "Как быстро конвертируются клиенты?"

**Запрос**:
```sql
SELECT
    cohort_week,
    new_clients,
    lead_rate_pct,
    avg_days_to_lead,
    median_days_to_lead,
    crm_rate_from_lead_pct,
    avg_days_lead_to_crm
FROM magnetto.dm_funnel_velocity
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_funnel_velocity)
  AND cohort_age_days >= 60  -- только созревшие когорты
ORDER BY cohort_week DESC
LIMIT 10
```

**Как интерпретировать**: молодые когорты (< 30 дней) ещё не успели пройти воронку — их конверсии занижены. Для честного анализа берём когорты с возрастом >= 60 дней (средний цикл сделки ~70 дней).

### 2. Сравнение когорт — улучшается ли воронка

**Когда спрашивают**: "Конверсия растёт или падает?", "Как когорты этого квартала vs прошлого?"

**Запрос**:
```sql
SELECT
    cohort_week,
    new_clients,
    lead_rate_pct,
    crm_rate_from_lead_pct,
    paid_rate_from_crm_pct
FROM magnetto.dm_funnel_velocity
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_funnel_velocity)
  AND cohort_age_days >= 90
ORDER BY cohort_week
```

**Как интерпретировать**: если lead_rate_pct растёт от когорты к когорте — сайт/реклама стали лучше привлекать лидов. Если crm_rate_from_lead_pct падает — проблема в обработке лидов (менеджеры, CRM).

### 3. Узкие места воронки

**Когда спрашивают**: "Где теряем клиентов?", "На каком этапе самая большая потеря?"

**Запрос**:
```sql
SELECT
    'Визит → Лид' AS stage,
    round(avg(lead_rate_pct), 2) AS avg_rate_pct
FROM magnetto.dm_funnel_velocity
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_funnel_velocity)
  AND cohort_age_days >= 60

UNION ALL

SELECT
    'Лид → CRM' AS stage,
    round(avg(crm_rate_from_lead_pct), 2) AS avg_rate_pct
FROM magnetto.dm_funnel_velocity
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_funnel_velocity)
  AND cohort_age_days >= 60

UNION ALL

SELECT
    'CRM → Оплата' AS stage,
    round(avg(paid_rate_from_crm_pct), 2) AS avg_rate_pct
FROM magnetto.dm_funnel_velocity
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_funnel_velocity)
  AND cohort_age_days >= 60
```

**Как интерпретировать**: самый низкий % — это bottleneck. Маркетолог влияет напрямую на первую стадию (Визит → Лид). На CRM и оплату влияет отдел продаж, но маркетинг может влиять косвенно через качество трафика.

### 4. Время созревания когорты

**Когда спрашивают**: "Когда когорта дозреет?", "Через сколько дней ждать сделки?", "Какой лаг конверсии?"

**Запрос**:
```sql
SELECT
    cohort_week,
    cohort_age_days,
    avg_days_to_lead,
    median_days_to_lead,
    avg_days_lead_to_crm,
    round(avg_days_to_lead + avg_days_lead_to_crm, 0) AS total_days_to_crm
FROM magnetto.dm_funnel_velocity
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_funnel_velocity)
  AND cohort_age_days >= 60
ORDER BY cohort_week DESC
LIMIT 5
```

**Как интерпретировать**: median_days_to_lead показывает типичное время до лида (медиана устойчивее среднего). total_days_to_crm — полный цикл от первого визита до CRM-сделки. Это критично для планирования: если запустили кампанию сегодня, результат по CRM будет через ~total_days_to_crm дней.

### 5. Свежие когорты — ранний сигнал

**Когда спрашивают**: "Как свежий трафик конвертируется?", "Есть ранние сигналы по новым кампаниям?"

**Запрос**:
```sql
SELECT
    cohort_week,
    cohort_age_days,
    new_clients,
    clients_with_lead,
    lead_rate_pct
FROM magnetto.dm_funnel_velocity
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_funnel_velocity)
  AND cohort_age_days BETWEEN 7 AND 30
ORDER BY cohort_week DESC
```

**Как интерпретировать**: для свежих когорт CRM-конверсия ещё не показательна (цикл 70 дней), но lead_rate_pct уже виден. Если у новой когорты lead_rate выше средней — хороший ранний сигнал.
