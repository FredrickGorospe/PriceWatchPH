import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';

import {
  bootstrapCsrf,
  correctPurchase,
  correctSale,
  getOutcomeState,
  isCancelledRequest,
  OutcomeApiError,
  recordPurchase,
  recordSale,
  skipOutcome,
} from '../api/client';
import type { OutcomeLifecycleState, OutcomeOperationResult, OutcomeState } from '../api/types';
import { AccessRequiredState, RequestFailureState } from '../components/AsyncStates';
import { formatMoneyDecimal } from '../formatting/decimal';
import { formatManilaTimestamp, manilaLocalInputToUtcInstant, utcInstantToManilaLocalInput } from '../formatting/time';
import styles from './OutcomeWorkflowPage.module.css';


type PageState =
  | { status: 'loading' }
  | { status: 'success'; outcome: OutcomeState }
  | { status: 'forbidden' }
  | { status: 'missing'; detail: string }
  | { status: 'invalid'; detail: string }
  | { status: 'error' };

interface OperationState {
  status: 'idle' | 'submitting';
  successMessage: string | null;
  errorMessage: string | null;
  reload: boolean;
  fieldErrors: Record<string, string[]> | null;
}

const IDLE_OPERATION: OperationState = {
  status: 'idle',
  successMessage: null,
  errorMessage: null,
  reload: false,
  fieldErrors: null,
};

const MONEY_PATTERN = /^\d+(\.\d{1,2})?$/;

function lifecycleLabel(state: OutcomeLifecycleState): string {
  return state.charAt(0).toUpperCase() + state.slice(1);
}

interface MoneyTimestampFormProps {
  regionLabel: string;
  heading: string;
  timestampLabel: string;
  priceLabel: string;
  submitLabel: string;
  defaultAt?: string;
  defaultPrice?: string;
  disabled: boolean;
  onSubmit: (utcAt: string, price: string) => void;
}

function MoneyTimestampForm({
  regionLabel,
  heading,
  timestampLabel,
  priceLabel,
  submitLabel,
  defaultAt = '',
  defaultPrice = '',
  disabled,
  onSubmit,
}: MoneyTimestampFormProps) {
  const [at, setAt] = useState(defaultAt);
  const [price, setPrice] = useState(defaultPrice);
  const [showPriceError, setShowPriceError] = useState(false);

  function handleSubmit() {
    // Light UX guard only - the server remains the authority on precision and finiteness.
    if (!MONEY_PATTERN.test(price)) {
      setShowPriceError(true);
      return;
    }
    const utcAt = manilaLocalInputToUtcInstant(at);
    if (utcAt === null) {
      return;
    }
    setShowPriceError(false);
    onSubmit(utcAt, price);
  }

  return (
    <section className={styles.formRegion} aria-label={regionLabel}>
      <h2>{heading}</h2>
      <label className={styles.field}>
        <span>{timestampLabel}</span>
        <input
          type="datetime-local"
          required
          value={at}
          onChange={(event) => setAt(event.target.value)}
        />
      </label>
      <label className={styles.field}>
        <span>{priceLabel}</span>
        <input
          type="text"
          inputMode="decimal"
          required
          value={price}
          onChange={(event) => setPrice(event.target.value)}
        />
      </label>
      {showPriceError && (
        <p role="alert">Enter a price with up to two decimal places.</p>
      )}
      <button type="button" disabled={disabled} onClick={handleSubmit}>{submitLabel}</button>
    </section>
  );
}

function SkipForm({
  disabled,
  onSubmit,
}: {
  disabled: boolean;
  onSubmit: (reason: string) => void;
}) {
  const [reason, setReason] = useState('');

  return (
    <section className={styles.formRegion} aria-label="Skip this deal flag">
      <h2>Skip this deal flag</h2>
      <label className={styles.field}>
        <span>Reason</span>
        <input
          type="text"
          required
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <button type="button" disabled={disabled} onClick={() => onSubmit(reason)}>
        Skip deal flag
      </button>
    </section>
  );
}

