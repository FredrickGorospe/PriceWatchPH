import type { PricePoint } from '../api/types';


export interface PriceHistoryChartPoint {
  day: string;
  condition: PricePoint['condition'];
  median: number;
  p25: number;
  p75: number;
  range: [number, number];
  evidence: PricePoint;
}

export function toChartPoint(evidence: PricePoint): PriceHistoryChartPoint {
  // Binary numbers are confined to chart geometry; evidence strings stay attached.
  const p25 = Number(evidence.p25);
  const p75 = Number(evidence.p75);

  return {
    day: evidence.day,
    condition: evidence.condition,
    median: Number(evidence.median),
    p25,
    p75,
    range: [p25, p75],
    evidence,
  };
}
