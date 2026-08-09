import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';

import {
  ApiError,
  getCompletePricePointHistory,
  getSku,
  isCancelledRequest,
} from '../api/client';
import type { ListingCondition, PricePoint, Sku } from '../api/types';
import PriceHistoryChart from '../charts/PriceHistoryChart';
import { AccessRequiredState, RequestFailureState } from '../components/AsyncStates';
import { formatMoneyDecimal } from '../formatting/decimal';
import { categoryLabel, skuDisplayName } from '../formatting/sku';
import { formatDateOnly } from '../formatting/time';
import styles from './SkuDetailPage.module.css';


type ResourceState<T> =
  | { status: 'loading' }
  | { status: 'success'; value: T }
  | { status: 'error'; error: ApiError };

const CONDITION_OPTIONS: Array<{ value: ListingCondition | ''; label: string }> = [
  { value: '', label: 'All conditions' },
  { value: 'new', label: 'New' },
  { value: 'like_new', label: 'Like new' },
  { value: 'used', label: 'Used' },
  { value: 'for_parts', label: 'For parts' },
];

function apiError(state: ResourceState<unknown>): ApiError | null {
  return state.status === 'error' ? state.error : null;
}

export default function SkuDetailPage() {
  const { skuId = '' } = useParams();
  const [condition, setCondition] = useState<ListingCondition | ''>('');
  const [skuAttempt, setSkuAttempt] = useState(0);
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const [skuState, setSkuState] = useState<ResourceState<Sku>>({ status: 'loading' });
  const [historyState, setHistoryState] = useState<ResourceState<PricePoint[]>>({
    status: 'loading',
  });

  useEffect(() => {
    const controller = new AbortController();
    setSkuState({ status: 'loading' });

    getSku(skuId, controller.signal)
      .then((sku) => setSkuState({ status: 'success', value: sku }))
      .catch((error: unknown) => {
        if (isCancelledRequest(error)) {
          return;
        }
        setSkuState({
          status: 'error',
          error: error instanceof ApiError
            ? error
            : new ApiError('network', 'The SKU request failed.'),
        });
      });

    return () => controller.abort();
  }, [skuId, skuAttempt]);

  useEffect(() => {
    const controller = new AbortController();
    setHistoryState({ status: 'loading' });

    getCompletePricePointHistory(skuId, condition, controller.signal)
      .then((points) => setHistoryState({ status: 'success', value: points }))
      .catch((error: unknown) => {
        if (isCancelledRequest(error)) {
          return;
        }
        setHistoryState({
          status: 'error',
          error: error instanceof ApiError
            ? error
            : new ApiError('network', 'The history request failed.'),
        });
      });

    return () => controller.abort();
  }, [skuId, condition, historyAttempt]);

  const skuError = apiError(skuState);
  const historyError = apiError(historyState);

  if (skuError?.kind === 'forbidden' || historyError?.kind === 'forbidden') {
    return <AccessRequiredState />;
  }

  if (skuError?.kind === 'not-found' || historyError?.kind === 'not-found') {
    return (
      <section className={styles.state} role="status">
        <p className={styles.eyebrow}>Missing catalogue record</p>
        <h1>SKU not found</h1>
        <p>The requested canonical SKU does not exist.</p>
        <Link to="/deals">Return to deals</Link>
      </section>
    );
  }

  if (skuState.status === 'error') {
    return (
      <RequestFailureState
        title="SKU could not be loaded."
        retryLabel="Retry SKU"
        onRetry={() => setSkuAttempt((attempt) => attempt + 1)}
      />
    );
  }

  if (skuState.status === 'loading') {
    return <p className={styles.status} role="status">Loading SKU...</p>;
  }

  const sku = skuState.value;

  function selectCondition(value: string) {
    setHistoryState({ status: 'loading' });
    setCondition(value as ListingCondition | '');
  }

  return (
    <article>
      <Link className={styles.backLink} to="/deals">← Back to deals</Link>
      <header className={styles.hero}>
        <div>
          <p className={styles.eyebrow}>{categoryLabel(sku.category)}</p>
          <h1>{skuDisplayName(sku)}</h1>
          <p>Canonical catalogue identity</p>
        </div>
        <dl className={styles.catalogueFacts}>
          <div><dt>Launch MSRP</dt><dd>{formatMoneyDecimal(sku.launch_msrp)}</dd></div>
          <div><dt>Launch date</dt><dd>{formatDateOnly(sku.launch_date)}</dd></div>
        </dl>
      </header>

      <section className={styles.historyControls} aria-labelledby="history-controls-heading">
        <div>
          <p className={styles.eyebrow}>Sealed pricing evidence</p>
          <h2 id="history-controls-heading">History selection</h2>
        </div>
        <label>
          <span>Condition</span>
          <select value={condition} onChange={(event) => selectCondition(event.target.value)}>
            {CONDITION_OPTIONS.map((option) => (
              <option key={option.value || 'all'} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
      </section>

      {historyState.status === 'loading' && (
        <p className={styles.status} role="status">Loading complete price history...</p>
      )}

      {historyState.status === 'error' && (
        <RequestFailureState
          title="Price history could not be loaded."
          retryLabel="Retry price history"
          onRetry={() => setHistoryAttempt((attempt) => attempt + 1)}
        />
      )}

      {historyState.status === 'success' && historyState.value.length === 0 && (
        <p className={styles.status} role="status">
          No persisted price history is available for this selection.
        </p>
      )}

      {historyState.status === 'success' && historyState.value.length > 0 && (
        <>
          <p className={styles.loadedStatus} role="status">
            {historyState.value.length} persisted price{' '}
            {historyState.value.length === 1 ? 'point' : 'points'} loaded.
          </p>
          <PriceHistoryChart pricePoints={historyState.value} />
        </>
      )}
    </article>
  );
}
