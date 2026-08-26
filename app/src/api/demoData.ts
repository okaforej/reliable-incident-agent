import type { Comparison, EvidencePoint, Scenario, ServiceEdge, ServiceNode } from "./types";

const rootCause =
  "Checkout latency was caused by postgres connection exhaustion after checkout deployed a database pool max_open_connections change from 20 to 80.";

export const demoScenarios: Scenario[] = [
  {
    id: "checkout_db_pool_exhaustion",
    name: "Checkout DB pool exhaustion",
    description:
      "Checkout requests breached latency SLOs after a database pool configuration change increased concurrency against postgres.",
    severity: "SEV-2",
    timeWindow: "10:02-10:34 UTC",
    affectedServices: ["checkout", "postgres", "payments"],
    recentChanges: ["checkout deploy changed max_open_connections from 20 to 80 at 09:57 UTC"]
  }
];

export const demoEvidence: EvidencePoint[] = [
  { timestamp: "10:00", checkoutLatencyMs: 180, checkoutErrorRate: 0.4, postgresConnections: 38, paymentLatencyMs: 120 },
  { timestamp: "10:05", checkoutLatencyMs: 440, checkoutErrorRate: 1.2, postgresConnections: 71, paymentLatencyMs: 190 },
  { timestamp: "10:10", checkoutLatencyMs: 980, checkoutErrorRate: 4.8, postgresConnections: 96, paymentLatencyMs: 310 },
  { timestamp: "10:15", checkoutLatencyMs: 1450, checkoutErrorRate: 8.1, postgresConnections: 100, paymentLatencyMs: 460 },
  { timestamp: "10:20", checkoutLatencyMs: 1520, checkoutErrorRate: 9.4, postgresConnections: 100, paymentLatencyMs: 520 },
  { timestamp: "10:25", checkoutLatencyMs: 890, checkoutErrorRate: 3.5, postgresConnections: 82, paymentLatencyMs: 250 },
  { timestamp: "10:30", checkoutLatencyMs: 260, checkoutErrorRate: 0.8, postgresConnections: 49, paymentLatencyMs: 140 }
];

export const demoNodes: ServiceNode[] = [
  { id: "checkout", label: "checkout", status: "degraded" },
  { id: "postgres", label: "postgres", status: "saturated" },
  { id: "payments", label: "payments", status: "collateral" },
  { id: "catalog", label: "catalog", status: "healthy" },
  { id: "redis", label: "redis", status: "healthy" }
];

export const demoEdges: ServiceEdge[] = [
  { id: "checkout-postgres", source: "checkout", target: "postgres", label: "primary writes" },
  { id: "checkout-payments", source: "checkout", target: "payments", label: "payment auth" },
  { id: "checkout-catalog", source: "checkout", target: "catalog", label: "pricing" },
  { id: "checkout-redis", source: "checkout", target: "redis", label: "sessions" }
];

export const demoComparison: Comparison = {
  scenarioId: "checkout_db_pool_exhaustion",
  weak: {
    mode: "weak",
    runId: "demo-weak",
    trace: {
      incidentId: "inc-checkout-001",
      incidentDescription:
        "Checkout p95 latency and intermittent 5xx responses spiked during the incident window.",
      toolCalls: [
        {
          sequence: 1,
          toolName: "get_service_health",
          arguments: { service: "checkout" },
          result: {
            status: "degraded",
            summary: "checkout p95 latency exceeded SLO and error rate rose above baseline",
            evidence_id: "metric.checkout.latency.p95"
          }
        },
        {
          sequence: 2,
          toolName: "search_logs",
          arguments: { service: "checkout", query: "timeout" },
          result: {
            matches: 12,
            summary: "timeout errors observed while waiting for database connections",
            evidence_id: "log.checkout.db-timeout"
          }
        }
      ],
      finalRootCause: rootCause
    },
    evaluation: {
      rcaCorrect: true,
      grounded: false,
      investigationSufficient: false,
      toolEfficient: true,
      behavioralSloPass: false,
      reasons: [
        "RCA matches the expected root cause.",
        "Trace did not retrieve postgres saturation evidence.",
        "Trace did not retrieve the checkout configuration change that distinguishes cause from symptom."
      ]
    }
  },
  reliable: {
    mode: "reliable",
    runId: "demo-reliable",
    trace: {
      incidentId: "inc-checkout-001",
      incidentDescription:
        "Checkout p95 latency and intermittent 5xx responses spiked during the incident window.",
      toolCalls: [
        {
          sequence: 1,
          toolName: "get_service_health",
          arguments: { service: "checkout" },
          result: {
            status: "degraded",
            summary: "checkout p95 latency exceeded SLO with database wait time dominating request time",
            evidence_id: "metric.checkout.latency.p95"
          }
        },
        {
          sequence: 2,
          toolName: "get_dependencies",
          arguments: { service: "checkout" },
          result: {
            dependencies: ["postgres", "payments", "catalog", "redis"],
            summary: "checkout depends on postgres for order writes and payments for authorization"
          }
        },
        {
          sequence: 3,
          toolName: "get_metrics",
          arguments: { service: "postgres", metric_name: "active_connections" },
          result: {
            max_active_connections: 100,
            saturation_window: "10:10-10:22 UTC",
            summary: "postgres active connections pinned at the configured ceiling during the checkout impact window",
            evidence_id: "metric.postgres.active_connections"
          }
        },
        {
          sequence: 4,
          toolName: "get_recent_changes",
          arguments: { service: "checkout" },
          result: {
            change_id: "chg-checkout-pool-80",
            summary: "checkout deploy changed max_open_connections from 20 to 80 shortly before the incident"
          }
        },
        {
          sequence: 5,
          toolName: "get_service_health",
          arguments: { service: "payments" },
          result: {
            status: "collateral",
            summary: "payments latency rose after checkout retries increased and recovered with checkout",
            evidence_id: "metric.payments.latency.p95"
          }
        }
      ],
      finalRootCause: rootCause
    },
    evaluation: {
      rcaCorrect: true,
      grounded: true,
      investigationSufficient: true,
      toolEfficient: true,
      behavioralSloPass: true,
      reasons: [
        "RCA matches the expected root cause.",
        "Trace retrieved checkout, postgres, and deployment evidence.",
        "Trace distinguished collateral payments symptoms from the initiating postgres saturation."
      ]
    }
  }
};
