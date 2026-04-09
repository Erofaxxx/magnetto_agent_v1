# bad_queries

## Назначение

Ежедневный рейтинг поисковых запросов (search terms), по которым была показана реклама. В отличие от `bad_keywords` (фразы, которые мы добавили сами), здесь — реальные запросы пользователей, которые Яндекс сматчил с нашими ключами. Позволяет находить нецелевые запросы для добавления в минус-слова, обнаруживать хронические источники пустого трафика и выявлять запросы, которые стабильно дают конверсии.

## Источник данных и окно

- Таблица: `magnetto.direct_search_queries_goals`
- Окно: **180 дней** (в два раза больше, чем у keywords и placements — запросы накапливают данные медленнее)
- Фильтр: только записи с `Clicks > 0`
- Обновление: `REFRESH EVERY 1 DAY OFFSET 3 HOUR`

## Ключевые метрики

### goal_score — расширенный взвешенный балл

Для запросов используется более широкая палитра целей, чем для ключей и площадок:

| Уровень | Вес | Цели |
|---------|-----|------|
| Макро (tier 1) | ×10 | Все лиды, уникальный/целевой/целевой звонок, Звонок, CRM создан/оплачен, Заявка на тендер, Начало оформления заказа |
| Микро (tier 2) | ×3 | Отправка формы, клик по номеру, Заполнил контакты, Отправил контакты, Отправка формы телефон, клик по телефону (моб.), клик по телефону Magnetto, Скачать презентацию, Скачивание файла, Отправка формы ипотека |
| Слабые (tier 3) | ×1 | Добавить в избранное |

Итого 20 целей против 10 в `bad_keywords` — запросы оцениваются полнее.

`goal_score_rate = goal_score / clicks` — конверсионность запроса на клик (не умножается на 100, в отличие от keywords).

### is_chronic и is_recent

- `is_recent = 1` — запрос показывался в последние 20 дней (актуален)
- `is_chronic = 1` — запрос активен 14+ дней (`days_active >= 14`): появляется систематически, а не разово
- `days_active` — количество уникальных дат, когда был хотя бы один клик

Хронический нецелевой запрос (`is_chronic = 1`, `goal_score = 0`) — первый кандидат в минус-слова.

### matched_keyword
Ключевая фраза, с которой сматчился запрос. Помогает понять: это проблема конкретного ключа или широкое несоответствие группы.

### Бенчмарки по кампании

- `bench_roas` — средний ROAS по кампании (взвешенный по кликам)
- `bench_goal_score` — средний goal_score на клик по кампании
- `goal_rate_deviation` — отклонение запроса от бенчмарка: `-1.0` если конверсий нет
- `roas_deviation` — отклонение ROAS: `-1.0` если выручки нет

## Автоматический вердикт (zone_status + zone_reason)

### pending
Запрос неактуален (`is_recent = 0`) или данных мало (`clicks < 5` или `cost < 200`).

### green — конвертирующий запрос
Любое из условий:
- ROAS > 2 — прямая окупаемость
- `goal_rate_deviation >= 0` И `goal_score >= 20` — запрос конвертирует не хуже среднего И набрал значимый балл

`zone_reason`: `g:roas>2`, `g:gdev>=0+gs>=20`.

### red — проблемный запрос, добавить в минус-слова
Любое из условий:
- Отказов > 90% И нет выручки — явно нецелевая аудитория
- Отказов > 60% И нет выручки И goal_rate_deviation < −0.5 — нецелевой трафик с большим отрывом хуже медианы
- Нет конверсий вообще И расход > 400 руб

`zone_reason`: `r:bounce>90+no_roas`, `r:bounce>60+no_roas+gdev<-0.5`, `r:no_goals+cost>400`.

### yellow — неоднозначный запрос
Не дотянул до green, не провалился до red. Требует контекстного суждения.

## Когда zone_status можно пересмотреть

- **Информационные запросы в yellow** — «сколько стоит квартира в казани», «планировка двушки» — не конвертируют напрямую, но это потенциальные клиенты на ранней стадии. Агент может оценить their контекст, а не только метрики
- **Запросы конкурентов в yellow/red** — «ЖК Водный мир цены» — нецелевые для нашего ЖК, однозначно в минус, даже если cost < 400
- **Брендовые запросы в любом статусе** — «Magnetto» или «Costura Town» — не должны попадать в минус-слова ни при каком раскладе
- **Хронический red с низким расходом** — `is_chronic = 1`, cost = 50 руб — алгоритм ставит pending (cost < 200), но это систематическая проблема

В таких случаях агент смотрит на `Query`, `matched_keyword`, `bounce_rate`, `days_active`, `is_chronic` и выносит суждение самостоятельно.

## Структура таблицы

