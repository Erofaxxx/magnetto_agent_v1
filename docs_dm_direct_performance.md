# dm_direct_performance

## Назначение

Основная витрина статистики Яндекс Директа. Ежедневный срез показателей по каждой паре кампания × группа объявлений × тип сети. Охватывает весь путь от показа до оплаченной сделки: показы → клики → сессии → лиды → CRM создан → CRM оплачен. Это первое место, куда смотрит агент при любом вопросе о результатах рекламы.

## Источник данных и покрытие

- Источник: `magnetto.direct_custom_report` (выгрузка из Яндекс Директ API)
- Обновление: `REFRESH EVERY 1 DAY OFFSET 3 HOUR` — данные актуальны с утра
- Данные с: **01.11.2025**
- Кампании: 10 активных кампаний, 48 групп объявлений
- Типы сети: **SEARCH** (поиск) и **AD_NETWORK** (РСЯ)

## Гранулярность

Одна строка = **один день × одна кампания × одна группа × один тип сети**.

Это значит:
- Для агрегации по кампании — `GROUP BY campaign_id`
- Для агрегации по дню — `GROUP BY date`
- Для сравнения поиска и РСЯ — `GROUP BY ad_network_type`
- Для уровня группы — `GROUP BY adgroup_id`

## Структура таблицы

| Поле | Тип | Описание |
|------|-----|----------|
| date | Date | Дата (день) |
| campaign_id | UInt64 | ID кампании — JOIN с campaigns_settings |
| campaign_name | String | Название кампании |
| adgroup_id | UInt64 | ID группы — JOIN с adgroups_settings |
| adgroup_name | String | Название группы |
| ad_network_type | String | SEARCH / AD_NETWORK |
| impressions | UInt64 | Показы рекламы |
| clicks | UInt64 | Клики по объявлениям |
| cost | Float64 | Расход (руб, с НДС) |
| sessions | UInt64 | Сессии на сайте (из Метрики) |
| bounces | UInt64 | Отказы (из Метрики) |
| purchase_revenue | Float64 | Выручка (атрибуция Директа) |
| purchase_profit | Float64 | Прибыль (атрибуция Директа) |
| leads_all | UInt64 | Все лиды — цель 314553735 |
| unique_calls | UInt64 | Уникальный звонок — цель 201619840 |
| targeted_calls | UInt64 | Уникально-целевой звонок — цель 201619843 |
| order_created | UInt64 | CRM: Заказ создан — цель 332069613 |
| order_paid | UInt64 | CRM: Заказ оплачен — цель 332069614 |
| form_submissions | UInt64 | Автоцель: отправка формы — цель 322914144 |
| phone_clicks | UInt64 | Клик по телефону — цель 314248561 |
| quiz_completed | UInt64 | Прошёл квиз — цель 321286959 |
| spam_traffic | UInt64 | Мусорный трафик (сумма спам-целей) |

## Воронка конверсий

```
impressions → clicks → sessions → leads_all → order_created → order_paid
  9.8M          540K      ≈500K       200            33              8
```

Статистика за всё время (ноябрь 2025 — апрель 2026):
- Общий расход: **1 783 271 руб**
- Лиды: **200** (CPL ≈ 8 916 руб)
- CRM создан: **33** (CPA ≈ 54 038 руб)
- CRM оплачен: **8** (CPO ≈ 222 909 руб)
- Конверсия лид → CRM: **16.5%**

### Состав лидов

`leads_all` — агрегированная цель, в неё входят все виды лидов. Детализация по типам:
- `unique_calls` — уникальные звонки (телефония)
- `targeted_calls` — целевые звонки (длиннее порога)
- `form_submissions` — отправки форм
- `phone_clicks` — клики по кнопке телефона (мобильный трафик)

Сумма `unique_calls + form_submissions` ≠ `leads_all` — там другая методология атрибуции в Метрике.

## Поиск vs РСЯ — ключевые различия

|  | SEARCH | AD_NETWORK |
|--|--------|------------|
| Расход | 444 422 руб | 1 338 849 руб |
| Клики | 2 673 | 537 366 |
| CPC | ~166 руб | ~2.5 руб |
| Лиды | 23 | 177 |
| CPL | ~19 305 руб | ~7 564 руб |
| CRM создан | 22 | 11 |
| Спам | 16 | 93 376 |

**Поиск** — дорогой трафик, высокая конверсионность, минимум спама.
**РСЯ** — дешёвый клик, огромный объём, но ~17% трафика — спам. Большой объём лидов, но конверсия в CRM ниже.

## Метрики, которые агент считает сам

Эти поля не хранятся в таблице — вычисляются в запросе:

