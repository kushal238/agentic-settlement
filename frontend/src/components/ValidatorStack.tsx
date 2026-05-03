import { useState } from 'react';
import { ChevronDown, ChevronUp, AlertTriangle } from 'lucide-react';
import type { WorldSnapshot, ValidatorPhase } from '../sim/types';

interface Props {
  validatorIds: string[];
  groupIndex: number;
  snapshot: WorldSnapshot | null;
  prevSnapshot: WorldSnapshot | null;
  selectedActor: string | null;
  onSelect: (id: string) => void;
  faults: Record<string, boolean>;
  onToggleFault: (vid: string) => void;
  toggling: string | null;
}

const PHASE_COLORS: Record<ValidatorPhase, { border: string; bg: string; text: string; dot: string }> = {
  idle:      { border: 'border-gray-700', bg: 'bg-gray-900', text: 'text-gray-400', dot: 'bg-gray-600' },
  verifying: { border: 'border-yellow-700', bg: 'bg-yellow-950/20', text: 'text-yellow-300', dot: 'bg-yellow-500' },
  certified: { border: 'border-green-700', bg: 'bg-green-950/20', text: 'text-green-300', dot: 'bg-green-500' },
  rejected:  { border: 'border-red-800', bg: 'bg-red-950/20', text: 'text-red-400', dot: 'bg-red-500' },
  settling:  { border: 'border-purple-700', bg: 'bg-purple-950/20', text: 'text-purple-300', dot: 'bg-purple-500' },
  settled:   { border: 'border-emerald-700', bg: 'bg-emerald-950/20', text: 'text-emerald-300', dot: 'bg-emerald-500' },
  dead:      { border: 'border-gray-800', bg: 'bg-gray-900/50', text: 'text-gray-600', dot: 'bg-gray-700' },
  divergent: { border: 'border-orange-700', bg: 'bg-orange-950/20', text: 'text-orange-300', dot: 'bg-orange-500' },
};

function getPhase(vid: string, snapshot: WorldSnapshot | null): ValidatorPhase {
  return snapshot?.validators[vid]?.phase ?? 'idle';
}

function groupSummary(validatorIds: string[], snapshot: WorldSnapshot | null) {
  const counts: Partial<Record<ValidatorPhase, number>> = {};
  for (const vid of validatorIds) {
    const p = getPhase(vid, snapshot);
    counts[p] = (counts[p] ?? 0) + 1;
  }
  return counts;
}

/** Dominant phase for border/bg colour of the whole stack card */
function dominantPhase(counts: Partial<Record<ValidatorPhase, number>>): ValidatorPhase {
  const priority: ValidatorPhase[] = ['divergent', 'settled', 'settling', 'rejected', 'dead', 'certified', 'verifying', 'idle'];
  for (const p of priority) {
    if (counts[p]) return p;
  }
  return 'idle';
}

