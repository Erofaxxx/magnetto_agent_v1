# Инструкция для фронтенд Claude Code: фильтр по кабинетам Директа

> Скопируй этот файл целиком в чат с Claude Code на фронте — он самодостаточный.

## Контекст

На бэкенде (FastAPI, `server.asktab.ru`) добавлена фильтрация таблиц `bad_placements`, `bad_keywords`, `bad_queries` по рекламному кабинету Яндекс Директа. У клиента Magnetto 4 кабинета (`audit-magnetto-tab1..tab4`), и в каждой строке этих таблиц теперь есть колонка `cabinet_name`.

Нужно добавить на фронте **селектор кабинета** рядом с существующим фильтром `zone_status` — чтобы пользователь мог смотреть плохие площадки/ключи/запросы отдельно по каждому кабинету.

**Важно:** список кабинетов **нельзя хардкодить**. Он приходит с бэкенда и может измениться (если подключат новый кабинет, он появится в списке автоматически).

---

## 1. Что изменилось в API

### `GET /api/tables`

**Было** (ответ):
```json
{
  "queries": [
    {
      "name": "bad_placements",
      "description": "Плохие площадки",
      "sortable_columns": [...],
      "filterable_zone_status": true
    }
  ]
}
```

**Стало** (ответ):
```json
{
  "queries": [
    {
      "name": "bad_placements",
      "description": "Плохие площадки",
      "sortable_columns": ["Placement", "CampaignName", "...", "cabinet_name"],
      "filterable_zone_status": true,
      "filterable_cabinet": true,
      "cabinets": ["audit-magnetto-tab1", "audit-magnetto-tab2", "audit-magnetto-tab3", "audit-magnetto-tab4"]
    },
    {
      "name": "daily_briefing",
      "filterable_cabinet": false,
      "cabinets": []
    }
  ],
  "cabinets": ["audit-magnetto-tab1", "audit-magnetto-tab2", "audit-magnetto-tab3", "audit-magnetto-tab4"]
}
```

Новые поля:
- `filterable_cabinet: boolean` — поддерживает ли таблица фильтр по кабинету (рисовать ли селектор).
- `cabinets: string[]` — список допустимых значений для этой таблицы. Пустой, если `filterable_cabinet = false`.
- Корневой `cabinets` — общий список (одинаков для всех filterable-таблиц), удобен для единого селектора в шапке.

### `GET /api/tables/{query_name}`

Добавлен новый query-параметр:

| Параметр | Тип | Пример | Обязательный |
|----------|-----|--------|--------------|
| `cabinet_name` | string | `audit-magnetto-tab3` | нет |

Значение должно быть **из списка `cabinets`**, который пришёл в `/api/tables`. Если передать произвольную строку — бэк вернёт `400 Unknown cabinet '...'. Available: [...]`.

Пример запроса с комбинацией фильтров:
```
GET /api/tables/bad_placements?cabinet_name=audit-magnetto-tab3&zone_status=red&sort_by=cost&sort_dir=desc&limit=50
```

Формат ответа не изменился:
```json
{
  "columns": ["Placement", "CampaignName", "...", "cabinet_name"],
  "rows": [ [...], [...] ],
  "row_count": 50,
  "total_count": 1247
}
```

`total_count` корректно учитывает фильтр — пагинация работает как раньше.

### Что делать с таблицами без `filterable_cabinet`

Для `daily_briefing` (и любой будущей таблицы с `filterable_cabinet: false`) — **не показывай селектор кабинета**. Фронт должен смотреть на флаг, а не на имя таблицы.

---

## 2. Что сделать на фронте

### 2.1. Расширить тип ответа `/api/tables`

Если у тебя есть TypeScript-типы для API — добавь поля. Примерная форма:

```ts
interface TableQueryMeta {
  name: string;
  description: string;
  sortable_columns: string[];
  filterable_zone_status: boolean;
  filterable_cabinet: boolean;   // ← новое
  cabinets: string[];             // ← новое
}

interface TablesResponse {
  queries: TableQueryMeta[];
  cabinets: string[];             // ← новое (глобальный список)
}
```

### 2.2. Добавить состояние выбранного кабинета

Рядом с состоянием `zoneStatus` (или как у тебя называется) заведи `cabinetName: string | null`. Начальное значение `null` = "все кабинеты".

### 2.3. Нарисовать селектор

