import { useEffect, useRef } from 'react';
import { scaleLinear } from 'd3-scale';
import { select } from 'd3-selection';
import { axisBottom } from 'd3-axis';
import { Play, Pause, SkipBack, SkipForward } from 'lucide-react';
import { useSimStore } from '../store/simStore';
import type { Speed } from '../store/simStore';

const SPEEDS: Speed[] = [0.25, 1, 4, 16];

export function Timeline() {
  const events = useSimStore((s) => s.events);
  const epoch = useSimStore((s) => s.epoch);
  const currentTime = useSimStore((s) => s.currentTime);
  const playing = useSimStore((s) => s.playing);
  const speed = useSimStore((s) => s.speed);
  const { play, pause, setSpeed, stepForward, stepBackward, setCurrentTime } = useSimStore();

  const axisRef = useRef<SVGGElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const totalUs = events.length > 0 ? events[events.length - 1]!.t_end_us - epoch : 1;

  useEffect(() => {
    if (!axisRef.current || !containerRef.current) return;
    const w = containerRef.current.clientWidth - 32; // padding
    const scale = scaleLinear().domain([0, totalUs / 1000]).range([0, w]); // display in ms
    const axis = axisBottom(scale)
      .ticks(8)
      .tickFormat((d) => `${(d as number).toFixed(1)}ms`);
    select(axisRef.current).call(axis as never);
    select(axisRef.current).selectAll('text').attr('fill', '#9CA3AF').style('font-size', '10px');
    select(axisRef.current).selectAll('line,path').attr('stroke', '#374151');
  }, [totalUs, events]);

  const w = containerRef.current?.clientWidth ?? 600;
  const trackW = w - 32;
  const playheadX = totalUs > 0 ? (currentTime / totalUs) * trackW + 16 : 16;

  // Tick marks for events
  const ticks = events.map((ev) => {
    const x = ((ev.t_start_us - epoch) / totalUs) * trackW + 16;
    const color =
      ev.kind.startsWith('certificate') ? '#10B981' :
      ev.kind.startsWith('rejection') || ev.kind.startsWith('return_402') ? '#EF4444' :
      ev.kind.startsWith('fanout') || ev.kind === 'post_settle' ? '#3B82F6' :
      '#6B7280';
    return { x, color, id: ev.id };
  });

  function handleTrackClick(e: React.MouseEvent<SVGRectElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = (e.clientX - rect.left) / rect.width;
    setCurrentTime(frac * totalUs);
  }

  return (
    <div className="panel flex flex-col gap-2 p-3" ref={containerRef}>
      <div className="flex items-center gap-2">
        <button onClick={stepBackward} className="p-1 hover:text-white text-gray-400 transition-colors" title="Step back">
          <SkipBack size={14} />
        </button>
        <button
          onClick={() => playing ? pause() : play()}
          className="p-1.5 rounded bg-gray-700 hover:bg-gray-600 text-white transition-colors"
          title={playing ? 'Pause' : 'Play'}
        >
          {playing ? <Pause size={14} /> : <Play size={14} />}
        </button>
        <button onClick={stepForward} className="p-1 hover:text-white text-gray-400 transition-colors" title="Step forward">
          <SkipForward size={14} />
        </button>
        <div className="flex gap-1 ml-2">
          {SPEEDS.map((s) => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              className={`text-xs px-2 py-0.5 rounded transition-colors ${speed === s ? 'bg-blue-600 text-white' : 'bg-gray-700 text-gray-300 hover:bg-gray-600'}`}
            >
              {s}×
            </button>
          ))}
        </div>
        <span className="ml-auto text-xs text-gray-500 tabular-nums">
          {(currentTime / 1000).toFixed(2)}ms
        </span>
      </div>

      <svg className="w-full" style={{ height: 48, overflow: 'visible' }}>
        {/* Track background */}
        <rect
          x={16}
          y={14}
          width={trackW}
          height={4}
          rx={2}
          fill="#374151"
          className="cursor-pointer"
          onClick={handleTrackClick}
        />
        {/* Event ticks */}
        {ticks.map((t) => (
          <line key={t.id} x1={t.x} x2={t.x} y1={10} y2={22} stroke={t.color} strokeWidth={1} opacity={0.7} />
        ))}
        {/* Playhead */}
        <line x1={playheadX} x2={playheadX} y1={8} y2={24} stroke="white" strokeWidth={2} />
        <circle cx={playheadX} cy={16} r={4} fill="white" />
        {/* D3 axis */}
        <g ref={axisRef} transform={`translate(16, 26)`} />
      </svg>
    </div>
  );
}
