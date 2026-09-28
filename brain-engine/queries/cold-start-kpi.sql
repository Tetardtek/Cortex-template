-- cold-start-kpi.sql — KPI North Star : NO HANDOFF productif < 2 min
-- Ref : brain-constitution.md §3
-- Usage : sqlite3 brain.db < brain-engine/queries/cold-start-kpi.sql

-- Vue globale
SELECT
    total_no_handoff,
    passes,
    pass_rate_pct || '%' AS pass_rate,
    CASE
        WHEN pass_rate_pct >= 80 THEN '✅ Layer 0 stable'
        WHEN pass_rate_pct >= 60 THEN '⚠️  Layer 0 à surveiller'
        ELSE '🔴 Layer 0 insuffisant — enrichir brain-constitution.md'
    END AS verdict
FROM v_cold_start_kpi;

-- Détail par session
SELECT
    sess_id,
    date,
    CASE cold_start_kpi_pass
        WHEN 1 THEN '✅ pass'
        WHEN 0 THEN '❌ fail'
        ELSE '— non mesuré'
    END AS kpi,
    notes
FROM sessions
WHERE handoff_level = 'NO'
ORDER BY date DESC
LIMIT 10;