| Метрика | Формула |
|---------|---------|
| CTR | `clicks / nullIf(impressions, 0) * 100` |
| CPC | `cost / nullIf(clicks, 0)` |
| CPL | `cost / nullIf(leads_all, 0)` |
| CPA (CRM создан) | `cost / nullIf(order_created, 0)` |
| CPO (CRM оплачен) | `cost / nullIf(order_paid, 0)` |
| Доля сессий | `sessions / nullIf(clicks, 0) * 100` |
| Bounce rate | `bounces / nullIf(sessions, 0) * 100` |
| CR лид | `leads_all / nullIf(sessions, 0) * 100` |
| Конверсия лид→CRM | `order_created / nullIf(leads_all, 0) * 100` |
| Доля спама | `spam_traffic / nullIf(clicks, 0) * 100` |

Всегда использовать `nullIf(..., 0)` в знаменателе — в таблице бывают дни без кликов/лидов.

## Нюансы и подводные камни

### adgroup_name = '0' и adgroup_id = 0
В части строк группа не определена — это записи на уровне кампании без разбивки по группе (обычно из кампаний типа «Товарная» или «Медийная», где группы не фиксируются на уровне API). При агрегации по кампании это не мешает — просто GROUP BY campaign_id.

### spam_traffic — отдельная история для РСЯ
В РСЯ `spam_traffic` составляет ~17% от всех кликов (93 376 из 537 366). Это цели Метрики, помечающие роботный/нецелевой трафик. При расчёте реального CPL для РСЯ можно скорректировать:

```sql
(clicks - spam_traffic) AS clean_clicks,
cost / nullIf(clicks - spam_traffic, 0) AS real_cpc
```

### purchase_revenue и purchase_profit — атрибуция Директа
Это не CRM-данные, а атрибуция Яндекс Директа по модели, настроенной в кампании. Могут расходиться с фактическими данными CRM. Для оценки реальной выручки ориентироваться на `order_created` и `order_paid`.

### Данные за сегодня
Данные обновляются в 03:00. За текущий день данных нет или они неполные — фильтровать `WHERE date < today()`.

## Текущие кампании (за всё время)

| Кампания | Расход | Лиды | CRM создан | Спам |
|----------|--------|------|------------|------|
| Товарная COSTURA TOWN | 666 702 | 65 | 20 | 39 327 |
| COSTURA/Конкуренты/РСЯ | 593 492 | 75 | 1 | 33 359 |
| COSTURA/Дорогие покупки/РСЯ | 203 492 | 37 | 2 | 12 118 |
| COSTURA/Брендовые/Поиск | 187 091 | 6 | 7 | 4 |
| Копия Конкуренты/РСЯ | 87 838 | 5 | 2 | 3 630 |
| Брендовые/РСЯ 2вер | 20 107 | 6 | 0 | 2 763 |
| Медийная Costura Town | 8 810 | 3 | 1 | 525 |
| *(остальные)* | ~22 000 | ~3 | — | — |

## Помесячная динамика

| Месяц | Расход | Клики | Лиды | CRM создан | Спам |
|-------|--------|-------|------|------------|------|
| Ноябрь 2025 | 207 125 | 77 166 | 27 | 3 | 9 383 |
| Декабрь 2025 | 541 612 | 144 572 | 40 | 10 | 23 756 |
| Январь 2026 | 304 281 | 108 421 | 30 | 4 | 27 975 |
| Февраль 2026 | 331 134 | 92 198 | 40 | 9 | 11 854 |
| Март 2026 | 319 378 | 93 304 | 54 | 6 | 16 390 |
| Апрель 2026 | 79 740 | 24 378 | 9 | 1 | 4 034 |

Март — лучший месяц по лидам (54). Декабрь — пиковый расход (541К).

## Сценарии использования для AI-агента

### 1. Общий результат Директа за период

**Триггеры**: "Как работает Директ?", "Итоги за месяц", "Сколько потратили и что получили?"

```sql
SELECT
    sum(impressions)                                          AS impressions,
    sum(clicks)                                               AS clicks,
    round(sum(cost), 0)                                       AS cost,
    sum(leads_all)                                            AS leads,
    sum(order_created)                                        AS crm_created,
    sum(order_paid)                                           AS crm_paid,
    round(sum(cost) / nullIf(sum(clicks), 0), 2)             AS cpc,
    round(sum(cost) / nullIf(sum(leads_all), 0), 0)          AS cpl,
    round(sum(cost) / nullIf(sum(order_created), 0), 0)      AS cpa_crm,
    round(sum(leads_all) / nullIf(sum(sessions), 0) * 100, 2) AS cr_lead_pct,
    sum(spam_traffic)                                         AS spam
FROM magnetto.dm_direct_performance
WHERE date >= today() - 30
  AND date < today()
```

