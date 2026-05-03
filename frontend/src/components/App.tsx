import { useState, useEffect, useRef } from 'react';
import { Controls } from './Controls';
import { ActorPanel } from './ActorPanel';
import { ValidatorGrid } from './ValidatorGrid';
import { FlowCanvas } from './FlowCanvas';
import { SimpleTopology } from './SimpleTopology';
import { SwimlaneView } from './SwimlaneView';
import { Timeline } from './Timeline';
import { MethodLog } from './MethodLog';
import { Inspector } from './Inspector';
import { useSimStore } from '../store/simStore';

// Playback loop — advances currentTime via requestAnimationFrame
function usePlaybackLoop() {
  const lastRealRef = useRef<number | null>(null);

  useEffect(() => {
    let rafId: number;

    function tick(realNow: number) {
      const { playing, speed, currentTime, events, epoch } = useSimStore.getState();

      if (playing && lastRealRef.current !== null) {
        const realDeltaMs = realNow - lastRealRef.current;
        const simDeltaUs = realDeltaMs * 1000 * speed;
        const maxTime = events.length > 0 ? events[events.length - 1]!.t_end_us - epoch : 0;
        const newTime = currentTime + simDeltaUs;

        if (newTime >= maxTime) {
          useSimStore.getState().setCurrentTime(maxTime);
          useSimStore.getState().pause();
          lastRealRef.current = null;
        } else {
          useSimStore.getState().setCurrentTime(newTime);
        }
      }

      if (playing) {
        lastRealRef.current = realNow;
      } else {
        lastRealRef.current = null;
      }

      rafId = requestAnimationFrame(tick);
    }

    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, []);
}

export function App() {
  usePlaybackLoop();

  const snapshots = useSimStore((s) => s.snapshots);
  const playheadIndex = useSimStore((s) => s.playheadIndex);

  const currentSnapshot = playheadIndex >= 0 && playheadIndex < snapshots.length
    ? snapshots[playheadIndex] ?? null
    : null;
  const prevSnapshot = playheadIndex > 0 && (playheadIndex - 1) < snapshots.length
    ? snapshots[playheadIndex - 1] ?? null
    : null;

  const [selectedActor, setSelectedActor] = useState<string | null>(null);
  const [hoveredActor, setHoveredActor] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const viewMode = useSimStore((s) => s.viewMode);

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-gray-950 font-mono">
      {/* Top bar */}
      <Controls />

      {/* Top visualization — simple, sequence, or detailed */}
      {viewMode === 'simple' ? (
        <div className="px-4 pt-2 pb-1" style={{ minHeight: 220 }}>
          <SimpleTopology
            snapshot={currentSnapshot}
            selectedActor={selectedActor}
            onSelectActor={setSelectedActor}
            onHoverActor={setHoveredActor}
          />
        </div>
      ) : viewMode === 'sequence' ? (
        <SwimlaneView />
      ) : (
        /* Detailed: original actor band + flow canvas */
        <div className="relative px-4 pt-3 pb-1" style={{ minHeight: 220 }}>
          <div className="grid grid-cols-4 gap-2 relative z-10">
            <div
              onMouseEnter={() => setHoveredActor('client')}
              onMouseLeave={() => setHoveredActor(null)}
            >
              <ActorPanel
                actorId="client"
                snapshot={currentSnapshot}
                prevSnapshot={prevSnapshot}
                selected={selectedActor === 'client'}
                onClick={() => setSelectedActor('client')}
              />
            </div>
            <div
              onMouseEnter={() => setHoveredActor('resource-server')}
              onMouseLeave={() => setHoveredActor(null)}
            >
              <ActorPanel
                actorId="resource-server"
                snapshot={currentSnapshot}
                prevSnapshot={prevSnapshot}
                selected={selectedActor === 'resource-server'}
                onClick={() => setSelectedActor('resource-server')}
              />
            </div>
            <div
              onMouseEnter={() => setHoveredActor('facilitator')}
              onMouseLeave={() => setHoveredActor(null)}
            >
              <ActorPanel
                actorId="facilitator"
                snapshot={currentSnapshot}
                prevSnapshot={prevSnapshot}
                selected={selectedActor === 'facilitator'}
                onClick={() => setSelectedActor('facilitator')}
              />
            </div>
            <ValidatorGrid
              snapshot={currentSnapshot}
              prevSnapshot={prevSnapshot}
              selectedActor={selectedActor}
              onSelect={setSelectedActor}
            />
          </div>

          {/* SVG flow canvas overlay */}
          <div className="absolute inset-0 pointer-events-none z-20 px-4 pt-3 pb-1">
            <FlowCanvas />
          </div>
        </div>
      )}

      {/* Timeline */}
      <div className="px-4 py-1">
        <Timeline />
      </div>

      {/* Log + Inspector */}
      <div className="flex-1 grid grid-cols-[1fr_320px] gap-2 px-4 pb-3 min-h-0">
        <MethodLog
          onSelect={setSelectedEventId}
          selectedEventId={selectedEventId}
        />
        <Inspector
          selectedEventId={selectedEventId}
          hoveredActor={hoveredActor}
        />
      </div>
    </div>
  );
}
