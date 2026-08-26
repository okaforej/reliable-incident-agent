PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS evaluations;
DROP TABLE IF EXISTS investigation_events;
DROP TABLE IF EXISTS tool_calls;
DROP TABLE IF EXISTS action_proposals;
DROP TABLE IF EXISTS chat_messages;
DROP TABLE IF EXISTS comparisons;
DROP TABLE IF EXISTS investigation_runs;
DROP TABLE IF EXISTS replay_instances;
DROP TABLE IF EXISTS replay_state;
DROP TABLE IF EXISTS expected_outcomes;
DROP TABLE IF EXISTS changes;
DROP TABLE IF EXISTS logs;
DROP TABLE IF EXISTS metric_points;
DROP TABLE IF EXISTS metrics;
DROP TABLE IF EXISTS dependencies;
DROP TABLE IF EXISTS services;
DROP TABLE IF EXISTS incidents;
DROP TABLE IF EXISTS scenarios;

CREATE TABLE scenarios (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT NOT NULL
);

CREATE TABLE incidents (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL REFERENCES scenarios(id),
  title TEXT NOT NULL,
  severity TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL,
  affected_service TEXT NOT NULL,
  customer_impact TEXT NOT NULL,
  target_sli TEXT NOT NULL,
  symptoms_json TEXT NOT NULL
);

CREATE TABLE services (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL REFERENCES scenarios(id),
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  team TEXT NOT NULL
);

CREATE TABLE dependencies (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL REFERENCES scenarios(id),
  source_service TEXT NOT NULL,
  target_service TEXT NOT NULL,
  protocol TEXT NOT NULL,
  critical_paths_json TEXT NOT NULL
);

CREATE TABLE metrics (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL REFERENCES scenarios(id),
  service TEXT NOT NULL,
  name TEXT NOT NULL,
  unit TEXT NOT NULL,
  description TEXT NOT NULL,
  threshold REAL
);

CREATE TABLE metric_points (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  metric_id TEXT NOT NULL REFERENCES metrics(id),
  ts TEXT NOT NULL,
  value REAL NOT NULL
);

CREATE TABLE logs (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL REFERENCES scenarios(id),
  ts TEXT NOT NULL,
  service TEXT NOT NULL,
  level TEXT NOT NULL,
  message TEXT NOT NULL,
  fields_json TEXT NOT NULL
);

CREATE TABLE changes (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL REFERENCES scenarios(id),
  ts TEXT NOT NULL,
  service TEXT NOT NULL,
  kind TEXT NOT NULL,
  summary TEXT NOT NULL,
  details_json TEXT NOT NULL
);

CREATE TABLE expected_outcomes (
  scenario_id TEXT PRIMARY KEY REFERENCES scenarios(id),
  root_cause TEXT NOT NULL
);

CREATE TABLE replay_instances (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL REFERENCES scenarios(id),
  status TEXT NOT NULL,
  checkout_db_pool_connections INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE investigation_runs (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL REFERENCES scenarios(id),
  replay_instance_id TEXT NOT NULL REFERENCES replay_instances(id),
  agent_config_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  incident_id TEXT NOT NULL,
  incident_description TEXT NOT NULL,
  final_root_cause TEXT,
  final_result_json TEXT,
  hypotheses_json TEXT,
  prompt_version TEXT,
  tool_schema_version TEXT,
  model TEXT,
  provider_metadata_json TEXT,
  error TEXT
);

CREATE TABLE investigation_events (
  run_id TEXT NOT NULL REFERENCES investigation_runs(id),
  event_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  type TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  PRIMARY KEY (run_id, event_id)
);

CREATE TABLE tool_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES investigation_runs(id),
  sequence INTEGER NOT NULL,
  tool_name TEXT NOT NULL,
  purpose TEXT NOT NULL,
  arguments_json TEXT NOT NULL,
  result_json TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  status TEXT NOT NULL,
  duration_ms INTEGER NOT NULL
);

