## Skill: Обнаружение и расследование аномалий

**База данных:** `magnetto`
**Основная витрина:** `dm_traffic_performance`
**Метрики для мониторинга:** `visits`, `goal_314553735` (Все лиды), `bounces`, `new_users`

### Алгоритм расследования

1. **Выгрузи исторические данные** — минимум 30–90 дней для baseline
2. **Рассчитай baseline** — mean + std за период до аномалии
3. **Флаги аномалий** — |z-score| > 2 или отклонение > 30% от среднего
4. **Сегментируй** — найди, в каком сегменте (канал, кампания, устройство, проект) концентрируется аномалия
5. **Сформулируй гипотезу** — аномалия в данных или в бизнесе?

### Z-score в Python

```python
import numpy as np

# Рассчитай статистику baseline (исключи аномальный период):
baseline = df[df['date'] < anomaly_start]
mean_val = baseline['metric'].mean()
std_val = baseline['metric'].std()

# Флаги:
df['z_score'] = (df['metric'] - mean_val) / std_val
df['is_anomaly'] = df['z_score'].abs() > 2

result = df[df['is_anomaly']].to_markdown(index=False)
```

### Сравнение с аналогичным периодом

```sql
-- Текущая неделя vs та же неделя прошлого года:
SELECT
    toStartOfWeek(date) AS week,
    SUM(visits) AS visits_current,
    lagInFrame(SUM(visits), 52) OVER (ORDER BY toStartOfWeek(date)) AS visits_last_year,
    (SUM(visits) - lagInFrame(SUM(visits), 52) OVER (ORDER BY toStartOfWeek(date)))
    / lagInFrame(SUM(visits), 52) OVER (ORDER BY toStartOfWeek(date)) * 100 AS yoy_pct
FROM magnetto.dm_traffic_performance
WHERE date >= today() - INTERVAL 1 YEAR
GROUP BY week
ORDER BY week
```

### Сегментация для локализации аномалии

```sql
-- Разбивка по каналу в аномальный день:
SELECT
    utm_source,
    utm_medium,
    SUM(visits) AS visits,
    SUM(goal_314553735) AS leads  -- Все лиды — magnetto
FROM magnetto.dm_traffic_performance
WHERE date = '2024-03-15'  -- аномальная дата
GROUP BY utm_source, utm_medium
ORDER BY visits DESC
```

```sql
-- Разбивка по проекту и устройству:
SELECT
    project_slug,
    device_category,
    SUM(visits) AS visits,
    SUM(goal_314553735) AS leads
FROM magnetto.dm_traffic_performance
WHERE date = '2024-03-15'
GROUP BY project_slug, device_category
ORDER BY visits DESC
```

### Спам/бот-трафик

Поле `goal_402733217` — флаг мусорного трафика. Резкий рост визитов при нулевых лидах — сигнал бот-атаки.

```sql
-- Доля мусорного трафика по дням:
SELECT
    date,
    SUM(visits) AS visits,
    SUM(goal_402733217) AS spam_sessions,
    round(SUM(goal_402733217) / SUM(visits) * 100, 1) AS spam_pct,
    SUM(goal_314553735) AS leads
FROM magnetto.dm_traffic_performance
WHERE date >= today() - 30
GROUP BY date
ORDER BY date
```

### Типичные причины аномалий

| Паттерн | Вероятная причина |
|---|---|
| Резкий рост визитов без роста лидов | Спам/боты (проверь goal_402733217), акция, публикация |
| Резкое падение в один день | Технический сбой, блокировка домена, изменение UTM |
| Постепенный тренд вниз | Изменение алгоритма, сезонность, конкуренция |
| Аномалия в одном канале | Изменение ставок/бюджетов, отключение кампании |
| Аномалия в одном устройстве | Технический сбой мобильной версии |
| Резкий рост лидов без роста трафика | Изменение формы/квиза, акция для тёплой базы |
| Рост `project_slug` = 'site', падение ЖК-страниц | Смена посадочных страниц в рекламе |

### Вывод аномалий

```python
# Таблица с флагами:
anomalies = df[df['is_anomaly']].copy()
anomalies['отклонение'] = anomalies['z_score'].apply(
    lambda z: f"⚠️ +{z:.1f}σ" if z > 0 else f"⚠️ {z:.1f}σ"
)
result = anomalies[['date', 'metric', 'отклонение']].to_markdown(index=False)
```

Аномалия — исследуй, не игнорируй. Рост трафика без роста лидов — это не успех, это сигнал.
