# bad_placements

## Назначение

Ежедневный рейтинг площадок РСЯ по эффективности. Для каждой площадки (сайта или приложения, где показывалась реклама) рассчитаны метрики за 60 дней, отклонение от эталона по кампании и автоматический вердикт. Позволяет находить площадки, которые дают дорогой или нецелевой трафик, и площадки-лидеры, которые стоит масштабировать.

## Источник данных и окно

- Таблица: `magnetto.direct_custom_report`
- Фильтр: только `AdNetworkType = 'AD_NETWORK'` (только РСЯ; поиск не входит)
- Окно: **60 дней** скользящих от последней даты в отчёте
- Обновление: `REFRESH EVERY 1 DAY OFFSET 3 HOUR`

## Ключевые метрики

### goal_score — взвешенный балл конверсий

| Уровень | Вес | Цели |
|---------|-----|------|
| Макро (tier 1) | ×10 | Все лиды, уникальный/целевой звонок, CRM создан/оплачен |
| Микро (tier 2) | ×3 | Отправка формы, клик по телефону |
| Слабые (tier 3) | ×1 | Скачать презентацию |

`goal_score_rate = (goal_score / clicks) × 100` — конверсионность площадки на клик.

### Бенчмарки — эталон по кампании

Для каждой кампании считаются собственные эталоны **взвешенные по кликам**:

- `avg_cpc_campaign` — средний CPC по кампании (все площадки)
- `bench_roas_campaign` — средний ROAS по кампании
- `bench_goal_score_rate` — средний goal_score_rate по кампании

Отклонения считаются именно от этих значений, а не от аккаунтовых.

### is_recent
`1` = площадка активна в последние 20 дней. `0` = площадка давно не показывалась — вердикт теряет актуальность.

### Отклонения

- `cpc_deviation` — насколько CPC площадки выше/ниже среднего по кампании: `+0.5` = дороже на 50%, `-0.3` = дешевле на 30%
- `goal_rate_deviation` — отклонение goal_score_rate от бенчмарка кампании: `-1.0` если конверсий нет
- `roas_deviation` — отклонение ROAS: `-1.0` если выручки нет

## Автоматический вердикт (zone_status + zone_reason)

Вердикт — стартовая точка для анализа. Алгоритм консервативен: при недостатке данных ставит `pending`.

### pending
Площадка неактивна (`is_recent = 0`) ИЛИ данных мало (`clicks < 10` или `cost < 200`).

### red — исключить или проверить
Любое из условий:
- Нет целевых действий и нет выручки при расходе > 400 руб
- CPC втрое выше среднего по кампании — и ни одной конверсии
- Нет выручки, расход > 250, goal_score_rate вдвое ниже бенчмарка

`zone_reason` объясняет конкретную причину: `r:no_goals+cost>400`, `r:cpc>3x+no_goals`, `r:no_roas+low_gsr+cost>250`.

### green — перспективная площадка
Любое из условий:
- ROAS от 2 до 50 при CPC не выше 1.5× среднего — нормальная окупаемость
- ROAS > 50 — выдающийся результат
- goal_score_rate в 3–5× выше бенчмарка при нормальном CPC
- goal_score_rate в 5× и более выше бенчмарка — вне зависимости от CPC

`zone_reason`: `g:roas_2-50+cpc_ok`, `g:roas>50`, `g:gsr_3-5x+cpc_ok`, `g:gsr>5x`.

### yellow — неоднозначно
Всё, что не попало в red и green. Площадка не провалилась, но и не показала явного результата. Требует контекстного суждения.

## Когда zone_status можно пересмотреть

- **Площадка в red, но это нишевый профильный сайт** — может давать качественную аудиторию с долгим циклом, конверсий в окне 60 дней нет, но трафик целевой
- **Площадка в pending из-за is_recent = 0** — показывалась полгода назад и дала хорошие результаты; возможно, стоит проверить, не исключена ли она случайно
- **Площадка в yellow с высоким bounce_rate** — алгоритм не смотрит на bounce_rate при выставлении yellow; агент может сам принять решение, что это red
- **Площадки-агрегаторы недвижимости** (cian.ru, avito.ru) — у них особая логика: высокий CPC, но качественный трафик. Смотреть на `tier12` конверсии вручную

В этих случаях агент смотрит на `goal_score`, `bounce_rate`, `cost`, `cpc_deviation` и даёт своё суждение поверх `zone_status`.

## Структура таблицы

