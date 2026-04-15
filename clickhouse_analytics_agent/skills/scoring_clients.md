# Скоринг клиентов и ретаргетинг

## Система скоринга — три уровня

```
dm_step_goal_impact          dm_path_templates
(какие цели работают)        (какие пути работают)
        │                            │
        └──────────┐    ┌────────────┘
                   ▼    ▼
          dm_active_clients_scoring
          (кто горячий и что делать)
```

Обновление: dm_step_goal_impact (06:00) → dm_path_templates (07:00) → dm_active_clients_scoring (08:00).

## Таблица magnetto.dm_active_clients_scoring

Финальный продукт скоринга. Ежедневно оценивает каждого активного неконвертированного клиента (~368K): насколько близок к сделке, что делать, когда показать рекламу.

**Поля**: client_id, total_visits, last_visit_date, days_since_last, first_traffic_source, last_traffic_source, last_project, has_lead, lift_score, matched_goals, priority (hot/warm/cold), next_step, recommended_goal_id, recommended_goal_name, recommended_lift, optimal_retarget_days, snapshot_date.

### Связь с кабинетами Директа

У Magnetto 4 кабинета Директа, но один счётчик Метрики — **`cabinet_name` в этой витрине отсутствует**. Единственный мост к кабинету: `last_project` (slug из URL `/our-projects/[slug]`) джойним с `magnetto.project_cabinet_map`:

```sql
SELECT s.client_id, s.priority, s.lift_score, s.last_project,
       coalesce(m.cabinet_name, 'unknown') AS cabinet_name
FROM magnetto.dm_active_clients_scoring s
LEFT JOIN magnetto.project_cabinet_map m
    ON s.last_project = m.project_slug AND m.is_primary = 1
WHERE s.snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_active_clients_scoring)
```

Маппинг достоверен для `costura-town / niti / rivayat / origana`; остальные проекты и клиенты без `last_project` остаются без кабинета — всегда оговаривай долю `unknown` в ответе.

## Как вычисляется lift_score

1. Для каждого визита клиента (шаги 1-10) разворачиваем goals_in_visit
2. Каждую пару (visit_number, goal_id) матчим с dm_step_goal_impact через INNER JOIN
3. Суммируем все lift'ы — это **lift_score**

Пример: клиент на 1-м визите выполнил "Заполнил контакты" (lift 157) + "Клик по телефону" (lift 64) → lift_score = 221.

## Рекомендация (recommended_goal)

next_step = min(total_visits + 1, 10). Находим цель с max lift на этом шаге (исключая CRM-тавтологии и мусор: 332069613, 332069614, 402733217, 405315077, 405315078, 407450615, 541504123).

## Тайминг (optimal_retarget_days)

Медиана days_since_prev_visit у конвертеров на данном шаге. Шаг 2: 4 дня, Шаг 3: 3 дня, Шаги 4-8: 2-3 дня.

## Приоритеты

```
HOT  = (has_lead=1 И days_since_last ≤ 7) ИЛИ (lift_score > 100 И days_since_last ≤ 3)
WARM = (lift_score > 20 И days_since_last ≤ 14) ИЛИ (lift_score > 0 И days_since_last ≤ 3)
COLD = все остальные
```

Текущее распределение: ~418 hot, ~9K warm, ~358K cold.

## SQL-шаблоны

### Горячие клиенты (утренняя сводка)
```sql
SELECT client_id, total_visits, days_since_last, lift_score, has_lead,
       last_project, recommended_goal_name, optimal_retarget_days
FROM magnetto.dm_active_clients_scoring
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_active_clients_scoring)
  AND priority = 'hot'
ORDER BY lift_score DESC
LIMIT 50
```

### Таргет-лист для проекта
```sql
-- last_project = основной slug кабинета (costura-town→tab1, niti→tab2, rivayat→tab3, origana→tab4)
SELECT client_id, total_visits, days_since_last, lift_score, priority,
       recommended_goal_name, optimal_retarget_days
FROM magnetto.dm_active_clients_scoring
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_active_clients_scoring)
  AND last_project = 'costura-town'
  AND priority IN ('hot', 'warm')
ORDER BY lift_score DESC
```

### Горячие клиенты по кабинету (через project_cabinet_map)
```sql
SELECT s.client_id, s.priority, s.lift_score, s.last_project,
       s.recommended_goal_name, s.optimal_retarget_days
FROM magnetto.dm_active_clients_scoring s
INNER JOIN magnetto.project_cabinet_map m
    ON s.last_project = m.project_slug AND m.is_primary = 1
WHERE s.snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_active_clients_scoring)
  AND m.cabinet_name = 'audit-magnetto-tab3'   -- rivayat
  AND s.priority IN ('hot', 'warm')
ORDER BY s.lift_score DESC
LIMIT 50
```

### Клиенты, которых пора ретаргетить СЕГОДНЯ
```sql
SELECT client_id, last_project, priority, recommended_goal_name
FROM magnetto.dm_active_clients_scoring
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_active_clients_scoring)
  AND priority IN ('hot', 'warm')
  AND days_since_last BETWEEN toUInt16(round(optimal_retarget_days - 1))
                           AND toUInt16(round(optimal_retarget_days + 1))
ORDER BY lift_score DESC
```

### Почему клиент горячий — расшифровка скора
```sql
SELECT s.visit_number, s.goal_name, round(s.lift, 1) AS lift
FROM magnetto.dm_client_journey AS j
ARRAY JOIN goals_in_visit AS gid
INNER JOIN magnetto.dm_step_goal_impact AS s
    ON s.visit_number = toUInt8(least(j.visit_number, 10)) AND s.goal_id = gid
WHERE j.client_id = <CLIENT_ID>
ORDER BY s.lift DESC
```

### Статистика по приоритетам (здоровье системы)
```sql
SELECT snapshot_date, priority, count() AS clients, round(avg(lift_score), 0) AS avg_score
FROM magnetto.dm_active_clients_scoring
GROUP BY snapshot_date, priority
ORDER BY snapshot_date DESC, CASE priority WHEN 'hot' THEN 1 WHEN 'warm' THEN 2 ELSE 3 END
```

### Распределение по приоритетам (текущее)
```sql
SELECT priority, count() AS clients,
       countIf(has_lead = 1) AS with_lead,
       countIf(last_project != '') AS with_project,
       round(avg(lift_score), 0) AS avg_score,
       round(avg(optimal_retarget_days), 1) AS avg_retarget_days
FROM magnetto.dm_active_clients_scoring
WHERE snapshot_date = (SELECT max(snapshot_date) FROM magnetto.dm_active_clients_scoring)
GROUP BY priority
ORDER BY CASE priority WHEN 'hot' THEN 1 WHEN 'warm' THEN 2 ELSE 3 END
```
