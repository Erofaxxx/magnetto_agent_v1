# dm_path_templates

## Назначение

Группирует клиентов по дедуплицированным цепочкам каналов и показывает, какие последовательности каналов приводят к конверсии, с какой вероятностью и за какую стоимость.

## Какую проблему решает

Стандартная атрибуция (last click, first click) приписывает конверсию одному каналу. В реальности клиент девелопера проходит путь из нескольких касаний: сначала нашёл через органику, потом увидел рекламу, потом вернулся через органику и оставил заявку. Витрина показывает эти цепочки целиком и сравнивает их по эффективности.

Это критично для бюджетирования: если путь ['organic', 'ad', 'organic'] конвертирует в 5%, а ['ad'] — в 0.014%, то реклама работает как подогрев внутри мульти-канального пути, а не как самостоятельный канал.

## Источник данных

- `magnetto.dm_conversion_paths` — путь каждого клиента (channels_dedup_path, has_crm_created)
- `magnetto.dm_direct_performance` — средний CPC для оценки стоимости пути

## Обновление

REFRESH EVERY 1 DAY OFFSET 7 HOUR (после dm_conversion_paths в 06:00).

## Как работает (полная логика)

### Шаг 1: Дедупликация каналов

В `dm_conversion_paths` у каждого клиента есть `channels_dedup_path` — массив каналов с убранными подряд идущими повторами. Например:

```
Сырой путь:     ad → ad → organic → organic → ad → organic
Дедуплицированный: ['ad', 'organic', 'ad', 'organic']
```

Это убирает шум от повторных визитов из того же канала и показывает реальную последовательность переключений.

### Шаг 2: Группировка по паттерну

```sql
GROUP BY channels_dedup_path
HAVING count() >= 10  -- минимум 10 клиентов для статзначимости
```

Из 632K клиентов получается **52 уникальных паттерна** с достаточной выборкой.

### Шаг 3: Метрики каждого паттерна

- **total_clients** — сколько клиентов прошли этот путь
- **converters** — сколько из них стали CRM-сделкой
- **cr_pct** — конверсия паттерна (converters / total_clients × 100)
- **avg_visits** — среднее количество визитов (не шагов, а визитов — один шаг может содержать несколько визитов из одного канала)
- **avg_window_days / median_window_days** — окно конверсии (только по конвертерам): сколько дней от первого визита до CRM-сделки

### Шаг 4: Оценка стоимости

```sql
estimated_path_cost = ad_touches × avg_cpc
cost_per_conversion = estimated_path_cost × total_clients / converters
```

- **ad_touches** — количество шагов 'ad' в паттерне (0, 1, 2...)
- **avg_cpc** — средний cost-per-click из всего бюджета Директа (sum(cost)/sum(clicks))
- **estimated_path_cost** — оценка, сколько стоит один проход этого пути
- **cost_per_conversion** — оценка стоимости одной конверсии через этот путь

Это грубая оценка (реальный CPC зависит от кампании), но достаточная для сравнения паттернов между собой.

## Структура таблицы

| Поле | Тип | Описание |
|------|-----|----------|
| pattern | Array(String) | Дедуплицированный путь каналов |
| dedup_steps | UInt8 | Кол-во шагов в пути |
| ad_touches | UInt8 | Кол-во платных касаний ('ad') |
| total_clients | UInt32 | Клиентов с этим паттерном |
| converters | UInt32 | Из них CRM-сделок |
| cr_pct | Float32 | Конверсия паттерна, % |
| avg_visits | Float32 | Среднее визитов в пути |
| avg_window_days | Float32 | Среднее окно конверсии (дни), только конвертеры |
| median_window_days | Float32 | Медиана окна конверсии |
| estimated_path_cost | Float32 | Оценка стоимости пути (ad_touches × avg_cpc) |
| cost_per_conversion | Nullable(Float32) | Стоимость конверсии через этот путь |
| snapshot_date | Date | Дата рефреша |

ORDER BY: (dedup_steps, pattern)
Текущий объём: **52 паттерна**, 25 из них имеют конверсии.

## Ключевые находки из данных

### Реклама как самостоятельный канал почти не конвертирует

| Паттерн | Клиентов | Конверсий | CR% |
|---------|----------|-----------|-----|
| ['ad'] | 580 117 | 83 | 0.014% |
| ['organic'] | 21 129 | 341 | 1.614% |
| ['organic', 'ad', 'organic'] | 261 | 13 | 4.981% |

580K клиентов пришли только через рекламу, но CR всего 0.014%. Organic в 115 раз эффективнее. А комбинация organic → ad → organic даёт 5% — в 356 раз лучше, чем чистая реклама.

### Мульти-канальные пути с organic конвертируют лучше всего

