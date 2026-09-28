-- graduation-candidates.sql — Patterns L3a prêts pour graduation vers L3b (toolkit)
-- Usage : sqlite3 brain.db < brain-engine/queries/graduation-candidates.sql

SELECT
    agent,
    projet,
    stack,
    pattern_id,
    validations,
    seuil_graduation,
    ROUND(CAST(validations AS REAL) / seuil_graduation * 100) || '%' AS progress,
    last_validated
FROM agent_memory
WHERE graduated = 0
  AND validations >= seuil_graduation
ORDER BY validations DESC;
