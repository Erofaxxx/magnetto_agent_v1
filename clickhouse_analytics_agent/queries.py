"""
Named ClickHouse queries for GET /api/tables/{query_name}.

Структура каждого запроса:
  description      — короткое описание для фронта
  sql              — SELECT без ORDER BY и LIMIT (добавляются динамически)
  sortable_columns — белый список колонок, по которым разрешена сортировка
  filterable_zone_status — флаг: поддерживается ли фильтрация по zone_status

Добавляй новые запросы сюда — endpoint подхватит их автоматически.
"""

QUERIES: dict[str, dict] = {
    "bad_placements": {
        "description": "Плохие площадки",
        "sql": """
            SELECT
                `Placement`,
                `CampaignName`,
                cost,
                clicks,
                cpc,
                purchase_revenue,
                roas,
                goal_score_rate,
                bounce_rate,
                avg_cpc_campaign,
                bench_roas_campaign,
                bench_goal_score_rate,
                zone_status,
                zone_reason
            FROM magnetto.bad_placements
            WHERE (zone_status != 'pending' OR zone_status IS NULL)
        """,
        "sortable_columns": ["Placement", "CampaignName", "cpc", "cost", "clicks", "purchase_revenue", "roas", "goal_score_rate", "tier12_conversions", "med_cpc_campaign", "med_gsr_campaign", "med_roas_campaign", "zone_status"],
        "filterable_zone_status": True,
    },
    "bad_keywords": {
        "description": "Плохие ключевые запросы",
        "sql": """
            SELECT
                `Criterion`,
                `CampaignName`,
                ad_network_type,
                `AdGroupName`,
                cpc,
                goal_score_rate,
                avg_bid,
                cpc_to_bid_ratio,
                purchase_revenue,
                roas,
                med_roas,
                tier12_conversions,
                med_goal_score_rate,
                zone_status
            FROM magnetto.bad_keywords
            WHERE (zone_status != 'pending')
        """,
        "sortable_columns": ["Criterion", "CampaignName", "AdGroupName", "cpc", "goal_score_rate", "avg_bid", "cpc_to_bid_ratio", "purchase_revenue", "roas", "med_roas", "tier12_conversions", "med_goal_score_rate", "zone_status"],
        "filterable_zone_status": True,
    },
    "bad_queries": {
        "description": "Плохие поисковые запросы",
        "sql": """
            SELECT
                `Query`,
                `CriterionType`,
                `CampaignName`,
                `TargetingCategory`,
                `roas`,
                `goal_score_rate`,
                `cost`,
                `clicks`,
                `cpc`,
                `bounce_rate`,
                `zone_status`,
                `zone_reason`
            FROM magnetto.bad_queries
            WHERE (zone_status != 'pending')
        """,
        "sortable_columns": ["Query", "CriterionType", "CampaignName", "TargetingCategory", "roas", "goal_score_rate", "cost", "clicks", "cpc", "bounce_rate", "zone_status", "zone_reason"],
        "filterable_zone_status": True,
    },
}