| Паттерн | CR% | Стоимость за конверсию |
|---------|-----|----------------------|
| ['messenger', 'organic'] | 16.67% | 0 (бесплатный) |
| ['organic', 'referral', 'organic'] | 8.70% | 0 |
| ['organic', 'internal', 'organic'] | 6.52% | 0 |
| ['ad', 'organic', 'ad', 'organic'] | 6.12% | 108 руб. |
| ['organic', 'ad', 'organic'] | 4.98% | 66 руб. |

Organic в начале или в конце пути — практически обязательное условие конверсии.

### Реклама работает как подогрев в середине пути

Лучшие платные паттерны: те, где ad стоит МЕЖДУ organic-визитами. Реклама напоминает клиенту о проекте, а конверсия происходит при возврате через organic. Стоимость конверсии через такие пути — 66–329 руб., что на порядки дешевле прямого привлечения через ad (23 080 руб.).

## Сценарии использования для AI-агента

### 1. Какие пути конвертируют

**Когда спрашивают**: "Какие каналы работают?", "Откуда приходят покупатели?", "Какой путь клиента до сделки?"

**Запрос**:
```sql
SELECT pattern, total_clients, converters, cr_pct,
       round(median_window_days, 0) AS median_days
FROM magnetto.dm_path_templates
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_path_templates)
  AND converters > 0
ORDER BY cr_pct DESC
```

**Как интерпретировать**: паттерны с высоким CR% — это эталонные пути. Задача маркетинга — увеличить долю клиентов, проходящих именно по этим путям.

### 2. Эффективность рекламных расходов по путям

**Когда спрашивают**: "Сколько стоит конверсия?", "Где самый дешёвый лид?", "Оптимизировать бюджет"

**Запрос**:
```sql
SELECT pattern, ad_touches, total_clients, converters, cr_pct,
       round(estimated_path_cost, 0) AS path_cost,
       round(cost_per_conversion, 0) AS cost_per_conv
FROM magnetto.dm_path_templates
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_path_templates)
  AND ad_touches > 0
  AND converters > 0
ORDER BY cost_per_conversion ASC
```

**Как интерпретировать**: пути с низким cost_per_conversion — лучшие инвестиции. ['organic', 'ad', 'organic'] за 66 руб./конверсию vs ['ad'] за 23 080 руб. — разница в 350 раз.

### 3. Роль рекламы — самостоятельная или поддерживающая

**Когда спрашивают**: "Реклама вообще работает?", "Стоит ли увеличить бюджет?", "Какая роль рекламы в воронке?"

**Запрос**:
```sql
SELECT
    if(ad_touches = 0, 'без рекламы', 'с рекламой') AS ad_type,
    sum(total_clients) AS clients,
    sum(converters) AS converts,
    round(sum(converters) / sum(total_clients) * 100, 3) AS cr_pct
FROM magnetto.dm_path_templates
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_path_templates)
GROUP BY ad_type
```

**Как интерпретировать**: сравнение общей конверсии путей с рекламой и без. Если "без рекламы" конвертирует лучше в процентах — реклама привлекает объём, но не качество. Если "с рекламой" дешевле по cost_per_conversion — реклама работает как усилитель.

### 4. Скорость конверсии по типам путей

**Когда спрашивают**: "Как быстро конвертируются клиенты из рекламы?", "Сколько дней до сделки?"

**Запрос**:
```sql
SELECT pattern, converters, cr_pct,
       round(avg_window_days, 0) AS avg_days,
       round(median_window_days, 0) AS median_days,
       round(avg_visits, 1) AS avg_visits
FROM magnetto.dm_path_templates
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_path_templates)
  AND converters >= 2
ORDER BY median_window_days ASC
```

**Как интерпретировать**: median_window_days показывает типичное время до сделки по этому пути. Короткие пути (['ad'], ['direct']) конвертируют быстро (0–2 дня), но редко. Длинные мульти-канальные пути — медленнее (20–60 дней), но с гораздо более высоким CR%.

### 5. Какие паттерны убыточны

**Когда спрашивают**: "Где теряем деньги?", "Какие пути неэффективны?"

**Запрос**:
```sql
SELECT pattern, ad_touches, total_clients, converters, cr_pct,
       round(estimated_path_cost, 0) AS path_cost
FROM magnetto.dm_path_templates
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_path_templates)
  AND ad_touches > 0
  AND converters = 0
ORDER BY total_clients DESC
```

**Как интерпретировать**: паттерны с рекламными касаниями, но нулевой конверсией — это сжигание бюджета. Если ['ad', 'direct'] имеет 500 клиентов и 0 конверсий — эти клиенты платные, но не конвертируются. Нужно либо менять стратегию (подталкивать к organic-возврату), либо исключить эти аудитории.
