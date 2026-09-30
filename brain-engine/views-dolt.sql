-- views-dolt.sql — les vues de surveillance, en dialecte Dolt/MySQL.
--
-- ⚠️  Six vues existaient dans `brain.db` (SQLite) et ZÉRO dans Dolt — mesuré
--     le 04/09 en auditant le BSI. La base que le brain lit n'avait aucune de
--     ses vues de surveillance : `migrate.py` les affiche, mais il les lit dans
--     SQLite, la base que plus personne ne consulte.
--
-- Elles sont dérivées : rien ne s'y écrit, tout se recalcule. Ce fichier est
-- donc la SOURCE, et `dolt sql < views-dolt.sql` la régénère à l'identique.
--
-- Traduction de SQLite vers MySQL : `julianday('now') - julianday(x)` devient
-- `TIMESTAMPDIFF`. Les dates sont en UTC dans les deux bases — `UTC_TIMESTAMP()`
-- et non `NOW()`, qui rendrait l'heure locale et surestimerait tout âge de deux
-- heures en CEST. C'est le défaut du 22/08, et il ne sera pas réintroduit ici.

DROP VIEW IF EXISTS v_open_claims;
CREATE VIEW v_open_claims AS
    SELECT sess_id, scope, opened_at, expires_at,
           ROUND(TIMESTAMPDIFF(MINUTE, opened_at, UTC_TIMESTAMP()) / 60.0, 1)
               AS age_hours
    FROM claims
    WHERE status = 'open'
    ORDER BY opened_at DESC;

-- Un claim « stale » se mesure depuis son EXPIRATION, pas depuis son ouverture.
-- La version SQLite disait `opened_at + 4 hours` : l'âge ne pouvait que
-- grandir, et une session de trois jours devenait un oubli par simple
-- écoulement du temps. Dix claims `pilote` ont été fermés à tort pour ça.
-- `expires_at` est repoussé par `bsi-claim.sh touch`, appelé à chaque commit.
DROP VIEW IF EXISTS v_stale_claims;
CREATE VIEW v_stale_claims AS
    SELECT sess_id, scope, opened_at, expires_at,
           ROUND(TIMESTAMPDIFF(MINUTE,
                 COALESCE(expires_at,
                          DATE_ADD(opened_at,
                                   INTERVAL COALESCE(ttl_hours, 4) HOUR)),
                 UTC_TIMESTAMP()) / 60.0, 1) AS expire_depuis_h
    FROM claims
    WHERE status = 'open'
      AND UTC_TIMESTAMP() > COALESCE(expires_at,
              DATE_ADD(opened_at, INTERVAL COALESCE(ttl_hours, 4) HOUR))
    ORDER BY expire_depuis_h DESC;

DROP VIEW IF EXISTS v_active_locks;
CREATE VIEW v_active_locks AS
    SELECT filepath, holder, claimed_at, expires_at,
           CASE WHEN UTC_TIMESTAMP() < expires_at THEN 'active'
                ELSE 'expired' END AS lock_status
    FROM locks
    ORDER BY claimed_at DESC;

DROP VIEW IF EXISTS v_cold_start_kpi;
CREATE VIEW v_cold_start_kpi AS
    SELECT COUNT(*) AS total_no_handoff,
           SUM(CASE WHEN cold_start_kpi_pass = 1 THEN 1 ELSE 0 END) AS passes,
           ROUND(100.0 * SUM(CASE WHEN cold_start_kpi_pass = 1 THEN 1 ELSE 0 END)
                 / NULLIF(SUM(CASE WHEN cold_start_kpi_pass IS NOT NULL
                                   THEN 1 ELSE 0 END), 0), 1) AS pass_rate_pct
    FROM sessions
    WHERE handoff_level = 'NO';

DROP VIEW IF EXISTS v_metabolism_7d;
CREATE VIEW v_metabolism_7d AS
    SELECT date, type,
           AVG(health_score) OVER (ORDER BY date
               ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS health_7d_avg,
           SUM(CASE WHEN type = 'build-brain' THEN 1 ELSE 0 END) OVER (
               ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS build_7d,
           SUM(CASE WHEN type = 'use-brain' THEN 1 ELSE 0 END) OVER (
               ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS use_7d
    FROM sessions;
