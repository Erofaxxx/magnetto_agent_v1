"""
Реестр skills — динамически подгружаемых инструкций для агента.

Каждый skill — это пара:
  router_hint : подсказка роутеру (какие ключевые слова/сценарии активируют скилл)
  full_path   : путь к .md файлу с детальными инструкциями

Добавление нового скилла:
  1. Создай skills/<name>.md
  2. Добавь запись в SKILLS ниже
  — код агента трогать не нужно.
"""

from pathlib import Path

_SKILLS_DIR = Path(__file__).parent

SKILLS: dict[str, dict] = {
    "clickhouse_querying": {
        "router_hint": (
            "SQL запрос к базе данных, выгрузить данные, написать SELECT, "
            "получить данные из ClickHouse, запрос к таблице, показать данные, "
            "сколько, топ, список, найди в базе"
        ),
        "full_path": _SKILLS_DIR / "clickhouse_querying.md",
    },
    "python_analysis": {
        "router_hint": (
            "анализ данных Python, рассчитать метрику, посчитать, сравнить значения, "
            "обработать данные, parquet файл, pandas, DataFrame, агрегация, "
            "среднее, медиана, процент, доля, динамика"
        ),
        "full_path": _SKILLS_DIR / "python_analysis.md",
    },
    "visualization": {
        "router_hint": (
            "график, диаграмма, визуализация, нарисуй, построй график, "
            "динамика на графике, тренд, столбчатая, линейная, гистограмма, "
            "scatter, heatmap, барчарт"
        ),
        "full_path": _SKILLS_DIR / "visualization.md",
    },
    "campaign_analysis": {
        "router_hint": (
            "кампании, каналы, источники трафика, utm_campaign, utm_source, "
            "конверсия каналов, качество трафика, откуда лиды, first touch, last touch, "
            "рекламные каналы, органика, директ, dm_traffic_performance"
        ),
        "full_path": _SKILLS_DIR / "campaign_analysis.md",
    },
    "cohort_analysis": {
        "router_hint": (
            "когорты, когортный анализ, удержание клиентов, retention, "
            "dm_client_journey, dm_client_profile, "
            "цикл сделки, клиенты по периодам, первый визит, прогрев"
        ),
        "full_path": _SKILLS_DIR / "cohort_analysis.md",
    },
    "anomaly_detection": {
        "router_hint": (
            "аномалии, аномальные значения, резкое изменение, выбросы, "
            "почему упало, почему выросло, неожиданный скачок, странные данные, "
            "необычное поведение, резкий рост, резкое падение, исследуй причину"
        ),
        "full_path": _SKILLS_DIR / "anomaly_detection.md",
    },
    "weekly_report": {
        "router_hint": (
            "еженедельный отчёт, сводка за неделю, итоги периода, дашборд, "
            "отчёт за месяц, общая сводка, ключевые метрики за период, "
            "weekly report, WoW, week over week, итоговый отчёт"
        ),
        "full_path": _SKILLS_DIR / "weekly_report.md",
    },
    "segmentation": {
        "router_hint": (
            "сегмент аудитории, именованный сегмент, для сегмента, покажи сегмент, "
            "лояльные покупатели, тёплые лиды, аудитория из сегмента, использовать сегмент, "
            "ретаргет сегмент, атрибуция для сегмента, segment, audience, "
            "кто из сегмента, анализ по сегменту"
        ),
        "full_path": _SKILLS_DIR / "segmentation.md",
    },
    "attribution": {
        "router_hint": (
            "атрибуция, data-driven атрибуция, вклад канала, Markov, Shapley, "
            "linear attribution, u-shaped, time decay, позиционная атрибуция, "
            "какой канал важнее, куда вкладывать бюджет, мультиканальная атрибуция, "
            "removal effect, attribution credit, customer journey attribution, "
            "какие каналы закрывают сделку, какие каналы открывают, attribution share"
        ),
        "full_path": _SKILLS_DIR / "attribution.md",
    },
}


def load_skill_instructions(active_skills: list[str]) -> str:
    """
    Загрузить и объединить инструкции для активных скиллов.

    Args:
        active_skills: список имён скиллов из SKILLS

    Returns:
        Строка с объединёнными инструкциями (или пустая строка если нет скиллов).
    """
    if not active_skills:
        return ""

    parts: list[str] = []
    for skill_name in active_skills:
        skill = SKILLS.get(skill_name)
        if skill is None:
            continue
        path: Path = skill["full_path"]
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(content)
        except Exception as exc:
            # Скилл не загружен — агент продолжит без него
            print(f"⚠️  Could not load skill '{skill_name}' from {path}: {exc}")

    return "\n\n---\n\n".join(parts)
