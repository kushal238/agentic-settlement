import { useSimStore } from '../store/simStore';
import type { SimEvent, WorldSnapshot } from '../sim/types';

interface Props {
  selectedEventId: string | null;
  hoveredActor: string | null;
}

function JsonView({ data }: { data: unknown }) {
  if (data == null) return <span className="text-gray-500">null</span>;
  return (
    <pre className="text-xs text-gray-300 whitespace-pre-wrap break-all">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

function SnapshotView({ actor, snapshot }: { actor: string; snapshot: WorldSnapshot }) {
  let data: unknown;
  if (actor === 'client') data = snapshot.client;
  else if (actor === 'resource-server') data = snapshot.resourceServer;
  else if (actor === 'facilitator') data = snapshot.facilitator;
  else data = snapshot.validators[actor];
  return <JsonView data={data} />;
}

export function Inspector({ selectedEventId, hoveredActor }: Props) {
  const events = useSimStore((s) => s.events);
  const snapshots = useSimStore((s) => s.snapshots);
  const playheadIndex = useSimStore((s) => s.playheadIndex);

  const selectedEvent: SimEvent | undefined = events.find((e) => e.id === selectedEventId);
  const currentSnapshot = playheadIndex >= 0 && playheadIndex < snapshots.length
    ? snapshots[playheadIndex]
    : null;

  const showActor = hoveredActor && currentSnapshot;

  return (
    <div className="panel flex flex-col overflow-hidden h-full">
      <div className="panel-header">Inspector</div>
      <div className="flex-1 overflow-y-auto p-3 text-xs">
        {showActor ? (
          <>
            <div className="text-gray-400 mb-2 font-bold uppercase tracking-widest">{hoveredActor}</div>
            <SnapshotView actor={hoveredActor} snapshot={currentSnapshot!} />
          </>
        ) : selectedEvent ? (
          <>
            <div className="text-gray-400 mb-1 font-bold uppercase tracking-widest">Event</div>
            <div className="text-blue-300 mb-2 font-bold">{selectedEvent.label}</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs mb-3">
              <span className="text-gray-500">kind</span><span className="text-gray-200">{selectedEvent.kind}</span>
              <span className="text-gray-500">step</span><span className="text-gray-200">{selectedEvent.step}</span>
              <span className="text-gray-500">from</span><span className="text-gray-200">{selectedEvent.from}</span>
              <span className="text-gray-500">to</span><span className="text-gray-200">{selectedEvent.to ?? '—'}</span>
              <span className="text-gray-500">outcome</span>
              <span className={selectedEvent.outcome === 'ok' ? 'text-green-400' : selectedEvent.outcome === 'error' ? 'text-red-400' : 'text-gray-400'}>
                {selectedEvent.outcome ?? '—'}
              </span>
              <span className="text-gray-500">duration</span>
              <span className="text-gray-200">{((selectedEvent.t_end_us - selectedEvent.t_start_us) / 1000).toFixed(3)}ms</span>
            </div>
            {selectedEvent.payload != null && (
              <>
                <div className="text-gray-400 mb-1 font-bold uppercase tracking-widest text-xs">Payload</div>
                <JsonView data={selectedEvent.payload} />
              </>
            )}
          </>
        ) : (
          <div className="text-gray-600 italic">
            Click a log entry or hover an actor to inspect
          </div>
        )}
      </div>
    </div>
  );
}