function OutcomeEvidence({ outcome }: { outcome: OutcomeState }) {
  const { lifecycle_state: lifecycleState } = outcome;
  const showPurchase = lifecycleState === 'open' || lifecycleState === 'closed';
  const showSale = lifecycleState === 'closed';

  return (
    <section className={styles.evidence} aria-label="Outcome evidence">
      <h2>Outcome evidence</h2>
      <dl>
        {lifecycleState === 'skipped' && (
          <div><dt>Skip reason</dt><dd>{outcome.skip_reason}</dd></div>
        )}
        {showPurchase && (
          <>
            <div>
              <dt>Purchased at (Asia/Manila)</dt>
              <dd>{formatManilaTimestamp(outcome.bought_at)}</dd>
            </div>
            <div><dt>Purchase price</dt><dd>{formatMoneyDecimal(outcome.bought_price)}</dd></div>
          </>
        )}
        {showSale && (
          <>
            <div>
              <dt>Sold at (Asia/Manila)</dt>
              <dd>{formatManilaTimestamp(outcome.sold_at)}</dd>
            </div>
            <div><dt>Sale price</dt><dd>{formatMoneyDecimal(outcome.sold_price)}</dd></div>
          </>
        )}
        {showPurchase && (
          <div>
            <dt>Days held</dt>
            <dd>
              {outcome.days_held === null
                ? 'Not yet available (no sale recorded)'
                : `${outcome.days_held} day(s) held`}
            </dd>
          </div>
        )}
        {showPurchase && (
          <div>
            <dt>{lifecycleState === 'open' ? 'Realised margin (not yet realised)' : 'Realised margin'}</dt>
            <dd>{formatMoneyDecimal(outcome.realised_margin)}</dd>
          </div>
        )}
      </dl>
    </section>
  );
}

