# dm_active_clients_scoring

## Назначение

Финальный продукт системы скоринга. Ежедневно оценивает каждого активного неконвертированного клиента: насколько он близок к сделке, что с ним делать, когда показать рекламу и какое действие стимулировать.

## Какую проблему решает

У Magnetto ~368K активных клиентов (визит за 90 дней, ещё без CRM-сделки). Невозможно вручную оценить каждого. Витрина автоматически ранжирует их по вероятности конверсии и даёт конкретные рекомендации — готовый таргет-лист для ретаргетинга с указанием "кому, когда, что показать".

## Источники данных

- `magnetto.dm_client_profile` — профиль клиента (визиты, источники, проект, лид)
- `magnetto.dm_client_journey` — визиты с целями (goals_in_visit)
- `magnetto.dm_step_goal_impact` — lift целей по шагам (для расчёта скора)
- `magnetto.dm_client_profile` (конвертеры) — медианы gap'ов между визитами

## Обновление

REFRESH EVERY 1 DAY OFFSET 8 HOUR — последняя в цепочке, после всех зависимостей.

## Как работает (полная логика)

### Шаг 1: Отбор активных клиентов

```sql
WHERE has_crm_created = 0 AND last_visit_date >= today() - 90
```

Берём всех, кто:
- Ещё НЕ стал CRM-сделкой
- Был на сайте в последние 90 дней (неактивных отсекаем — при 70-дневном цикле 90 дней = разумный горизонт)

Текущий объём: **367 945 клиентов**.

### Шаг 2: Расчёт lift_score

Для каждого клиента:

1. Берём все его визиты из `dm_client_journey` (шаги 1–10)
2. Для каждого визита разворачиваем массив `goals_in_visit` через `ARRAY JOIN`
3. Каждую пару (visit_number, goal_id) матчим с `dm_step_goal_impact` через `INNER JOIN`
4. Суммируем все lift'ы — это **lift_score**

```
Пример: клиент на 1-м визите выполнил "Заполнил контактные данные" (lift 157)
и "Клик по телефону" (lift 64). Его lift_score = 157 + 64 = 221.
```

Если у клиента нет ни одной значимой цели (нет совпадений в dm_step_goal_impact) — его lift_score = 0.

**matched_goals** — количество совпавших пар (visit_number × goal_id). Чем больше — тем надёжнее скор (больше сигналов).

### Шаг 3: Рекомендация на следующий шаг

```
next_step = min(total_visits + 1, 10)
```

Для каждого шага в `dm_step_goal_impact` находим цель с максимальным lift (исключая мусорные цели: Спам, CRM Отказ, Мусорный трафик и CRM-тавтологии).

Результат: `recommended_goal_name` + `recommended_lift` — конкретная цель, к которой нужно подтолкнуть клиента на следующем визите.

### Шаг 4: Тайминг ретаргетинга

Из конвертеров (has_crm_created = 1) считаем медиану `days_since_prev_visit` на каждом шаге. Это отвечает на вопрос: "Через сколько дней конвертеры обычно возвращаются на этом этапе?"

```
Шаг 2: медиана 4 дня
Шаг 3: медиана 3 дня
Шаги 4–8: медиана 2–3 дня
```

`optimal_retarget_days` — через столько дней после последнего визита нужно показать рекламу, чтобы попасть в ритм конвертеров.

### Шаг 5: Приоритет

```
HOT  = (есть лид И визит ≤ 7 дней назад)
       ИЛИ (lift_score > 100 И визит ≤ 3 дней назад)

WARM = (lift_score > 20 И визит ≤ 14 дней назад)
       ИЛИ (lift_score > 0 И визит ≤ 3 дней назад)

COLD = все остальные
```

Логика: два фактора определяют приоритет — **сила сигнала** (lift_score, has_lead) и **свежесть** (days_since_last). Горячий клиент — тот, кто показал сильные сигналы И был на сайте недавно.

Текущее распределение:

