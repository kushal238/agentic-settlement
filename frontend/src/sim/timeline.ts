import { scaleLinear } from 'd3-scale';
import type { ScaleLinear } from 'd3-scale';
import type { SimEvent } from './types';

export type TimeScale = ScaleLinear<number, number>;

export function buildTimelineScale(events: SimEvent[], width: number): TimeScale {
  if (events.length === 0) return scaleLinear().domain([0, 1]).range([0, width]);
  const t0 = events[0]!.t_start_us;
  const t1 = events[events.length - 1]!.t_end_us;
  return scaleLinear()
    .domain([0, t1 - t0])
    .range([0, width])
    .clamp(true);
}

export function eventIndexAtTime(events: SimEvent[], epoch: number, currentTime: number): number {
  let idx = -1;
  for (let i = 0; i < events.length; i++) {
    if (events[i]!.t_start_us - epoch <= currentTime) idx = i;
    else break;
  }
  return idx;
}
