import { FormEvent, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Gauge,
  GitCompareArrows,
  History,
  Info,
  Layers3,
  LoaderCircle,
  Menu,
  MessageSquare,
  PanelLeftClose,
  Play,
  RotateCcw,
  Send,
  ShieldCheck,
  TerminalSquare,
  Wifi,
  WifiOff,
  XCircle
} from "lucide-react";
import { api, errorMessage, subscribeToInvestigationEvents } from "./api/liveClient";
import type {
  ActionConfirmationResponse,
  ActionProposal,
  BehavioralEvaluation,
  ComparisonResponse,
  ComparisonSummary,
  InvestigationAccepted,
  InvestigationEvent,
  InvestigationFollowUpExchange,
  InvestigationResponse,
  InvestigationSummary,
  ScenarioSummary,
  ToolCall
} from "./api/contracts";
import { Badge, Button, Card, CardHeader, Select, StatusDot } from "./components/ui";
import {
  getProviderAvailability,
  unavailableMessage,
  type ProviderAvailability
} from "./providerAvailability";
import { appendInvestigationEvent, formatElapsedTime, hydrateCompletedRun, latestActionProposal, visibleInvestigationEvents } from "./workspaceState";

type View = "investigator" | "comparison";
type Drawer = "investigations" | "context" | null;
type ChatExchange = InvestigationFollowUpExchange;
type StreamState = "idle" | "connecting" | "live" | "reconnecting" | "closed";

export default function Workspace() {
  const [view, setView] = useState<View>("investigator");
  const [menuOpen, setMenuOpen] = useState(false);
  const [investigatorScenarioId, setInvestigatorScenarioId] = useState("");
  const [comparisonScenarioId, setComparisonScenarioId] = useState("");
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: api.scenarios });
  const provider = getProviderAvailability({
    isPending: health.isPending,
    isError: health.isError,
    data: health.data,
    error: health.error
  });
  const providerTone = provider.kind === "ready"
    ? "success"
    : provider.kind === "loading"
      ? "info"
      : provider.kind === "api_unavailable" || provider.kind === "api_unhealthy"
        ? "danger"
        : "warning";
  const currentFeature = view === "investigator" ? "Incident Investigator" : "Compare Agent Versions";

  function chooseView(next: View) {
    setView(next);
    setMenuOpen(false);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="feature-nav">
          <div className="feature-menu-wrap">
            <button
              className="menu-trigger"
              type="button"
              aria-label="Open feature menu"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
            >
              <Menu size={20} />
            </button>
            {menuOpen ? (
              <nav className="feature-menu" aria-label="Features">
                <span className="eyebrow">Features</span>
                <button className={view === "investigator" ? "active" : ""} type="button" onClick={() => chooseView("investigator")}>
                  <ShieldCheck size={17} />
                  <span><strong>Incident Investigator</strong><small>Investigate and resolve incidents</small></span>
                </button>
                <button className={view === "comparison" ? "active" : ""} type="button" onClick={() => chooseView("comparison")}>
                  <GitCompareArrows size={17} />
                  <span><strong>Compare Agent Versions</strong><small>Evaluate behavioral reliability</small></span>
                </button>
              </nav>
            ) : null}
          </div>
          <div className="brand-mark"><ShieldCheck size={20} aria-hidden="true" /></div>
          <div className="current-feature"><p>Reliable Incident Agent</p><h1>{currentFeature}</h1></div>
        </div>
        <Badge tone={providerTone}><StatusDot tone={providerTone} />{provider.label}</Badge>
      </header>

      {scenarios.isError ? <ErrorBanner message={errorMessage(scenarios.error)} /> : null}
      <div hidden={view !== "investigator"}>
        <InvestigatorView
          scenarios={scenarios.data ?? []}
          scenario={scenarios.data?.find((item) => item.id === investigatorScenarioId)}
          scenarioId={investigatorScenarioId}
          onScenario={setInvestigatorScenarioId}
          provider={provider}
        />
      </div>
      <div hidden={view !== "comparison"}>
        <ComparisonView
          scenarios={scenarios.data ?? []}
          scenarioId={comparisonScenarioId}
          onScenario={setComparisonScenarioId}
          provider={provider}
        />
      </div>
    </main>
  );
}