CREATE TABLE comparisons (
  id TEXT PRIMARY KEY,
  scenario_id TEXT NOT NULL REFERENCES scenarios(id),
  created_at TEXT NOT NULL,
  baseline_run_id TEXT NOT NULL REFERENCES investigation_runs(id),
  candidate_run_id TEXT NOT NULL REFERENCES investigation_runs(id)
);

CREATE TABLE chat_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES investigation_runs(id),
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  evidence_ids_json TEXT NOT NULL,
  tool_calls_json TEXT NOT NULL,
  action_proposal_id TEXT
);

CREATE TABLE action_proposals (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES investigation_runs(id),
  action_name TEXT NOT NULL,
  arguments_json TEXT NOT NULL,
  expected_impact TEXT NOT NULL,
  status TEXT NOT NULL,
  result_json TEXT,
  verification_status TEXT NOT NULL,
  verification_tool_calls_json TEXT NOT NULL,
  recovery_assessment_json TEXT,
  agent_assessment_error TEXT
);

CREATE TABLE evaluations (
  run_id TEXT PRIMARY KEY REFERENCES investigation_runs(id),
  rca_correct INTEGER NOT NULL,
  grounded INTEGER NOT NULL,
  investigation_sufficient INTEGER NOT NULL,
  tool_efficient INTEGER NOT NULL,
  behavioral_slo_pass INTEGER NOT NULL,
  reasons_json TEXT NOT NULL
);

INSERT INTO scenarios (id, name, description) VALUES (
  'checkout_db_pool_exhaustion',
  'Checkout Latency Spike',
  'Checkout latency and intermittent HTTP 503s during payment submission.'
);

INSERT INTO incidents VALUES (
  'inc_checkout_001',
  'checkout_db_pool_exhaustion',
  'Checkout latency and errors during payment submit',
  'SEV2',
  '2026-08-24T09:12:00Z',
  '2026-08-24T09:41:00Z',
  'checkout',
  '23 percent of checkout attempts exceeded 3 seconds; 4.8 percent returned HTTP 503.',
  'Checkout POST /checkout p95 latency below 500 ms.',
  '["frontend /checkout POST latency increased","checkout p95 latency exceeded 3 seconds","some payment submissions were cancelled upstream"]'
);

INSERT INTO services VALUES
  ('svc_frontend', 'checkout_db_pool_exhaustion', 'frontend', 'web', 'storefront'),
  ('svc_checkout', 'checkout_db_pool_exhaustion', 'checkout', 'api', 'orders'),
  ('svc_payments', 'checkout_db_pool_exhaustion', 'payments', 'api', 'payments'),
  ('svc_postgres', 'checkout_db_pool_exhaustion', 'postgres', 'database', 'platform-data');

INSERT INTO dependencies VALUES
  ('dep_frontend_checkout', 'checkout_db_pool_exhaustion', 'frontend', 'checkout', 'http', '["POST /checkout"]'),
  ('dep_checkout_payments', 'checkout_db_pool_exhaustion', 'checkout', 'payments', 'http', '["POST /payments/authorize"]'),
  ('dep_checkout_postgres', 'checkout_db_pool_exhaustion', 'checkout', 'postgres', 'postgres', '["orders","carts","idempotency_keys"]');

INSERT INTO metrics VALUES
  ('metric_checkout_latency', 'checkout_db_pool_exhaustion', 'checkout', 'http.server.duration.p95_ms', 'ms', 'Checkout p95 latency for POST /checkout.', 500),
  ('metric_checkout_error_rate', 'checkout_db_pool_exhaustion', 'checkout', 'http.server.errors.percent', 'percent', 'Checkout HTTP 503 percentage.', 1),
  ('metric_postgres_connections', 'checkout_db_pool_exhaustion', 'postgres', 'db.connections.active', 'connections', 'Active postgres connections against max_connections=100.', 85),
  ('metric_payments_latency', 'checkout_db_pool_exhaustion', 'payments', 'http.server.duration.p95_ms', 'ms', 'Payments p95 latency showing collateral symptoms are not initiating failure.', 400);

