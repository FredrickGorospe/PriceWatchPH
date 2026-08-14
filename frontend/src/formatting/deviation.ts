import type { DecimalString } from '../api/types';


export interface BaselineDeviation {
  /** Signed percentage difference, for tone selection only. */
  percent: number;
  /** Rendered value, e.g. `-22.5%`. */
  text: string;
}

/*
 * A presentation-only comparison of two persisted Decimals.
 *
 * Binary numbers are confined to this display value exactly as they are in
 * chart geometry: the authoritative Decimal strings are still rendered
 * verbatim beside it, and nothing derived here is ever sent back to the API.
 */
export function deviationFromBaseline(
  price: DecimalString | null,
  baselineMedian: DecimalString | null,
): BaselineDeviation | null {
  if (price === null || baselineMedian === null) {
    return null;
  }

  const observed = Number(price);
  const baseline = Number(baselineMedian);

  if (!Number.isFinite(observed) || !Number.isFinite(baseline) || baseline === 0) {
    return null;
  }

  const percent = ((observed - baseline) / baseline) * 100;
  const magnitude = Math.abs(percent).toFixed(1);
  const sign = Number(magnitude) === 0 ? '' : percent < 0 ? '-' : '+';

  return { percent, text: `${sign}${magnitude}%` };
}
