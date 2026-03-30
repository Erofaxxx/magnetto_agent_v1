# Скилл: Data-Driven Атрибуция

Активируется при запросах про: **атрибуция**, вклад канала, data-driven атрибуция, Markov, Shapley,
linear attribution, u-shaped, time decay, позиционная атрибуция, какой канал важнее, куда вкладывать
бюджет, customer journey attribution, какие каналы закрывают сделку, какие каналы открывают,
removal effect, attribution credit, мультиканальная атрибуция.

---

## Контекст: застройщик, не e-commerce

- **Конверсия** = лид (goal 314553735, `has_lead = 1`). Это основной KPI для атрибуции.
- **Финальная конверсия** = оплаченная сделка (`has_crm_paid = 1`). Сделок мало — для Markov используй лиды.
- **Выручки нет** в путях клиента. Attribution credit = доля лидов/сделок, а не доля выручки.
- **Spend нет** → CPA и ROAS недоступны.

---

## Доступные модели

| Модель | Витрина | Когда использовать |
|--------|---------|-------------------|
| Last Touch | `dm_client_journey` (is_converting_visit) | Быстро: какой канал присутствовал при лиде |
| First Touch | `dm_client_profile` (first_utm_source) | Какой канал инициировал знакомство |
| Linear | `dm_conversion_paths` | Равное распределение — базовый бенчмарк |
| U-Shaped (Position-Based) | `dm_conversion_paths` | Когда важен и вход, и закрытие |
| Time Decay | `dm_conversion_paths` | Акцент на ближних к лиду касаниях |
| **Markov Chain** | `dm_conversion_paths` | **Основная data-driven модель** — честный вклад каждого канала |

---

## Данные dm_conversion_paths

### Ключевые поля
| Поле | Тип | Описание |
|------|-----|----------|
| `client_id` | UInt64 | ID клиента |
| `converted` | UInt8 | 1 = клиент оставил лид (`has_lead = 1`), 0 = нет |
| `has_crm_paid` | UInt8 | 1 = сделка оплачена (финальный KPI) |
| `path_length` | UInt16 | Количество касаний (визитов) в пути |
| `first_touch_date` | Date | Дата первого касания |
| `first_lead_date` | Date | Дата первого лида |
| `conversion_window_days` | UInt16 | Дней от первого касания до лида |
| `channels_path` | Array(String) | Полный путь по типам трафика |
| `channels_dedup_path` | Array(String) | Путь без повторов подряд |
| `sources_path` | Array(String) | Путь по utm_source |
| `campaigns_path` | Array(String) | Путь по utm_campaign |
| `days_from_first_path` | Array(UInt16) | Дней от первого касания на каждом шаге |

**Правило выбора колонки:**
- Стратегический вопрос ("какие каналы важнее") → `channels_path`
- Тактический вопрос ("какой источник/кампания") → `sources_path` / `campaigns_path`
- Пустую строку `""` в sources_path считать каналом `organic/direct`, не удалять

---

## Шаг 1 — SQL-выгрузка

### Для Linear / U-Shape / Time Decay (конвертировавшие)

```sql
SELECT
    client_id,
    converted,
    path_length,
    channels_path,
    sources_path,
    campaigns_path,
    days_from_first_path
FROM magnetto.dm_conversion_paths
WHERE converted = 1
```

### Для Markov Chain — по каналам (channels_path)

```sql
-- Все converted=1 + ~1/10 случайных converted=0
SELECT
    client_id,
    converted,
    channels_path
FROM magnetto.dm_conversion_paths
WHERE converted = 1
   OR (converted = 0 AND rand() % 10 = 0)
```

> Выборка 1/10 от non-converted достаточна для надёжного Markov. Без null-путей base_p = 1.0 (математически неверно).

### Для Markov Chain — по источникам или кампаниям

```sql
SELECT
    client_id,
    converted,
    channels_path,
    sources_path,
    campaigns_path
FROM magnetto.dm_conversion_paths
WHERE converted = 1
   OR (converted = 0 AND rand() % 10 = 0)
```

---

## Шаг 2 — Python-код

> `df` уже загружен. Всегда устанавливать переменную `result`.
> Attribution credit = доля лидов (не выручки).

---

### Алгоритм: Linear Attribution

