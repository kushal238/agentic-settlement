import { useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useSimStore } from '../store/simStore';

const STEP_COLORS: Record<number, string> = {
  1: 'text-amber-400',
  2: 'text-red-400',
  3: 'text-blue-400',
  4: 'text-purple-400',
  5: 'text-orange-400',
  6: 'text-violet-400',
  7: 'text-blue-400',
  8: 'text-amber-400',
  9: 'text-gray-400',
  10: 'text-gray-400',
  11: 'text-green-400',
};

const OUTCOME_ICON: Record<string, string> = {
  ok: '✓',
  error: '✗',
  timeout: '⏱',
};

interface Props {
  onSelect: (eventId: string) => void;
  selectedEventId: string | null;
}

export function MethodLog({ onSelect, selectedEventId }: Props) {
  const events = useSimStore((s) => s.events);
  const epoch = useSimStore((s) => s.epoch);
  const playheadIndex = useSimStore((s) => s.playheadIndex);
  const listRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to active event
  useEffect(() => {
    if (listRef.current && playheadIndex >= 0) {
      const rows = listRef.current.querySelectorAll('[data-row]');
      const row = rows[playheadIndex];
      row?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }, [playheadIndex]);

  const visibleEvents = events.slice(0, Math.max(0, playheadIndex + 1));

  return (
    <div className="panel flex flex-col overflow-hidden">
      <div className="panel-header">Method Call Log</div>
      <div ref={listRef} className="flex-1 overflow-y-auto text-xs">
        {events.length === 0 && (
          <div className="px-3 py-6 text-gray-600 italic text-center">
            Click Run to start the simulation
          </div>
        )}
        <AnimatePresence initial={false}>
          {visibleEvents.map((ev, idx) => {
            const relMs = ((ev.t_start_us - epoch) / 1000).toFixed(3);
            const isActive = idx === playheadIndex;
            const isSelected = ev.id === selectedEventId;
            const stepColor = STEP_COLORS[ev.step] ?? 'text-gray-400';
            const outcomeIcon = ev.outcome ? OUTCOME_ICON[ev.outcome] ?? '' : '';

            return (
              <motion.div
                key={ev.id}
                data-row
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.15 }}
                className={`flex items-baseline gap-2 px-3 py-1 cursor-pointer hover:bg-gray-800 border-l-2 transition-colors ${
                  isActive ? 'bg-gray-800 border-blue-500' : isSelected ? 'bg-gray-850 border-gray-600' : 'border-transparent'
                }`}
                onClick={() => {
                  onSelect(ev.id);
                }}
              >
                <span className="text-gray-600 tabular-nums shrink-0 w-20">t+{relMs}ms</span>
                <span className={`shrink-0 font-bold ${stepColor}`}>[{ev.step}]</span>
                <span className="text-gray-300 truncate flex-1">{ev.label}</span>
                {outcomeIcon && (
                  <span className={ev.outcome === 'ok' ? 'text-green-400' : ev.outcome === 'timeout' ? 'text-gray-400' : 'text-red-400'}>
                    {outcomeIcon}
                  </span>
                )}
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </div>
  );
}