INSERT INTO metric_points (metric_id, ts, value) VALUES
  ('metric_checkout_latency', '2026-08-24T09:00:00Z', 210),
  ('metric_checkout_latency', '2026-08-24T09:10:00Z', 260),
  ('metric_checkout_latency', '2026-08-24T09:20:00Z', 2980),
  ('metric_checkout_latency', '2026-08-24T09:30:00Z', 3360),
  ('metric_checkout_latency', '2026-08-24T09:45:00Z', 240),
  ('metric_checkout_error_rate', '2026-08-24T09:00:00Z', 0.2),
  ('metric_checkout_error_rate', '2026-08-24T09:10:00Z', 0.3),
  ('metric_checkout_error_rate', '2026-08-24T09:20:00Z', 4.8),
  ('metric_checkout_error_rate', '2026-08-24T09:30:00Z', 5.1),
  ('metric_checkout_error_rate', '2026-08-24T09:45:00Z', 0.4),
  ('metric_postgres_connections', '2026-08-24T09:00:00Z', 42),
  ('metric_postgres_connections', '2026-08-24T09:10:00Z', 45),
  ('metric_postgres_connections', '2026-08-24T09:20:00Z', 100),
  ('metric_postgres_connections', '2026-08-24T09:30:00Z', 100),
  ('metric_postgres_connections', '2026-08-24T09:45:00Z', 48),
  ('metric_payments_latency', '2026-08-24T09:00:00Z', 130),
  ('metric_payments_latency', '2026-08-24T09:10:00Z', 140),
  ('metric_payments_latency', '2026-08-24T09:20:00Z', 180),
  ('metric_payments_latency', '2026-08-24T09:30:00Z', 190),
  ('metric_payments_latency', '2026-08-24T09:45:00Z', 135);

INSERT INTO logs VALUES
  ('log_checkout_pool_wait_timeout', 'checkout_db_pool_exhaustion', '2026-08-24T09:18:22Z', 'checkout', 'error', 'db acquire timeout after 2000ms', '{"pool":"orders","wait_ms":2000,"open_connections":80,"route":"POST /checkout"}'),
  ('log_postgres_too_many_clients', 'checkout_db_pool_exhaustion', '2026-08-24T09:19:03Z', 'postgres', 'error', 'remaining connection slots are reserved for superuser connections', '{"active_connections":100,"max_connections":100,"database":"orders"}'),
  ('log_payments_upstream_cancelled', 'checkout_db_pool_exhaustion', '2026-08-24T09:20:11Z', 'payments', 'warn', 'request cancelled by upstream client', '{"upstream":"checkout","route":"POST /payments/authorize"}'),
  ('log_checkout_recovered_after_rollback', 'checkout_db_pool_exhaustion', '2026-08-24T09:41:20Z', 'checkout', 'info', 'db pool max_open_connections restored', '{"pool":"orders","max_open_connections":20}');

INSERT INTO changes VALUES
  ('chg_checkout_pool_80', 'checkout_db_pool_exhaustion', '2026-08-24T09:11:00Z', 'checkout', 'config', 'Increase checkout orders database pool size', '{"config_key":"db.max_open_connections","before":20,"after":80,"reason":"attempt to reduce queueing during flash-sale traffic"}'),
  ('chg_frontend_banner', 'checkout_db_pool_exhaustion', '2026-08-24T09:07:00Z', 'frontend', 'content', 'Publish promotion banner', '{"route":"GET /","risk":"low"}');

INSERT INTO expected_outcomes VALUES (
  'checkout_db_pool_exhaustion',
  'Checkout latency was caused by postgres connection exhaustion after checkout deployed a database pool max_open_connections change from 20 to 80.'
);

