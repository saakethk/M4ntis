/** TradeCPU limits, from hardware/docs/tradecpu_full_specification.md section 1. */
export const NUM_STOCK_BUFFERS = 5;
export const NUM_VAR_SLOTS = 15;
/** Each buffer holds the last 30 ticks, so every lookback N is in ticks and capped by this. */
export const BUFFER_DEPTH = 30;
export const PROGRAM_WORDS = 512;

/** Bar size the backtester aggregates minute data into; one bar = one tick to the FPGA. */
export const RESOLUTIONS = [
  { value: '1m', label: '1 minute', minutes: 1 },
  { value: '5m', label: '5 minutes', minutes: 5 },
  { value: '15m', label: '15 minutes', minutes: 15 },
  { value: '30m', label: '30 minutes', minutes: 30 },
  { value: '1h', label: '1 hour', minutes: 60 },
  { value: '1d', label: '1 day', minutes: 390 },
] as const;

export type Resolution = (typeof RESOLUTIONS)[number]['value'];

const SESSION_MINUTES = 390;

/** Human-readable span of `ticks` bars at a resolution, in regular-session time. */
export function ticksToDuration(ticks: number, resolution: string): string {
  const r = RESOLUTIONS.find((x) => x.value === resolution);
  if (!r) return '';
  if (r.value === '1d') return `${ticks} trading day${ticks === 1 ? '' : 's'}`;
  const minutes = ticks * r.minutes;
  if (minutes < 60) return `${minutes} min`;
  if (minutes < SESSION_MINUTES) return `${+(minutes / 60).toFixed(1)} h`;
  return `${+(minutes / SESSION_MINUTES).toFixed(1)} sessions`;
}