export function ValidatorStack({
  validatorIds,
  groupIndex,
  snapshot,
  prevSnapshot,
  selectedActor,
  onSelect,
  faults,
  onToggleFault,
  toggling,
}: Props) {
  const [expanded, setExpanded] = useState(false);

  const startIdx = validatorIds[0]?.replace('validator-', '') ?? '?';
  const endIdx = validatorIds[validatorIds.length - 1]?.replace('validator-', '') ?? '?';
  const rangeLabel = validatorIds.length === 1 ? `V${startIdx}` : `V${startIdx}–V${endIdx}`;

  const counts = groupSummary(validatorIds, snapshot);
  const dom = dominantPhase(counts);
  const colors = PHASE_COLORS[dom];

  const hasFault = validatorIds.some((v) => faults[v]);
  const hasDivergent = (counts['divergent'] ?? 0) > 0;
  const isAnySelected = validatorIds.some((v) => v === selectedActor);

  const STACK_DEPTH = Math.min(validatorIds.length - 1, 3);

  return (
    <div className="relative">
      {/* Background stack cards (depth illusion) */}
      {Array.from({ length: STACK_DEPTH }, (_, d) => d + 1).reverse().map((depth) => (
        <div
          key={depth}
          className={`absolute rounded border ${colors.border} bg-gray-900`}
          style={{
            top: depth * 4,
            left: depth * 4,
            right: -depth * 4,
            bottom: -depth * 4,
            zIndex: 10 - depth,
          }}
        />
      ))}

      {/* Front card */}
      <div
        className={`relative panel cursor-pointer transition-all duration-150 ${colors.bg} ${colors.border} ${
          isAnySelected ? 'ring-1 ring-blue-500' : hasFault ? 'border-red-800 bg-red-950/30' : ''
        }`}
        style={{ zIndex: 10 + STACK_DEPTH }}
        onClick={() => {
          if (validatorIds.length === 1) {
            onSelect(validatorIds[0]!);
          } else {
            setExpanded((v) => !v);
          }
        }}
      >
        {/* Header */}
        <div className="panel-header flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-mono">{rangeLabel}</span>
            <span className="text-xs text-gray-600">({validatorIds.length})</span>
            {hasDivergent && (
              <span title="State divergence detected">
                <AlertTriangle size={11} className="text-orange-400" />
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <span className={`text-xs px-1.5 py-0.5 rounded-full font-bold ${colors.bg} ${colors.text} border ${colors.border}`}>
              {dom}
            </span>
            {validatorIds.length > 1 && (
              <button
                onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v); }}
                className="text-gray-500 hover:text-gray-300 ml-0.5"
              >
                {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </button>
            )}
          </div>
        </div>

        {/* Summary badges */}
        <div className="flex flex-wrap gap-1 px-2 py-1.5 text-xs">
          {(Object.entries(counts) as [ValidatorPhase, number][])
            .filter(([, count]) => count > 0)
            .map(([phase, count]) => {
              const c = PHASE_COLORS[phase];
              return (
                <span key={phase} className={`px-1.5 py-0.5 rounded ${c.bg} ${c.text} border ${c.border}`}>
                  {count} {phase}
                </span>
              );
            })}
        </div>
      </div>

      {/* Expanded individual validator rows */}
      {expanded && (
        <div
          className="absolute left-0 right-0 bg-gray-900 border border-gray-700 rounded shadow-xl mt-1 overflow-hidden"
          style={{ zIndex: 100 + groupIndex * 10 }}
        >
          {validatorIds.map((vid) => {
            const phase = getPhase(vid, snapshot);
            const prevPhase = getPhase(vid, prevSnapshot);
            const pc = PHASE_COLORS[phase];
            const isFaulty = faults[vid] ?? false;
            const isToggling = toggling === vid;
            const bal = snapshot?.validators[vid]?.balance_of_agent;
            const nonce = snapshot?.validators[vid]?.nonce_for_agent;
            return (
              <div
                key={vid}
                className={`flex items-center justify-between px-2 py-1.5 text-xs border-b border-gray-800 cursor-pointer hover:bg-gray-800 ${
                  selectedActor === vid ? 'bg-gray-800' : ''
                } ${isFaulty ? 'bg-red-950/20' : ''}`}
                onClick={(e) => { e.stopPropagation(); onSelect(vid); }}
              >
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${pc.dot} ${phase !== prevPhase ? 'animate-pulse' : ''}`} />
                  <span className="text-gray-300 font-mono">{vid}</span>
                  {bal != null && (
                    <span className="text-gray-600 tabular-nums">bal:{bal}</span>
                  )}
                  {nonce != null && (
                    <span className="text-gray-600 tabular-nums">n:{nonce}</span>
                  )}
                </div>
                <div className="flex items-center gap-1.5">
                  <span className={`px-1.5 py-0.5 rounded-full font-bold ${pc.bg} ${pc.text} border ${pc.border}`}>
                    {phase}
                  </span>
                  <button
                    onClick={(e) => { e.stopPropagation(); onToggleFault(vid); }}
                    disabled={isToggling}
                    title={isFaulty ? 'Clear fault' : 'Inject Byzantine fault'}
                    className={`px-1 py-0.5 rounded text-xs transition-colors disabled:opacity-40 ${
                      isFaulty
                        ? 'bg-red-900/40 text-red-400 hover:text-red-300'
                        : 'bg-transparent text-gray-600 hover:text-yellow-400 hover:bg-yellow-900/20'
                    }`}
                  >
                    {isFaulty ? '⚡off' : '⚡'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
