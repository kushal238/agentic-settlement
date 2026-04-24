import { motion, AnimatePresence } from 'framer-motion';
import type { WorldSnapshot } from '../sim/types';

interface Props {
  actorId: string;
  snapshot: WorldSnapshot | null;
  prevSnapshot: WorldSnapshot | null;
  selected?: boolean;
  faulty?: boolean;
  onClick?: () => void;
}

function changed<T>(prev: T, curr: T): boolean {
  return JSON.stringify(prev) !== JSON.stringify(curr);
}

function FieldRow({ label, value, highlight }: { label: string; value: string; highlight: boolean }) {
  return (
    <div className={`flex justify-between gap-2 px-3 py-1 rounded transition-colors duration-300 ${highlight ? 'bg-yellow-500/20 text-yellow-300' : ''}`}>
      <span className="text-gray-400 shrink-0">{label}</span>
      <span className="text-right truncate font-mono text-xs">{value}</span>
    </div>
  );
}

function PhaseChip({ phase }: { phase: string }) {
  const colors: Record<string, string> = {
    idle: 'bg-gray-700 text-gray-300',
    collecting: 'bg-blue-900 text-blue-300',
    verifying: 'bg-yellow-900 text-yellow-300',
    certified: 'bg-green-900 text-green-300',
    rejected: 'bg-red-900 text-red-300',
    settling: 'bg-purple-900 text-purple-300',
    settled: 'bg-emerald-900 text-emerald-300',
    dead: 'bg-gray-800 text-gray-500',
    evaluating: 'bg-orange-900 text-orange-300',
    failed: 'bg-red-900 text-red-400',
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-bold ${colors[phase] ?? 'bg-gray-700 text-gray-300'}`}>
      {phase}
    </span>
  );
}

export function ActorPanel({ actorId, snapshot, prevSnapshot, selected, faulty, onClick }: Props) {
  const isValidator = actorId.startsWith('validator-');
  const title = actorId === 'client' ? 'Client / Agent'
    : actorId === 'resource-server' ? 'Resource Server'
    : actorId === 'facilitator' ? 'Facilitator'
    : actorId.replace('validator-', 'Validator ');

  const renderFields = () => {
    if (!snapshot) return null;

    if (actorId === 'client') {
      const c = snapshot.client;
      const p = prevSnapshot?.client;
      return (
        <>
          <FieldRow label="nonce" value={String(c.nonce)} highlight={!!p && changed(p.nonce, c.nonce)} />
          <FieldRow label="balance" value={String(c.balance)} highlight={!!p && changed(p.balance, c.balance)} />
          <FieldRow label="claim" value={c.pending_claim ?? '—'} highlight={!!p && changed(p.pending_claim, c.pending_claim)} />
          <FieldRow label="proof quorum" value={c.last_proof_quorum != null ? String(c.last_proof_quorum) : '—'} highlight={!!p && changed(p.last_proof_quorum, c.last_proof_quorum)} />
        </>
      );
    }

    if (actorId === 'resource-server') {
      const r = snapshot.resourceServer;
      const p = prevSnapshot?.resourceServer;
      return (
        <>
          <FieldRow label="recipient" value={r.recipient} highlight={false} />
          <FieldRow label="amount" value={String(r.required_amount)} highlight={false} />
          <FieldRow label="status" value={r.last_status != null ? String(r.last_status) : '—'} highlight={!!p && changed(p.last_status, r.last_status)} />
        </>
      );
    }

    if (actorId === 'facilitator') {
      const f = snapshot.facilitator;
      const p = prevSnapshot?.facilitator;
      return (
        <>
          <FieldRow label="f" value={String(f.f)} highlight={false} />
          <FieldRow label="quorum (2f+1)" value={String(f.quorum_threshold)} highlight={false} />
          <FieldRow label="certs" value={String(f.certificates_collected)} highlight={!!p && changed(p.certificates_collected, f.certificates_collected)} />
          <div className="flex justify-between px-3 py-1">
            <span className="text-gray-400">phase</span>
            <PhaseChip phase={f.phase} />
          </div>
        </>
      );
    }

    if (isValidator) {
      const v = snapshot.validators[actorId];
      const pv = prevSnapshot?.validators[actorId];
      if (!v) return null;
      return (
        <>
          <FieldRow label="nonce" value={v.nonce_for_agent != null ? String(v.nonce_for_agent) : '—'} highlight={!!pv && changed(pv.nonce_for_agent, v.nonce_for_agent)} />
          <FieldRow label="balance" value={v.balance_of_agent != null ? String(v.balance_of_agent) : '—'} highlight={!!pv && changed(pv.balance_of_agent, v.balance_of_agent)} />
          <div className="flex justify-between px-3 py-1">
            <span className="text-gray-400">phase</span>
            <PhaseChip phase={v.phase} />
          </div>
        </>
      );
    }

    return null;
  };

  return (
    <motion.div
      layout
      className={`panel flex flex-col min-h-[140px] cursor-pointer transition-all duration-150 ${
        faulty ? 'border-red-800 bg-red-950/30' : selected ? 'ring-1 ring-blue-500' : 'hover:border-gray-500'
      }`}
      onClick={onClick}
    >
      <div className="panel-header flex items-center justify-between">
        <span>{title}</span>
        {snapshot && isValidator && <PhaseChip phase={snapshot.validators[actorId]?.phase ?? 'idle'} />}
        {snapshot && actorId === 'facilitator' && <PhaseChip phase={snapshot.facilitator.phase} />}
      </div>
      <div className="flex flex-col gap-0.5 py-2 text-xs">
        <AnimatePresence mode="sync">
          {snapshot ? (
            <motion.div
              key="fields"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex flex-col gap-0.5"
            >
              {renderFields()}
            </motion.div>
          ) : (
            <motion.div
              key="empty"
              className="px-3 text-gray-600 italic"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
            >
              idle
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
