import { useEffect, useState } from 'react';
import { Zap, ZapOff } from 'lucide-react';
import { ActorPanel } from './ActorPanel';
import { ValidatorStack } from './ValidatorStack';
import { getFaultState, setFault } from '../protocol/api';
import { useSimStore } from '../store/simStore';
import type { WorldSnapshot } from '../sim/types';

interface Props {
  snapshot: WorldSnapshot | null;
  prevSnapshot: WorldSnapshot | null;
  selectedActor: string | null;
  onSelect: (id: string) => void;
}

/** Split an array into chunks of at most `size` elements */
function chunk<T>(arr: T[], size: number): T[][] {
  const out: T[][] = [];
  for (let i = 0; i < arr.length; i += size) {
    out.push(arr.slice(i, i + size));
  }
  return out;
}

export function ValidatorGrid({ snapshot, prevSnapshot, selectedActor, onSelect }: Props) {
  const f = useSimStore((s) => s.f);
  const n = 3 * f + 1;
  const validatorIds = Array.from({ length: n }, (_, i) => `validator-${i}`);

  const [faults, setFaults] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(validatorIds.map((v) => [v, false])),
  );
  const [toggling, setToggling] = useState<string | null>(null);

  // Reload fault state from backend whenever f changes (new validators instantiated)
  useEffect(() => {
    setFaults(Object.fromEntries(validatorIds.map((v) => [v, false])));
    getFaultState()
      .then((state) => {
        if (Object.keys(state).length > 0) setFaults(state);
      })
      .catch(() => {/* backend not ready yet */});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [f]);

  async function toggleFault(vid: string) {
    setToggling(vid);
    const next = !faults[vid];
    try {
      await setFault(vid, next);
      setFaults((prev) => ({ ...prev, [vid]: next }));
    } finally {
      setToggling(null);
    }
  }

  const faultCount = Object.values(faults).filter(Boolean).length;
  const quorumThreshold = 2 * f + 1;
  const healthyCount = n - faultCount;
  const quorumPossible = healthyCount >= quorumThreshold;

  // For n=4: render individual 2x2 grid (existing UX)
  // For n>4: render stacked groups of 4 validators
  const useStacked = n > 4;
  const groups = useStacked ? chunk(validatorIds, 4) : [validatorIds];

  return (
    <div className="flex flex-col gap-1 h-full">
      {/* Header */}
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-gray-500 uppercase tracking-widest">
          Validators (n={n}, f={f})
        </span>
        <span
          className={`text-xs px-2 py-0.5 rounded-full ${
            quorumPossible ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-300'
          }`}
        >
          quorum {quorumPossible ? 'possible' : 'impossible'}
        </span>
      </div>

      {/* Validator panels */}
      {!useStacked ? (
        /* n=4: classic 2×2 individual panels with zap button */
        <div className="grid grid-cols-2 gap-1 flex-1">
          {validatorIds.map((vid) => {
            const isFaulty = faults[vid] ?? false;
            const isToggling = toggling === vid;
            return (
              <div key={vid} className="relative">
                <ActorPanel
                  actorId={vid}
                  snapshot={snapshot}
                  prevSnapshot={prevSnapshot}
                  selected={selectedActor === vid}
                  onClick={() => onSelect(vid)}
                  faulty={isFaulty}
                />
                <button
                  onClick={(e) => { e.stopPropagation(); toggleFault(vid); }}
                  disabled={isToggling}
                  title={isFaulty ? 'Clear fault (restore normal)' : 'Inject Byzantine fault (always rejects)'}
                  className={`absolute top-1.5 right-1.5 p-0.5 rounded transition-colors z-10 ${
                    isFaulty
                      ? 'text-red-400 hover:text-red-300 bg-red-900/40'
                      : 'text-gray-600 hover:text-yellow-400 bg-transparent hover:bg-yellow-900/20'
                  } disabled:opacity-40`}
                >
                  {isFaulty ? <ZapOff size={12} /> : <Zap size={12} />}
                </button>
              </div>
            );
          })}
        </div>
      ) : (
        /* n>4: stacked groups in a 2×N grid */
        <div className="grid grid-cols-2 gap-2 flex-1 content-start">
          {groups.map((group, gi) => (
            <ValidatorStack
              key={gi}
              groupIndex={gi}
              validatorIds={group}
              snapshot={snapshot}
              prevSnapshot={prevSnapshot}
              selectedActor={selectedActor}
              onSelect={onSelect}
              faults={faults}
              onToggleFault={toggleFault}
              toggling={toggling}
            />
          ))}
        </div>
      )}

      {/* Footer info */}
      {faultCount > 0 && (
        <div className="text-xs text-center text-gray-500 mt-1">
          {faultCount} fault{faultCount > 1 ? 's' : ''} injected — {healthyCount}/{n} healthy
          {!quorumPossible && <span className="text-red-400 ml-1">(quorum impossible)</span>}
        </div>
      )}
    </div>
  );
}