| Приоритет | Клиентов | С лидами | С проектом | Ср. скор | Ср. ретаргет |
|-----------|----------|----------|------------|----------|--------------|
| hot | 418 | 163 | 381 | 333 | 2.5 дня |
| warm | 8 955 | 110 | 7 923 | 68 | 3 дня |
| cold | 358 572 | 705 | 329 361 | 8 | 3.5 дня |

## Структура таблицы

| Поле | Тип | Описание |
|------|-----|----------|
| client_id | UInt64 | ID клиента (Метрика) |
| total_visits | UInt32 | Всего визитов на сайт |
| last_visit_date | Date | Дата последнего визита |
| days_since_last | UInt16 | Дней с последнего визита |
| first_traffic_source | String | Источник первого визита |
| last_traffic_source | String | Источник последнего визита |
| last_project | String | Последний ЖК, который смотрел |
| has_lead | UInt8 | Есть лид (1/0) |
| lift_score | Float32 | Сумма lift'ов по всем целям клиента |
| matched_goals | UInt16 | Кол-во совпавших целей со step_goal_impact |
| priority | String | hot / warm / cold |
| next_step | UInt8 | Следующий визит (capped 10) |
| recommended_goal_id | UInt32 | ID цели для стимулирования |
| recommended_goal_name | String | Название цели |
| recommended_lift | Float32 | Ожидаемый lift рекомендованной цели |
| optimal_retarget_days | Float32 | Через сколько дней показать рекламу |
| snapshot_date | Date | Дата рефреша |

ORDER BY: (priority, client_id)

## Сценарии использования для AI-агента

### 1. Утренняя сводка

**Когда спрашивают**: "Что сегодня?", "Покажи горячих", "Кого ретаргетить?"

Использовать запрос из файла `agent_daily_briefing.sql` — он даёт полную сводку с объяснениями по каждому клиенту.

### 2. Таргет-лист для конкретного проекта

**Когда спрашивают**: "Дай список для ретаргетинга по Costura", "Кто интересуется Costura?"

**Запрос**:
```sql
SELECT client_id, total_visits, days_since_last, lift_score, priority,
       recommended_goal_name, optimal_retarget_days
FROM magnetto.dm_active_clients_scoring
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_active_clients_scoring)
  AND last_project = 'costura-town'
  AND priority IN ('hot', 'warm')
ORDER BY lift_score DESC
```

### 3. Клиенты, которых пора ретаргетить СЕГОДНЯ

**Когда спрашивают**: "Кого показать рекламу сегодня?", "Кто готов к контакту?"

**Запрос**:
```sql
SELECT client_id, last_project, priority, recommended_goal_name
FROM magnetto.dm_active_clients_scoring
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_active_clients_scoring)
  AND priority IN ('hot', 'warm')
  AND days_since_last BETWEEN toUInt16(round(optimal_retarget_days - 1))
                           AND toUInt16(round(optimal_retarget_days + 1))
ORDER BY lift_score DESC
```

**Логика**: берём клиентов, у которых days_since_last ≈ optimal_retarget_days (±1 день). Это те, кто сейчас в оптимальном окне для контакта.

### 4. Почему клиент горячий — объяснение скора

**Когда спрашивают**: "Почему этот клиент в hot?", "Расшифруй скор"

**Запрос**:
```sql
SELECT s.visit_number, s.goal_name, round(s.lift, 1) AS lift
FROM magnetto.dm_client_journey AS j
ARRAY JOIN goals_in_visit AS gid
INNER JOIN magnetto.dm_step_goal_impact AS s
    ON s.visit_number = toUInt8(least(j.visit_number, 10)) AND s.goal_id = gid
WHERE j.client_id = <CLIENT_ID>
ORDER BY s.lift DESC
```

### 5. Статистика по приоритетам — трекинг здоровья системы

**Когда спрашивают**: "Сколько горячих сегодня vs вчера?", "Динамика скоринга"

**Запрос**:
```sql
SELECT snapshot_date, priority, count() AS clients, round(avg(lift_score), 0) AS avg_score
FROM magnetto.dm_active_clients_scoring
GROUP BY snapshot_date, priority
ORDER BY snapshot_date DESC, CASE priority WHEN 'hot' THEN 1 WHEN 'warm' THEN 2 ELSE 3 END
```