Рядом с существующим фильтром `zone_status`. Требования:
- **Не рендерить**, если у текущей таблицы `filterable_cabinet === false`.
- Варианты в выпадашке: "Все кабинеты" (null) + все значения из `meta.cabinets` для этой таблицы.
- Подпись вариантов — можно сокращать: `audit-magnetto-tab3` → `tab3` или сопоставлять с проектом:
  - `audit-magnetto-tab1` → **Costura Town**
  - `audit-magnetto-tab2` → **Niti**
  - `audit-magnetto-tab3` → **Rivayat**
  - `audit-magnetto-tab4` → **Origana**

  Маппинг названий проектов делай **на фронте**, ориентируясь на значение из `cabinets` (по индексу `tab1/tab2/tab3/tab4` в конце строки). Если бэк вернёт неизвестный `tabN` — просто покажи исходное значение.

### 2.4. Прокидывать `cabinet_name` в запрос

При запросе `/api/tables/{query_name}` добавь параметр:
```ts
const params = new URLSearchParams();
if (zoneStatus) params.set("zone_status", zoneStatus);
if (cabinetName) params.set("cabinet_name", cabinetName);
if (sortBy) params.set("sort_by", sortBy);
params.set("sort_dir", sortDir);
params.set("limit", String(limit));

fetch(`${API_BASE}/api/tables/${queryName}?${params}`)
```

### 2.5. Сбрасывать фильтр при смене таблицы

Если пользователь был на `bad_placements` с выбранным кабинетом и переключился на `daily_briefing` (где фильтра нет) — сбрасывай `cabinetName = null`, чтобы при возврате на `bad_placements` не осталось залипшего значения (либо сохраняй и применяй обратно — на твой вкус, но обязательно не отправляй `cabinet_name` в запросы к таблицам с `filterable_cabinet: false`).

### 2.6. (Опционально) Показать колонку `cabinet_name` в таблице

`cabinet_name` теперь есть в `columns` ответа — **последняя колонка**. Никаких действий не требуется, если рендеринг колонок у тебя универсальный (по `columns`). Если есть хардкод-списки колонок для каждой таблицы — добавь `cabinet_name` в конец.

---

## 3. Чек-лист приёмки

- [ ] Селектор кабинета отображается на страницах `bad_placements`, `bad_keywords`, `bad_queries`.
- [ ] Селектор **не отображается** на `daily_briefing`.
- [ ] Список значений в селекторе соответствует `meta.cabinets` (не хардкод).
- [ ] Выбор кабинета перерисовывает таблицу с отфильтрованными данными.
- [ ] Счётчик общего кол-ва строк (`total_count`) обновляется после фильтрации.
- [ ] Работает комбинация фильтров `zone_status` + `cabinet_name`.
- [ ] Сортировка `sort_by` работает поверх фильтра.
- [ ] Опция "Все кабинеты" возвращает таблицу без фильтра (параметр `cabinet_name` не отправляется).
- [ ] Смена таблицы на `daily_briefing` не оставляет `cabinet_name` в последующих запросах.
- [ ] При 400-ошибке от бэка (`Unknown cabinet`) фронт показывает понятное сообщение, а не ломается.

---

## 4. Edge cases

1. **Бэк ещё не вернул список кабинетов** (первый запрос, кэш пуст, ClickHouse временно недоступен) — `cabinets` может быть пустым массивом. Если `filterable_cabinet: true` но `cabinets: []` — не рендерь селектор или рендерь его задизейбленным.
2. **Пользователь держит открытую вкладку несколько часов** — список кабинетов на бэке кэшируется на 1 час, после чего обновляется. Если в будущем появится `tab5` — не перезагружая вкладку, пользователь его не увидит, пока не обновит `/api/tables` (можно при открытии страницы таблицы вызывать `/api/tables` заново, это дешёвый запрос).
3. **Нестандартные значения** — если бэк вдруг вернёт непривычное значение (`null`, пустая строка, кабинет без префикса `audit-magnetto-`) — покажи как есть, не ломайся. Фильтр опирается на whitelist от бэка, так что валидное значение всегда пройдёт.

---

## 5. Дизайн-подсказки

- Если UI дропдаун zone_status — то же самое визуально и для cabinet_name, по соседству.
- Альтернатива — компактные чипсы `tab1 / tab2 / tab3 / tab4 / Все` над таблицей (меньше кликов).
- Выбранный кабинет полезно отразить в URL (`?cabinet=tab3`) чтобы ссылкой можно было поделиться.

---

## Готово

Когда сделаешь — проверь в браузере:
1. Открой `bad_placements`, выбери кабинет → таблица фильтруется.
2. Добавь `zone_status=red` → фильтруется одновременно по зоне и кабинету.
3. Переключись на `daily_briefing` → селектор кабинета исчез.
4. Открой `/api/tables` в сетевой вкладке — увидишь, что значения приходят из `cabinets`, а не захардкожены у тебя.
