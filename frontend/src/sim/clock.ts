export function monotonic(): number {
  return performance.now() * 1000;
}

export interface Timed<T> {
  result: T;
  t_start_us: number;
  t_end_us: number;
}

export async function measureAsync<T>(fn: () => Promise<T>): Promise<Timed<T>> {
  const t_start_us = monotonic();
  const result = await fn();
  const t_end_us = monotonic();
  return { result, t_start_us, t_end_us };
}