| Поле | Тип | Описание |
|------|-----|----------|
| report_date | Date | Дата расчёта |
| Query | String | Реальный поисковый запрос пользователя |
| CriterionType | String | Тип таргетинга (KEYWORD / AUTOTARGETING и др.) |
| TargetingCategory | String | Категория автотаргетинга (если применимо) |
| CampaignId | UInt64 | ID кампании |
| CampaignName | String | Название кампании |
| matched_keyword | String | Ключ, с которым сматчился запрос |
| clicks | UInt64 | Клики за 180 дней |
| impressions | UInt64 | Показы |
| cost | Float64 | Расход (руб) |
| ctr | Nullable(Float64) | CTR (%) |
| cpc | Nullable(Float64) | CPC (руб) |
| bounce_rate | Nullable(Float64) | Доля отказов (%) |
| days_active | UInt64 | Дней с хотя бы одним кликом |
| is_chronic | UInt8 | 1 = активен 14+ дней |
| is_recent | UInt8 | 1 = активен в последние 20 дней |
| purchase_revenue | Float64 | Выручка (атрибуция Директа) |
| roas | Nullable(Float64) | Выручка / расход |
| goal_score | Float64 | Взвешенный балл конверсий |
| goal_score_rate | Nullable(Float64) | goal_score на клик |
| goal_rate_deviation | Nullable(Float64) | Отклонение от бенчмарка кампании |
| roas_deviation | Nullable(Float64) | Отклонение ROAS от бенчмарка |
| bench_roas | Nullable(Float64) | Средний ROAS по кампании |
| bench_goal_score | Nullable(Float64) | Средний goal_score на клик по кампании |
| zone_status | String | green / yellow / red / pending |
| zone_reason | String | Машиночитаемая причина вердикта |

## Сценарии использования для AI-агента

### 1. Красные запросы — кандидаты в минус-слова

**Триггеры**: "Какие запросы добавить в минус-слова?", "Нецелевые поисковые запросы", "Что чистить?"

```sql
SELECT
    Query, matched_keyword, CampaignName,
    clicks, cost, bounce_rate,
    goal_score, days_active, is_chronic,
    zone_reason
FROM magnetto.bad_queries
WHERE zone_status = 'red'
ORDER BY cost DESC
LIMIT 30
```

### 2. Хронические нецелевые запросы — системная проблема

**Триггеры**: "Есть ли запросы, которые всё время тратят бюджет без конверсий?", "Хронические минус-слова"

```sql
SELECT
    Query, matched_keyword, CampaignName,
    days_active, clicks, cost,
    goal_score, bounce_rate, zone_status
FROM magnetto.bad_queries
WHERE is_chronic = 1
  AND goal_score = 0
  AND is_recent = 1
ORDER BY cost DESC
```

### 3. Запросы, которые хорошо конвертируют — добавить как ключи

**Триггеры**: "Какие запросы хорошо работают?", "Запросы для расширения семантики", "Что добавить в ключи?"

```sql
SELECT
    Query, matched_keyword, CampaignName,
    clicks, cost, roas, goal_score,
    goal_score_rate, bench_goal_score,
    round(goal_rate_deviation * 100, 0) AS deviation_pct,
    zone_reason
FROM magnetto.bad_queries
WHERE zone_status = 'green'
ORDER BY goal_score DESC
```

### 4. Запросы с высоким bounce_rate — некачественный трафик

**Триггеры**: "Запросы с высоким процентом отказов", "Где плохая посадочная или нецелевой трафик?"

```sql
SELECT
    Query, matched_keyword, CampaignName,
    clicks, bounce_rate, cost,
    goal_score, zone_status
FROM magnetto.bad_queries
WHERE bounce_rate > 70
  AND is_recent = 1
  AND clicks >= 5
ORDER BY bounce_rate DESC
```

### 5. Запросы, сматченные через автотаргетинг

**Триггеры**: "Какие запросы приходят через автотаргетинг?", "Что притягивает автотаргетинг?"

```sql
SELECT
    Query, TargetingCategory, CampaignName,
    clicks, cost, bounce_rate,
    goal_score, zone_status, zone_reason
FROM magnetto.bad_queries
WHERE CriterionType = 'AUTOTARGETING'
  AND is_recent = 1
ORDER BY cost DESC
```

### 6. Запросы по ключу — что реально ищут по фразе

**Триггеры**: "Что ищут по ключу 'купить квартиру казань'?", "Какие запросы сматчились с ключом X?"

```sql
SELECT
    Query, clicks, cost, bounce_rate,
    goal_score, zone_status
FROM magnetto.bad_queries
WHERE matched_keyword ILIKE '%<ключ>%'
ORDER BY cost DESC
```

### 7. Запросы по кампании — полный срез

**Триггеры**: "Поисковые запросы кампании X", "Какой трафик идёт в кампанию Y?"

```sql
SELECT
    zone_status,
    count()        AS queries,
    sum(cost)      AS total_cost,
    sum(goal_score) AS total_gs,
    round(avg(bounce_rate), 1) AS avg_bounce
FROM magnetto.bad_queries
WHERE CampaignName ILIKE '%<название>%'
  AND is_recent = 1
GROUP BY zone_status
ORDER BY total_cost DESC
```

## Таблица триггеров

| Вопрос агента | Что смотреть |
|---------------|--------------|
| "Минус-слова / нецелевые запросы" | `zone_status = 'red'`, ORDER BY cost DESC |
| "Хронические проблемы" | `is_chronic = 1 AND goal_score = 0` |
| "Запросы для расширения семантики" | `zone_status = 'green'` |
| "Высокий bounce по запросам" | `bounce_rate > 70 AND is_recent = 1` |
| "Автотаргетинг что притягивает?" | `CriterionType = 'AUTOTARGETING'` |
| "Что ищут по ключу X?" | `matched_keyword ILIKE '%X%'` |
| "Запросы кампании X" | `CampaignName ILIKE '%X%'` |
| "Почему запрос красный?" | `zone_reason` — код причины |
| "Сколько дней запрос активен?" | `days_active`, `is_chronic` |
