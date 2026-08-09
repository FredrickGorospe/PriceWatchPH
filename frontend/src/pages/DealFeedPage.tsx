import { useEffect, useState } from 'react';
import { Link } from 'react-router';

import { ApiError, getDealFlagPage, isCancelledRequest } from '../api/client';
import type { DealFlag, Page } from '../api/types';
import { AccessRequiredState, RequestFailureState } from '../components/AsyncStates';
import { formatMoneyDecimal } from '../formatting/decimal';
import { categoryLabel, conditionLabel, skuDisplayName } from '../formatting/sku';
import { formatDateOnly, formatManilaTimestamp } from '../formatting/time';
import styles from './DealFeedPage.module.css';


const DEALS_PATH = '/api/v1/deal-flags/';
const SERVER_PAGE_SIZE = 25;

type DealFeedState =
  | { status: 'loading' }
  | { status: 'success'; page: Page<DealFlag>; offset: number }
  | { status: 'forbidden' }
  | { status: 'error' };

interface DealRequest {
  url: string;
  offset: number;
  attempt: number;
}

function DealCard({ deal }: { deal: DealFlag }) {
  const name = skuDisplayName(deal.sku);
  const baseline = deal.baseline_pricepoint;

  return (
    <article className={styles.card}>
      <div className={styles.cardHeading}>
        <div>
          <p className={styles.category}>{categoryLabel(deal.sku.category)}</p>
          <h2><Link to={`/skus/${deal.sku.id}`}>{name}</Link></h2>
        </div>
        <div className={styles.score}>
          <span>Persisted score</span>
          <strong>{deal.score}</strong>
        </div>
      </div>

      <div className={styles.primaryEvidence}>
        <div>
          <span>Asking price</span>
          <strong>{formatMoneyDecimal(deal.listing.price)}</strong>
        </div>
        <div>
          <span>Condition</span>
          <strong>{conditionLabel(deal.listing.condition)}</strong>
        </div>
      </div>

      <p className={styles.reason}>{deal.reason}</p>

      <dl className={styles.evidenceGrid}>
        <div><dt>Baseline day</dt><dd>{formatDateOnly(baseline.day)}</dd></div>
        <div><dt>Baseline median</dt><dd>{formatMoneyDecimal(baseline.median)}</dd></div>
        <div><dt>MAD</dt><dd>{formatMoneyDecimal(baseline.mad)}</dd></div>
        <div><dt>Sample count</dt><dd>{baseline.n_listings}</dd></div>
        <div><dt>Observed</dt><dd>{formatManilaTimestamp(deal.listing.observed_at)}</dd></div>
        <div><dt>Flagged</dt><dd>{formatManilaTimestamp(deal.flagged_at)}</dd></div>
      </dl>
    </article>
  );
}

export default function DealFeedPage() {
  const [request, setRequest] = useState<DealRequest>({
    url: DEALS_PATH,
    offset: 0,
    attempt: 0,
  });
  const [state, setState] = useState<DealFeedState>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });

    getDealFlagPage(request.url, controller.signal)
      .then((page) => setState({ status: 'success', page, offset: request.offset }))
      .catch((error: unknown) => {
        if (isCancelledRequest(error)) {
          return;
        }
        if (error instanceof ApiError && error.kind === 'forbidden') {
          setState({ status: 'forbidden' });
          return;
        }
        setState({ status: 'error' });
      });

    return () => controller.abort();
  }, [request]);

  function retry() {
    setRequest((current) => ({ ...current, attempt: current.attempt + 1 }));
  }

  function loadPage(url: string, offset: number) {
    setRequest((current) => ({ url, offset, attempt: current.attempt + 1 }));
  }

  if (state.status === 'forbidden') {
    return <AccessRequiredState />;
  }

  return (
    <section aria-labelledby="deals-heading">
      <div className={styles.pageHeading}>
        <div>
          <p className={styles.eyebrow}>Persisted signals</p>
          <h1 id="deals-heading">Deal feed</h1>
        </div>
        <p>Server-ordered flags backed by sealed baseline evidence.</p>
      </div>

      {state.status === 'loading' && (
        <p className={styles.status} role="status">Loading persisted deals...</p>
      )}

      {state.status === 'error' && (
        <RequestFailureState
          title="Deal feed could not be loaded."
          retryLabel="Retry deal feed"
          onRetry={retry}
        />
      )}

      {state.status === 'success' && state.page.results.length === 0 && (
        <p className={styles.status} role="status">
          No persisted deal flags are available.
        </p>
      )}

      {state.status === 'success' && state.page.results.length > 0 && (
        <>
          <div className={styles.feed}>
            {state.page.results.map((deal) => <DealCard key={deal.id} deal={deal} />)}
          </div>
          <nav className={styles.pagination} aria-label="Deal feed pages">
            <button
              type="button"
              aria-label="Previous deals"
              disabled={state.page.previous === null}
              onClick={() => state.page.previous && loadPage(
                state.page.previous,
                Math.max(0, state.offset - SERVER_PAGE_SIZE),
              )}
            >
              Previous
            </button>
            <p>
              Showing {state.offset + 1}–{state.offset + state.page.results.length} of{' '}
              {state.page.count}
            </p>
            <button
              type="button"
              aria-label="Next deals"
              disabled={state.page.next === null}
              onClick={() => state.page.next && loadPage(
                state.page.next,
                state.offset + state.page.results.length,
              )}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </section>
  );
}
