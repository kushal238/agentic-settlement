import { create } from 'zustand';
import type { SimEvent, WorldSnapshot } from '../sim/types';
import { eventIndexAtTime } from '../sim/timeline';

export type SimStatus = 'idle' | 'running' | 'done' | 'error';
export type Speed = 0.25 | 1 | 4 | 16;

interface SimStore {
  events: SimEvent[];
  snapshots: WorldSnapshot[];  // snapshots[i] = world state after events[i] completes
  epoch: number;               // t_start_us of first event
  currentTime: number;         // µs from epoch
  playheadIndex: number;       // last event with t_start_us - epoch <= currentTime
  playing: boolean;
  speed: Speed;
  status: SimStatus;
  error: string | null;

  setEvents(events: SimEvent[], snapshots: WorldSnapshot[]): void;
  setCurrentTime(t: number): void;
  setPlayheadIndex(i: number): void;
  play(): void;
  pause(): void;
  setSpeed(s: Speed): void;
  stepForward(): void;
  stepBackward(): void;
  reset(): void;
  setStatus(s: SimStatus): void;
  setError(e: string): void;
}

export const useSimStore = create<SimStore>((set, get) => ({
  events: [],
  snapshots: [],
  epoch: 0,
  currentTime: 0,
  playheadIndex: -1,
  playing: false,
  speed: 1,
  status: 'idle',
  error: null,

  setEvents(events, snapshots) {
    const epoch = events.length > 0 ? events[0]!.t_start_us : 0;
    set({ events, snapshots, epoch, currentTime: 0, playheadIndex: -1 });
  },

  setCurrentTime(t) {
    const { events, epoch } = get();
    const playheadIndex = eventIndexAtTime(events, epoch, t);
    set({ currentTime: t, playheadIndex });
  },

  setPlayheadIndex(i) {
    const { events, epoch } = get();
    if (i < 0 || i >= events.length) return;
    const t = events[i]!.t_start_us - epoch;
    set({ currentTime: t, playheadIndex: i });
  },

  play() {
    set({ playing: true });
  },

  pause() {
    set({ playing: false });
  },

  setSpeed(s) {
    set({ speed: s });
  },

  stepForward() {
    const { playheadIndex, events } = get();
    const next = Math.min(playheadIndex + 1, events.length - 1);
    get().setPlayheadIndex(next);
  },

  stepBackward() {
    const { playheadIndex } = get();
    const prev = Math.max(playheadIndex - 1, 0);
    get().setPlayheadIndex(prev);
  },

  reset() {
    set({
      events: [],
      snapshots: [],
      epoch: 0,
      currentTime: 0,
      playheadIndex: -1,
      playing: false,
      status: 'idle',
      error: null,
    });
  },

  setStatus(s) {
    set({ status: s });
  },

  setError(e) {
    set({ error: e, status: 'error', playing: false });
  },
}));