function InvestigatorView({ scenarios, scenario, scenarioId, onScenario, provider }: {
  scenarios: ScenarioSummary[];
  scenario?: ScenarioSummary;
  scenarioId: string;
  onScenario: (id: string) => void;
  provider: ProviderAvailability;
}) {
  const history = useQuery({ queryKey: ["investigations"], queryFn: api.listInvestigations });
  const [drawer, setDrawer] = useState<Drawer>("investigations");
  const [accepted, setAccepted] = useState<InvestigationAccepted | null>(null);
  const [events, setEvents] = useState<InvestigationEvent[]>([]);
  const [run, setRun] = useState<InvestigationResponse | null>(null);
  const [chat, setChat] = useState<ChatExchange[]>([]);
  const [verification, setVerification] = useState<ActionConfirmationResponse | null>(null);
  const [busy, setBusy] = useState<"start" | "history" | "chat" | "action" | null>(null);
  const [streamState, setStreamState] = useState<StreamState>("idle");
  const [streamAttempt, setStreamAttempt] = useState(0);
  const [runFailure, setRunFailure] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const activeRunId = useRef<string | null>(null);

  function clearInvestigation() {
    activeRunId.current = null;
    setAccepted(null);
    setEvents([]);
    setRun(null);
    setChat([]);
    setVerification(null);
    setError(null);
    setStreamState("idle");
    setRunFailure(null);
  }

  async function refreshRun(runId: string) {
    try {
      const snapshot = await api.getInvestigation(runId);
      if (activeRunId.current !== runId) return;
      const hydration = hydrateCompletedRun(snapshot);
      if (hydration) {
        setRun(hydration.run);
        setChat(hydration.followUps);
        setVerification(hydration.actionResult);
        setAccepted(null);
        activeRunId.current = null;
        setStreamState("closed");
        void history.refetch();
      } else if (snapshot.status === "failed") {
        setStreamState("closed");
        setRunFailure(snapshot.error);
        setError(snapshot.error);
        void history.refetch();
      }
    } catch (requestError) {
      if (activeRunId.current !== runId) return;
      setStreamState("reconnecting");
      setError(`Live progress is disconnected. The run was not restarted. ${errorMessage(requestError)}`);
    }
  }

  useEffect(() => {
    if (!accepted) return;
    let active = true;
    setStreamState("connecting");
    const unsubscribe = subscribeToInvestigationEvents(accepted.run_id, {
      onOpen: () => {
        if (!active) return;
        setStreamState("live");
        setError(null);
      },
      onEvent: (event) => {
        if (!active) return;
        setEvents((current) => appendInvestigationEvent(current, event));
        if (event.type === "investigation.completed") {
          setStreamState("closed");
          void refreshRun(accepted.run_id);
        } else if (event.type === "investigation.failed") {
          setStreamState("closed");
          setRunFailure(event.payload.error);
          setError(event.payload.error);
          void history.refetch();
        }
      },
      onDisconnect: () => {
        if (!active) return;
        setStreamState("reconnecting");
        void refreshRun(accepted.run_id);
      },
      onMalformedEvent: (streamError) => {
        if (!active) return;
        setStreamState("closed");
        setError(`${streamError.message} Run ${shortId(accepted.run_id)} remains available for a status check.`);
      }
    });
    return () => {
      active = false;
      unsubscribe();
    };
  }, [accepted?.run_id, streamAttempt]);

  const runActive = accepted !== null && run === null && runFailure === null;

  function changeScenario(id: string) {
    if (runActive) return;
    clearInvestigation();
    onScenario(id);
    setDrawer(id ? "context" : "investigations");
  }

  async function start() {
    if (!scenarioId) return;
    clearInvestigation();
    setBusy("start");
    setDrawer(null);
    try {
      const next = await api.startInvestigation(scenarioId);
      activeRunId.current = next.run_id;
      setAccepted(next);
      void history.refetch();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  }

  async function openHistory(item: InvestigationSummary) {
    if (runActive) return;
    clearInvestigation();
    onScenario(item.scenario_id);
    setBusy("history");
    setDrawer(null);
    try {
      const snapshot = await api.getInvestigation(item.run_id);
      const hydration = hydrateCompletedRun(snapshot);
      if (hydration) {
        setRun(hydration.run);
        setChat(hydration.followUps);
        setVerification(hydration.actionResult);
        setStreamState("closed");
      } else if (snapshot.status === "failed") {
        setRunFailure(snapshot.error);
        setError(snapshot.error);
        setStreamState("closed");
      } else if (snapshot.status === "queued" || snapshot.status === "running") {
        activeRunId.current = snapshot.run_id;
        setAccepted({ run_id: snapshot.run_id, scenario_id: snapshot.scenario_id, status: snapshot.status });
      }
    } catch (requestError) {
      setError(errorMessage(requestError));
      setDrawer("investigations");
    } finally {
      setBusy(null);
    }
  }

  async function send(message: string) {
    if (!run) return;
    setBusy("chat");
    setError(null);
    try {
      const response = await api.sendMessage(run.run_id, message);
      setChat((items) => [...items, { question: message, response }]);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  }

  async function confirm(proposal: ActionProposal) {
    if (!run) return;
    setBusy("action");
    setError(null);
    try {
      setVerification(await api.confirmAction(run.run_id, proposal.id));
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  }

  const proposal = latestActionProposal(
    run?.trace.final_result.action_proposal ?? null,
    chat.map((exchange) => exchange.response),
    verification
  );
  const selectedRunId = run?.run_id ?? accepted?.run_id ?? null;

  return (
    <section className={`investigator-shell${drawer ? " drawer-open" : " drawer-collapsed"}`}>
      <nav className="drawer-rail" aria-label="Investigator panels">
        <button className={drawer === "investigations" ? "active" : ""} type="button" aria-label="Investigation history" aria-pressed={drawer === "investigations"} onClick={() => setDrawer((current) => current === "investigations" ? null : "investigations")}><History size={17} /><span>History</span></button>
        <button className={drawer === "context" ? "active" : ""} type="button" aria-pressed={drawer === "context"} disabled={!scenario} onClick={() => setDrawer((current) => current === "context" ? null : "context")}><Info size={18} /><span>Context</span></button>
        {drawer ? <button className="collapse-control" type="button" onClick={() => setDrawer(null)}><PanelLeftClose size={18} /><span>Collapse</span></button> : null}
      </nav>

      {drawer ? (
        <aside className="shared-drawer">
          {drawer === "investigations" ? (
            <InvestigationsDrawer scenarios={scenarios} scenarioId={scenarioId} history={history.data ?? []} historyPending={history.isPending} historyError={history.isError ? errorMessage(history.error) : null} selectedRunId={selectedRunId} disabled={runActive || busy === "history"} onScenario={changeScenario} onHistory={openHistory} />
          ) : <IncidentContext scenario={scenario} verification={verification} />}
        </aside>
      ) : null}

      <section className="investigation-workspace">
        <div className="workspace-heading">
          <div><span className="eyebrow">Investigation workspace</span><h2>{scenario?.name ?? "Incident workspace"}</h2></div>
          {accepted ? <StreamBadge state={streamState} /> : run ? <Badge tone={run.trace.final_result.outcome === "abstain" ? "warning" : "success"}>{run.trace.final_result.outcome === "abstain" ? "Abstained" : "Completed"}</Badge> : null}
        </div>
        {!provider.ready ? <ProviderBanner provider={provider} operation="investigation" /> : null}
        {error ? <ErrorBanner message={error} /> : null}

        <div className="workspace-content">
          {!scenario ? <EmptyWorkspace onOpen={() => setDrawer("investigations")} />
            : run ? <CompletedWorkspace run={run} chat={chat} proposal={proposal} verification={verification} actionBusy={busy === "action"} onConfirm={confirm} />
              : accepted ? <LiveTimeline accepted={accepted} events={events} streamState={streamState} failure={runFailure} onRetry={() => { void refreshRun(accepted.run_id); setStreamAttempt((value) => value + 1); }} />
                : <SelectedIncident scenario={scenario} provider={provider} busy={busy === "start"} onStart={start} />}
        </div>

        <IncidentComposer runReady={Boolean(run)} disabled={busy !== null} onSend={send} />
      </section>
    </section>
  );
}

function InvestigationsDrawer({ scenarios, scenarioId, history, historyPending, historyError, selectedRunId, disabled, onScenario, onHistory }: {
  scenarios: ScenarioSummary[];
  scenarioId: string;
  history: InvestigationSummary[];
  historyPending: boolean;
  historyError: string | null;
  selectedRunId: string | null;
  disabled: boolean;
  onScenario: (id: string) => void;
  onHistory: (item: InvestigationSummary) => Promise<void>;
}) {
  const groups = groupInvestigations(history);
  return <>
    <div className="drawer-heading"><span className="eyebrow">History</span><h2>Investigations</h2><p>Start or reopen a run.</p></div>
    <label className="incident-finder"><span>Find an incident</span><select value={scenarioId} disabled={disabled} onChange={(event) => onScenario(event.target.value)}><option value="">Select an incident…</option>{scenarios.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.severity}</option>)}</select></label>
    <div className="history-list" aria-busy={historyPending}>
      {historyPending ? <p className="drawer-empty"><LoaderCircle className="spin" size={15} />Loading investigation history…</p> : null}
      {historyError ? <div className="drawer-error"><AlertTriangle size={15} /><span>{historyError}</span></div> : null}
      {!historyPending && !historyError && !history.length ? <p className="drawer-empty">No investigations yet. Select an incident above to begin.</p> : null}
      {groups.map((group) => <section className="history-group" key={group.label}><h3>{group.label}</h3>{group.items.map((item) => <button className={selectedRunId === item.run_id ? "history-item active" : "history-item"} type="button" disabled={disabled} onClick={() => void onHistory(item)} key={item.run_id}><span><strong>{item.incident_title}</strong><small>{item.incident_id}</small></span><span><small>{historyStatus(item)}</small><time>{formatHistoryTime(item.created_at)}</time></span></button>)}</section>)}
    </div>
  </>;
}

function IncidentContext({ scenario, verification }: { scenario?: ScenarioSummary; verification: ActionConfirmationResponse | null }) {
  if (!scenario) return <div className="drawer-empty-state"><Info size={24} /><p>Select an incident to view its source context.</p></div>;
  const operationalStatus = verification?.verification_status === "verified" ? "mitigated" : scenario.status;
  return <>
    <div className="drawer-heading"><span className="eyebrow">Incident context</span><h2>{scenario.name}</h2><p>{scenario.incident_id}</p></div>
    <div className="context-badges"><Badge tone={severityTone(scenario.severity)}>{scenario.severity}</Badge><Badge tone={operationalStatus === "mitigated" ? "success" : "danger"}><StatusDot tone={operationalStatus === "mitigated" ? "success" : "danger"} />{operationalStatus}</Badge></div>
    <dl className="context-facts"><div><dt>Affected service</dt><dd>{scenario.affected_service}</dd></div><div><dt>Target SLI</dt><dd>{scenario.target_sli}</dd></div><div><dt>Started</dt><dd>{formatTimestamp(scenario.started_at)}</dd></div><div><dt>Customer impact</dt><dd>{scenario.customer_impact}</dd></div></dl>
    {scenario.symptoms.length ? <div className="context-symptoms"><span>Alert symptoms</span>{scenario.symptoms.map((symptom) => <p key={symptom}><Activity size={13} />{symptom}</p>)}</div> : null}
    <div className="replay-label"><CircleDot size={14} /><span>Replay environment · deterministic telemetry</span></div>
  </>;
}

function EmptyWorkspace({ onOpen }: { onOpen: () => void }) {
  return <Card className="empty-workspace"><div className="empty-icon"><ShieldCheck size={28} /></div><span className="eyebrow">Incident Investigator</span><h3>Select an incident</h3><p>Review its context, then start the agent.</p><Button onClick={onOpen}><History size={15} />Find incident</Button></Card>;
}

function SelectedIncident({ scenario, provider, busy, onStart }: { scenario: ScenarioSummary; provider: ProviderAvailability; busy: boolean; onStart: () => Promise<void> }) {
  return <Card className="selected-incident"><div className="selected-incident-main"><div><span className="eyebrow">Ready to investigate · {scenario.incident_id}</span><h3>{scenario.name}</h3><p>{scenario.customer_impact}</p></div><div className="selected-badges"><Badge tone={severityTone(scenario.severity)}>{scenario.severity}</Badge><Badge tone="neutral">{scenario.affected_service}</Badge></div></div><div className="start-boundary"><div><strong>Autonomous investigation</strong><p>A real LLM will form hypotheses and choose observability tools against deterministic telemetry. No model work has started yet.</p></div><Button onClick={() => void onStart()} disabled={!provider.ready || busy}><Play size={16} />{busy ? "Starting investigation" : "Start investigation"}</Button></div></Card>;
}

function LiveTimeline({ accepted, events, streamState, failure, onRetry }: { accepted: InvestigationAccepted; events: InvestigationEvent[]; streamState: StreamState; failure: string | null; onRetry: () => void }) {
  const visibleEvents = visibleInvestigationEvents(events);
  const hasFailureEvent = events.some((event) => event.type === "investigation.failed");
  const connectionNeedsAttention = streamState === "reconnecting" || (streamState === "closed" && !failure);
  return <Card><CardHeader eyebrow={`Run ${shortId(accepted.run_id)}`} title="Live investigation timeline" action={<StreamBadge state={streamState} />}>Operational milestones appear as the agent works. Raw model reasoning is never displayed.</CardHeader>{connectionNeedsAttention ? <div className="reconnect-banner"><WifiOff size={15} /><span>Progress connection interrupted. The same run is preserved and no investigation was restarted.</span><Button variant="secondary" onClick={onRetry}>Reconnect</Button></div> : null}<div className="timeline live-timeline" aria-live="polite">{visibleEvents.length ? visibleEvents.map((event, index) => <ProgressEventEntry event={event} current={index === visibleEvents.length - 1} key={event.id} />) : <TimelineEntry icon={<LoaderCircle className="spin" size={16} />} label="Run accepted" current><p>The investigation is queued. Waiting for the first durable progress event.</p></TimelineEntry>}{failure && !hasFailureEvent ? <TimelineEntry icon={<XCircle size={16} />} label="Investigation failed" current><h3>Investigation could not complete</h3><p>{failure}</p></TimelineEntry> : null}</div></Card>;
}

function ProgressEventEntry({ event, current }: { event: InvestigationEvent; current: boolean }) {
  const time = formatEventTime(event.created_at);
  if (event.type === "tool.completed") return <ToolEntry call={event.payload.tool_call} current={current} timestamp={time} />;
  if (event.type === "tool.started") return <TimelineEntry icon={<LoaderCircle className="spin" size={16} />} label={`${time} · ${humanizeToolName(event.payload.tool_name)}`} current><div className="active-step"><span className="pulse-dot" /><div><h3>{event.summary}</h3><p>{event.payload.purpose}</p></div></div></TimelineEntry>;
  if (event.type === "hypotheses.updated") return <TimelineEntry icon={<CircleDot size={16} />} label={`${time} · Hypotheses updated`} current={current}><p className="event-summary">{event.summary}</p><HypothesisList hypotheses={event.payload.hypotheses} /></TimelineEntry>;
  if (event.type === "investigation.failed") return <TimelineEntry icon={<XCircle size={16} />} label={`${time} · Investigation failed`} current><h3>{event.summary}</h3><p>{event.payload.error}</p></TimelineEntry>;
  if (event.type === "investigation.completed") return <TimelineEntry icon={<CheckCircle2 size={16} />} label={`${time} · Investigation complete`} current><h3>{event.summary}</h3><p>{event.payload.tool_call_count} observability tool calls completed. Retrieving the canonical result.</p></TimelineEntry>;
  return <TimelineEntry icon={<Activity size={16} />} label={`${time} · Investigation started`} current={current}><h3>{event.summary}</h3><p>The investigator is testing evidence-backed hypotheses for this incident.</p></TimelineEntry>;
}

function StreamBadge({ state }: { state: StreamState }) {
  if (state === "live") return <Badge tone="success"><Wifi size={13} />Live</Badge>;
  if (state === "reconnecting") return <Badge tone="warning"><WifiOff size={13} />Reconnecting</Badge>;
  if (state === "closed") return <Badge tone="neutral">Stream closed</Badge>;
  return <Badge tone="info"><LoaderCircle className="spin" size={13} />Connecting</Badge>;
}

function CompletedWorkspace({ run, chat, proposal, verification, actionBusy, onConfirm }: {
  run: InvestigationResponse;
  chat: ChatExchange[];
  proposal: ActionProposal | null;
  verification: ActionConfirmationResponse | null;
  actionBusy: boolean;
  onConfirm: (proposal: ActionProposal) => Promise<void>;
}) {
  const result = run.trace.final_result;
  const supportingCalls = run.trace.tool_calls.filter((call) => call.evidence_ids.some((id) => result.evidence_ids.includes(id)));
  return <div className="completed-stack">
    <Card className={`outcome-card outcome-${result.outcome}`}><div className="outcome-heading"><div><span className="eyebrow">{result.outcome === "abstain" ? "Investigation abstained" : result.outcome === "error" ? "Investigation failed" : "Root cause analysis"}</span><h3>{result.root_cause ?? (result.outcome === "abstain" ? "The available evidence is insufficient for a defensible root cause." : run.trace.final_root_cause)}</h3></div><Badge tone={result.outcome === "error" ? "danger" : result.outcome === "abstain" ? "warning" : "success"}>{result.confidence} confidence</Badge></div>{result.mitigation ? <div className="outcome-mitigation"><strong>Recommended mitigation</strong><p>{result.mitigation}</p></div> : null}{result.missing_evidence.length ? <div className="missing-evidence"><strong>Missing evidence</strong><ul>{result.missing_evidence.map((item) => <li key={item}>{item}</li>)}</ul></div> : null}</Card>
    <Card className="supporting-evidence"><CardHeader eyebrow="Grounded conclusion" title="Supporting evidence">Only evidence retrieved during this run supports the conclusion.</CardHeader><div className="supporting-evidence-list">{supportingCalls.length ? supportingCalls.map((call) => <div key={`support-${call.sequence}-${call.tool_name}`}><TerminalSquare size={16} /><span><strong>{call.purpose}</strong><small>{humanizeToolName(call.tool_name)}</small><EvidenceIds ids={call.evidence_ids.filter((id) => result.evidence_ids.includes(id))} /></span></div>) : <div className="no-supporting-evidence"><AlertTriangle size={16} /><p>No retrieved tool call matched the final evidence references.</p></div>}</div></Card>
    {proposal && !verification ? <Card className="action-card"><CardHeader eyebrow="Human confirmation required" title="Proposed mitigation">The agent cannot change replay state without confirmation.</CardHeader><div className="action-card-body"><ActionConfirmation proposal={proposal} busy={actionBusy} onConfirm={onConfirm} /></div></Card> : null}
    {verification ? <Card className="verification-card"><CardHeader eyebrow="Confirmed action" title="Post-action verification">Deterministic telemetry owns the recovery verdict.</CardHeader><div className="verification-card-body"><VerificationDetails verification={verification} /></div></Card> : null}
    {chat.length ? <Card className="conversation-card"><CardHeader eyebrow="Same run context" title="Follow-up conversation">Answers remain grounded in evidence retrieved for this investigation.</CardHeader><div className="conversation-list">{chat.map((exchange, index) => <ChatExchangeView exchange={exchange} index={index} key={`${exchange.response.run_id}-${index}`} />)}</div></Card> : null}
    <details className="disclosure-card"><summary><span><strong>Investigation trail</strong><small>{run.trace.tool_calls.length} observability tool calls · {run.trace.agent_config_id} policy</small></span><ChevronDown size={17} /></summary><div className="timeline">{run.trace.tool_calls.map((call) => <ToolEntry call={call} key={`${call.sequence}-${call.tool_name}`} />)}{result.hypothesis_summary.length ? <TimelineEntry icon={<CircleDot size={16} />} label="Final hypothesis state"><HypothesisList hypotheses={result.hypothesis_summary} /></TimelineEntry> : null}{chat.flatMap((exchange, index) => exchange.response.tool_calls.map((call) => <ToolEntry call={call} key={`chat-${index}-${call.sequence}-${call.tool_name}`} />))}</div></details>
    {run.evaluation ? <details className="disclosure-card reliability-disclosure"><summary><span><strong>Behavioral SLO</strong><small>Grounding · Investigation sufficiency · Tool efficiency</small></span><span className={run.evaluation.behavioral_slo_pass ? "passfail pass" : "passfail fail"}>{run.evaluation.behavioral_slo_pass ? "PASS" : "FAIL"}</span><ChevronDown size={17} /></summary><div className="disclosure-body"><PrimarySloSummary evaluation={run.evaluation} /></div></details> : null}
  </div>;
}

function TimelineEntry({ icon, label, children, current = false }: { icon: React.ReactNode; label: string; children: React.ReactNode; current?: boolean }) {
  return <article className={`timeline-entry${current ? " timeline-current" : ""}`}><div className="timeline-icon">{icon}</div><div><span className="timeline-label">{label}</span><div className="timeline-content">{children}</div></div></article>;
}

function ToolEntry({ call, current = false, timestamp }: { call: ToolCall; current?: boolean; timestamp?: string }) {
  return <TimelineEntry icon={call.status === "error" ? <XCircle size={16} /> : <TerminalSquare size={16} />} label={`${timestamp ? `${timestamp} · ` : ""}${call.sequence}. ${humanizeToolName(call.tool_name)}`} current={current || call.status === "error"}><ToolCallDetails call={call} current={current} /></TimelineEntry>;
}

function ToolCallDetails({ call, current = false }: { call: ToolCall; current?: boolean }) {
  const [expanded, setExpanded] = useState(current || call.status === "error");
  const wasCurrent = useRef(current);
  useEffect(() => { if (current) setExpanded(true); else if (wasCurrent.current) setExpanded(false); wasCurrent.current = current; }, [current]);
  return <div className="tool-call"><div className="tool-summary-row"><div><p className="tool-purpose">{call.purpose || "Tool purpose was not supplied."}</p><div className="tool-meta"><Badge tone={call.status === "ok" ? "success" : "danger"}>{call.status}</Badge><span>{call.duration_ms} ms</span><span>{call.evidence_ids.length} evidence {call.evidence_ids.length === 1 ? "item" : "items"}</span></div></div><button className="tool-expand" type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}><span>{expanded ? "Hide details" : "View details"}</span><ChevronDown size={15} /></button></div>{expanded ? <div className="tool-detail-panel"><div className="json-pair"><JsonPayload label="Arguments" value={call.arguments} /><JsonPayload label="Result" value={call.result} /></div><div className="tool-evidence"><span>Evidence returned</span>{call.evidence_ids.length ? <EvidenceIds ids={call.evidence_ids} /> : <p className="muted-copy">This tool call returned no evidence identifiers.</p>}</div></div> : null}</div>;
}