### 2. Сравнение кампаний по эффективности

**Триггеры**: "Какая кампания лучше?", "Сравни кампании по CPL", "Где лучший ROI?"

```sql
SELECT
    campaign_name,
    ad_network_type,
    round(sum(cost), 0)                                       AS cost,
    sum(clicks)                                               AS clicks,
    sum(leads_all)                                            AS leads,
    sum(order_created)                                        AS crm_created,
    round(sum(cost) / nullIf(sum(leads_all), 0), 0)          AS cpl,
    round(sum(cost) / nullIf(sum(order_created), 0), 0)      AS cpa_crm,
    round(sum(spam_traffic) / nullIf(sum(clicks), 0) * 100, 1) AS spam_pct
FROM magnetto.dm_direct_performance
WHERE date >= today() - 30
  AND date < today()
GROUP BY campaign_id, campaign_name, ad_network_type
ORDER BY cost DESC
```

### 3. Поиск vs РСЯ — сравнение каналов

**Триггеры**: "Что лучше — поиск или РСЯ?", "Сравни каналы", "Где дешевле лиды?"

```sql
SELECT
    ad_network_type,
    round(sum(cost), 0)                                  AS cost,
    sum(clicks)                                          AS clicks,
    sum(leads_all)                                       AS leads,
    sum(order_created)                                   AS crm_created,
    round(sum(cost) / nullIf(sum(clicks), 0), 2)        AS cpc,
    round(sum(cost) / nullIf(sum(leads_all), 0), 0)     AS cpl,
    round(sum(cost) / nullIf(sum(order_created), 0), 0) AS cpa_crm,
    sum(spam_traffic)                                    AS spam,
    round(sum(spam_traffic) / nullIf(sum(clicks), 0) * 100, 1) AS spam_pct
FROM magnetto.dm_direct_performance
WHERE date >= today() - 30
  AND date < today()
GROUP BY ad_network_type
ORDER BY cost DESC
```

### 4. Помесячная динамика — тренд

**Триггеры**: "Динамика по месяцам", "Растут или падают лиды?", "Тренд расхода"

```sql
SELECT
    toStartOfMonth(date)                                      AS month,
    round(sum(cost), 0)                                       AS cost,
    sum(clicks)                                               AS clicks,
    sum(leads_all)                                            AS leads,
    sum(order_created)                                        AS crm_created,
    round(sum(cost) / nullIf(sum(leads_all), 0), 0)          AS cpl,
    round(sum(spam_traffic) / nullIf(sum(clicks), 0) * 100, 1) AS spam_pct
FROM magnetto.dm_direct_performance
WHERE date < today()
GROUP BY month
ORDER BY month
```

### 5. Ежедневный расход — последние N дней

**Триггеры**: "Сколько тратим в день?", "Расход за последнюю неделю", "Дневная динамика"

```sql
SELECT
    date,
    round(sum(cost), 0)   AS cost,
    sum(clicks)           AS clicks,
    sum(leads_all)        AS leads,
    sum(order_created)    AS crm_created,
    sum(spam_traffic)     AS spam
FROM magnetto.dm_direct_performance
WHERE date >= today() - 14
  AND date < today()
GROUP BY date
ORDER BY date DESC
```

### 6. Группы объявлений по эффективности внутри кампании

**Триггеры**: "Какие группы лучше работают в кампании X?", "Детализация по группам"

```sql
SELECT
    adgroup_name,
    round(sum(cost), 0)                                  AS cost,
    sum(clicks)                                          AS clicks,
    sum(leads_all)                                       AS leads,
    round(sum(cost) / nullIf(sum(leads_all), 0), 0)     AS cpl,
    round(sum(bounces) / nullIf(sum(sessions), 0) * 100, 1) AS bounce_pct,
    sum(spam_traffic)                                    AS spam
FROM magnetto.dm_direct_performance
WHERE date >= today() - 30
  AND date < today()
  AND campaign_name ILIKE '%<название>%'
  AND adgroup_id != 0
GROUP BY adgroup_id, adgroup_name
ORDER BY cost DESC
```

### 7. Воронка — конверсия по этапам

**Триггеры**: "Покажи воронку", "Где теряем больше всего?", "CR лид в CRM"

