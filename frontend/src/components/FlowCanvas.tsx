import { useEffect, useRef, useState } from 'react';
import { useSimStore } from '../store/simStore';
import type { SimEvent } from '../sim/types';

// Fixed x-positions (fraction of canvas width) per actor zone
const ACTOR_X: Record<string, number> = {
  'client': 0.125,
  'resource-server': 0.375,
  'facilitator': 0.625,
  'validator-0': 0.8125,
  'validator-1': 0.9375,
  'validator-2': 0.8125,
  'validator-3': 0.9375,
};

// Y offsets for validators (top row vs bottom row)
const ACTOR_Y_FRAC: Record<string, number> = {
  'client': 0.5,
  'resource-server': 0.5,
  'facilitator': 0.5,
  'validator-0': 0.25,
  'validator-1': 0.25,
  'validator-2': 0.75,
  'validator-3': 0.75,
};

const KIND_COLOR: Record<string, string> = {
  get_resource: '#F59E0B',
  return_402: '#EF4444',
  post_settle: '#3B82F6',
  return_result: '#3B82F6',
  retry_request: '#F59E0B',
  return_200: '#10B981',
};

function colorForEvent(ev: SimEvent): string {
  if (KIND_COLOR[ev.kind]) return KIND_COLOR[ev.kind]!;
  if (ev.kind.startsWith('fanout')) return '#3B82F6';
  if (ev.kind.startsWith('certificate')) return '#10B981';
  if (ev.kind.startsWith('rejection')) return '#EF4444';
  if (ev.kind.startsWith('timeout')) return '#6B7280';
  if (ev.kind.startsWith('settle_')) return '#8B5CF6';
  return '#6B7280';
}

interface Packet {
  id: string;
  event: SimEvent;
  progress: number; // 0..1
  color: string;
}

export function FlowCanvas() {
  const events = useSimStore((s) => s.events);
  const playheadIndex = useSimStore((s) => s.playheadIndex);
  const playing = useSimStore((s) => s.playing);
  const containerRef = useRef<SVGSVGElement>(null);
  const [dim, setDim] = useState({ w: 800, h: 120 });
  const packetsRef = useRef<Map<string, Packet>>(new Map());
  const [, forceRender] = useState(0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const obs = new ResizeObserver((entries) => {
      const e = entries[0];
      if (e) setDim({ w: e.contentRect.width, h: e.contentRect.height });
    });
    if (containerRef.current) obs.observe(containerRef.current);
    return () => obs.disconnect();
  }, []);

  // Trigger packet for the active event
  useEffect(() => {
    if (playheadIndex < 0 || playheadIndex >= events.length) return;
    const ev = events[playheadIndex]!;
    if (!ev.to) return;

    packetsRef.current.set(ev.id, { id: ev.id, event: ev, progress: 0, color: colorForEvent(ev) });

    if (!playing) {
      // jump to end immediately when stepping
      packetsRef.current.forEach((p) => { p.progress = 1; });
      forceRender((n) => n + 1);
    }
  }, [playheadIndex]);

  useEffect(() => {
    if (!playing) {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      return;
    }

    let last = performance.now();
    function tick(now: number) {
      const dt = (now - last) / 600; // packet crosses canvas in ~600ms at 1x
      last = now;
      let dirty = false;
      packetsRef.current.forEach((p, k) => {
        p.progress = Math.min(1, p.progress + dt);
        if (p.progress >= 1) {
          packetsRef.current.delete(k);
        }
        dirty = true;
      });
      if (dirty) forceRender((n) => n + 1);
      rafRef.current = requestAnimationFrame(tick);
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => { if (rafRef.current) cancelAnimationFrame(rafRef.current); };
  }, [playing]);

  const { w, h } = dim;

  function actorXY(actorId: string): [number, number] {
    const xFrac = ACTOR_X[actorId] ?? 0.5;
    const yFrac = ACTOR_Y_FRAC[actorId] ?? 0.5;
    return [xFrac * w, yFrac * h];
  }

  const arrows: JSX.Element[] = [];

  packetsRef.current.forEach((packet) => {
    const { event, progress, color } = packet;
    if (!event.to) return;

    const [x1, y1] = actorXY(event.from);
    const [x2, y2] = actorXY(event.to);

    const cx = (x1 + x2) / 2;
    const cy = Math.min(y1, y2) - 30;
    const t = progress;
    const px = (1 - t) * (1 - t) * x1 + 2 * (1 - t) * t * cx + t * t * x2;
    const py = (1 - t) * (1 - t) * y1 + 2 * (1 - t) * t * cy + t * t * y2;

    arrows.push(
      <g key={packet.id}>
        <path
          d={`M ${x1} ${y1} Q ${cx} ${cy} ${x2} ${y2}`}
          fill="none"
          stroke={color}
          strokeWidth={1.5}
          strokeDasharray="4 4"
          opacity={0.4}
        />
        <circle cx={px} cy={py} r={6} fill={color} opacity={0.9} />
      </g>,
    );
  });

  // Actor anchor dots
  const anchors = Object.keys(ACTOR_X).map((id) => {
    const [x, y] = actorXY(id);
    return <circle key={id} cx={x} cy={y} r={3} fill="#374151" stroke="#6B7280" strokeWidth={1} />;
  });

  return (
    <svg
      ref={containerRef}
      className="w-full h-full pointer-events-none"
      style={{ overflow: 'visible' }}
    >
      {anchors}
      {arrows}
    </svg>
  );
}
