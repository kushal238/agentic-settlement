import { useState } from 'react';
import { Play, RotateCcw, AlertCircle, CheckCircle2, Loader2, XCircle } from 'lucide-react';
import { useSimStore } from '../store/simStore';
import { runSimulation } from '../sim/engine';
import { resetNonce, getCurrentNonce } from '../protocol/wallet';
import { reconfigureValidators } from '../protocol/api';
import { SCENARIOS } from '../sim/scenarios';
import type { ScenarioId } from '../sim/scenarios';

const F_OPTIONS = [1, 2, 3, 4, 5] as const;

export function Controls() {
  const status = useSimStore((s) => s.status);
  const error = useSimStore((s) => s.error);
  const reset = useSimStore((s) => s.reset);
  const snapshots = useSimStore((s) => s.snapshots);
  const f = useSimStore((s) => s.f);
  const setF = useSimStore((s) => s.setF);
  const scenario = useSimStore((s) => s.scenario);
  const setScenario = useSimStore((s) => s.setScenario);

  const [reconfiguring, setReconfiguring] = useState(false);
  const [resetting, setResetting] = useState(false);

  const isRunning = status === 'running';
  const isBusy = isRunning || reconfiguring || resetting;

  // Determine if quorum was met in the last simulation run
  const finalSnapshot = snapshots.length > 0 ? snapshots[snapshots.length - 1] : null;
  const quorumMet = finalSnapshot?.facilitator.phase === 'settled';

  function handleRun() {
    runSimulation();
  }

  async function handleReset() {
    setResetting(true);
    // Rebuild backend validators from genesis so their account nonces go back to 0,
    // matching the frontend wallet reset. Without this, the backend nonce diverges
    // after any successful settlement and the next happy path sends the wrong nonce.
    try { await reconfigureValidators(f); } catch { /* backend may not be running */ }
    reset();
    resetNonce();
    setResetting(false);
  }

  async function handleFChange(newF: number) {
    if (newF === f) return;
    setReconfiguring(true);
    try {
      await reconfigureValidators(newF);
      setF(newF);
      reset();
      resetNonce();
    } catch {
      // Backend may not be running yet; update UI state anyway so it's ready
      setF(newF);
      reset();
      resetNonce();
    } finally {
      setReconfiguring(false);
    }
  }

  function handleScenarioChange(id: ScenarioId) {
    setScenario(id);
    reset();
    resetNonce();
  }

  const n = 3 * f + 1;
  const selectedScenario = SCENARIOS.find((s) => s.id === scenario)!;

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 border-b border-gray-800 flex-wrap">
      {/* Brand */}
      <div className="flex items-center gap-2 shrink-0">
        <span className="text-lg font-bold text-white tracking-tight">FastSet</span>
        <span className="text-xs text-gray-500 px-2 py-0.5 rounded bg-gray-800">Agentic Micropayment Simulator</span>
      </div>

      <div className="w-px h-5 bg-gray-700 mx-1 shrink-0" />

      {/* Fault tolerance selector */}
      <div className="flex items-center gap-1.5 shrink-0">
        <span className="text-xs text-gray-500 whitespace-nowrap">f =</span>
        <div className="flex gap-0.5">
          {F_OPTIONS.map((fv) => (
            <button
              key={fv}
              onClick={() => handleFChange(fv)}
              disabled={isBusy}
              title={`f=${fv}: n=${3*fv+1} validators, quorum=${2*fv+1}`}
              className={`w-7 h-6 text-xs rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
                fv === f
                  ? 'bg-blue-600 text-white font-bold'
                  : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
              }`}
            >
              {fv}
            </button>
          ))}
        </div>
        <span className="text-xs text-gray-600 whitespace-nowrap">
          {reconfiguring ? (
            <Loader2 size={11} className="inline animate-spin text-blue-400" />
          ) : (
            <>(n={n}, q={2*f+1})</>
          )}
        </span>
      </div>

      <div className="w-px h-5 bg-gray-700 mx-1 shrink-0" />

      {/* Scenario selector */}
      <div className="flex items-center gap-1.5 shrink-0">
        <span className="text-xs text-gray-500 whitespace-nowrap">Scenario:</span>
        <select
          value={scenario}
          onChange={(e) => handleScenarioChange(e.target.value as ScenarioId)}
          disabled={isBusy}
          className="text-xs bg-gray-800 border border-gray-700 text-gray-200 rounded px-2 py-1 disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:border-blue-500 cursor-pointer"
        >
          {SCENARIOS.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
        {selectedScenario.failedCheck && (
          <span className="text-xs text-orange-400 hidden sm:inline">
            — {selectedScenario.failedCheck} fails
          </span>
        )}
      </div>

      {/* Status + actions pushed right */}
      <div className="flex items-center gap-2 ml-auto">
        {status === 'error' && error && (
          <div className="flex items-center gap-1.5 text-red-400 text-xs">
            <AlertCircle size={14} />
            <span className="max-w-xs truncate">{error}</span>
          </div>
        )}
        {status === 'done' && quorumMet && (
          <div className="flex items-center gap-1.5 text-green-400 text-xs">
            <CheckCircle2 size={14} />
            <span>Settlement complete</span>
          </div>
        )}
        {status === 'done' && !quorumMet && (
          <div className="flex items-center gap-1.5 text-orange-400 text-xs">
            <XCircle size={14} />
            <span>Quorum failed — no settlement</span>
          </div>
        )}
        {isRunning && (
          <div className="flex items-center gap-1.5 text-blue-400 text-xs">
            <Loader2 size={14} className="animate-spin" />
            <span>Running…</span>
          </div>
        )}

        <span className="text-xs text-gray-500 tabular-nums ml-2">
          nonce: {getCurrentNonce()}
        </span>

        <button
          onClick={handleReset}
          disabled={isBusy}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          title="Reset simulation and nonce (also restores backend to genesis)"
        >
          {resetting ? <Loader2 size={12} className="animate-spin" /> : <RotateCcw size={12} />}
          Reset
        </button>

        <button
          onClick={handleRun}
          disabled={isBusy}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {isRunning ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
          Run
        </button>
      </div>
    </div>
  );
}
