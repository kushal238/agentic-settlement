import { useMemo } from 'react';
import { useSimStore } from '../store/simStore';
import type { SimEvent } from '../sim/types';

const FIXED_ACTORS = [
  { id: 'client', label: 'Client (AI Agent)' },
  { id: 'resource-server', label: 'Resource Server' },
  { id: 'facilitator', label: 'Facilitator' },
] as const;

const COLUMN_WIDTH = 180;
const HEADER_HEIGHT = 56;
const ROW_HEIGHT = 38;
const ROW_TOP_PAD = 24;
const MIN_LIFELINE_HEIGHT = 480;

const COLOR = {
  ok: '#10b981',
  error: '#ef4444',
  timeout: '#f59e0b',
  internal: '#60a5fa',
  muted: '#374151',
  textDim: '#9ca3af',
  textBright: '#e5e7eb',
};

function outcomeColor(ev: SimEvent): string {
  if (ev.to === null) return COLOR.internal;
  switch (ev.outcome ?? 'ok') {
    case 'error':
      return COLOR.error;
    case 'timeout':
      return COLOR.timeout;
    default:
      return COLOR.ok;
  }
}

export function SwimlaneView() {
  const f = useSimStore((s) => s.f);
  const events = useSimStore((s) => s.events);
  const playheadIndex = useSimStore((s) => s.playheadIndex);

  const n = 3 * f + 1;
  const actors = useMemo(
    () => [
      ...FIXED_ACTORS.map((a) => ({ ...a })),
      ...Array.from({ length: n }, (_, i) => ({
        id: `validator-${i}`,
        label: `validator-${i}`,
      })),
    ],
    [n],
  );

  const xMap = useMemo(() => {
    const m = new Map<string, number>();
    actors.forEach((a, i) => m.set(a.id, i * COLUMN_WIDTH + COLUMN_WIDTH / 2));
    return m;
  }, [actors]);

  const totalWidth = actors.length * COLUMN_WIDTH;
  const lifelineHeight = Math.max(
    MIN_LIFELINE_HEIGHT,
    ROW_TOP_PAD + (events.length + 1) * ROW_HEIGHT,
  );
  const totalHeight = HEADER_HEIGHT + lifelineHeight;

  // Reveal events up to the playhead (-1 means nothing visible yet)
  const visibleCount = Math.max(0, playheadIndex + 1);

  return (
    <div className="flex-1 overflow-auto px-4 pt-3 pb-2 bg-gray-950">
      <svg
        width={totalWidth}
        height={totalHeight}
        className="block"
        style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}
      >
        <defs>
          {(['ok', 'error', 'timeout', 'internal'] as const).map((kind) => (
            <marker
              key={kind}
              id={`arrow-${kind}`}
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="7"
              markerHeight="7"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" fill={COLOR[kind]} />
            </marker>
          ))}
        </defs>

        {/* Lifelines + headers */}
        {actors.map((actor, i) => {
          const x = i * COLUMN_WIDTH + COLUMN_WIDTH / 2;
          const isValidator = actor.id.startsWith('validator-');
          return (
            <g key={actor.id}>
              <rect
                x={x - 78}
                y={6}
                width={156}
                height={HEADER_HEIGHT - 12}
                rx={6}
                fill={isValidator ? '#0f172a' : '#1f2937'}
                stroke={isValidator ? '#1e293b' : '#374151'}
                strokeWidth={1}
              />
              <text
                x={x}
                y={HEADER_HEIGHT / 2 + 4}
                textAnchor="middle"
                fontSize={11}
                fontWeight={600}
                fill={COLOR.textBright}
              >
                {actor.label}
              </text>
              <line
                x1={x}
                y1={HEADER_HEIGHT}
                x2={x}
                y2={HEADER_HEIGHT + lifelineHeight}
                stroke={COLOR.muted}
                strokeWidth={1}
                strokeDasharray="4 6"
              />
            </g>
          );
        })}

        {/* Events */}
        {events.slice(0, visibleCount).map((ev, i) => {
          const y = HEADER_HEIGHT + ROW_TOP_PAD + i * ROW_HEIGHT;
          const fromX = xMap.get(ev.from);
          const toX = ev.to ? xMap.get(ev.to) : null;
          const color = outcomeColor(ev);
          const markerKind =
            ev.to === null
              ? 'internal'
              : ev.outcome === 'error'
              ? 'error'
              : ev.outcome === 'timeout'
              ? 'timeout'
              : 'ok';

          if (fromX === undefined) return null;

          // Internal action (to=null): small circle on the source lifeline + label to the right
          if (toX === null || toX === undefined) {
            return (
              <g key={ev.id}>
                <circle cx={fromX} cy={y} r={4} fill={color} />
                <text
                  x={fromX + 12}
                  y={y + 4}
                  fontSize={10}
                  fill={COLOR.textDim}
                >
                  {ev.label}
                </text>
                <text
                  x={fromX - 14}
                  y={y + 4}
                  fontSize={9}
                  fill={COLOR.textDim}
                  textAnchor="end"
                >
                  [{ev.step}]
                </text>
              </g>
            );
          }

          // Cross-lane arrow
          const leftToRight = toX > fromX;
          const labelX = (fromX + toX) / 2;
          const x1 = leftToRight ? fromX + 5 : fromX - 5;
          const x2 = leftToRight ? toX - 5 : toX + 5;
          return (
            <g key={ev.id}>
              <line
                x1={x1}
                y1={y}
                x2={x2}
                y2={y}
                stroke={color}
                strokeWidth={1.5}
                markerEnd={`url(#arrow-${markerKind})`}
              />
              <text
                x={labelX}
                y={y - 5}
                fontSize={10}
                fill={COLOR.textBright}
                textAnchor="middle"
              >
                {ev.label}
              </text>
              <circle cx={fromX} cy={y} r={2.5} fill={color} />
              {/* Step badge near the source */}
              <text
                x={leftToRight ? fromX + 10 : fromX - 10}
                y={y + 11}
                fontSize={9}
                fill={COLOR.textDim}
                textAnchor={leftToRight ? 'start' : 'end'}
              >
                step {ev.step}
              </text>
            </g>
          );
        })}

        {/* Empty-state hint */}
        {visibleCount === 0 && (
          <text
            x={totalWidth / 2}
            y={HEADER_HEIGHT + 80}
            textAnchor="middle"
            fontSize={12}
            fill={COLOR.textDim}
          >
            Click Run to start the swimlane
          </text>
        )}
      </svg>
    </div>
  );
}
