import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Zap, ZapOff } from 'lucide-react';
import { useSimStore } from '../store/simStore';
import type { SimEvent, WorldSnapshot } from '../sim/types';
import { getFaultState, setFault } from '../protocol/api';

interface Props {
  snapshot: WorldSnapshot | null;
  selectedActor: string | null;
  onSelectActor: (id: string) => void;
  onHoverActor: (id: string | null) => void;
}

// ─── colour helpers ────────────────────────────────────────────────────────

function phaseColor(phase: string): string {
  const map: Record<string, string> = {
    idle: '#374151', collecting: '#1e3a5f', evaluating: '#3b2e00',
    settled: '#064e3b', failed: '#450a0a', verifying: '#1e3a5f',
    certified: '#064e3b', rejected: '#450a0a', settling: '#2e1065',
    dead: '#1f2937', divergent: '#431407',
  };
  return map[phase] ?? '#374151';
}

function phaseText(phase: string): string {
  const map: Record<string, string> = {
    idle: '#6B7280', collecting: '#60A5FA', evaluating: '#FBBF24',
    settled: '#34D399', failed: '#F87171', verifying: '#60A5FA',
    certified: '#34D399', rejected: '#F87171', settling: '#A78BFA',
    dead: '#4B5563', divergent: '#FB923C',
  };
  return map[phase] ?? '#9CA3AF';
}

function eventColor(ev: SimEvent): string {
  if (ev.kind === 'return_200') return '#10B981';
  if (ev.kind === 'return_402' || ev.kind.startsWith('rejection')) return '#EF4444';
  if (ev.kind.startsWith('certificate') || ev.kind === 'settle_ok') return '#10B981';
  if (ev.kind.startsWith('fanout') || ev.kind === 'post_settle') return '#3B82F6';
  if (ev.kind === 'get_resource' || ev.kind === 'retry_request') return '#F59E0B';
  if (ev.kind.startsWith('timeout')) return '#6B7280';
  return '#8B5CF6';
}

// ─── column mapping — new layout: bft | client | resource ─────────────────

type Column = 'bft' | 'client' | 'resource';

function columnOf(actorId: string): Column {
  if (actorId === 'client') return 'client';
  if (actorId === 'resource-server') return 'resource';
  // facilitator and all validators share the BFT column
  return 'bft';
}

// ─── packet type ──────────────────────────────────────────────────────────

interface Packet {
  id: string;
  event: SimEvent;
  color: string;
  progress: number;
}

// ─── Node box ─────────────────────────────────────────────────────────────

interface NodeBoxProps {
  label: string;
  sublabel?: string;
  phase?: string;
  selected: boolean;
  onClick: () => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  children?: React.ReactNode;
  style?: React.CSSProperties;
  nodeRef?: React.RefObject<HTMLDivElement>;
}

function NodeBox({ label, sublabel, phase, selected, onClick, onMouseEnter, onMouseLeave, children, style, nodeRef }: NodeBoxProps) {
  const bg = phase ? phaseColor(phase) : '#1F2937';
  const borderColor = selected ? '#3B82F6' : '#374151';

  return (
    <div
      ref={nodeRef}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      style={{
        background: bg,
        border: `1.5px solid ${borderColor}`,
        boxShadow: selected ? '0 0 0 1px #3B82F6' : undefined,
        borderRadius: 10,
        padding: '10px 14px',
        cursor: 'pointer',
        transition: 'all 0.15s',
        minWidth: 110,
        ...style,
      }}
    >
      <div style={{ fontSize: 11, color: '#9CA3AF', marginBottom: 2 }}>{sublabel}</div>
      <div style={{ fontSize: 13, fontWeight: 700, color: '#F3F4F6' }}>{label}</div>
      {phase && (
        <div style={{ fontSize: 10, color: phaseText(phase), marginTop: 4, fontFamily: 'monospace' }}>
          {phase}
        </div>
      )}
      {children}
    </div>
  );
}

// ─── Small connector annotation ────────────────────────────────────────────

