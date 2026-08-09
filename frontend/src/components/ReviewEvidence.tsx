import type { ReviewListing } from '../api/types';
import { formatMoneyDecimal } from '../formatting/decimal';
import { conditionLabel, skuDisplayName } from '../formatting/sku';
import { formatManilaTimestamp } from '../formatting/time';
import styles from './ReviewEvidence.module.css';


function resolutionLabel(method: string): string {
  return method
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function valueOrUnavailable(value: string | null): string {
  return value === null || value === '' ? 'Unavailable' : value;
}

export default function ReviewEvidence({ review }: { review: ReviewListing }) {
  const raw = review.raw_evidence;
  const derived = review.derived_listing;

  return (
    <div className={styles.evidence}>
      <section className={styles.region} aria-label="Raw source evidence">
        <h2>Raw source evidence</h2>
        <dl>
          <div><dt>Raw title</dt><dd>{raw.raw_title}</dd></div>
          <div><dt>Normalized title</dt><dd>{raw.normalised_title}</dd></div>
          <div><dt>Raw price text</dt><dd>{raw.raw_price_text}</dd></div>
          <div><dt>Source</dt><dd>{raw.source.name}</dd></div>
          <div><dt>Occurred</dt><dd>{formatManilaTimestamp(raw.occurred_at)}</dd></div>
          <div><dt>Fetched</dt><dd>{formatManilaTimestamp(raw.fetched_at)}</dd></div>
          <div><dt>Source listing</dt><dd><a href={raw.url}>Open original listing</a></dd></div>
        </dl>
      </section>

      <section className={styles.region} aria-label="Derived listing state">
        <h2>Derived listing state</h2>
        <dl>
          <div><dt>Price</dt><dd>{formatMoneyDecimal(derived.price)}</dd></div>
          <div><dt>Condition</dt><dd>{conditionLabel(derived.condition)}</dd></div>
          <div><dt>Location</dt><dd>{valueOrUnavailable(derived.location)}</dd></div>
          <div><dt>Resolution</dt><dd>{resolutionLabel(derived.resolution_method)}</dd></div>
          <div><dt>Confidence</dt><dd>{derived.resolution_confidence}</dd></div>
          <div><dt>Resolved</dt><dd>{formatManilaTimestamp(derived.resolved_at)}</dd></div>
          <div><dt>Observed</dt><dd>{formatManilaTimestamp(derived.observed_at)}</dd></div>
          <div><dt>Price kind</dt><dd>{valueOrUnavailable(derived.price_kind)}</dd></div>
          <div><dt>Trade side</dt><dd>{valueOrUnavailable(derived.trade_side)}</dd></div>
          <div>
            <dt>Reviewed unresolved</dt>
            <dd>{formatManilaTimestamp(derived.reviewed_unresolved_at)}</dd>
          </div>
        </dl>
      </section>

      <section className={styles.region} aria-label="Current curated SKU">
        <h2>Current curated SKU</h2>
        {review.current_sku === null ? (
          <p>No SKU currently assigned.</p>
        ) : (
          <p>{skuDisplayName(review.current_sku)}</p>
        )}
      </section>
    </div>
  );
}