```python
from collections import defaultdict

credits = defaultdict(float)
total_converted = 0

for _, row in df[df['converted'] == 1].iterrows():
    path = list(row['channels_path'])
    if not path:
        continue
    w = 1.0 / len(path)
    for ch in path:
        credits[ch] += w
    total_converted += 1

print(f"Конверсий (лидов): {total_converted}")

total_credit = sum(credits.values())
rows = []
for ch, credit in sorted(credits.items(), key=lambda x: -x[1]):
    rows.append(f"| {ch} | {credit:.1f} | {credit / total_credit:.1%} |")

result = "## Linear Attribution — вклад каналов (по лидам)\n\n"
result += "| Канал | Attribution Credit | Доля |\n|---|---|---|\n"
result += "\n".join(rows)
result += f"\n\nПокрытие: {total_converted:,} лидов"
```

---

### Алгоритм: U-Shaped (Position-Based) Attribution

```python
from collections import defaultdict

credits = defaultdict(float)

for _, row in df[df['converted'] == 1].iterrows():
    path = list(row['channels_path'])
    n = len(path)
    if not path:
        continue
    if n == 1:
        credits[path[0]] += 1.0
    elif n == 2:
        credits[path[0]] += 0.5
        credits[path[1]] += 0.5
    else:
        credits[path[0]] += 0.4     # first touch
        credits[path[-1]] += 0.4    # last touch
        mid_w = 0.2 / (n - 2)
        for ch in path[1:-1]:
            credits[ch] += mid_w

total = sum(credits.values())
rows = []
for ch, credit in sorted(credits.items(), key=lambda x: -x[1]):
    rows.append(f"| {ch} | {credit:.1f} | {credit / total:.1%} |")

result = "## U-Shaped Attribution — вклад каналов (по лидам)\n\n"
result += "| Канал | Attribution Credit | Доля |\n|---|---|---|\n"
result += "\n".join(rows)
```

---

### Алгоритм: Time Decay Attribution

```python
import numpy as np
from collections import defaultdict

credits = defaultdict(float)

for _, row in df[df['converted'] == 1].iterrows():
    path = list(row['channels_path'])
    days = list(row['days_from_first_path'])
    if not path:
        continue
    max_day = max(days) if days else len(path) - 1
    raw_w = np.array([np.exp(-0.5 * (max_day - d)) for d in days], dtype=float)
    if raw_w.sum() == 0:
        raw_w = np.ones(len(path))
    norm_w = raw_w / raw_w.sum()
    for ch, w in zip(path, norm_w):
        credits[ch] += float(w)

total = sum(credits.values())
rows = []
for ch, credit in sorted(credits.items(), key=lambda x: -x[1]):
    rows.append(f"| {ch} | {credit:.1f} | {credit / total:.1%} |")

result = "## Time Decay Attribution — вклад каналов (по лидам)\n\n"
result += "| Канал | Attribution Credit | Доля |\n|---|---|---|\n"
result += "\n".join(rows)
```

---

### Алгоритм: Markov Chain Attribution (основной data-driven)

> Использовать выборочную SQL-выгрузку выше. Расчёт на всех строках — медленно.