export default function OutcomeWorkflowPage() {
  const { dealFlagId = '' } = useParams();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<PageState>({ status: 'loading' });
  const [operation, setOperation] = useState<OperationState>(IDLE_OPERATION);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    setOperation(IDLE_OPERATION);

    async function load() {
      try {
        // Fired concurrently, not sequentially awaited: CSRF bootstrap and the
        // outcome read are independent (the read sends no CSRF header), and the
        // outcome fetch must be dispatched in the same synchronous tick as the
        // bootstrap call rather than gated behind its resolution.
        const [, outcome] = await Promise.all([
          bootstrapCsrf(controller.signal),
          getOutcomeState(dealFlagId, controller.signal),
        ]);
        setState({ status: 'success', outcome });
      } catch (error) {
        if (isCancelledRequest(error)) {
          return;
        }
        if (error instanceof OutcomeApiError && error.status === 403) {
          setState({ status: 'forbidden' });
          return;
        }
        if (
          error instanceof OutcomeApiError
          && error.status === 404
          && error.code === 'deal_flag_not_found'
        ) {
          setState({ status: 'missing', detail: error.detail ?? 'Deal flag not found.' });
          return;
        }
        if (
          error instanceof OutcomeApiError
          && error.status === 409
          && error.code === 'invalid_outcome_state'
        ) {
          setState({
            status: 'invalid',
            detail: error.detail ?? 'Outcome is in an invalid persisted state.',
          });
          return;
        }
        setState({ status: 'error' });
      }
    }

    void load();
    return () => controller.abort();
  }, [dealFlagId, attempt]);

  async function runOperation(
    action: () => Promise<OutcomeOperationResult>,
    successMessage: string,
  ) {
    setOperation({ ...IDLE_OPERATION, status: 'submitting' });
    try {
      const result = await action();
      setState({ status: 'success', outcome: result });
      setOperation({ ...IDLE_OPERATION, successMessage });
    } catch (error) {
      if (error instanceof OutcomeApiError && error.status === 403) {
        setState({ status: 'forbidden' });
        return;
      }
      if (error instanceof OutcomeApiError && error.status === 409 && error.code === 'invalid_outcome_state') {
        setState({
          status: 'invalid',
          detail: error.detail ?? 'Outcome is in an invalid persisted state.',
        });
        return;
      }
      if (error instanceof OutcomeApiError && error.status === 400) {
        setOperation({
          ...IDLE_OPERATION,
          errorMessage: error.detail ?? 'Request validation failed.',
          fieldErrors: error.errors,
        });
        return;
      }
      if (
        error instanceof OutcomeApiError
        && (
          (error.status === 404 && error.code === 'outcome_not_found')
          || (error.status === 409 && (
            error.code === 'outcome_already_exists' || error.code === 'ineligible_outcome_state'
          ))
        )
      ) {
        setOperation({
          ...IDLE_OPERATION,
          errorMessage: error.detail ?? 'Outcome operation could not be completed.',
          reload: true,
        });
        return;
      }
      setOperation({
        ...IDLE_OPERATION,
        errorMessage: 'Outcome operation could not be completed.',
      });
    }
  }

  if (state.status === 'forbidden') {
    return <AccessRequiredState />;
  }
  if (state.status === 'missing') {
    return <p className={styles.status} role="status">{state.detail}</p>;
  }
  if (state.status === 'invalid') {
    return (
      <section aria-labelledby="outcome-invalid-heading">
        <p className={styles.eyebrow}>Operational error</p>
        <h1 id="outcome-invalid-heading">Outcome requires manual correction</h1>
        <p>{state.detail}</p>
        <p className={styles.backLink}><Link to="/deals">Back to deal feed</Link></p>
      </section>
    );
  }
  if (state.status === 'error') {
    return (
      <RequestFailureState
        title="Outcome could not be loaded."
        retryLabel="Retry outcome"
        onRetry={() => setAttempt((value) => value + 1)}
      />
    );
  }
  if (state.status === 'loading') {
    return <p className={styles.status} role="status">Loading outcome...</p>;
  }

  const { outcome } = state;
  const numericDealFlagId = Number(dealFlagId);
  const submitting = operation.status === 'submitting';

  return (
    <article aria-labelledby="outcome-heading">
      <header className={styles.pageHeading}>
        <p className={styles.eyebrow}>Outcome workflow</p>
        <h1 id="outcome-heading">Outcome for deal flag {outcome.deal_flag_id}</h1>
      </header>

      <p className={styles.lifecycle}>Current state: {lifecycleLabel(outcome.lifecycle_state)}</p>

      {operation.successMessage && (
        <p className={styles.success} role="status">{operation.successMessage}</p>
      )}

      {operation.errorMessage && (
        <div role="alert">
          <p>{operation.errorMessage}</p>
          {operation.fieldErrors && (
            <ul>
              {Object.entries(operation.fieldErrors).flatMap(([field, messages]) => (
                messages.map((message) => <li key={`${field}-${message}`}>{field}: {message}</li>)
              ))}
            </ul>
          )}
          {operation.reload && (
            <button type="button" onClick={() => setAttempt((value) => value + 1)}>
              Reload outcome
            </button>
          )}
        </div>
      )}

      {outcome.lifecycle_state === 'untracked' && (
        <p>No outcome has been recorded for this deal flag yet.</p>
      )}

      {outcome.lifecycle_state !== 'untracked' && <OutcomeEvidence outcome={outcome} />}

      <div className={styles.forms}>
        {outcome.lifecycle_state === 'untracked' && (
          <SkipForm
            disabled={submitting}
            onSubmit={(reason) => void runOperation(
              () => skipOutcome(numericDealFlagId, reason),
              'Deal flag marked skipped.',
            )}
          />
        )}

        {(outcome.lifecycle_state === 'untracked' || outcome.lifecycle_state === 'skipped') && (
          <MoneyTimestampForm
            regionLabel="Record purchase"
            heading="Record purchase"
            timestampLabel="Purchased at (Asia/Manila)"
            priceLabel="Purchase price"
            submitLabel="Record purchase"
            disabled={submitting}
            onSubmit={(at, price) => void runOperation(
              () => recordPurchase(numericDealFlagId, at, price),
              'Purchase recorded.',
            )}
          />
        )}

        {outcome.lifecycle_state === 'open' && (
          <MoneyTimestampForm
            regionLabel="Record sale"
            heading="Record sale"
            timestampLabel="Sold at (Asia/Manila)"
            priceLabel="Sale price"
            submitLabel="Record sale"
            disabled={submitting}
            onSubmit={(at, price) => void runOperation(
              () => recordSale(numericDealFlagId, at, price),
              'Sale recorded.',
            )}
          />
        )}

        {(outcome.lifecycle_state === 'open' || outcome.lifecycle_state === 'closed') && (
          <MoneyTimestampForm
            key={`correct-purchase-${outcome.bought_at ?? ''}-${outcome.bought_price ?? ''}`}
            regionLabel="Correct purchase"
            heading="Correct purchase"
            timestampLabel="Purchased at (Asia/Manila)"
            priceLabel="Purchase price"
            submitLabel="Correct purchase"
            defaultAt={utcInstantToManilaLocalInput(outcome.bought_at)}
            defaultPrice={outcome.bought_price ?? ''}
            disabled={submitting}
            onSubmit={(at, price) => void runOperation(
              () => correctPurchase(numericDealFlagId, at, price),
              'Purchase evidence corrected.',
            )}
          />
        )}

        {outcome.lifecycle_state === 'closed' && (
          <MoneyTimestampForm
            key={`correct-sale-${outcome.sold_at ?? ''}-${outcome.sold_price ?? ''}`}
            regionLabel="Correct sale"
            heading="Correct sale"
            timestampLabel="Sold at (Asia/Manila)"
            priceLabel="Sale price"
            submitLabel="Correct sale"
            defaultAt={utcInstantToManilaLocalInput(outcome.sold_at)}
            defaultPrice={outcome.sold_price ?? ''}
            disabled={submitting}
            onSubmit={(at, price) => void runOperation(
              () => correctSale(numericDealFlagId, at, price),
              'Sale evidence corrected.',
            )}
          />
        )}
      </div>

      <p className={styles.backLink}><Link to="/deals">Back to deal feed</Link></p>
    </article>
  );
}
