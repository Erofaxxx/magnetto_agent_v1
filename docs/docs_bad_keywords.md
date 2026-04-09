# bad_keywords

## Назначение

Ежедневный рейтинг ключевых фраз по эффективности. Для каждой фразы рассчитаны метрики за 60 дней, отклонение от медианы по кампании и автоматический вердикт (`zone_status`). Позволяет быстро находить ключи, которые тратят бюджет без отдачи, и ключи, которые работают лучше остальных.

## Источник данных и окно

- Таблица: `magnetto.direct_custom_report`
- Фильтр: только `CriterionType = 'KEYWORD'` (ключевые фразы; автотаргетинг и аудитории не входят)
- Окно: **60 дней** (скользящее, пересчитывается каждый день)
- Обновление: `REFRESH EVERY 1 DAY OFFSET 3 HOUR`

## Ключевые метрики

### goal_score — взвешенный балл конверсий

Не просто количество конверсий, а их ценность по уровням:

| Уровень | Вес | Цели |
|---------|-----|------|
| Макро (tier 1) | ×10 | Все лиды, уникальный/целевой звонок, CRM создан/оплачен |
| Микро (tier 2) | ×3 | Отправка формы, клик по телефону |
| Слабые (tier 3) | ×1 | Скачать презентацию |

`goal_score_rate = (goal_score / clicks) × 100` — эффективность фразы на клик. Именно его сравнивают с медианой по кампании.

`tier12_conversions` — только строгие макро-конверсии без весов (чистый счётчик лидов и CRM).

### bid_zone — зона по соотношению CPC к ставке

`cpc_to_bid_ratio = фактический CPC / средняя ставка по кликам`

| Зона | Соотношение | Смысл |
|------|-------------|-------|
| A | < 0.4 | Очень дешёвые клики — возможно, нерелевантный трафик или низкая конкуренция |
| B | 0.4 – 0.7 | Норма |
| C | 0.7 – 0.9 | Высокая конкуренция |
| D | > 0.9 | Клики почти по потолку ставки — перегретый аукцион |

### Отклонения от медианы кампании

Все отклонения считаются относительно **медианы по кампании + сети** (не по аккаунту):

- `goal_rate_deviation` — отклонение goal_score_rate: `0` = на уровне медианы, `-0.5` = вдвое хуже, `+0.3` = на 30% лучше
- `roas_deviation` — то же по ROAS (выручка / расход)
- Если конверсий/выручки нет — принудительно `-1.0` (худший случай)

## Автоматический вердикт (zone_status)

Вердикт — это стартовая точка для анализа, а не окончательный приговор. Алгоритм консервативен: при недостатке данных выставляет `pending`.

### pending
Мало данных: `cost < 300` И `clicks < 20`. Делать выводы рано.

### green / yellow / red — логика зависит от bid_zone

Для зон C и D (дорогие клики) — более строгие требования к конверсиям, потому что высокий CPC должен окупаться:

| bid_zone | green | yellow | red |
|----------|-------|--------|-----|
| D (>0.9) | goal_dev ≥ −0.2 И roas_dev ≥ −0.2 | одно из двух в норме | оба хуже порогов |
| C (0.7–0.9) | goal_dev ≥ −0.2 И roas_dev ≥ −0.3 | частичное соответствие | оба плохие |
| B (норма) | goal_dev ≥ −0.2 | goal_dev ≥ −0.5 ИЛИ roas_dev ≥ −0.2 | оба хуже |
| A (<0.4) | goal_dev ≥ −0.3 (и есть tier1 или стоит мало) | goal_dev ≥ −0.6 | tier12=0 И cost > 500 |

## Когда zone_status можно пересмотреть

Алгоритм не учитывает контекст. Агент может прийти к другому выводу в следующих случаях:

- **Брендовые фразы в зоне red** — ROAS может быть низким, но трафик стратегически важен
- **Новые фразы в pending** — 60 дней данных нет, но фраза запущена недавно специально
- **Зона A с нулём конверсий, но низкий расход** — алгоритм выдаёт red при cost > 500, агент может дать жёлтый вердикт при cost = 200
- **Сезонность** — окно 60 дней может захватить или пропустить пик спроса

В таких случаях смотреть на сырые метрики: `goal_score`, `tier12_conversions`, `cost`, `ctr`, `cpc_to_bid_ratio` — и делать вывод самостоятельно.

## Структура таблицы

