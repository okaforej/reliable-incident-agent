import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  GitBranch,
  Network,
  RefreshCw,
  Server,
  ShieldCheck,
  TerminalSquare,
  XCircle
} from "lucide-react";
import { Background, Controls, MarkerType, Position, ReactFlow, type Edge, type Node } from "@xyflow/react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";
import { comparisonWithFallback, getComparison, getScenarios, scenariosWithFallback } from "./api/client";
import { demoEdges, demoEvidence, demoNodes } from "./api/demoData";
import type { AgentMode, BehavioralEvaluation, Comparison, InvestigationRun, Scenario, ToolCall } from "./api/types";
import { Badge, Button, Card, CardHeader, MetricTile, Select, StatusDot } from "./components/ui";

const sliRows: Array<{ key: keyof BehavioralEvaluation; label: string }> = [
  { key: "rcaCorrect", label: "RCA correctness" },
  { key: "grounded", label: "Grounded" },
  { key: "investigationSufficient", label: "Sufficient" },
  { key: "toolEfficient", label: "Efficient" },
  { key: "behavioralSloPass", label: "Behavioral SLO" }
];

const modeLabels: Record<AgentMode, { title: string; eyebrow: string }> = {
  baseline: {
    title: "Version A baseline",
    eyebrow: "baseline trajectory"
  },
  candidate: {
    title: "Version B candidate",
    eyebrow: "candidate trajectory"
  }
};

function App() {
  const [selectedScenario, setSelectedScenario] = useState("checkout_db_pool_exhaustion");
  const [activeMode, setActiveMode] = useState<AgentMode>("candidate");
  const [showBehavioralSlo, setShowBehavioralSlo] = useState(false);

  const scenariosQuery = useQuery({
    queryKey: ["scenarios"],
    queryFn: getScenarios
  });

  const scenarios = scenariosWithFallback(scenariosQuery.data);
  const selectedScenarioSummary = scenarios.find((scenario) => scenario.id === selectedScenario) ?? scenarios[0];

  const comparisonQuery = useQuery({
    queryKey: ["comparison", selectedScenario],
    queryFn: () => getComparison(selectedScenario),
    enabled: Boolean(selectedScenario)
  });

  const comparison = comparisonWithFallback(comparisonQuery.data, selectedScenario);
  const activeRun = comparison[activeMode];
  const usingFallback = scenariosQuery.isError || comparisonQuery.isError;

  const workflowStatus = comparisonQuery.isFetching ? "Running comparison" : usingFallback ? "Demo fallback" : "API connected";
  const workflowTone = comparisonQuery.isFetching ? "warning" : usingFallback ? "warning" : "success";

  useEffect(() => {
    setShowBehavioralSlo(false);
  }, [selectedScenario]);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <div className="brand-mark">
            <ShieldCheck size={21} aria-hidden="true" />
          </div>
          <div>
            <p>Reliable Incident Agent</p>
            <h1>Incident command center</h1>
          </div>
        </div>

        <div className="topbar-controls">
          <Select label="Replay scenario" value={selectedScenario} onChange={setSelectedScenario}>
            {scenarios.map((scenario) => (
              <option value={scenario.id} key={scenario.id}>
                {scenario.name}
              </option>
            ))}
          </Select>
          <Button
            onClick={() => {
              setShowBehavioralSlo(false);
              void comparisonQuery.refetch();
            }}
            disabled={comparisonQuery.isFetching}
          >
            <RefreshCw size={16} aria-hidden="true" />
            Run comparison
          </Button>
          <Button onClick={() => setShowBehavioralSlo(true)} variant="secondary">
            <ShieldCheck size={16} aria-hidden="true" />
            Reveal SLO
          </Button>
          <Badge tone={workflowTone}>
            <StatusDot tone={workflowTone} />
            {workflowStatus}
          </Badge>
        </div>
      </header>

      <div className="workspace-grid">
        <IncidentRail scenario={selectedScenarioSummary} comparison={comparison} />

        <section className="main-column">
          <ModeTabs activeMode={activeMode} comparison={comparison} onChange={setActiveMode} />
          <OutputOnlyPanel comparison={comparison} revealed={showBehavioralSlo} onReveal={() => setShowBehavioralSlo(true)} />
          <Transcript run={activeRun} revealed={showBehavioralSlo} />
          <ComparisonPanel comparison={comparison} revealed={showBehavioralSlo} />
        </section>

        <section className="insights-column">
          <SloScorecard
            baseline={comparison.baseline.evaluation}
            candidate={comparison.candidate.evaluation}
            revealed={showBehavioralSlo}
          />
          <EvidencePanel scenarioId={selectedScenario} run={activeRun} />
          <GraphPanel scenarioId={selectedScenario} run={activeRun} />
        </section>
      </div>
    </main>
  );
}

