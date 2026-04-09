# dm_step_goal_impact

## Назначение

Фундамент системы скоринга. Для каждой пары (номер визита × цель Метрики) вычисляет, насколько выполнение этой цели на этом шаге повышает вероятность CRM-сделки.

## Какую проблему решает

Маркетолог видит 57 целей в Метрике и не знает, какие из них реально влияют на продажи, а какие — шум. Витрина даёт точный ответ: "Отправка формы ипотека на 1-м визите повышает шанс сделки в 284 раза, а прохождение квиза — только в 19 раз". Это позволяет перераспределить бюджет на стимулирование действительно работающих целей.

## Источники данных

- `magnetto.dm_client_journey` — визиты клиентов с целями (goals_in_visit)
- `magnetto.dm_client_profile` — флаг конверсии (has_crm_created)

## Обновление

REFRESH EVERY 1 DAY OFFSET 6 HOUR (после dm_client_journey в 05:00 и dm_client_profile в 04:00).

## Как работает lift-анализ (полная логика)

### Шаг 1: Определяем конвертеров

```sql
converters AS (
    SELECT client_id FROM magnetto.dm_client_profile WHERE has_crm_created = 1
)
```

Это ~569 клиентов, у которых есть CRM-сделка.

### Шаг 2: Разворачиваем цели по визитам

```sql
goal_visits AS (
    SELECT client_id, visit_number, arrayJoin(goals_in_visit) AS goal_id
    FROM magnetto.dm_client_journey
    WHERE visit_number BETWEEN 1 AND 10 AND length(goals_in_visit) > 0
)
```

У каждого визита есть массив `goals_in_visit` — например, [322914144, 314248561] означает "отправил форму и кликнул по телефону". `arrayJoin` превращает одну строку в несколько — по строке на каждую цель.

Анализируем только визиты 1–10, потому что дальше слишком мало данных для статистики.

### Шаг 3: Считаем группу "с целью"

Для каждой пары (visit_number, goal_id):
- **clients_with_goal** — сколько уникальных клиентов выполнили эту цель на этом шаге
- **converters_with_goal** — сколько из них стали CRM-сделками

Фильтр: минимум 20 клиентов (`HAVING clients_with_goal >= 20`) — иначе статистически незначимо.

### Шаг 4: Считаем базовую линию

Для каждого visit_number:
- **clients_at_step** — всего клиентов, дошедших до этого шага
- **converters_at_step** — всего конвертеров на этом шаге

### Шаг 5: Вычитаем группу "без цели"

```
clients_without_goal = clients_at_step - clients_with_goal
converters_without_goal = converters_at_step - converters_with_goal
```

### Шаг 6: Считаем конверсионные ставки и lift

```
rate_with_goal    = converters_with_goal / clients_with_goal
rate_without_goal = converters_without_goal / clients_without_goal
lift              = rate_with_goal / rate_without_goal
```

**Lift = 284** означает: клиент, отправивший форму ипотеки на 1-м визите, конвертируется в 284 раза чаще, чем клиент, который этого не сделал.

### Маппинг целей

В витрине goal_id преобразуется в человекочитаемое название через `transform()` — жёстко зашитый маппинг всех 57 целей. Это позволяет агенту не знать ID целей, а работать с названиями.

## Структура таблицы

| Поле | Тип | Описание |
|------|-----|----------|
| visit_number | UInt8 | Номер визита (1–10) |
| goal_id | UInt32 | ID цели Метрики |
| goal_name | String | Название цели |
| clients_at_step | UInt32 | Всего клиентов, дошедших до этого шага |
| clients_with_goal | UInt32 | Из них выполнили эту цель |
| clients_without_goal | UInt32 | Не выполнили |
| converters_with_goal | UInt32 | Конвертеры среди выполнивших цель |
| converters_without_goal | UInt32 | Конвертеры среди НЕ выполнивших |
| rate_with_goal | Float32 | Конверсия группы "с целью" |
| rate_without_goal | Float32 | Конверсия группы "без цели" |
| lift | Float32 | rate_with / rate_without (>1 = цель помогает) |
| snapshot_date | Date | Дата рефреша |

ORDER BY: (visit_number, goal_id)
Текущий объём: **234 строки** (10 шагов × ~24 значимые цели).

## Что означают значения lift

| Диапазон lift | Интерпретация | Пример |
|--------------|---------------|--------|
| > 100 | Почти гарантированная конверсия | CRM Заказ создан (lift 1798) — клиент уже в CRM, ожидаемо |
| 50–100 | Сильный сигнал покупательского интереса | Уникальный звонок (lift 66), Клик по телефону (lift 64) |
| 10–50 | Умеренный сигнал | Просмотр квартир (lift ~20), Квиз (lift 19.6) |
| 1–10 | Слабый сигнал | Переход в соцсеть, Скачивание файла |
| < 1 | Отрицательная корреляция | Цель ассоциирована с НЕконверсией |

