-- metabolism-dashboard.sql — Vue santé brain sur 7 jours
-- Usage : sqlite3 brain.db < brain-engine/queries/metabolism-dashboard.sql

-- Ratio use-brain / build-brain sur 7 jours
SELECT
    COUNT(*) AS sessions_7d,
    SUM(CASE WHEN type = 'build-brain' THEN 1 ELSE 0 END) AS build_brain,
    SUM(CASE WHEN type = 'use-brain'   THEN 1 ELSE 0 END) AS use_brain,
    ROUND(
        CAST(SUM(CASE WHEN type='use-brain' THEN 1 ELSE 0 END) AS REAL) /
        NULLIF(SUM(CASE WHEN type='build-brain' THEN 1 ELSE 0 END), 0),
    2) AS ratio_use_build,
    ROUND(AVG(health_score), 2) AS avg_health_score,
    CASE
        WHEN ROUND(CAST(SUM(CASE WHEN type='use-brain' THEN 1 ELSE 0 END) AS REAL) /
             NULLIF(SUM(CASE WHEN type='build-brain' THEN 1 ELSE 0 END), 0), 2) >= 1.0
        THEN '✅ équilibré'
        WHEN ROUND(CAST(SUM(CASE WHEN type='use-brain' THEN 1 ELSE 0 END) AS REAL) /
             NULLIF(SUM(CASE WHEN type='build-brain' THEN 1 ELSE 0 END), 0), 2) >= 0.5
        THEN '⚠️  à surveiller'
        ELSE '🔴 boucle narcissique'
    END AS verdict
FROM sessions
WHERE date >= date('now', '-7 days');