```sql
SELECT
    sum(impressions)                                              AS impressions,
    sum(clicks)                                                   AS clicks,
    sum(sessions)                                                 AS sessions,
    sum(leads_all)                                                AS leads,
    sum(order_created)                                            AS crm_created,
    sum(order_paid)                                               AS crm_paid,
    round(sum(clicks) / nullIf(sum(impressions), 0) * 100, 2)   AS ctr_pct,
    round(sum(sessions) / nullIf(sum(clicks), 0) * 100, 1)      AS session_rate_pct,
    round(sum(leads_all) / nullIf(sum(sessions), 0) * 100, 2)   AS cr_lead_pct,
    round(sum(order_created) / nullIf(sum(leads_all), 0) * 100, 1) AS cr_crm_pct,
    round(sum(order_paid) / nullIf(sum(order_created), 0) * 100, 1) AS cr_paid_pct
FROM magnetto.dm_direct_performance
WHERE date >= today() - 30
  AND date < today()
```

### 8. Качество трафика — сессии, отказы, спам

**Триггеры**: "Какой трафик качественный?", "Где больше всего мусора?", "Процент отказов по кампаниям"

```sql
SELECT
    campaign_name,
    ad_network_type,
    sum(clicks)                                                    AS clicks,
    sum(sessions)                                                  AS sessions,
    round(sum(sessions) / nullIf(sum(clicks), 0) * 100, 1)       AS session_rate_pct,
    round(sum(bounces) / nullIf(sum(sessions), 0) * 100, 1)      AS bounce_pct,
    sum(spam_traffic)                                              AS spam,
    round(sum(spam_traffic) / nullIf(sum(clicks), 0) * 100, 1)   AS spam_pct
FROM magnetto.dm_direct_performance
WHERE date >= today() - 30
  AND date < today()
GROUP BY campaign_id, campaign_name, ad_network_type
ORDER BY spam_pct DESC
```

### 9. Состав лидов — из чего складываются конверсии

**Триггеры**: "Откуда берутся лиды?", "Соотношение звонков и форм", "Типы конверсий"

```sql
SELECT
    sum(leads_all)       AS leads_all,
    sum(unique_calls)    AS unique_calls,
    sum(targeted_calls)  AS targeted_calls,
    sum(form_submissions) AS forms,
    sum(phone_clicks)    AS phone_clicks,
    sum(quiz_completed)  AS quiz,
    sum(order_created)   AS crm_created,
    sum(order_paid)      AS crm_paid
FROM magnetto.dm_direct_performance
WHERE date >= today() - 30
  AND date < today()
```

### 10. Связь с настройками кампании — стратегия + результат

**Триггеры**: "Какой CPL у кампаний с автостратегией?", "Сравни стратегии по эффективности"

```sql
SELECT
    c.strategy_search_type,
    count(DISTINCT p.campaign_id)                            AS campaigns,
    round(sum(p.cost), 0)                                    AS cost,
    sum(p.leads_all)                                         AS leads,
    round(sum(p.cost) / nullIf(sum(p.leads_all), 0), 0)     AS cpl
FROM magnetto.dm_direct_performance p
JOIN magnetto.campaigns_settings c USING (campaign_id)
WHERE p.date >= today() - 30
  AND p.date < today()
GROUP BY c.strategy_search_type
ORDER BY cpl
```

### 11. Сравнение двух периодов — было vs стало

**Триггеры**: "Сравни с прошлым месяцем", "Изменились ли показатели?", "До и после изменений"

```sql
SELECT
    if(date >= today() - 30, 'текущий', 'предыдущий') AS period,
    round(sum(cost), 0)                                AS cost,
    sum(leads_all)                                     AS leads,
    round(sum(cost) / nullIf(sum(leads_all), 0), 0)   AS cpl,
    sum(order_created)                                 AS crm_created
FROM magnetto.dm_direct_performance
WHERE date >= today() - 60
  AND date < today()
GROUP BY period
ORDER BY period DESC
```

## Таблица триггеров

| Вопрос агента | Что смотреть |
|---------------|--------------|
| "Итоги Директа" | Суммы за период: cost, leads, crm_created, cpl, cpa |
| "Какая кампания лучше?" | GROUP BY campaign_id, ORDER BY cpl / crm_created |
| "Поиск vs РСЯ" | GROUP BY ad_network_type |
| "Динамика по месяцам" | GROUP BY toStartOfMonth(date) |
| "Дневной расход" | GROUP BY date, ORDER BY date DESC |
| "Воронка конверсий" | impressions → clicks → sessions → leads → crm_created → crm_paid |
| "Где мусор / спам?" | spam_traffic / clicks * 100, ORDER BY spam_pct DESC |
| "Состав лидов" | unique_calls, form_submissions, phone_clicks |
| "Качество трафика" | bounces / sessions, sessions / clicks |
| "Связать с настройками" | JOIN с campaigns_settings / adgroups_settings по campaign_id / adgroup_id |
| "Данные за сегодня" | Не использовать — данные обновляются в 03:00 |