function Connector({ label, sublabel }: { label: string; sublabel?: string }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 2,
      flexShrink: 0,
      userSelect: 'none',
    }}>
      <span style={{ fontSize: 9, color: '#4B5563', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{label}</span>
      <span style={{ color: '#374151', fontSize: 16 }}>↔</span>
      {sublabel && <span style={{ fontSize: 9, color: '#374151', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>{sublabel}</span>}
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────

export function SimpleTopology({ snapshot, selectedActor, onSelectActor, onHoverActor }: Props) {
  const events = useSimStore((s) => s.events);
  const playheadIndex = useSimStore((s) => s.playheadIndex);
  const playing = useSimStore((s) => s.playing);
  const f = useSimStore((s) => s.f);
  const n = 3 * f + 1;
  const validatorIds = Array.from({ length: n }, (_, i) => `validator-${i}`);

  // ── fault state ──
  const [faults, setFaults] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(validatorIds.map((v) => [v, false])),
  );
  const [toggling, setToggling] = useState<string | null>(null);

  useEffect(() => {
    setFaults(Object.fromEntries(validatorIds.map((v) => [v, false])));
    getFaultState()
      .then((state) => { if (Object.keys(state).length > 0) setFaults(state); })
      .catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f]);

  async function toggleFault(vid: string, e: React.MouseEvent) {
    e.stopPropagation();
    setToggling(vid);
    const next = !faults[vid];
    try {
      await setFault(vid, next);
      setFaults((prev) => ({ ...prev, [vid]: next }));
    } finally {
      setToggling(null);
    }
  }

  // ── animated packets ──
  const packetsRef = useRef<Map<string, Packet>>(new Map());
  const [, forceRender] = useState(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (playheadIndex < 0 || playheadIndex >= events.length) return;
    const ev = events[playheadIndex]!;
    if (!ev.to) return;
    packetsRef.current.set(ev.id, { id: ev.id, event: ev, color: eventColor(ev), progress: 0 });
    if (!playing) {
      packetsRef.current.forEach((p) => { p.progress = 1; });
      forceRender((c) => c + 1);
    }
  }, [playheadIndex]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!playing) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      return;
    }
    let last = performance.now();
    function tick(now: number) {
      const dt = (now - last) / 600;
      last = now;
      let dirty = false;
      packetsRef.current.forEach((p, k) => {
        p.progress = Math.min(1, p.progress + dt);
        if (p.progress >= 1) packetsRef.current.delete(k);
        dirty = true;
      });
      if (dirty) forceRender((c) => c + 1);
      rafRef.current = requestAnimationFrame(tick);
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [playing]);

  // ── measure DOM centres for precise SVG arrows ──
  const containerRef = useRef<HTMLDivElement>(null);
  const bftRef = useRef<HTMLDivElement>(null);
  const clientRef = useRef<HTMLDivElement>(null);
  const resourceRef = useRef<HTMLDivElement>(null);

  const [centres, setCentres] = useState<Record<Column, number>>({ bft: 0.18, client: 0.5, resource: 0.82 });
  const [dim, setDim] = useState({ w: 900, h: 200 });

  function recompute() {
    const container = containerRef.current;
    if (!container) return;
    const cr = container.getBoundingClientRect();
    setDim({ w: cr.width, h: cr.height });

    function cx(ref: React.RefObject<HTMLDivElement>) {
      if (!ref.current) return 0;
      const r = ref.current.getBoundingClientRect();
      return (r.left + r.width / 2 - cr.left) / cr.width;
    }
    setCentres({ bft: cx(bftRef), client: cx(clientRef), resource: cx(resourceRef) });
  }

  useEffect(() => {
    recompute(); // initial measurement after mount
    const obs = new ResizeObserver(() => recompute());
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── build SVG arrows ──
  const MID_Y = 0.5;

  const arrows: JSX.Element[] = [];
  packetsRef.current.forEach((packet) => {
    const { event, progress, color } = packet;
    if (!event.to) return;

    const fromCol = columnOf(event.from);
    const toCol = columnOf(event.to);
    if (fromCol === toCol) return;

    const x1 = centres[fromCol] * dim.w;
    const x2 = centres[toCol] * dim.w;
    const y = MID_Y * dim.h;
    const cx = (x1 + x2) / 2;
    const cy = y - 40;
    const t = progress;
    const px = (1 - t) * (1 - t) * x1 + 2 * (1 - t) * t * cx + t * t * x2;
    const py = (1 - t) * (1 - t) * y + 2 * (1 - t) * t * cy + t * t * y;

    arrows.push(
      <g key={packet.id}>
        <path
          d={`M ${x1} ${y} Q ${cx} ${cy} ${x2} ${y}`}
          fill="none"
          stroke={color}
          strokeWidth={1.5}
          strokeDasharray="5 4"
          opacity={0.35}
        />
        <circle cx={px} cy={py} r={6} fill={color} opacity={0.9} />
        <text
          x={cx}
          y={cy - 6}
          textAnchor="middle"
          fontSize={9}
          fill={color}
          opacity={0.85}
          fontFamily="monospace"
        >
          {event.label.length > 24 ? event.label.slice(0, 22) + '…' : event.label}
        </text>
      </g>,
    );
  });

  // ── snapshot shortcuts ──
  const clientPhase = snapshot ? (snapshot.client.pending_claim ? 'active' : 'idle') : 'idle';
  const rsPhase = snapshot
    ? (snapshot.resourceServer.last_status === 200 ? 'ok'
      : snapshot.resourceServer.last_status === 402 ? 'payment_required' : 'idle')
    : 'idle';
  const facPhase = snapshot?.facilitator.phase ?? 'idle';

  const faultCount = Object.values(faults).filter(Boolean).length;
  const quorumThreshold = 2 * f + 1;
  const healthyCount = n - faultCount;
  const quorumPossible = healthyCount >= quorumThreshold;

  return (
    <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      {/* SVG overlay — pointer-events: none so DOM clicks pass through */}
      <div
        ref={containerRef}
        style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
      >
        <svg width="100%" height="100%" style={{ overflow: 'visible' }}>
          {arrows}
        </svg>
      </div>

      {/* ── Node row: BFT | connector | Client | connector | API Server ── */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '14px 20px',
        position: 'relative',
        zIndex: 1,
      }}>

        {/* ── LEFT: BFT Server (Facilitator + validator threads) ── */}
        <div
          ref={bftRef}
          style={{
            flex: 2,
            border: `1.5px solid ${selectedActor === 'facilitator' ? '#3B82F6' : '#374151'}`,
            borderRadius: 12,
            background: phaseColor(facPhase),
            padding: '10px 14px',
            cursor: 'pointer',
            transition: 'all 0.15s',
          }}
          onClick={() => onSelectActor('facilitator')}
          onMouseEnter={() => onHoverActor('facilitator')}
          onMouseLeave={() => onHoverActor(null)}
        >
          <div style={{ fontSize: 11, color: '#9CA3AF' }}>BFT Server</div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#F3F4F6' }}>Facilitator</div>
            <div style={{ fontSize: 10, color: phaseText(facPhase), fontFamily: 'monospace' }}>{facPhase}</div>
          </div>
          {snapshot && (
            <div style={{ fontSize: 10, color: '#6B7280', fontFamily: 'monospace', marginBottom: 6 }}>
              certs {snapshot.facilitator.certificates_collected}/{snapshot.facilitator.quorum_threshold} needed
            </div>
          )}

          {/* Quorum badge */}
          <div style={{
            display: 'inline-block', fontSize: 9, padding: '1px 6px', borderRadius: 99,
            background: quorumPossible ? '#064e3b' : '#450a0a',
            color: quorumPossible ? '#34D399' : '#F87171',
            marginBottom: 8,
          }}>
            quorum {quorumPossible ? 'possible' : 'impossible'} · n={n} f={f}
          </div>

          {/* Validator thread rows */}
          <div
            style={{ display: 'flex', flexDirection: 'column', gap: 3 }}
            onClick={(e) => e.stopPropagation()}
          >
            {validatorIds.map((vid) => {
              const vs = snapshot?.validators[vid];
              const phase = vs?.phase ?? 'idle';
              const isFaulty = faults[vid] ?? false;
              const isSelected = selectedActor === vid;
              return (
                <div
                  key={vid}
                  onClick={() => onSelectActor(vid)}
                  onMouseEnter={() => onHoverActor(vid)}
                  onMouseLeave={() => onHoverActor(null)}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '3px 6px', borderRadius: 6,
                    background: isFaulty ? '#450a0a' : isSelected ? '#1e3a5f' : '#111827',
                    border: `1px solid ${isSelected ? '#3B82F6' : isFaulty ? '#7F1D1D' : '#1F2937'}`,
                    cursor: 'pointer', transition: 'all 0.12s',
                  }}
                >
                  <div style={{
                    width: 6, height: 6, borderRadius: '50%',
                    background: isFaulty ? '#EF4444' : phaseText(phase),
                    flexShrink: 0,
                  }} />
                  <span style={{ fontSize: 10, color: '#9CA3AF', fontFamily: 'monospace', flexShrink: 0 }}>
                    {vid.replace('validator-', 'v')}
                  </span>
                  <span style={{ fontSize: 10, color: phaseText(phase), fontFamily: 'monospace', flex: 1 }}>
                    {isFaulty ? 'byzantine' : phase}
                  </span>
                  {vs && (
                    <span style={{ fontSize: 9, color: '#4B5563', fontFamily: 'monospace' }}>
                      bal:{vs.balance_of_agent ?? '—'}
                    </span>
                  )}
                  <button
                    onClick={(e) => toggleFault(vid, e)}
                    disabled={toggling === vid}
                    title={isFaulty ? 'Clear fault' : 'Inject Byzantine fault'}
                    style={{
                      background: 'none', border: 'none', padding: '0 2px', cursor: 'pointer',
                      color: isFaulty ? '#EF4444' : '#4B5563',
                      opacity: toggling === vid ? 0.4 : 1,
                      display: 'flex', alignItems: 'center',
                    }}
                  >
                    {isFaulty ? <ZapOff size={10} /> : <Zap size={10} />}
                  </button>
                  {vs?.phase === 'divergent' && (
                    <AlertTriangle size={10} style={{ color: '#FB923C', flexShrink: 0 }} />
                  )}
                </div>
              );
            })}
          </div>
        </div>

        {/* Connector: BFT ↔ Client */}
        <Connector label="get claim cert" sublabel="fanout / vote" />

        {/* ── CENTER: Client (Agent / PC) ── */}
        <NodeBox
          nodeRef={clientRef}
          sublabel="PC / Agent"
          label="Client"
          phase={clientPhase}
          selected={selectedActor === 'client'}
          onClick={() => onSelectActor('client')}
          onMouseEnter={() => onHoverActor('client')}
          onMouseLeave={() => onHoverActor(null)}
          style={{ flex: 1 }}
        >
          {snapshot && (
            <div style={{ marginTop: 6, fontSize: 10, color: '#6B7280', fontFamily: 'monospace' }}>
              <div>balance: {snapshot.client.balance}</div>
              <div>nonce: {snapshot.client.nonce}</div>
            </div>
          )}
        </NodeBox>

        {/* Connector: Client → API Server */}
        <Connector label="present cert" sublabel="get resource" />

        {/* ── RIGHT: Resource Server (API Server) ── */}
        <NodeBox
          nodeRef={resourceRef}
          sublabel="API Server"
          label="Resource Server"
          phase={rsPhase}
          selected={selectedActor === 'resource-server'}
          onClick={() => onSelectActor('resource-server')}
          onMouseEnter={() => onHoverActor('resource-server')}
          onMouseLeave={() => onHoverActor(null)}
          style={{ flex: 1 }}
        >
          {snapshot && (
            <div style={{ marginTop: 6, fontSize: 10, color: '#6B7280', fontFamily: 'monospace' }}>
              <div>needs: {snapshot.resourceServer.required_amount}</div>
              <div>status: {snapshot.resourceServer.last_status ?? '—'}</div>
            </div>
          )}
          <div style={{ marginTop: 6, fontSize: 9, color: '#374151', fontFamily: 'monospace', lineHeight: 1.4 }}>
            verifies cert only —<br />no validator contact
          </div>
        </NodeBox>
      </div>
    </div>
  );
}
