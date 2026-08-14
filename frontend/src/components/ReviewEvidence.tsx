import type { ReviewListing } from '../api/types';
import { formatMoneyDecimal } from '../formatting/decimal';
import { conditionLabel, skuDisplayName } from '../formatting/sku';
import { formatManilaTimestamp } from '../formatting/time';
import MetricReadout, { ReadoutList } from './MetricReadout';
import StatusIndicator from './StatusIndicator';
import type { Tone } from './StatusIndicator';
import styles from './ReviewEvidence.module.css';


function resolutionLabel(method: string): string {
  return method
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

// Confidence in how the SKU was reached, so the reviewer knows how much of the
// derived state to trust before confirming it.
function resolutionTone(method: string): Tone {
  if (method === 'unresolved') {
    return 'caution';
  }
  if (method === 'fuzzy_match') {
    return 'caution';
  }
  if (method === 'human_confirmed' || method === 'exact_alias') {
    return 'positive';
  }
  return 'neutral';
}

function valueOrUnavailable(value: string | null): string {
  return value === null || value === '' ? 'Unavailable' : value;
}

export default function ReviewEvidence({ review }: { review: ReviewListing }) {
  const raw = review.raw_evidence;
  const derived = review.derived_listing;

  return (
    <div className={styles.evidence}>
      {/* Immutable source text: recessed and monospaced, never editable. */}
      <section className={`pw-well ${styles.region} ${styles.rawRegion}`} aria-label="Raw source evidence">
        <div className={styles.regionHead}>
          <h2>Raw source evidence</h2>
          <span className={styles.sealTag}>Immutable</span>
        </div>
        <ReadoutList className={styles.regionList}>
          <MetricReadout label="Raw title" mono className={styles.wideReadout}>
            {raw.raw_title}
          </MetricReadout>
          <MetricReadout label="Normalized title" mono className={styles.wideReadout}>
            {raw.normalised_title}
          </MetricReadout>
          <MetricReadout label="Raw price text" mono>{raw.raw_price_text}</MetricReadout>
          <MetricReadout label="Source" mono>{raw.source.name}</MetricReadout>
          <MetricReadout label="Occurred" mono>
            {formatManilaTimestamp(raw.occurred_at)}
          </MetricReadout>
          <MetricReadout label="Fetched" mono>
            {formatManilaTimestamp(raw.fetched_at)}
          </MetricReadout>
        </ReadoutList>
        <p className={styles.sourceLink}>
          <a href={raw.url}>Open original listing</a>
        </p>
      </section>

      <section className={`pw-well-soft ${styles.region}`} aria-label="Derived listing state">
        <div className={styles.regionHead}>
          <h2>Derived listing state</h2>
        </div>
        <ReadoutList className={styles.regionList}>
          <MetricReadout label="Price" size="md" mono>
            {formatMoneyDecimal(derived.price)}
          </MetricReadout>
          <MetricReadout label="Condition" mono>
            {conditionLabel(derived.condition)}
          </MetricReadout>
          <MetricReadout label="Resolution" mono lamp={resolutionTone(derived.resolution_method)}>
            {resolutionLabel(derived.resolution_method)}
          </MetricReadout>
          <MetricReadout label="Confidence" mono>{derived.resolution_confidence}</MetricReadout>
          <MetricReadout label="Location" mono>
            {valueOrUnavailable(derived.location)}
          </MetricReadout>
          <MetricReadout label="Resolved" mono>
            {formatManilaTimestamp(derived.resolved_at)}
          </MetricReadout>
          <MetricReadout label="Observed" mono>
            {formatManilaTimestamp(derived.observed_at)}
          </MetricReadout>
          <MetricReadout label="Price kind" mono>
            {valueOrUnavailable(derived.price_kind)}
          </MetricReadout>
          <MetricReadout label="Trade side" mono>
            {valueOrUnavailable(derived.trade_side)}
          </MetricReadout>
          <MetricReadout label="Reviewed unresolved" mono>
            {formatManilaTimestamp(derived.reviewed_unresolved_at)}
          </MetricReadout>
        </ReadoutList>
      </section>

      <section className={`pw-well-soft ${styles.region} ${styles.skuRegion}`} aria-label="Current curated SKU">
        <div className={styles.regionHead}>
          <h2>Current curated SKU</h2>
        </div>
        {review.current_sku === null ? (
          <>
            <StatusIndicator tone="caution">Unassigned</StatusIndicator>
            <p className={styles.skuValue}>No SKU currently assigned.</p>
          </>
        ) : (
          <>
            <StatusIndicator tone="positive">Assigned</StatusIndicator>
            <p className={styles.skuValue}>{skuDisplayName(review.current_sku)}</p>
          </>
        )}
      </section>
    </div>
  );
}
