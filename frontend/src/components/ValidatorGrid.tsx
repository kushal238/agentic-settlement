import { useEffect, useState } from 'react';
import { Zap, ZapOff } from 'lucide-react';
import { ActorPanel } from './ActorPanel';
import { getFaultState, setFault } from '../protocol/api';
import type { WorldSnapshot } from '../sim/types';

interface Props {
  snapshot: WorldSnapshot | null;
  prevSnapshot: WorldSnapshot | null;
  selectedActor: string | null;
  onSelect: (id: string) => void;
}

const VALIDATORS = ['validator-0', 'validator-1', 'validator-2', 'validator-3'] as const;

export function ValidatorGrid({ snapshot, prevSnapshot, selectedActor, onSelect }: Props) {
  const [faults, setFaults] = useState<Record<string, boolean>>({
    'validator-0': false,
    'validator-1': false,
    'validator-2': false,
    'validator-3': false,
  });
  const [toggling, setToggling] = useState<string | null>(null);

  // Load initial fault state from backend
  useEffect(() => {
    getFaultState().then((state) => {
      if (Object.keys(state).length > 0) setFaults(state);
    }).catch(() => {/* backend not ready yet */});
  }, []);

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
  const quorumPossible = (4 - faultCount) >= 3; // need 3 of 4 for f=1

  return (
    <div className="flex flex-col gap-1 h-full">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-gray-500 uppercase tracking-widest">Validators (n=4, f=1)</span>
        <span className={`text-xs px-2 py-0.5 rounded-full ${quorumPossible ? 'bg-emerald-900 text-emerald-300' : 'bg-red-900 text-red-300'}`}>
          quorum {quorumPossible ? 'possible' : 'impossible'}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-1 flex-1">
        {VALIDATORS.map((vid) => {
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
              {/* Fault injection toggle */}
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
      {faultCount > 0 && (
        <div className="text-xs text-center text-gray-500 mt-1">
          {faultCount} fault{faultCount > 1 ? 's' : ''} injected — {4 - faultCount}/4 healthy
          {!quorumPossible && <span className="text-red-400 ml-1">(quorum impossible)</span>}
        </div>
      )}
    </div>
  );
}