```python
import numpy as np
from collections import defaultdict

START, CONV, NULL = '(start)', '(conversion)', '(null)'

print(f"Строк: {len(df):,} | Конверсий (лидов): {df['converted'].sum():,}")

# 1. Строим пути с терминальными состояниями
paths = []
for _, row in df.iterrows():
    ch = list(row['channels_path'])
    if not ch:
        continue
    terminal = CONV if row['converted'] == 1 else NULL
    paths.append([START] + ch + [terminal])

print(f"Путей собрано: {len(paths):,}")

# 2. Подсчёт переходов
trans_counts = defaultdict(lambda: defaultdict(int))
for path in paths:
    for a, b in zip(path[:-1], path[1:]):
        trans_counts[a][b] += 1

# 3. Матрица переходов
states = sorted({s for path in paths for s in path})
idx = {s: i for i, s in enumerate(states)}
n = len(states)

T = np.zeros((n, n))
for fr, to_dict in trans_counts.items():
    total = sum(to_dict.values())
    for to, cnt in to_dict.items():
        T[idx[fr]][idx[to]] = cnt / total

for absorbing in [CONV, NULL]:
    if absorbing in idx:
        T[idx[absorbing]] = 0.0
        T[idx[absorbing]][idx[absorbing]] = 1.0

def conv_prob(matrix):
    Tp = np.linalg.matrix_power(matrix, 100)
    return float(Tp[idx[START], idx[CONV]])

base_p = conv_prob(T)
print(f"Базовая вероятность конверсии (лид): {base_p:.4f}")

if base_p >= 0.99:
    result = (
        "⚠️ ОШИБКА ДАННЫХ: base_p = {:.4f}\n\n"
        "В выгрузке отсутствуют пути `converted=0` — Markov работает некорректно.\n"
        "Повтори `clickhouse_query` с условием:\n"
        "```sql\nWHERE converted = 1\n   OR (converted = 0 AND rand() % 10 = 0)\n```"
    ).format(base_p)
else:
    channels = [s for s in states if s not in (START, CONV, NULL)]
    removal = {}
    for ch in channels:
        T_rem = T.copy()
        ci, ni = idx[ch], idx[NULL]
        for i in range(n):
            if T_rem[i][ci] > 0:
                T_rem[i][ni] += T_rem[i][ci]
                T_rem[i][ci] = 0.0
        removal[ch] = max(0.0, base_p - conv_prob(T_rem))

    total_removal = sum(removal.values())
    total_leads = int(df['converted'].sum())

    if total_removal == 0:
        result = "⚠️ Markov: нулевые removal effects — недостаточно данных."
    else:
        rows = []
        for ch in sorted(removal, key=lambda x: -removal[x]):
            share = removal[ch] / total_removal
            re_pct = removal[ch] / base_p * 100
            attr_leads = share * total_leads
            rows.append(f"| {ch} | {re_pct:.1f}% | {share:.1%} | {attr_leads:.0f} |")

        result = "## Markov Chain Attribution (по лидам)\n\n"
        result += "| Канал | Removal Effect | Attribution Share | Attributed Leads |\n"
        result += "|---|---|---|---|\n"
        result += "\n".join(rows)
        result += (
            f"\n\n**Removal Effect** — на сколько падает вероятность лида при удалении канала из всех путей.\n"
            f"База: {base_p:.4f} | Лидов: {total_leads:,} | Путей: {len(paths):,}"
        )
```

---

## Сравнительная таблица моделей

```python
# models = {'Linear': {'organic': 0.35, 'ad': 0.28, ...},
#            'U-Shaped': {...}, 'Markov': {...}}

channels_all = sorted({ch for m in models.values() for ch in m})
model_names = list(models.keys())
header = "| Канал | " + " | ".join(model_names) + " |"
sep = "|---|" + "---|" * len(model_names)
rows = [header, sep]
for ch in channels_all:
    vals = [f"{models[m].get(ch, 0):.1%}" for m in model_names]
    rows.append(f"| {ch} | " + " | ".join(vals) + " |")

result = "## Сравнение моделей атрибуции\n\n" + "\n".join(rows)
```

---

## Рекомендации по бюджету (без spend-данных)

Spend в ClickHouse **отсутствует** — точный CPA недоступен.
Если пользователь просит бюджетные рекомендации:

1. **Дать attribution share** по каналам из Markov
2. **Объяснить**: "Для точного CPA нужны расходы из Яндекс Директа — подключи данные о spend"
3. **Дать качественный вывод без домыслов:**

| Ситуация | Вывод |
|----------|-------|
| Высокий Markov + низкий Last Touch | Канал важен стратегически, недооценён в last-touch отчётах |
| Высокий Last Touch + низкий Markov | "Закрыватель" — без него лид не состоится, но сам не генерирует спрос |
| Высокий First Touch + низкий Markov | "Охватный" канал — инициирует интерес, но не решает исход |
| Расхождение между моделями > 2× | Сигнал: канал либо сильно недооценён, либо переоценён |

---

## Правила интерпретации

- **n < 100 лидов в сегменте** → не строить Markov, использовать Linear или U-Shaped
- **Removal effect < 1% от base_p** → канал статистически незначим, отметить ⚠️
- **dm_conversion_paths ≠ все клиенты** — только клиенты с отслеживаемым journey; анонимные не входят
- **sources_path содержит `""`** — это organic/direct, не удалять из путей, считать отдельным каналом
- Всегда указывать: покрытие (сколько лидов попало в модель)
- **Attribution credit = лиды**, не выручка. Для сделок (`has_crm_paid`) использовать отдельный анализ через dm_client_profile.