function HypothesisList({ hypotheses }: { hypotheses: InvestigationResponse["trace"]["final_result"]["hypothesis_summary"] }) {
  return <div className="hypothesis-list">{hypotheses.map((item) => <div key={item.hypothesis}><Badge tone={item.status === "supported" ? "success" : item.status === "weakened" ? "danger" : "warning"}>{item.status}</Badge><span>{item.hypothesis}</span><EvidenceIds ids={item.evidence_ids} /></div>)}</div>;
}

function ChatExchangeView({ exchange, index }: { exchange: ChatExchange; index: number }) {
  return <section className="chat-exchange"><span className="eyebrow">Follow-up {index + 1}</span><div className="chat-bubble user"><strong>You</strong><p>{exchange.question}</p></div><div className="chat-bubble agent"><strong>Investigator</strong><p>{exchange.response.message}</p><EvidenceIds ids={exchange.response.evidence_ids} /></div></section>;
}

function IncidentComposer({ runReady, disabled, onSend }: { runReady: boolean; disabled: boolean; onSend: (message: string) => Promise<void> }) {
  const [message, setMessage] = useState("");
  function submit(event: FormEvent) { event.preventDefault(); const value = message.trim(); if (!value || !runReady || disabled) return; setMessage(""); void onSend(value); }
  return <form className="workspace-composer" onSubmit={submit}><MessageSquare size={18} /><input value={message} onChange={(event) => setMessage(event.target.value)} placeholder={runReady ? "Ask about this investigation…" : "Follow-up is available after the investigation completes"} disabled={!runReady || disabled} aria-label="Ask about this investigation" /><Button type="submit" disabled={!runReady || disabled || !message.trim()}><Send size={15} />Send</Button></form>;
}

