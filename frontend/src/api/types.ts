export type DecimalString = string;
export type ISODateString = string;
export type UTCDateTimeString = string;

export type SkuCategory =
  | 'gpu'
  | 'cpu'
  | 'ram'
  | 'mobo'
  | 'monitor'
  | 'peripheral';

export type ListingCondition = 'new' | 'like_new' | 'used' | 'for_parts';

export interface SkuSummary {
  id: number;
  brand: string;
  model: string;
  variant: string;
  category: SkuCategory;
}

export interface Sku extends SkuSummary {
  launch_msrp: DecimalString;
  launch_date: ISODateString;
}

export interface Listing {
  id: number;
  sku_id: number | null;
  price: DecimalString | null;
  condition: ListingCondition | null;
  resolution_confidence: DecimalString;
  resolution_method: string;
  resolved_at: UTCDateTimeString;
  observed_at: UTCDateTimeString | null;
  price_kind: string | null;
  trade_side: string | null;
}

export interface PricePoint {
  id: number;
  sku_id: number;
  condition: ListingCondition;
  day: ISODateString;
  median: DecimalString;
  p25: DecimalString;
  p75: DecimalString;
  n_listings: number;
  mad: DecimalString | null;
  window_start_day: ISODateString | null;
  window_end_day: ISODateString | null;
  calculated_at: UTCDateTimeString | null;
  calculation_contract_version: string | null;
}

export interface DealFlag {
  id: number;
  sku: SkuSummary;
  listing: Listing;
  baseline_pricepoint: PricePoint;
  score: DecimalString;
  reason: string;
  flagged_at: UTCDateTimeString;
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
