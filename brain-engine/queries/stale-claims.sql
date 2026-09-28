-- stale-claims.sql — Claims ouverts depuis plus de 4h
-- Usage : sqlite3 brain.db < brain-engine/queries/stale-claims.sql

SELECT
    sess_id,
    scope,
    opened_at,
    ROUND((julianday('now') - julianday(opened_at)) * 24, 1) AS age_hours
FROM claims
WHERE status = 'open'
  AND julianday('now') > julianday(opened_at, '+4 hours')
ORDER BY age_hours DESC;
