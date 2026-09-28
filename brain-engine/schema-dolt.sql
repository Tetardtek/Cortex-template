-- schema-dolt.sql — la déclaration des tables de la base vivante.
--
-- ⚠️  GÉNÉRÉ par scripts/dolt-schema-gen.sh — ne pas éditer à la main.
--     Modifier la base, puis régénérer. Éditer ici ferait diverger la
--     déclaration de ce qu'elle décrit, ce que tout ce chantier combat.
--
-- Les six VUES ne sont pas ici : elles vivent dans views-dolt.sql, écrites
-- à la main parce qu'elles portent leur raisonnement. Une source chacun.
--
-- Les défauts d'enum sont réécrits en littéral : dolt les rend en index
-- numérique (DEFAULT '1' pour 'open'), et ce défaut survit à la 2.3.2.
--
-- Vérifié par rechargement réel dans un dépôt Dolt jetable avant écriture.

SET FOREIGN_KEY_CHECKS=0;
SET UNIQUE_CHECKS=0;
DROP TABLE IF EXISTS `agent_loads`;
CREATE TABLE `agent_loads` (
  `id` int NOT NULL AUTO_INCREMENT,
  `sess_id` varchar(128) NOT NULL,
  `agent` varchar(128) NOT NULL,
  `tokens_estimated` int,
  `loaded_at` datetime NOT NULL,
  `reason` text,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `agent_memory`;
CREATE TABLE `agent_memory` (
  `id` int NOT NULL AUTO_INCREMENT,
  `agent` varchar(128) NOT NULL,
  `projet` varchar(128) NOT NULL,
  `stack` varchar(128) NOT NULL,
  `pattern_id` varchar(128) NOT NULL,
  `validations` int NOT NULL DEFAULT '0',
  `kpi_score` double NOT NULL DEFAULT '0',
  `graduated` tinyint NOT NULL DEFAULT '0',
  `seuil_graduation` int NOT NULL DEFAULT '3',
  `last_validated` datetime,
  `notes` text,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `agent` (`agent`,`projet`,`stack`,`pattern_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `agents`;
CREATE TABLE `agents` (
  `id` varchar(128) NOT NULL,
  `name` varchar(255) NOT NULL,
  `type` varchar(64),
  `context_tier` enum('always','hot','warm','cold') DEFAULT 'cold',
  `domain` json,
  `status` enum('active','stable','draft','deprecated') DEFAULT 'active',
  `scope` varchar(64),
  `owner` varchar(64) DEFAULT 'human',
  `lifecycle` varchar(64),
  `read_mode` varchar(64),
  `triggers` json,
  `receives_from` json,
  `sends_to` json,
  `zone_access` json,
  `signals` json,
  `description` text,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `backlog_visions`;
CREATE TABLE `backlog_visions` (
  `id` varchar(128) NOT NULL,
  `project` varchar(128),
  `title` varchar(255) NOT NULL,
  `status` enum('seed','conception','ready','promoted','archived') DEFAULT 'seed',
  `filename` varchar(255),
  `description` text,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `project` (`project`),
  CONSTRAINT `backlog_visions_ibfk_1` FOREIGN KEY (`project`) REFERENCES `projects` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `chantiers`;
CREATE TABLE `chantiers` (
  `id` varchar(64) NOT NULL,
  `title` varchar(255) NOT NULL,
  `status` enum('proposed','active','paused','resolved','abandoned') NOT NULL DEFAULT 'proposed',
  `project` varchar(32) NOT NULL DEFAULT 'brain',
  `description` text,
  `resolved_by` json,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `circuit_breaker`;
CREATE TABLE `circuit_breaker` (
  `sess_id` varchar(128) NOT NULL,
  `fail_count` int NOT NULL DEFAULT '0',
  `last_fail_at` datetime,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`sess_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `claims`;
CREATE TABLE `claims` (
  `sess_id` varchar(128) NOT NULL,
  `type` varchar(64) NOT NULL,
  `scope` varchar(512) NOT NULL,
  `status` enum('open','closed','stale','paused','waiting_human','failed') NOT NULL DEFAULT 'open',
  `opened_at` datetime NOT NULL,
  `closed_at` datetime,
  `handoff_level` enum('NO','SEMI','SEMI+','FULL'),
  `story_angle` text,
  `health_score` double,
  `context_at_close` int,
  `cold_start_kpi_pass` tinyint,
  `ttl_hours` int DEFAULT '4',
  `expires_at` datetime,
  `instance` varchar(128),
  `parent_sess` varchar(128),
  `satellite_type` varchar(64),
  `satellite_level` varchar(64),
  `theme_branch` varchar(128),
  `zone` varchar(64),
  `mode` varchar(64),
  `result_status` varchar(64),
  `result_json` text,
  `workflow` varchar(128),
  `workflow_step` int,
  `project` varchar(128),
  `result` varchar(64),
  `duration_min` int,
  `energy` varchar(16),
  `intention` varchar(128),
  `tags` varchar(512),
  `deliverables` text,
  `agent_session` text,
  PRIMARY KEY (`sess_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `claims_archive`;
CREATE TABLE `claims_archive` (
  `sess_id` varchar(128) NOT NULL,
  `type` varchar(64) NOT NULL,
  `scope` varchar(512) NOT NULL,
  `status` enum('open','closed','stale','paused','waiting_human','failed') NOT NULL DEFAULT 'open',
  `opened_at` datetime NOT NULL,
  `closed_at` datetime,
  `handoff_level` enum('NO','SEMI','SEMI+','FULL'),
  `story_angle` text,
  `health_score` double,
  `context_at_close` int,
  `cold_start_kpi_pass` tinyint,
  `ttl_hours` int DEFAULT '4',
  `expires_at` datetime,
  `instance` varchar(128),
  `parent_sess` varchar(128),
  `satellite_type` varchar(64),
  `satellite_level` varchar(64),
  `theme_branch` varchar(128),
  `zone` varchar(64),
  `mode` varchar(64),
  `result_status` varchar(64),
  `result_json` text,
  `workflow` varchar(128),
  `workflow_step` int,
  `project` varchar(128),
  `result` varchar(64),
  `duration_min` int,
  `energy` varchar(16),
  `intention` varchar(128),
  `tags` varchar(512),
  `deliverables` text,
  `agent_session` text,
  `archived_at` datetime NOT NULL,
  PRIMARY KEY (`sess_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `cosmos_edges`;
CREATE TABLE `cosmos_edges` (
  `source_id` varchar(255) NOT NULL,
  `target_id` varchar(255) NOT NULL,
  `similarity` double NOT NULL,
  PRIMARY KEY (`source_id`,`target_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `decision_chantiers`;
CREATE TABLE `decision_chantiers` (
  `decision_id` varchar(64) NOT NULL,
  `chantier_id` varchar(64) NOT NULL,
  `linked_at` datetime NOT NULL,
  PRIMARY KEY (`decision_id`,`chantier_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `decisions`;
CREATE TABLE `decisions` (
  `id` varchar(64) NOT NULL,
  `title` varchar(255) NOT NULL,
  `status` enum('proposed','accepted','deprecated','superseded') NOT NULL DEFAULT 'proposed',
  `scope` varchar(64),
  `date` date,
  `deciders` json,
  `depends_on` json,
  `tags` json,
  `session` json,
  `filename` varchar(255),
  `description` text,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `project` varchar(32) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `embedding_hits`;
CREATE TABLE `embedding_hits` (
  `chunk_id` varchar(255) NOT NULL,
  `hit_count` int NOT NULL DEFAULT '0',
  `last_queried_at` datetime,
  PRIMARY KEY (`chunk_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `embeddings`;
CREATE TABLE `embeddings` (
  `chunk_id` varchar(255) NOT NULL,
  `filepath` varchar(512) NOT NULL,
  `title` varchar(512),
  `chunk_text` longtext NOT NULL,
  `vector` varbinary(4096),
  `model` varchar(128),
  `indexed` tinyint DEFAULT '0',
  `scope` varchar(32) NOT NULL DEFAULT 'work',
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  `last_queried_at` datetime,
  `hit_count` int DEFAULT '0',
  `permanent` tinyint DEFAULT '0',
  `x` double,
  `y` double,
  `z` double,
  `content_hash` char(64),
  PRIMARY KEY (`chunk_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `handoffs`;
CREATE TABLE `handoffs` (
  `filename` varchar(255) NOT NULL,
  `type` varchar(64),
  `projet` varchar(128),
  `status` enum('active','consumed','archived') NOT NULL DEFAULT 'active',
  `from_sess` varchar(128),
  `consumed_by` varchar(128),
  `created_at` datetime NOT NULL,
  `consumed_at` datetime,
  PRIMARY KEY (`filename`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `handoffs_archive`;
CREATE TABLE `handoffs_archive` (
  `filename` varchar(255) NOT NULL,
  `type` varchar(64),
  `projet` varchar(128),
  `status` enum('active','consumed','archived') NOT NULL DEFAULT 'active',
  `from_sess` varchar(128),
  `consumed_by` varchar(128),
  `created_at` datetime NOT NULL,
  `consumed_at` datetime,
  `archived_at` datetime NOT NULL,
  PRIMARY KEY (`filename`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `intention_edges`;
CREATE TABLE `intention_edges` (
  `source_id` varchar(128) NOT NULL,
  `target_id` varchar(128) NOT NULL,
  `relation` enum('blocks','depends_on') NOT NULL,
  PRIMARY KEY (`source_id`,`target_id`,`relation`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `intention_sessions`;
CREATE TABLE `intention_sessions` (
  `intention_id` varchar(128) NOT NULL,
  `sess_id` varchar(128) NOT NULL,
  `linked_at` datetime NOT NULL,
  PRIMARY KEY (`intention_id`,`sess_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `intention_tags`;
CREATE TABLE `intention_tags` (
  `intention_id` varchar(128) NOT NULL,
  `tag` varchar(64) NOT NULL,
  PRIMARY KEY (`intention_id`,`tag`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `intentions`;
CREATE TABLE `intentions` (
  `id` varchar(128) NOT NULL,
  `title` varchar(255) NOT NULL,
  `status` enum('identified','active','stasis','done','archived') NOT NULL,
  `project` varchar(128),
  `domain` varchar(64),
  `scope` varchar(64),
  `priority` enum('high','medium','low','none') DEFAULT 'medium',
  `brief` text,
  `next_step` text,
  `stasis_reason` text,
  `tenant` varchar(128),
  `ttl_days` int DEFAULT '60',
  `front` tinyint DEFAULT '0',
  `front_order` int,
  `agents` json,
  `adrs` json,
  `total_sessions` int DEFAULT '0',
  `total_duration` int DEFAULT '0',
  `last_touched` datetime,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `learning_modules`;
CREATE TABLE `learning_modules` (
  `id` varchar(128) NOT NULL,
  `track_id` varchar(128) NOT NULL,
  `title` varchar(255) NOT NULL,
  `status` enum('locked','exploring','acquired','a-faire','in-progress','paused') DEFAULT 'locked',
  `sort_order` int DEFAULT '0',
  `description` text,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`track_id`,`id`),
  CONSTRAINT `learning_modules_ibfk_1` FOREIGN KEY (`track_id`) REFERENCES `learning_tracks` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `learning_tracks`;
CREATE TABLE `learning_tracks` (
  `id` varchar(128) NOT NULL,
  `title` varchar(255) NOT NULL,
  `status` enum('exploring','paused','acquired') DEFAULT 'exploring',
  `domain` json,
  `feeds` json,
  `module_count` int DEFAULT '0',
  `modules_done` int DEFAULT '0',
  `description` text,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `locks`;
CREATE TABLE `locks` (
  `id` int NOT NULL AUTO_INCREMENT,
  `filepath` varchar(512) NOT NULL,
  `holder` varchar(128) NOT NULL,
  `claimed_at` datetime NOT NULL,
  `expires_at` datetime NOT NULL,
  `ttl_min` int NOT NULL DEFAULT '60',
  PRIMARY KEY (`id`),
  UNIQUE KEY `filepath` (`filepath`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `projects`;
CREATE TABLE `projects` (
  `id` varchar(128) NOT NULL,
  `title` varchar(255) NOT NULL,
  `status` enum('planned','cadrage','dev','active','prod','pause','archived') NOT NULL,
  `deploy` varchar(128),
  `stack` json,
  `url_prod` varchar(255),
  `repo` varchar(255),
  `tenant` varchar(128),
  `description` text,
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `sessions`;
CREATE TABLE `sessions` (
  `sess_id` varchar(128) NOT NULL,
  `date` varchar(32) NOT NULL,
  `type` varchar(64),
  `mode` varchar(64),
  `handoff_level` varchar(16),
  `tokens_used` int,
  `context_peak_pct` int,
  `context_at_close` int,
  `duration_min` int,
  `commits` int,
  `todos_closed` int,
  `saturation_flag` tinyint,
  `health_score` double,
  `cold_start_kpi_pass` tinyint,
  `notes` text,
  PRIMARY KEY (`sess_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `sessions_archive`;
CREATE TABLE `sessions_archive` (
  `sess_id` varchar(128) NOT NULL,
  `date` varchar(32) NOT NULL,
  `type` varchar(64),
  `mode` varchar(64),
  `handoff_level` varchar(16),
  `tokens_used` int,
  `context_peak_pct` int,
  `context_at_close` int,
  `duration_min` int,
  `commits` int,
  `todos_closed` int,
  `saturation_flag` tinyint,
  `health_score` double,
  `cold_start_kpi_pass` tinyint,
  `notes` text,
  `archived_at` datetime NOT NULL,
  PRIMARY KEY (`sess_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `signals`;
CREATE TABLE `signals` (
  `sig_id` varchar(128) NOT NULL,
  `from_sess` varchar(128),
  `to_sess` varchar(128) NOT NULL,
  `type` enum('READY_FOR_REVIEW','REVIEWED','BLOCKED_ON','HANDOFF','CHECKPOINT','INFO') NOT NULL,
  `projet` varchar(128),
  `payload` text,
  `state` enum('pending','delivered','archived') NOT NULL DEFAULT 'pending',
  `created_at` datetime NOT NULL,
  `delivered_at` datetime,
  PRIMARY KEY (`sig_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `signals_archive`;
CREATE TABLE `signals_archive` (
  `sig_id` varchar(128) NOT NULL,
  `from_sess` varchar(128),
  `to_sess` varchar(128) NOT NULL,
  `type` enum('READY_FOR_REVIEW','REVIEWED','BLOCKED_ON','HANDOFF','CHECKPOINT','INFO') NOT NULL,
  `projet` varchar(128),
  `payload` text,
  `state` enum('pending','delivered','archived') NOT NULL DEFAULT 'pending',
  `created_at` datetime NOT NULL,
  `delivered_at` datetime,
  `archived_at` datetime NOT NULL,
  PRIMARY KEY (`sig_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `todo_items`;
CREATE TABLE `todo_items` (
  `id` int NOT NULL AUTO_INCREMENT,
  `section_id` int NOT NULL,
  `text` text NOT NULL,
  `done` tinyint DEFAULT '0',
  `sort_order` int DEFAULT '0',
  `created_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `section_id` (`section_id`),
  CONSTRAINT `todo_items_ibfk_1` FOREIGN KEY (`section_id`) REFERENCES `todo_sections` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
DROP TABLE IF EXISTS `todo_sections`;
CREATE TABLE `todo_sections` (
  `id` int NOT NULL AUTO_INCREMENT,
  `project` varchar(128) NOT NULL,
  `title` varchar(255) NOT NULL,
  `intention_id` varchar(128),
  `status` enum('open','done','cancelled') DEFAULT 'open',
  `sort_order` int DEFAULT '0',
  `created_at` datetime NOT NULL,
  `updated_at` datetime NOT NULL,
  PRIMARY KEY (`id`),
  KEY `intention_id` (`intention_id`),
  KEY `project` (`project`),
  CONSTRAINT `todo_sections_ibfk_1` FOREIGN KEY (`project`) REFERENCES `projects` (`id`),
  CONSTRAINT `todo_sections_ibfk_2` FOREIGN KEY (`intention_id`) REFERENCES `intentions` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_bin;
