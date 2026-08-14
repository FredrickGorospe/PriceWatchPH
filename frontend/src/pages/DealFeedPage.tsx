import { useEffect, useState } from 'react';
import { Link } from 'react-router';

import {
  ApiError,
  type AccessDisposition,
  getDealFlagPage,
  isCancelledRequest,
} from '../api/client';
import { useReportAuthUiState } from '../auth/AuthUiContext';
import type { DealFlag, Page } from '../api/types';
import {
  AccessRequiredState,
  EmptyState,
  LoadingState,
  RequestFailureState,
} from '../components/AsyncStates';
import Button, { ButtonLink } from '../components/Button';
import MetricReadout, { ReadoutList } from '../components/MetricReadout';
import PageHeader from '../components/PageHeader';
import StatusIndicator from '../components/StatusIndicator';
import type { Tone } from '../components/StatusIndicator';
import type { ReadoutTone } from '../components/MetricReadout';
import { formatMoneyDecimal } from '../formatting/decimal';
import { deviationFromBaseline } from '../formatting/deviation';
import { categoryLabel, conditionLabel, skuDisplayName } from '../formatting/sku';
import { formatDateOnly, formatManilaTimestamp } from '../formatting/time';
import styles from './DealFeedPage.module.css';


const DEALS_PATH = '/api/v1/deal-flags/';
const SERVER_PAGE_SIZE = 25;

type DealFeedState =
  | { status: 'loading' }
  | { status: 'success'; page: Page<DealFlag>; offset: number }
  | { status: 'forbidden'; access: AccessDisposition }
  | { status: 'error' };

interface DealRequest {
  url: string;
  offset: number;
  attempt: number;
}

interface DeviationPresentation {
  text: string;
  signal: string;
  tone: Tone;
  readoutTone: ReadoutTone;
}

// Presentation only, exactly like the chart's numeric conversion: the state
// below is a factual comparison of two persisted Decimals, never a verdict.
function presentDeviation(deal: DealFlag): DeviationPresentation {
  const deviation = deviationFromBaseline(
    deal.listing.price,
    deal.baseline_pricepoint.median,
  );

  if (deviation === null) {
    return {
      text: 'Unavailable',
      signal: 'No comparison',
      tone: 'neutral',
      readoutTone: 'muted',
    };
  }
  if (deviation.percent < 0) {
    return {
      text: deviation.text,
      signal: 'Below baseline',
      tone: 'positive',
      readoutTone: 'positive',
    };
  }
  if (deviation.percent > 0) {
    return {
      text: deviation.text,
      signal: 'Above baseline',
      tone: 'negative',
      readoutTone: 'negative',
    };
  }
  return {
    text: deviation.text,
    signal: 'At baseline',
    tone: 'neutral',
    readoutTone: 'muted',
  };
}

function DealCard({ deal }: { deal: DealFlag }) {
  const name = skuDisplayName(deal.sku);
  const baseline = deal.baseline_pricepoint;
  const deviation = presentDeviation(deal);

  return (
    <article className={`pw-panel ${styles.card}`}>
      <div className={styles.identity}>
        <div className={styles.identityText}>
          <p className={styles.category}>{categoryLabel(deal.sku.category)}</p>
          <h2 className={styles.skuName}>
            <Link to={`/skus/${deal.sku.id}`}>{name}</Link>
          </h2>
        </div>
        <span className={styles.conditionTag}>{conditionLabel(deal.listing.condition)}</span>
      </div>

      {/* The instrument face: asking price and its deviation dominate the scan. */}
      <div className={`pw-well ${styles.instrument}`}>
        <ReadoutList layout="strip" className={styles.instrumentReadouts}>
          <MetricReadout label="Asking price" size="lg" mono>
            {formatMoneyDecimal(deal.listing.price)}
          </MetricReadout>
          <MetricReadout
            label="vs baseline median"
            size="lg"
            mono
            tone={deviation.readoutTone}
          >
            {deviation.text}
          </MetricReadout>
          <MetricReadout label="Baseline median" size="md" mono tone="muted">
            {formatMoneyDecimal(baseline.median)}
          </MetricReadout>
        </ReadoutList>
        <div className={styles.signalRow}>
          <StatusIndicator tone={deviation.tone}>{deviation.signal}</StatusIndicator>
          <span className={styles.score}>
            <span className={styles.scoreLabel}>Persisted score</span>
            <strong>{deal.score}</strong>
          </span>
        </div>
      </div>

      <p className={styles.reason}>{deal.reason}</p>

      <ReadoutList className={styles.evidenceGrid}>
        <MetricReadout label="Baseline day" mono>{formatDateOnly(baseline.day)}</MetricReadout>
        <MetricReadout label="MAD" mono>{formatMoneyDecimal(baseline.mad)}</MetricReadout>
        <MetricReadout label="Sample count" mono>{baseline.n_listings}</MetricReadout>
        <MetricReadout label="Observed" mono>
          {formatManilaTimestamp(deal.listing.observed_at)}
        </MetricReadout>
        <MetricReadout label="Flagged" mono>
          {formatManilaTimestamp(deal.flagged_at)}
        </MetricReadout>
      </ReadoutList>

      <div className={styles.cardActions}>
        <ButtonLink small to={`/deals/${deal.id}/outcome`}>Track outcome</ButtonLink>
        <ButtonLink small variant="ghost" to={`/reviews/${deal.listing.id}`}>
          Review or correct SKU
        </ButtonLink>
      </div>
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
          setState({ status: 'forbidden', access: error.access });
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

  useReportAuthUiState(
    state.status === 'success'
      ? 'authorized'
      : state.status === 'forbidden'
        ? state.access
        : 'unknown',
  );

  if (state.status === 'forbidden') {
    return <AccessRequiredState access={state.access} />;
  }

  if (state.status === 'loading') {
    return <LoadingState message="Loading persisted deals..." />;
  }

  return (
    <section aria-labelledby="deals-heading">
      <PageHeader
        eyebrow="Persisted signals"
        title="Deal feed"
        titleId="deals-heading"
        description="Server-ordered flags backed by sealed baseline evidence."
      />

      {state.status === 'error' && (
        <RequestFailureState
          title="Deal feed could not be loaded."
          retryLabel="Retry deal feed"
          onRetry={retry}
        />
      )}

      {state.status === 'success' && state.page.results.length === 0 && (
        <EmptyState
          message="No persisted deal flags are available."
          detail="Nothing is wrong: the pricing run produced no flags for this page."
        />
      )}

      {state.status === 'success' && state.page.results.length > 0 && (
        <>
          <div className={styles.feed}>
            {state.page.results.map((deal) => <DealCard key={deal.id} deal={deal} />)}
          </div>
          <nav className={styles.pagination} aria-label="Deal feed pages">
            <Button
              small
              aria-label="Previous deals"
              disabled={state.page.previous === null}
              onClick={() => state.page.previous && loadPage(
                state.page.previous,
                Math.max(0, state.offset - SERVER_PAGE_SIZE),
              )}
            >
              Previous
            </Button>
            <p>
              Showing {state.offset + 1}–{state.offset + state.page.results.length} of{' '}
              {state.page.count}
            </p>
            <Button
              small
              aria-label="Next deals"
              disabled={state.page.next === null}
              onClick={() => state.page.next && loadPage(
                state.page.next,
                state.offset + state.page.results.length,
              )}
            >
              Next
            </Button>
          </nav>
        </>
      )}
    </section>
  );
}