function ActionConfirmation({ proposal, busy, onConfirm }: { proposal: ActionProposal; busy: boolean; onConfirm: (proposal: ActionProposal) => Promise<void> }) {
  const args = proposal.arguments;
  const supported = proposal.action_name === "rollback_configuration" && args.service === "checkout" && args.config_key === "db.max_open_connections" && args.from_value === 80 && args.to_value === 20;
  if (!supported) return <ErrorBanner message="The model proposed an unsupported action. No confirmation control is available." />;
  return <div className="action-confirmation"><h3>Rollback checkout database pool</h3><p>{proposal.expected_impact}</p><div className="action-values"><div><span>Service</span><strong>{String(args.service)}</strong></div><div><span>Configuration</span><strong>{String(args.config_key)}</strong></div><div><span>Current value</span><strong>{String(args.from_value)}</strong></div><div><span>Rollback value</span><strong>{String(args.to_value)}</strong></div></div><Button onClick={() => void onConfirm(proposal)} disabled={busy}><RotateCcw size={15} />{busy ? "Confirming rollback" : "Confirm rollback"}</Button></div>;
}

function VerificationDetails({ verification }: { verification: ActionConfirmationResponse }) {
  const assessment = verification.recovery_assessment;
  return <div className="verification-details"><div className="verification-heading"><div><h3>Recovery verification</h3><p>Application code owns the verdict from returned telemetry. The investigator separately interprets that evidence.</p></div><Badge tone={verification.verification_status === "verified" ? "success" : "danger"}>{verification.verification_status}</Badge></div><div className="verification-results"><JsonPayload label="Confirmed replay state" value={verification.result} />{verification.verification_tool_calls.length ? verification.verification_tool_calls.map((call) => <section className="verification-call" key={`verify-${call.sequence}-${call.tool_name}`}><strong>{call.sequence}. {humanizeToolName(call.tool_name)}</strong><ToolCallDetails call={call} /></section>) : <p className="muted-copy">No post-action verification tools were returned.</p>}{assessment ? <section className="agent-assessment"><div><span>Investigator assessment</span><Badge tone={assessment.conclusion === "recovered" ? "success" : assessment.conclusion === "uncertain" ? "warning" : "danger"}>{assessment.conclusion.replace("_", " ")}</Badge></div><p>{assessment.summary}</p><EvidenceIds ids={assessment.evidence_ids} />{assessment.remaining_risks.length ? <ul>{assessment.remaining_risks.map((risk) => <li key={risk}>{risk}</li>)}</ul> : null}</section> : null}{verification.agent_assessment_error ? <div className="assessment-error"><AlertTriangle size={15} /><span>The action completed and telemetry was evaluated, but the investigator assessment failed: {verification.agent_assessment_error}</span></div> : null}</div></div>;
}