INSERT INTO scenarios (id, name, description) VALUES (
  'payments_gateway_timeout',
  'Payment Submission Failures',
  'Checkout payment authorization failures during card processing.'
);

INSERT INTO incidents VALUES (
  'inc_payments_001',
  'payments_gateway_timeout',
  'Payment authorization failures during checkout',
  'SEV3',
  '2026-08-23T15:04:00Z',
  '2026-08-23T15:22:00Z',
  'checkout',
  'Some card authorizations failed for 18 minutes; retries usually succeeded.',
  'Payment authorization error rate below 1 percent.',
  '["checkout reported payment_authorization_failed","payment submissions returned elevated 504 responses"]'
);

INSERT INTO services VALUES
  ('svc2_frontend', 'payments_gateway_timeout', 'frontend', 'web', 'storefront'),
  ('svc2_checkout', 'payments_gateway_timeout', 'checkout', 'api', 'orders'),
  ('svc2_payments', 'payments_gateway_timeout', 'payments', 'api', 'payments'),
  ('svc2_postgres', 'payments_gateway_timeout', 'postgres', 'database', 'platform-data'),
  ('svc2_gateway', 'payments_gateway_timeout', 'external-card-gateway', 'external', 'vendor');

INSERT INTO dependencies VALUES
  ('dep2_frontend_checkout', 'payments_gateway_timeout', 'frontend', 'checkout', 'http', '["POST /checkout"]'),
  ('dep2_checkout_payments', 'payments_gateway_timeout', 'checkout', 'payments', 'http', '["POST /payments/authorize"]'),
  ('dep2_checkout_postgres', 'payments_gateway_timeout', 'checkout', 'postgres', 'postgres', '["orders"]'),
  ('dep2_payments_gateway', 'payments_gateway_timeout', 'payments', 'external-card-gateway', 'https', '["card_authorization"]');

INSERT INTO metrics VALUES
  ('metric2_checkout_payment_errors', 'payments_gateway_timeout', 'checkout', 'checkout.payment.errors.percent', 'percent', 'Checkout payment authorization failure percentage.', 1),
  ('metric2_payments_gateway_timeouts', 'payments_gateway_timeout', 'payments', 'gateway.timeout.rate_per_min', 'timeouts/min', 'External card gateway timeout rate.', 2),
  ('metric2_postgres_connections', 'payments_gateway_timeout', 'postgres', 'db.connections.active', 'connections', 'Postgres remains below saturation.', 85);

INSERT INTO metric_points (metric_id, ts, value) VALUES
  ('metric2_checkout_payment_errors', '2026-08-23T14:55:00Z', 0.1),
  ('metric2_checkout_payment_errors', '2026-08-23T15:05:00Z', 3.1),
  ('metric2_checkout_payment_errors', '2026-08-23T15:15:00Z', 3.6),
  ('metric2_checkout_payment_errors', '2026-08-23T15:25:00Z', 0.2),
  ('metric2_payments_gateway_timeouts', '2026-08-23T14:55:00Z', 0),
  ('metric2_payments_gateway_timeouts', '2026-08-23T15:05:00Z', 42),
  ('metric2_payments_gateway_timeouts', '2026-08-23T15:15:00Z', 51),
  ('metric2_payments_gateway_timeouts', '2026-08-23T15:25:00Z', 1),
  ('metric2_postgres_connections', '2026-08-23T14:55:00Z', 44),
  ('metric2_postgres_connections', '2026-08-23T15:05:00Z', 45),
  ('metric2_postgres_connections', '2026-08-23T15:15:00Z', 43),
  ('metric2_postgres_connections', '2026-08-23T15:25:00Z', 44);

