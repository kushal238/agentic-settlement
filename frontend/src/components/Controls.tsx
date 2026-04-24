import { Play, RotateCcw, AlertCircle, CheckCircle2, Loader2 } from 'lucide-react';
import { useSimStore } from '../store/simStore';
import { runSimulation } from '../sim/engine';
import { resetNonce, getCurrentNonce } from '../protocol/wallet';

export function Controls() {
  const status = useSimStore((s) => s.status);
  const error = useSimStore((s) => s.error);
  const reset = useSimStore((s) => s.reset);

  const isRunning = status === 'running';

  function handleRun() {
    runSimulation();
  }

  function handleReset() {
    reset();
    resetNonce();
  }

  return (
    <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-800">
      <div className="flex items-center gap-2">
        <span className="text-lg font-bold text-white tracking-tight">FastSet</span>
        <span className="text-xs text-gray-500 px-2 py-0.5 rounded bg-gray-800">Agentic Micropayment Simulator</span>
      </div>

      <div className="flex items-center gap-2 ml-auto">
        {status === 'error' && error && (
          <div className="flex items-center gap-1.5 text-red-400 text-xs">
            <AlertCircle size={14} />
            <span className="max-w-xs truncate">{error}</span>
          </div>
        )}
        {status === 'done' && (
          <div className="flex items-center gap-1.5 text-green-400 text-xs">
            <CheckCircle2 size={14} />
            <span>Settlement complete</span>
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
          disabled={isRunning}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          title="Reset simulation and nonce (also restart the backend)"
        >
          <RotateCcw size={12} />
          Reset
        </button>

        <button
          onClick={handleRun}
          disabled={isRunning}
          className="flex items-center gap-1.5 px-4 py-1.5 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {isRunning ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
          Run
        </button>
      </div>
    </div>
  );
}