function JsonPayload({ label, value }: { label: string; value: Record<string, unknown> }) {
  return <div className="json-payload"><span>{label}</span><pre>{JSON.stringify(value, null, 2)}</pre></div>;
}

function ComparisonView({ scenarios, scenarioId, onScenario, provider }: { scenarios: ScenarioSummary[]; scenarioId: string; onScenario: (id: string) => void; provider: ProviderAvailability }) {
  const history = useQuery({ queryKey: ["comparisons"], queryFn: api.listComparisons });
  const [comparison, setComparison] = useState<ComparisonResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(true);
  const [selectedComparisonId, setSelectedComparisonId] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const selectedScenario = scenarios.find((scenario) => scenario.id === scenarioId);

  useEffect(() => {
    if (!busy) { setElapsedSeconds(0); return; }
    const startedAt = Date.now();
    const timer = window.setInterval(() => setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  function changeScenario(id: string) {
    onScenario(id);
    setComparison(null);
    setSelectedComparisonId(null);
    setError(null);
  }

  async function run() {
    setBusy(true);
    setHistoryOpen(false);
    setError(null);
    setComparison(null);
    setSelectedComparisonId(null);
    try {
      const result = await api.startComparison(scenarioId);
      setComparison(result);
      setSelectedComparisonId(result.comparison_id);
      void history.refetch();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(false);
    }
  }

  async function openComparison(item: ComparisonSummary) {
    if (busy) return;
    setHistoryBusy(true);
    setError(null);
    try {
      const result = await api.getComparison(item.comparison_id);
      setComparison(result);
      setSelectedComparisonId(result.comparison_id);
      onScenario(result.scenario_id);
      setHistoryOpen(false);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setHistoryBusy(false);
    }
  }

  return (
    <section className={`comparison-shell ${historyOpen ? "drawer-open" : "drawer-collapsed"}`}>
      <nav className="drawer-rail" aria-label="Comparison panels">
        <button className={historyOpen ? "active" : ""} type="button" aria-label="Comparison history" aria-pressed={historyOpen} onClick={() => setHistoryOpen((open) => !open)}><History size={17} /><span>History</span></button>
        {historyOpen ? <button className="collapse-control" type="button" onClick={() => setHistoryOpen(false)}><PanelLeftClose size={17} /><span>Close</span></button> : null}
      </nav>
      {historyOpen ? (
        <aside className="shared-drawer">
          <ComparisonHistoryDrawer items={history.data ?? []} pending={history.isPending} error={history.isError ? errorMessage(history.error) : null} selectedId={selectedComparisonId} disabled={busy || historyBusy} onOpen={openComparison} />
        </aside>
      ) : null}
      <section className="comparison-view">
        <section className="comparison-setup">
          <div className="comparison-intro">
            <span className="eyebrow">Agent evaluation</span>
            <h2>Compare agent investigations</h2>
            <p>Same incident and tools. Different configuration.</p>
          </div>
          <div className="comparison-controls">
            <Select label="Incident" value={scenarioId} disabled={busy} onChange={changeScenario}>
              <option value="">Select an incident…</option>
              {scenarios.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.severity}</option>)}
            </Select>
            <Button onClick={() => void run()} disabled={!scenarioId || !provider.ready || busy}>
              {busy ? <LoaderCircle className="spin" size={15} /> : <GitCompareArrows size={15} />}{busy ? "Running…" : "Compare"}
            </Button>
          </div>
          {selectedScenario ? (
            <div className="comparison-incident-strip">
              <span><strong>{selectedScenario.name}</strong><small>{selectedScenario.incident_id}</small></span>
              <Badge tone={severityTone(selectedScenario.severity)}>{selectedScenario.severity}</Badge>
              <Badge tone="neutral">{selectedScenario.affected_service}</Badge>
              <span className="comparison-sli"><small>Target SLI</small><strong>{selectedScenario.target_sli}</strong></span>
            </div>
          ) : null}
        </section>
        {!provider.ready ? <ProviderBanner provider={provider} operation="comparison" /> : null}
        {error ? <ErrorBanner message={error} /> : null}
        {busy ? <ComparisonRunningState scenario={selectedScenario} elapsedSeconds={elapsedSeconds} /> : comparison ? <ComparisonResults comparison={comparison} /> : <ComparisonEmptyState scenario={selectedScenario} />}
      </section>
    </section>
  );
}

function ComparisonHistoryDrawer({ items, pending, error, selectedId, disabled, onOpen }: {
  items: ComparisonSummary[];
  pending: boolean;
  error: string | null;
  selectedId: string | null;
  disabled: boolean;
  onOpen: (item: ComparisonSummary) => Promise<void>;
}) {
  const groups = groupComparisons(items);
  return <>
    <div className="drawer-heading"><span className="eyebrow">History</span><h2>Agent comparisons</h2></div>
    <div className="history-list comparison-history-list" aria-busy={pending}>
      {pending ? <p className="drawer-empty"><LoaderCircle className="spin" size={15} />Loading…</p> : null}
      {error ? <div className="drawer-error"><AlertTriangle size={15} /><span>{error}</span></div> : null}
      {!pending && !error && !items.length ? <p className="drawer-empty">No comparisons yet.</p> : null}
      {groups.map((group) => <section className="history-group" key={group.label}><h3>{group.label}</h3>{group.items.map((item) => <button className={selectedId === item.comparison_id ? "history-item active" : "history-item"} type="button" disabled={disabled} onClick={() => void onOpen(item)} key={item.comparison_id}><span><strong>{item.incident_title}</strong><small>Baseline ↔ Candidate</small></span><span><small>Compared</small><time>{formatHistoryTime(item.created_at)}</time></span></button>)}</section>)}
    </div>
  </>;
}

export function ComparisonRunningState({ scenario, elapsedSeconds }: { scenario?: ScenarioSummary; elapsedSeconds: number }) {
  return (
    <Card className="comparison-running-state" aria-live="polite">
      <div className="comparison-running-heading">
        <div className="running-pulse"><LoaderCircle className="spin" size={20} /></div>
        <div><span className="eyebrow">Comparison in progress</span><h3>{scenario?.name ?? "Selected incident"}</h3></div>
        <Badge tone="info">{formatElapsedTime(elapsedSeconds)}</Badge>
      </div>
      <div className="indeterminate-progress"><span /></div>
      <div className="running-agent-lanes">
        <div><span className="lane-dot" /><strong>Baseline</strong><small>Waiting for completed run</small></div>
        <div><span className="lane-dot" /><strong>Candidate</strong><small>Waiting for completed run</small></div>
      </div>
      <p>Results appear together when both independent investigations finish.</p>
    </Card>
  );
}

function ComparisonResults({ comparison }: { comparison: ComparisonResponse }) {
  return (
    <div className="comparison-stack">
      <div className="comparison-result-heading">
        <div><span className="eyebrow">Completed</span><h2>Comparison results</h2></div>
        <Badge tone="success">Run {shortId(comparison.comparison_id)}</Badge>
      </div>
      <Card className="comparison-score-card">
        <CardHeader eyebrow="Output" title="RCA correctness" action={<Badge tone="neutral">Separate measure</Badge>}>Final-answer accuracy.</CardHeader>
        <div className="output-grid"><RunOutcome label="Baseline" run={comparison.baseline} /><RunOutcome label="Candidate" run={comparison.candidate} /></div>
      </Card>
      <Card className="comparison-sli-card">
        <CardHeader eyebrow="Behavior" title="Behavioral SLO" action={<Gauge size={18} />}>Grounding, Sufficiency, and Efficiency.</CardHeader>
        <SliTable baseline={comparison.baseline.evaluation} candidate={comparison.candidate.evaluation} />
      </Card>
      <div className="comparison-section-heading"><div><span className="eyebrow">Evidence path</span><h2>Tool trajectories</h2></div><Badge tone="info">Same boundary</Badge></div>
      <div className="trajectory-grid"><Trajectory label="Baseline" run={comparison.baseline} /><Trajectory label="Candidate" run={comparison.candidate} /></div>
    </div>
  );
}

function ComparisonEmptyState({ scenario }: { scenario?: ScenarioSummary }) {
  return (
    <Card className="comparison-empty-state">
      <div className="comparison-empty-copy">
        <div className="comparison-empty-icon"><GitCompareArrows size={24} /></div>
        <span className="eyebrow">Controlled comparison</span>
        <h3>{scenario ? `Ready: ${scenario.name}` : "Select an incident"}</h3>
        <p>Compare RCA, Behavioral SLO, and tool path.</p>
      </div>
      <div className="experiment-frame">
        <article className="experiment-agent baseline-agent"><span>Baseline</span><strong>Reference</strong></article>
        <div className="experiment-boundary"><ArrowRight size={18} /><span>Same boundary</span><strong>Incident · model · tools</strong><ArrowRight size={18} /></div>
        <article className="experiment-agent candidate-agent"><span>Candidate</span><strong>Proposed</strong></article>
      </div>
      <div className="comparison-readouts">
        <div><ShieldCheck size={17} /><span><strong>RCA</strong></span></div>
        <div><Gauge size={17} /><span><strong>Behavioral SLO</strong></span></div>
        <div><Layers3 size={17} /><span><strong>Tool path</strong></span></div>
      </div>
    </Card>
  );
}

function PrimarySloSummary({ evaluation }: { evaluation: BehavioralEvaluation }) {
  const rows: Array<[string, boolean]> = [["Grounding", evaluation.grounded], ["Investigation sufficiency", evaluation.investigation_sufficient], ["Tool efficiency", evaluation.tool_efficient]];
  return <div className="primary-slo-summary"><div className="primary-slo-heading"><div><strong>Behavioral SLO</strong><p>RCA correctness remains a separate output measure.</p></div><PassFail value={evaluation.behavioral_slo_pass} /></div><div className="primary-slo-rows">{rows.map(([label, value]) => <div key={label}><span>{label}</span><PassFail value={value} /></div>)}</div></div>;
}

function RunOutcome({ label, run }: { label: string; run: InvestigationResponse }) {
  const result = run.trace.final_result;
  const correctness = run.evaluation?.rca_correct;
  return (
    <article className={`run-outcome run-outcome-${label.toLowerCase()}`}>
      <div className="run-outcome-heading"><span><small>{label} configuration</small><strong>{run.trace.agent_config_id}</strong></span><Badge tone={correctness ? "success" : correctness === false ? "danger" : "neutral"}>RCA {correctness ? "PASS" : correctness === false ? "FAIL" : "NOT SCORED"}</Badge></div>
      <div className="run-outcome-answer"><span>Final outcome</span><p>{result.root_cause ?? (result.outcome === "abstain" ? "The agent abstained because the available evidence was insufficient." : "No valid result was returned.")}</p></div>
      <div className="run-outcome-meta"><span><small>Model</small><strong>{run.trace.model}</strong></span><span><small>Prompt</small><strong>{run.trace.prompt_version}</strong></span><span><small>Tools</small><strong>{run.trace.tool_calls.length} calls</strong></span></div>
    </article>
  );
}

function SliTable({ baseline, candidate }: { baseline: BehavioralEvaluation | null; candidate: BehavioralEvaluation | null }) {
  type BehavioralSliKey = "grounded" | "investigation_sufficient" | "tool_efficient" | "behavioral_slo_pass";
  const rows: Array<[string, BehavioralSliKey]> = [["Grounding", "grounded"], ["Investigation sufficiency", "investigation_sufficient"], ["Tool efficiency", "tool_efficient"], ["Behavioral SLO", "behavioral_slo_pass"]];
  return <div className="sli-table"><div className="sli-row heading"><span>Metric</span><span>Baseline</span><span>Candidate</span></div>{rows.map(([label, key]) => <div className={`sli-row${key === "behavioral_slo_pass" ? " composite" : ""}`} key={key}><span>{label}</span><PassFail value={baseline?.[key]} /><PassFail value={candidate?.[key]} /></div>)}</div>;
}

function Trajectory({ label, run }: { label: string; run: InvestigationResponse }) {
  return <Card className={`trajectory-card trajectory-${label.toLowerCase()}`}><CardHeader eyebrow={run.trace.agent_config_id} title={label} action={<Badge tone="info">{run.trace.tool_calls.length} calls</Badge>} />{run.evaluation?.reasons.length ? <details className="trajectory-notes"><summary>Evaluator notes <ChevronDown size={14} /></summary><ul>{run.evaluation.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></details> : null}<div className="compact-trajectory">{run.trace.tool_calls.map((call) => <div key={`${label}-${call.sequence}`}><span>{call.sequence}</span><div><div className="compact-tool-heading"><strong>{humanizeToolName(call.tool_name)}</strong><small>{call.duration_ms} ms · {call.status}</small></div><p>{call.purpose}</p><EvidenceIds ids={call.evidence_ids} /></div></div>)}</div></Card>;
}

function PassFail({ value }: { value: boolean | null | undefined }) {
  if (value == null) return <span className="passfail unknown">NOT SCORED</span>;
  return <span className={value ? "passfail pass" : "passfail fail"}>{value ? <CheckCircle2 size={14} /> : <XCircle size={14} />}{value ? "PASS" : "FAIL"}</span>;
}

function EvidenceIds({ ids }: { ids: string[] }) {
  const [showAll, setShowAll] = useState(false);
  if (!ids.length) return null;
  const visible = showAll ? ids : ids.slice(0, 3);
  const remaining = ids.length - visible.length;
  return <div className="evidence-ids">{visible.map((id) => <code key={id}>{id}</code>)}{remaining > 0 ? <button type="button" onClick={() => setShowAll(true)}>Show {remaining} more</button> : showAll && ids.length > 3 ? <button type="button" onClick={() => setShowAll(false)}>Show less</button> : null}</div>;
}

function groupInvestigations(items: InvestigationSummary[]): Array<{ label: string; items: InvestigationSummary[] }> {
  const groups = new Map<string, InvestigationSummary[]>();
  for (const item of items) { const label = historyDateLabel(item.created_at); groups.set(label, [...(groups.get(label) ?? []), item]); }
  return [...groups].map(([label, grouped]) => ({ label, items: grouped }));
}

function groupComparisons(items: ComparisonSummary[]): Array<{ label: string; items: ComparisonSummary[] }> {
  const groups = new Map<string, ComparisonSummary[]>();
  for (const item of items) { const label = historyDateLabel(item.created_at); groups.set(label, [...(groups.get(label) ?? []), item]); }
  return [...groups].map(([label, grouped]) => ({ label, items: grouped }));
}

function historyDateLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Earlier";
  const today = new Date();
  const startToday = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const startDate = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayDifference = Math.round((startToday.valueOf() - startDate.valueOf()) / 86_400_000);
  if (dayDifference === 0) return "Today";
  if (dayDifference === 1) return "Yesterday";
  if (dayDifference >= 2 && dayDifference <= 7) return "Previous 7 days";
  return "Earlier";
}

function historyStatus(item: InvestigationSummary): string {
  if (item.status === "completed" && item.outcome === "root_cause") return "RCA found";
  if (item.status === "completed" && item.outcome === "abstain") return "Abstained";
  if (item.status === "completed" && item.outcome === "error") return "Completed with error";
  if (item.status === "completed") return "Completed";
  if (item.status === "failed") return "Failed";
  return item.status === "running" ? "Running" : "Queued";
}

function humanizeToolName(value: string): string { return value.split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" "); }
function severityTone(severity?: string): "danger" | "warning" | "neutral" { const value = severity?.toLowerCase() ?? ""; if (value.includes("1") || value.includes("critical")) return "danger"; if (value.includes("2") || value.includes("high")) return "warning"; return "neutral"; }
function formatTimestamp(value?: string): string { if (!value) return "-"; const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString([], { dateStyle: "medium", timeStyle: "short" }); }
function formatHistoryTime(value: string): string { const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); }
function formatEventTime(value: string): string { const parsed = new Date(value); return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
function shortId(value: string): string { return value.length > 12 ? `${value.slice(0, 8)}…` : value; }

function ProviderBanner({ provider, operation }: { provider: Exclude<ProviderAvailability, { kind: "ready" }>; operation: "investigation" | "comparison" }) {
  const tone = provider.kind === "loading" ? "info" : provider.kind === "key_missing" || provider.kind === "model_missing" ? "warning" : "danger";
  return <div className={`availability-banner availability-${tone}`} role={tone === "danger" ? "alert" : "status"}><AlertTriangle size={17} /><span>{unavailableMessage(provider, operation)}</span></div>;
}

function ErrorBanner({ message }: { message: string }) { return <div className="error-banner" role="alert"><AlertTriangle size={17} /><span>{message}</span></div>; }