function IncidentRail({ scenario, comparison }: { scenario: Scenario; comparison: Comparison }) {
  const baselineCalls = comparison.baseline.trace.toolCalls.length;
  const candidateCalls = comparison.candidate.trace.toolCalls.length;

  return (
    <aside className="incident-rail">
      <Card>
        <CardHeader eyebrow="Incident replay" title={scenario.name}>
          {scenario.description}
        </CardHeader>
        <div className="rail-stack">
          <MetricTile label="Severity" value={scenario.severity} tone="danger" />
          <MetricTile label="Time window" value={scenario.timeWindow} tone="info" />
          <MetricTile label="Version A calls" value={String(baselineCalls)} tone="warning" />
          <MetricTile label="Version B calls" value={String(candidateCalls)} tone="success" />
        </div>
      </Card>

      <Card>
        <CardHeader eyebrow="Scope" title="Affected services" />
        <div className="service-list">
          {scenario.affectedServices.map((service) => (
            <div className="service-row" key={service}>
              <Server size={16} aria-hidden="true" />
              <span>{service}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <CardHeader eyebrow="Change window" title="Recent changes" />
        <div className="change-list">
          {scenario.recentChanges.map((change) => (
            <div className="change-row" key={change}>
              <GitBranch size={15} aria-hidden="true" />
              <span>{change}</span>
            </div>
          ))}
        </div>
      </Card>
    </aside>
  );
}

function ModeTabs({
  activeMode,
  comparison,
  onChange
}: {
  activeMode: AgentMode;
  comparison: Comparison;
  onChange: (mode: AgentMode) => void;
}) {
  return (
    <div className="mode-tabs" role="tablist" aria-label="Investigation mode">
      {(["baseline", "candidate"] as const).map((mode) => {
        const run = comparison[mode];
        const selected = mode === activeMode;
        return (
          <button
            type="button"
            role="tab"
            aria-selected={selected}
            className={selected ? "mode-tab mode-tab-active" : "mode-tab"}
            onClick={() => onChange(mode)}
            key={mode}
          >
            <span>{modeLabels[mode].title}</span>
            <Badge tone={run.evaluation.rcaCorrect ? "success" : "danger"}>
              RCA {run.evaluation.rcaCorrect ? "PASS" : "FAIL"}
            </Badge>
          </button>
        );
      })}
    </div>
  );
}

function OutputOnlyPanel({
  comparison,
  revealed,
  onReveal
}: {
  comparison: Comparison;
  revealed: boolean;
  onReveal: () => void;
}) {
  const sameRca = comparison.baseline.trace.finalRootCause === comparison.candidate.trace.finalRootCause;

  return (
    <Card className="parity-card">
      <CardHeader eyebrow="Output-only evaluation" title="RCA accuracy makes these versions look equivalent">
        The final answer is the same before trajectory quality is evaluated.
      </CardHeader>
      <div className="parity-grid">
        <MetricTile
          label="Version A RCA"
          value={comparison.baseline.evaluation.rcaCorrect ? "PASS" : "FAIL"}
          tone={comparison.baseline.evaluation.rcaCorrect ? "success" : "danger"}
        />
        <MetricTile
          label="Version B RCA"
          value={comparison.candidate.evaluation.rcaCorrect ? "PASS" : "FAIL"}
          tone={comparison.candidate.evaluation.rcaCorrect ? "success" : "danger"}
        />
        <div className="parity-rca">
          <span>{sameRca ? "Identical final RCA" : "Different final RCA"}</span>
          <p>{comparison.baseline.trace.finalRootCause}</p>
        </div>
      </div>
      <div className="reveal-strip">
        <span>
          {revealed
            ? "Behavioral evaluation is visible. The trajectory explains whether the correct RCA was reliable."
            : "At this point, output accuracy alone says the versions are equivalent."}
        </span>
        {!revealed ? (
          <Button onClick={onReveal} variant="secondary">
            <ShieldCheck size={16} aria-hidden="true" />
            Reveal Behavioral SLO
          </Button>
        ) : null}
      </div>
    </Card>
  );
}

function Transcript({ run, revealed }: { run: InvestigationRun; revealed: boolean }) {
  return (
    <Card className="transcript-card">
      <CardHeader
        eyebrow={modeLabels[run.mode].eyebrow}
        title="Investigation transcript"
        action={
          <Badge tone={revealed ? (run.evaluation.behavioralSloPass ? "success" : "danger") : "neutral"}>
            {revealed ? `Behavioral SLO ${run.evaluation.behavioralSloPass ? "PASS" : "FAIL"}` : "RCA visible"}
          </Badge>
        }
      >
        {run.trace.incidentDescription}
      </CardHeader>

      <div className="prompt-card">
        <AlertTriangle size={18} aria-hidden="true" />
        <div>
          <span>Incident prompt</span>
          <p>Determine the root cause and gather enough operational evidence to support the answer.</p>
        </div>
      </div>

      <div className="tool-call-list">
        {run.trace.toolCalls.map((toolCall) => (
          <ToolCallCard toolCall={toolCall} key={`${run.runId}-${toolCall.sequence}-${toolCall.toolName}`} />
        ))}
      </div>

      <div className="rca-card">
        <div className="rca-icon">
          <CheckCircle2 size={18} aria-hidden="true" />
        </div>
        <div>
          <span>Final RCA</span>
          <p>{run.trace.finalRootCause}</p>
        </div>
      </div>

      {revealed ? (
        <div className="evaluator-notes">
          <div className="note-title">
            <CircleDashed size={16} aria-hidden="true" />
            Evaluator summary
          </div>
          {run.evaluation.reasons.map((reason) => (
            <p key={reason}>{reason}</p>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

function ToolCallCard({ toolCall }: { toolCall: ToolCall }) {
  return (
    <article className="tool-card">
      <div className="tool-index">{toolCall.sequence}</div>
      <div className="tool-body">
        <div className="tool-title">
          <TerminalSquare size={16} aria-hidden="true" />
          <strong>{toolCall.toolName}</strong>
        </div>
        <div className="tool-json-grid">
          <JsonBlock label="Arguments" value={toolCall.arguments} />
          <JsonBlock label="Result" value={toolCall.result} />
        </div>
      </div>
    </article>
  );
}

function JsonBlock({ label, value }: { label: string; value: Record<string, unknown> }) {
  return (
    <div className="json-block">
      <span>{label}</span>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

function SloScorecard({
  baseline,
  candidate,
  revealed
}: {
  baseline: BehavioralEvaluation;
  candidate: BehavioralEvaluation;
  revealed: boolean;
}) {
  const rows = revealed ? sliRows : sliRows.filter((row) => row.key === "rcaCorrect");

  return (
    <Card>
      <CardHeader eyebrow="Behavioral SLIs" title={revealed ? "RCA parity, then SLO" : "RCA parity only"}>
        {revealed
          ? "The composite SLO includes answer correctness and investigation behavior."
          : "Behavioral rows are hidden until the reveal step."}
      </CardHeader>
      <div className="slo-table">
        <div className="slo-row slo-heading">
          <span>SLI</span>
          <span>Version A</span>
          <span>Version B</span>
        </div>
        {rows.map((row) => (
          <div className="slo-row" key={row.key}>
            <span>{row.label}</span>
            <PassFail value={Boolean(baseline[row.key])} />
            <PassFail value={Boolean(candidate[row.key])} />
          </div>
        ))}
      </div>
      {!revealed ? <div className="masked-slo">Behavioral SLO results are intentionally hidden for the reveal.</div> : null}
    </Card>
  );
}

function PassFail({ value }: { value: boolean }) {
  return (
    <span className={value ? "passfail pass" : "passfail fail"}>
      {value ? <CheckCircle2 size={15} aria-hidden="true" /> : <XCircle size={15} aria-hidden="true" />}
      {value ? "PASS" : "FAIL"}
    </span>
  );
}

function EvidencePanel({ scenarioId, run }: { scenarioId: string; run: InvestigationRun }) {
  if (scenarioId !== "checkout_db_pool_exhaustion") {
    return (
      <Card className="evidence-card">
        <CardHeader eyebrow="Observed evidence" title="Active replay evidence">
          This panel follows the selected scenario instead of reusing checkout-specific charts.
        </CardHeader>
        <div className="observed-list">
          {run.trace.toolCalls.map((call) => (
            <div className="observed-row" key={`${run.runId}-evidence-${call.sequence}`}>
              <span>{call.sequence}</span>
              <p>{summarizeToolCall(call)}</p>
            </div>
          ))}
        </div>
      </Card>
    );
  }

  return (
    <Card className="evidence-card">
      <CardHeader eyebrow="Evidence" title="Metric timeline">
        Checkout impact aligns with postgres connection saturation after the checkout config change.
      </CardHeader>
      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height={250}>
          <LineChart data={demoEvidence} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#d7dee8" />
            <XAxis dataKey="timestamp" tickLine={false} axisLine={false} />
            <YAxis tickLine={false} axisLine={false} />
            <Tooltip />
            <Legend />
            <ReferenceLine x="10:05" stroke="#b45309" strokeDasharray="4 4" label="pool change" />
            <Line
              type="monotone"
              dataKey="checkoutLatencyMs"
              name="checkout p95 ms"
              stroke="#2563eb"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="postgresConnections"
              name="postgres connections"
              stroke="#dc2626"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="paymentLatencyMs"
              name="payments p95 ms"
              stroke="#0f766e"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="log-highlight">
        <Activity size={16} aria-hidden="true" />
        <span>Log highlight:</span>
        <p>checkout emitted database connection wait timeouts while postgres active connections pinned at ceiling.</p>
      </div>
    </Card>
  );
}

function GraphPanel({
  scenarioId,
  run
}: {
  scenarioId: string;
  run: InvestigationRun;
}) {
  const graph = useMemo(() => buildGraph(scenarioId, run), [scenarioId, run]);

  return (
    <Card className="graph-card">
      <CardHeader eyebrow="Topology" title="Service and trajectory graph">
        Service dependency map with visited investigation tools emphasized.
      </CardHeader>
      <div className="flow-wrap">
        <ReactFlow
          nodes={graph.nodes}
          edges={graph.edges}
          fitView
          minZoom={0.5}
          maxZoom={1.5}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={18} color="#d5dce8" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div className="graph-legend">
        <span><StatusDot tone="danger" /> Saturated</span>
        <span><StatusDot tone="warning" /> Degraded</span>
        <span><StatusDot tone="info" /> Collateral</span>
        <span><StatusDot tone="success" /> Healthy</span>
      </div>
    </Card>
  );
}

function buildGraph(scenarioId: string, run: InvestigationRun): { nodes: Node[]; edges: Edge[] } {
  const visitedServices = new Set(
    run.trace.toolCalls
      .map((call) => call.arguments.service)
      .filter((value): value is string => typeof value === "string")
  );

  if (scenarioId !== "checkout_db_pool_exhaustion") {
    const services = Array.from(visitedServices);
    const nodes: Node[] = services.map((service, index) => ({
      id: service,
      position: { x: 40 + (index % 3) * 210, y: 65 + Math.floor(index / 3) * 110 },
      data: {
        label: (
          <div className="flow-node flow-visited">
            <span>{service}</span>
            <Badge tone="neutral">visited</Badge>
          </div>
        )
      },
      type: "default",
      sourcePosition: Position.Right,
      targetPosition: Position.Left
    }));

    const edges: Edge[] = services.slice(1).map((service, index) => ({
      id: `${services[index]}-${service}`,
      source: services[index],
      target: service,
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { stroke: "#718096", strokeWidth: 1.5 }
    }));

    return { nodes, edges };
  }

  const positions: Record<string, { x: number; y: number }> = {
    checkout: { x: 20, y: 105 },
    postgres: { x: 300, y: 30 },
    payments: { x: 300, y: 175 },
    catalog: { x: 555, y: 58 },
    redis: { x: 555, y: 190 }
  };

  const nodes: Node[] = demoNodes.map((node) => ({
    id: node.id,
    position: positions[node.id] ?? { x: 0, y: 0 },
    data: {
      label: (
        <div className={`flow-node flow-${node.status} ${visitedServices.has(node.id) ? "flow-visited" : ""}`}>
          <span>{node.label}</span>
          {visitedServices.has(node.id) ? (
            <Badge tone="neutral">visited</Badge>
          ) : null}
        </div>
      )
    },
    type: "default",
    sourcePosition: Position.Right,
    targetPosition: Position.Left
  }));

  const edges: Edge[] = demoEdges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.label,
    markerEnd: { type: MarkerType.ArrowClosed },
    animated: visitedServices.has(edge.source) && visitedServices.has(edge.target),
    style: {
      stroke: edge.target === "postgres" ? "#dc2626" : "#718096",
      strokeWidth: edge.target === "postgres" ? 2.5 : 1.5
    }
  }));

  return { nodes, edges };
}

function ComparisonPanel({ comparison, revealed }: { comparison: Comparison; revealed: boolean }) {
  const baselineCalls = comparison.baseline.trace.toolCalls.map((call) => call.toolName);
  const candidateCalls = comparison.candidate.trace.toolCalls.map((call) => call.toolName);

  return (
    <Card>
      <CardHeader eyebrow="Version A vs Version B" title={revealed ? "Reliability regression check" : "Trajectory preview"}>
        {revealed
          ? "Both versions pass RCA correctness; the Behavioral SLO reveals whether the evidence path is production-ready."
          : "Tool trajectories are available, but the behavioral verdict is hidden until the SLO reveal."}
      </CardHeader>
      <div className="comparison-grid">
        <ComparisonColumn
          title="Version A baseline"
          calls={baselineCalls}
          evaluation={comparison.baseline.evaluation}
          revealed={revealed}
        />
        <ComparisonColumn
          title="Version B candidate"
          calls={candidateCalls}
          evaluation={comparison.candidate.evaluation}
          revealed={revealed}
        />
      </div>
    </Card>
  );
}

function ComparisonColumn({
  title,
  calls,
  evaluation,
  revealed
}: {
  title: string;
  calls: string[];
  evaluation: BehavioralEvaluation;
  revealed: boolean;
}) {
  return (
    <div className="comparison-column">
      <div className="comparison-title">
        <h3>{title}</h3>
        <Badge tone={revealed ? (evaluation.behavioralSloPass ? "success" : "danger") : "neutral"}>
          {revealed ? `Behavioral SLO ${evaluation.behavioralSloPass ? "PASS" : "FAIL"}` : "RCA PASS"}
        </Badge>
      </div>
      <div className="trajectory-list">
        {calls.map((call, index) => (
          <div className="trajectory-step" key={`${title}-${call}-${index}`}>
            <span>{index + 1}</span>
            <p>{call}</p>
            {index < calls.length - 1 ? <ChevronRight size={15} aria-hidden="true" /> : null}
          </div>
        ))}
      </div>
      <div className="comparison-verdict">
        <Network size={16} aria-hidden="true" />
        <span>
          {!revealed
            ? "Output accuracy has not exposed a reliability difference yet."
            : evaluation.behavioralSloPass
            ? "Correct RCA with supporting and distinguishing evidence."
            : "Correct RCA with an evidence coverage gap."}
        </span>
      </div>
    </div>
  );
}

function summarizeToolCall(toolCall: ToolCall): string {
  const service = typeof toolCall.arguments.service === "string" ? `${toolCall.arguments.service}: ` : "";
  const summary = toolCall.result.summary;
  if (typeof summary === "string" && summary.trim()) {
    return `${service}${summary}`;
  }

  const signals = toolCall.result.signals;
  if (Array.isArray(signals) && signals.length > 0) {
    return `${service}${signals.join("; ")}`;
  }

  return `${service}${toolCall.toolName}`;
}

export default App;