INSERT INTO logs VALUES
  ('log2_checkout_payment_failed', 'payments_gateway_timeout', '2026-08-23T15:08:09Z', 'checkout', 'warn', 'payment_authorization_failed from payments dependency', '{"dependency":"payments","status":504}'),
  ('log2_payments_gateway_timeout', 'payments_gateway_timeout', '2026-08-23T15:07:44Z', 'payments', 'error', 'external gateway request timed out', '{"gateway":"card-gateway","timeout_ms":500,"elapsed_ms":503}'),
  ('log2_postgres_healthy', 'payments_gateway_timeout', '2026-08-23T15:10:12Z', 'postgres', 'info', 'connections stable below saturation', '{"active_connections":45,"max_connections":100}');

INSERT INTO changes VALUES
  ('chg2_payments_gateway_timeout', 'payments_gateway_timeout', '2026-08-23T15:01:00Z', 'payments', 'config', 'Lower external card gateway timeout', '{"config_key":"gateway.card.timeout_ms","before":2000,"after":500,"rolled_back_at":"2026-08-23T15:21:00Z"}');

INSERT INTO expected_outcomes VALUES (
  'payments_gateway_timeout',
  'Checkout payment failures were caused by payments gateway timeouts after payments lowered the external card gateway timeout to 500 ms.'
);

INSERT INTO scenarios (id, name, description) VALUES (
  'insufficient_frontend_evidence',
  'Frontend Error Spike',
  'Frontend product page errors with partial observability evidence.'
);

INSERT INTO incidents VALUES (
  'inc_frontend_001',
  'insufficient_frontend_evidence',
  'Frontend product page error spike',
  'SEV3',
  '2026-08-22T11:30:00Z',
  '2026-08-22T11:43:00Z',
  'frontend',
  'Product detail pages intermittently returned HTTP 500 while caches warmed.',
  'Product detail page HTTP 5xx rate below 1 error per minute.',
  '["frontend product route HTTP 500 rate increased","checkout actions were not visibly impacted"]'
);

INSERT INTO services VALUES
  ('svc3_frontend', 'insufficient_frontend_evidence', 'frontend', 'web', 'storefront'),
  ('svc3_checkout', 'insufficient_frontend_evidence', 'checkout', 'api', 'orders'),
  ('svc3_payments', 'insufficient_frontend_evidence', 'payments', 'api', 'payments');

INSERT INTO dependencies VALUES
  ('dep3_frontend_checkout', 'insufficient_frontend_evidence', 'frontend', 'checkout', 'http', '["POST /checkout"]');

INSERT INTO metrics VALUES
  ('metric3_frontend_500s', 'insufficient_frontend_evidence', 'frontend', 'http.server.errors.rate_per_min', 'errors/min', 'Frontend product page HTTP 500 rate.', 1),
  ('metric3_checkout_latency', 'insufficient_frontend_evidence', 'checkout', 'http.server.duration.p95_ms', 'ms', 'Checkout remains healthy.', 500);

INSERT INTO metric_points (metric_id, ts, value) VALUES
  ('metric3_frontend_500s', '2026-08-22T11:20:00Z', 0),
  ('metric3_frontend_500s', '2026-08-22T11:35:00Z', 37),
  ('metric3_frontend_500s', '2026-08-22T11:45:00Z', 2),
  ('metric3_checkout_latency', '2026-08-22T11:20:00Z', 210),
  ('metric3_checkout_latency', '2026-08-22T11:35:00Z', 220),
  ('metric3_checkout_latency', '2026-08-22T11:45:00Z', 215);

INSERT INTO logs VALUES
  ('log3_frontend_product_error', 'insufficient_frontend_evidence', '2026-08-22T11:34:18Z', 'frontend', 'error', 'product page render failed after cache miss', '{"route":"GET /products/:id","cache":"product-metadata"}'),
  ('log3_checkout_healthy', 'insufficient_frontend_evidence', '2026-08-22T11:35:00Z', 'checkout', 'info', 'checkout healthy during frontend incident', '{"p95_ms":220}');

INSERT INTO expected_outcomes VALUES (
  'insufficient_frontend_evidence',
  'Insufficient evidence to determine a single root cause for the frontend product page errors.'
);