| Поле | Тип | Описание |
|------|-----|----------|
| report_date | Date | Дата расчёта |
| Placement | String | Домен или ID приложения |
| CampaignId | UInt64 | ID кампании |
| CampaignName | String | Название кампании |
| cost | Float64 | Расход (руб) за 60 дней |
| clicks | UInt64 | Клики |
| impressions | UInt64 | Показы |
| cpc | Nullable(Float64) | Фактический CPC (руб) |
| purchase_revenue | Float64 | Выручка (атрибуция Директа) |
| roas | Nullable(Float64) | Выручка / расход |
| goal_score | Float64 | Взвешенный балл конверсий |
| goal_score_rate | Nullable(Float64) | goal_score на 100 кликов |
| bounces | UInt64 | Отказы |
| bounce_rate | Nullable(Float64) | Доля отказов (%) |
| is_recent | UInt8 | 1 = активна в последние 20 дней |
| cpc_deviation | Nullable(Float64) | Отклонение CPC от среднего по кампании |
| goal_rate_deviation | Nullable(Float64) | Отклонение goal_score_rate от бенчмарка |
| roas_deviation | Nullable(Float64) | Отклонение ROAS от бенчмарка |
| avg_cpc_campaign | Nullable(Float64) | Средний CPC по кампании (эталон) |
| bench_roas_campaign | Nullable(Float64) | Средний ROAS по кампании (эталон) |
| bench_goal_score_rate | Nullable(Float64) | Средний goal_score_rate по кампании (эталон) |
| zone_status | String | green / yellow / red / pending |
| zone_reason | String | Машиночитаемая причина вердикта |

## Сценарии использования для AI-агента

### 1. Красные площадки с большим расходом — к исключению

**Триггеры**: "Какие площадки плохие?", "Что исключить из РСЯ?", "Площадки без конверсий"

```sql
SELECT
    Placement, CampaignName,
    cost, clicks, cpc, avg_cpc_campaign,
    goal_score, bounce_rate,
    zone_reason
FROM magnetto.bad_placements
WHERE zone_status = 'red'
ORDER BY cost DESC
LIMIT 30
```

### 2. Зелёные площадки — масштабировать или добавить в whitelist

**Триггеры**: "Лучшие площадки РСЯ", "Где хорошо конвертируют?", "Площадки для масштабирования"

```sql
SELECT
    Placement, CampaignName,
    cost, clicks, roas, goal_score_rate,
    bench_goal_score_rate,
    round(goal_rate_deviation * 100, 0) AS gsr_deviation_pct,
    zone_reason
FROM magnetto.bad_placements
WHERE zone_status = 'green'
ORDER BY goal_score_rate DESC
```

### 3. Дорогие площадки без конверсий (высокий CPC + нет результата)

**Триггеры**: "Где переплачиваем в РСЯ?", "Площадки с дорогими кликами без отдачи"

```sql
SELECT
    Placement, CampaignName,
    cpc, avg_cpc_campaign,
    round(cpc_deviation * 100, 0) AS cpc_overpay_pct,
    goal_score, cost, zone_status
FROM magnetto.bad_placements
WHERE cpc_deviation > 0.5
  AND goal_score = 0
  AND zone_status != 'pending'
ORDER BY cpc_deviation DESC
```

### 4. Площадки с высоким bounce_rate

**Триггеры**: "Где некачественный трафик в РСЯ?", "Высокий процент отказов по площадкам"

```sql
SELECT
    Placement, CampaignName,
    clicks, bounce_rate, cost,
    goal_score, roas, zone_status
FROM magnetto.bad_placements
WHERE bounce_rate > 70
  AND is_recent = 1
  AND clicks >= 10
ORDER BY bounce_rate DESC
```

### 5. Площадки по конкретной кампании

**Триггеры**: "Площадки РСЯ в кампании X", "Где показывается реклама ЖК Costura?"

```sql
SELECT
    Placement, cost, clicks, roas,
    goal_score_rate, bench_goal_score_rate,
    bounce_rate, zone_status, zone_reason
FROM magnetto.bad_placements
WHERE CampaignName ILIKE '%<название>%'
ORDER BY cost DESC
```

### 6. Неактивные площадки, которые когда-то были красными

**Триггеры**: "Есть ли площадки, которые исключили давно?", "Что в pending с плохой историей?"

```sql
SELECT
    Placement, CampaignName,
    cost, clicks, goal_score, roas,
    is_recent, zone_status, zone_reason
FROM magnetto.bad_placements
WHERE is_recent = 0
  AND goal_score = 0
  AND cost > 300
ORDER BY cost DESC
```

## Таблица триггеров

| Вопрос агента | Что смотреть |
|---------------|--------------|
| "Плохие площадки / что исключить?" | `zone_status = 'red'`, ORDER BY cost DESC |
| "Лучшие площадки / масштабировать" | `zone_status = 'green'`, ORDER BY goal_score_rate DESC |
| "Где переплачиваем?" | `cpc_deviation > 0.5` |
| "Некачественный трафик?" | `bounce_rate > 70 AND is_recent = 1` |
| "Площадки без отдачи с расходом" | `goal_score = 0 AND cost > 400 AND is_recent = 1` |
| "Площадки кампании X" | `CampaignName ILIKE '%X%'` |
| "Почему площадка красная?" | `zone_reason` — машиночитаемый код причины |
| "Площадка конкурирует с поиском?" | Этих данных нет — только РСЯ |