**Важно**: высокий lift у "CRM Заказ создан" (1798) и "CRM Заказ оплачен" (1183) — тавтология. Эти цели срабатывают ПОСЛЕ конверсии. Для рекомендаций они исключаются из dm_active_clients_scoring (вместе с мусорными: Спам, CRM Отказ и т.д.).

## Реально полезные цели (для рекомендаций)

На основе данных — цели с lift > 10, исключая тавтологии и мусор:

**Шаг 1 (первый визит):**
- Отправка формы ипотека → lift 284
- Отправил контактные данные → lift 165
- Заполнил контактные данные → lift 157
- Все лиды magnetto → lift 124
- Уникально-целевой звонок → lift 69
- Клик по телефону Magnetto → lift 64

**Шаги 2–5:**
- Те же цели, но lift снижается (на шаге 2 ~379→65, на шаге 5 ~239→24)
- Добавляется "Просмотр квартир" (lift ~20 на шагах 3–5)

**Шаги 7–10:**
- Lift всех целей падает ниже 35
- Самые значимые: Все лиды magnetto, Автоцель: отправка формы, Клик по телефону

## Сценарии использования для AI-агента

### 1. Какие цели стимулировать в рекламе

**Когда спрашивают**: "На какие действия нацелить рекламу?", "Какие цели работают?", "Что должен сделать клиент на сайте?"

**Запрос**:
```sql
SELECT goal_name, visit_number, lift, clients_with_goal, converters_with_goal
FROM magnetto.dm_step_goal_impact
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_step_goal_impact)
  AND lift > 10
  AND goal_id NOT IN (332069613, 332069614, 402733217, 405315077, 405315078, 407450615, 541504123)
  -- исключаем CRM-тавтологии и мусор
ORDER BY lift DESC
```

**Как интерпретировать**: топ целей по lift — это то, к чему нужно подталкивать клиента. Если "Отправка формы ипотека" имеет lift 284, значит рекламные креативы должны вести на ипотечный калькулятор/форму, а не на квиз (lift всего 20).

### 2. Работает ли конкретный инструмент

**Когда спрашивают**: "Квиз работает?", "Есть ли смысл в чат-боте?", "Jivo помогает продажам?"

**Запрос**:
```sql
SELECT visit_number, goal_name, lift, clients_with_goal, converters_with_goal
FROM magnetto.dm_step_goal_impact
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_step_goal_impact)
  AND goal_name LIKE '%квиз%'  -- или '%Jivo%', '%чат%' и т.д.
ORDER BY visit_number
```

**Как интерпретировать**: если lift < 5 на всех шагах — инструмент не влияет на конверсию. Можно отключить или перенаправить бюджет.

### 3. На каком шаге клиент "дозревает"

**Когда спрашивают**: "Когда клиент готов к покупке?", "На каком визите принимается решение?"

**Запрос**:
```sql
SELECT
    visit_number,
    max(lift) AS max_lift,
    argMax(goal_name, lift) AS strongest_goal,
    sum(converters_with_goal) AS total_converters
FROM magnetto.dm_step_goal_impact
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_step_goal_impact)
  AND goal_id NOT IN (332069613, 332069614, 402733217, 405315077, 405315078, 407450615, 541504123)
GROUP BY visit_number
ORDER BY visit_number
```

**Как интерпретировать**: шаг, на котором max_lift резко падает — это граница "дозревания". Если на шаге 1 lift=284, а на шаге 7 уже 31 — основное решение принимается в первые визиты. Рекламный контакт на ранних шагах критически важнее, чем на поздних.

### 4. Сравнение двух целей

**Когда спрашивают**: "Что лучше — звонок или форма?", "Ипотечный калькулятор vs обычная заявка?"

**Запрос**:
```sql
SELECT visit_number, goal_name, lift, clients_with_goal
FROM magnetto.dm_step_goal_impact
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_step_goal_impact)
  AND goal_name IN ('Отправка формы телефон', 'Уникальный звонок')
ORDER BY goal_name, visit_number
```

**Как интерпретировать**: цель с более высоким lift на ранних шагах — более сильный предиктор. Но нужно смотреть и на clients_with_goal — если у цели lift 284, но всего 48 клиентов, это менее надёжно, чем lift 65 при 351 клиенте.

### 5. Данные для dm_active_clients_scoring

Эта витрина **не запрашивается напрямую** для скоринга — dm_active_clients_scoring уже содержит предрассчитанные lift_score для каждого клиента. Но если нужно объяснить, ПОЧЕМУ клиент получил высокий скор:

**Запрос**:
```sql
-- Почему клиент X имеет lift_score = 2319?
SELECT s.visit_number, s.goal_name, s.lift
FROM magnetto.dm_client_journey AS j
ARRAY JOIN goals_in_visit AS gid
INNER JOIN magnetto.dm_step_goal_impact AS s
    ON s.visit_number = toUInt8(least(j.visit_number, 10)) AND s.goal_id = gid
WHERE j.client_id = 1775457576737720012
ORDER BY s.lift DESC
```