| Поле | Тип | Описание |
|------|-----|----------|
| report_date | Date | Дата расчёта (сегодня) |
| Criterion | String | Ключевая фраза |
| MatchType | String | Тип соответствия |
| ad_network_type | String | SEARCH / AD_NETWORK |
| CampaignId | UInt64 | ID кампании |
| CampaignName | String | Название кампании |
| AdGroupId | UInt64 | ID группы |
| AdGroupName | String | Название группы |
| clicks | UInt64 | Клики за 60 дней |
| impressions | UInt64 | Показы |
| cost | Float64 | Расход (руб) |
| ctr | Nullable(Float64) | CTR (%) |
| cpc | Nullable(Float64) | Фактический CPC (руб) |
| avg_bid | Nullable(Float64) | Средняя ставка (взвешенная по кликам) |
| cpc_to_bid_ratio | Nullable(Float64) | CPC / ставка (основа bid_zone) |
| purchase_revenue | Float64 | Выручка (атрибуция Директа) |
| roas | Nullable(Float64) | Выручка / расход |
| goal_score | Float64 | Взвешенный балл конверсий |
| goal_score_rate | Nullable(Float64) | goal_score на 100 кликов |
| tier12_conversions | UInt64 | Строгие макро-конверсии (без весов) |
| goal_rate_deviation | Nullable(Float64) | Отклонение goal_score_rate от медианы кампании |
| roas_deviation | Nullable(Float64) | Отклонение ROAS от медианы кампании |
| med_goal_score_rate | Nullable(Float64) | Медиана goal_score_rate по кампании |
| med_roas | Nullable(Float64) | Медиана ROAS по кампании |
| bid_zone | String | A / B / C / D |
| zone_status | String | green / yellow / red / pending |

## Сценарии использования для AI-агента

### 1. Красные ключи с большим расходом — срочные к проверке

**Триггеры**: "Какие ключи сжигают бюджет?", "Найди плохие ключевые фразы", "Что отключить?"

```sql
SELECT
    Criterion, MatchType, ad_network_type,
    CampaignName, AdGroupName,
    clicks, cost, tier12_conversions,
    goal_score_rate, med_goal_score_rate,
    bid_zone, zone_status
FROM magnetto.bad_keywords
WHERE zone_status = 'red'
ORDER BY cost DESC
LIMIT 30
```

### 2. Зеленые ключи — кандидаты на повышение ставок

**Триггеры**: "Где можно увеличить ставку?", "Какие ключи работают лучше всего?"

```sql
SELECT
    Criterion, ad_network_type, CampaignName, AdGroupName,
    clicks, cost, tier12_conversions,
    goal_score_rate, med_goal_score_rate,
    round(goal_rate_deviation * 100, 0) AS deviation_pct,
    bid_zone, cpc, avg_bid
FROM magnetto.bad_keywords
WHERE zone_status = 'green'
  AND goal_rate_deviation > 0.3
ORDER BY tier12_conversions DESC, goal_score_rate DESC
```

### 3. Зона D (перегрет аукцион) — дорого платим, смотрим окупаемость

**Триггеры**: "Где мы переплачиваем?", "Дорогие ключи"

```sql
SELECT
    Criterion, CampaignName, cost, cpc, avg_bid,
    round(cpc_to_bid_ratio, 2) AS cpc_bid_ratio,
    tier12_conversions, goal_score_rate, zone_status
FROM magnetto.bad_keywords
WHERE bid_zone = 'D'
ORDER BY cost DESC
```

### 4. Ключи в pending с большим расходом — нужно внимание

**Триггеры**: "Что накапливает расход без вердикта?", "Pending с расходом"

```sql
SELECT
    Criterion, ad_network_type, CampaignName,
    clicks, cost, tier12_conversions, goal_score
FROM magnetto.bad_keywords
WHERE zone_status = 'pending'
  AND cost > 500
ORDER BY cost DESC
```

### 5. Ключи по конкретной кампании или группе

**Триггеры**: "Покажи ключи кампании X", "Как работают ключи в группе Y?"

```sql
SELECT
    Criterion, MatchType, ad_network_type,
    clicks, cost, tier12_conversions,
    goal_score_rate, med_goal_score_rate,
    bid_zone, zone_status
FROM magnetto.bad_keywords
WHERE CampaignName ILIKE '%<название>%'
ORDER BY cost DESC
```

### 6. Сравнение поиска и РСЯ по одной фразе

**Триггеры**: "Как фраза X работает на поиске vs РСЯ?"

```sql
SELECT
    Criterion, ad_network_type,
    clicks, cost, cpc,
    tier12_conversions, goal_score_rate,
    bid_zone, zone_status
FROM magnetto.bad_keywords
WHERE Criterion ILIKE '%<фраза>%'
ORDER BY Criterion, ad_network_type
```

## Таблица триггеров

| Вопрос агента | Что смотреть |
|---------------|--------------|
| "Плохие / красные ключи" | `zone_status = 'red'`, ORDER BY cost DESC |
| "Лучшие ключи / зелёные" | `zone_status = 'green'`, ORDER BY goal_score_rate DESC |
| "Ключи без конверсий с расходом" | `tier12_conversions = 0 AND cost > 300` |
| "Где переплачиваем?" | `bid_zone = 'D'` |
| "Ключи без данных" | `zone_status = 'pending'` |
| "Ключи кампании X" | `CampaignName ILIKE '%X%'` |
| "Поиск vs РСЯ по фразе" | GROUP/FILTER по `ad_network_type` |
| "Насколько хуже/лучше медианы?" | `goal_rate_deviation`, `roas_deviation` |
