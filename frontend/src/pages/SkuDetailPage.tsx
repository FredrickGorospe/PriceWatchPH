import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';

import {
  ApiError,
  getCompletePricePointHistory,
  getSku,
  isCancelledRequest,
} from '../api/client';
import { useReportAuthUiState } from '../auth/AuthUiContext';
import type { ListingCondition, PricePoint, Sku } from '../api/types';
import PriceHistoryChart from '../charts/PriceHistoryChart';
import {
  AccessRequiredState,
  EmptyState,
  LoadingState,
  RequestFailureState,
} from '../components/AsyncStates';
import { ButtonLink } from '../components/Button';
import { SelectField } from '../components/Field';
import MetricReadout, { ReadoutList } from '../components/MetricReadout';
import StatusIndicator from '../components/StatusIndicator';
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
  const forbiddenError = skuError?.kind === 'forbidden'
    ? skuError
    : historyError?.kind === 'forbidden'
      ? historyError
      : null;

  useReportAuthUiState(
    forbiddenError !== null
      ? forbiddenError.access
      : skuState.status === 'success'
        ? 'authorized'
        : 'unknown',
  );

  if (forbiddenError !== null) {
    return <AccessRequiredState access={forbiddenError.access} />;
  }

  if (skuError?.kind === 'not-found' || historyError?.kind === 'not-found') {
    return (
      <section className={`pw-panel ${styles.state}`} role="status">
        <StatusIndicator tone="caution">Missing catalogue record</StatusIndicator>
        <h1>SKU not found</h1>
        <p>The requested canonical SKU does not exist.</p>
        <ButtonLink variant="primary" to="/deals">Return to deals</ButtonLink>
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
    return <LoadingState message="Checking PriceWatch PH access..." />;
  }

  const sku = skuState.value;

  function selectCondition(value: string) {
    setHistoryState({ status: 'loading' });
    setCondition(value as ListingCondition | '');
  }

  return (
    <article>
      <Link className={styles.backLink} to="/deals">
        <span aria-hidden="true">←</span> Back to deals
      </Link>

      {/* The asset nameplate: identity above, catalogue facts inset below it. */}
      <header className={`pw-panel ${styles.nameplate}`}>
        <div className={styles.nameplateIdentity}>
          <p className={styles.category}>{categoryLabel(sku.category)}</p>
          <h1 className={styles.skuName}>{skuDisplayName(sku)}</h1>
          <p className={styles.subtitle}>Canonical catalogue identity</p>
        </div>
        <ReadoutList layout="strip" className={`pw-well ${styles.catalogueFacts}`}>
          <MetricReadout label="Launch MSRP" size="md" mono>
            {formatMoneyDecimal(sku.launch_msrp)}
          </MetricReadout>
          <MetricReadout label="Launch date" size="md" mono tone="muted">
            {formatDateOnly(sku.launch_date)}
          </MetricReadout>
          <MetricReadout label="Catalogue ref" size="md" mono tone="muted">
            {`SKU-${sku.id}`}
          </MetricReadout>
        </ReadoutList>
      </header>

      <section
        className={`pw-frost ${styles.historyControls}`}
        aria-labelledby="history-controls-heading"
      >
        <div className={styles.historyControlsText}>
          <p className={styles.eyebrow}>Sealed pricing evidence</p>
          <h2 id="history-controls-heading">History selection</h2>
        </div>
        <div className={styles.historyControlsInputs}>
          <SelectField
            label="Condition"
            className={styles.conditionField}
            value={condition}
            onChange={(event) => selectCondition(event.target.value)}
          >
            {CONDITION_OPTIONS.map((option) => (
              <option key={option.value || 'all'} value={option.value}>{option.label}</option>
            ))}
          </SelectField>
        </div>
      </section>

      {historyState.status === 'loading' && (
        <LoadingState
          className={styles.historyState}
          message="Loading complete price history..."
        />
      )}

      {historyState.status === 'error' && (
        <div className={styles.historyState}>
          <RequestFailureState
            title="Price history could not be loaded."
            retryLabel="Retry price history"
            onRetry={() => setHistoryAttempt((attempt) => attempt + 1)}
          />
        </div>
      )}

      {historyState.status === 'success' && historyState.value.length === 0 && (
        <EmptyState
          className={styles.historyState}
          message="No persisted price history is available for this selection."
          detail="Try a different condition, or wait for the next pricing run."
        />
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
