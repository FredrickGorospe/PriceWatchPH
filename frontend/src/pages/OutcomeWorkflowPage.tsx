import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';

import {
  type AccessDisposition,
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
import { useReportAuthUiState } from '../auth/AuthUiContext';
import type { OutcomeLifecycleState, OutcomeOperationResult, OutcomeState } from '../api/types';
import {
  AccessRequiredState,
  EmptyState,
  LoadingState,
  RequestFailureState,
} from '../components/AsyncStates';
import Button from '../components/Button';
import Field from '../components/Field';
import MetricReadout, { ReadoutList } from '../components/MetricReadout';
import type { ReadoutTone } from '../components/MetricReadout';
import PageHeader from '../components/PageHeader';
import StatusIndicator from '../components/StatusIndicator';
import type { Tone } from '../components/StatusIndicator';
import indicatorStyles from '../components/StatusIndicator.module.css';
import { formatMoneyDecimal } from '../formatting/decimal';
import { formatManilaTimestamp, manilaLocalInputToUtcInstant, utcInstantToManilaLocalInput } from '../formatting/time';
import styles from './OutcomeWorkflowPage.module.css';


type PageState =
  | { status: 'loading' }
  | { status: 'success'; outcome: OutcomeState }
  | { status: 'forbidden'; access: AccessDisposition }
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

const LIFECYCLE_TONES: Record<OutcomeLifecycleState, Tone> = {
  untracked: 'neutral',
  skipped: 'caution',
  open: 'accent',
  closed: 'positive',
};

function lifecycleLabel(state: OutcomeLifecycleState): string {
  return state.charAt(0).toUpperCase() + state.slice(1);
}

// Sign of the realised margin, for readout tone only; the Decimal string
// itself is always rendered verbatim beside it.
function marginTone(margin: string | null): ReadoutTone {
  if (margin === null) {
    return 'muted';
  }
  return margin.trim().startsWith('-') ? 'negative' : 'positive';
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
  /** Corrections restate recorded evidence; recordings create it. */
  correction?: boolean;
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
  correction,
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
    <section
      className={`pw-panel ${styles.formRegion} ${correction ? styles.correctionRegion : ''}`}
      aria-label={regionLabel}
    >
      <div className={styles.formHead}>
        <h2>{heading}</h2>
        <span className={styles.formTag}>{correction ? 'Correction' : 'Record'}</span>
      </div>
      <div className={styles.formGrid}>
        <Field
          label={timestampLabel}
          type="datetime-local"
          required
          numeric
          value={at}
          onChange={(event) => setAt(event.target.value)}
        />
        <Field
          label={priceLabel}
          type="text"
          inputMode="decimal"
          required
          numeric
          invalid={showPriceError}
          value={price}
          onChange={(event) => setPrice(event.target.value)}
        />
      </div>
      {showPriceError && (
        <p className={styles.fieldAlert} role="alert">
          Enter a price with up to two decimal places.
        </p>
      )}
      <div className={styles.formActions}>
        <Button
          variant={correction ? 'secondary' : 'primary'}
          disabled={disabled}
          onClick={handleSubmit}
        >
          {submitLabel}
        </Button>
      </div>
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
    <section className={`pw-panel ${styles.formRegion}`} aria-label="Skip this deal flag">
      <div className={styles.formHead}>
        <h2>Skip this deal flag</h2>
        <span className={styles.formTag}>Record</span>
      </div>
      <div className={styles.formGrid}>
        <Field
          label="Reason"
          type="text"
          required
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
      </div>
      <div className={styles.formActions}>
        <Button variant="caution" disabled={disabled} onClick={() => onSubmit(reason)}>
          Skip deal flag
        </Button>
      </div>
    </section>
  );
}

function OutcomeEvidence({ outcome }: { outcome: OutcomeState }) {
  const { lifecycle_state: lifecycleState } = outcome;
  const showPurchase = lifecycleState === 'open' || lifecycleState === 'closed';
  const showSale = lifecycleState === 'closed';

  return (
    <section className={`pw-panel ${styles.evidence}`} aria-label="Outcome evidence">
      <div className={styles.formHead}>
        <h2>Outcome evidence</h2>
        <span className={styles.formTag}>Recorded</span>
      </div>

      {/* Realised margin is the result; it outranks every other recorded fact. */}
      {showPurchase && (
        <ReadoutList layout="strip" className={`pw-well ${styles.resultPanel}`}>
          <MetricReadout
            label={lifecycleState === 'open' ? 'Realised margin (not yet realised)' : 'Realised margin'}
            size="lg"
            mono
            tone={marginTone(outcome.realised_margin)}
          >
            {formatMoneyDecimal(outcome.realised_margin)}
          </MetricReadout>
          <MetricReadout label="Days held" size="md" mono tone="muted">
            {outcome.days_held === null
              ? 'Not yet available (no sale recorded)'
              : `${outcome.days_held} day(s) held`}
          </MetricReadout>
        </ReadoutList>
      )}

      <ReadoutList layout="pair" className={styles.evidenceGrid}>
        {lifecycleState === 'skipped' && (
          <MetricReadout label="Skip reason">{outcome.skip_reason}</MetricReadout>
        )}
        {showPurchase && (
          <>
            <MetricReadout label="Purchased at (Asia/Manila)" mono>
              {formatManilaTimestamp(outcome.bought_at)}
            </MetricReadout>
            <MetricReadout label="Purchase price" mono>
              {formatMoneyDecimal(outcome.bought_price)}
            </MetricReadout>
          </>
        )}
        {showSale && (
          <>
            <MetricReadout label="Sold at (Asia/Manila)" mono>
              {formatManilaTimestamp(outcome.sold_at)}
            </MetricReadout>
            <MetricReadout label="Sale price" mono>
              {formatMoneyDecimal(outcome.sold_price)}
            </MetricReadout>
          </>
        )}
      </ReadoutList>
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
          setState({ status: 'forbidden', access: error.access });
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
        setState({ status: 'forbidden', access: error.access });
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
  if (state.status === 'missing') {
    return <EmptyState message={state.detail} />;
  }
  if (state.status === 'invalid') {
    return (
      <section className={`pw-panel ${styles.invalidState}`} aria-labelledby="outcome-invalid-heading">
        <StatusIndicator tone="negative">Operational error</StatusIndicator>
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
    return <LoadingState message="Loading outcome..." />;
  }

  const { outcome } = state;
  const numericDealFlagId = Number(dealFlagId);
  const submitting = operation.status === 'submitting';

  return (
    <article aria-labelledby="outcome-heading">
      <PageHeader
        eyebrow="Outcome workflow"
        title={`Outcome for deal flag ${outcome.deal_flag_id}`}
        titleId="outcome-heading"
      />

      {/* One lifecycle readout, lamp seated in the same chip as its wording. */}
      <p className={`${styles.lifecycle} ${indicatorStyles[LIFECYCLE_TONES[outcome.lifecycle_state]]}`}>
        <span className={indicatorStyles.lamp} aria-hidden="true" />
        Current state: {lifecycleLabel(outcome.lifecycle_state)}
      </p>

      {operation.successMessage && (
        <p className={styles.success} role="status">{operation.successMessage}</p>
      )}

      {operation.errorMessage && (
        <div className={styles.operationAlert} role="alert">
          <StatusIndicator tone="negative">Operation failed</StatusIndicator>
          <p>{operation.errorMessage}</p>
          {operation.fieldErrors && (
            <ul className={styles.fieldErrors}>
              {Object.entries(operation.fieldErrors).flatMap(([field, messages]) => (
                messages.map((message) => <li key={`${field}-${message}`}>{field}: {message}</li>)
              ))}
            </ul>
          )}
          {operation.reload && (
            <Button small onClick={() => setAttempt((value) => value + 1)}>
              Reload outcome
            </Button>
          )}
        </div>
      )}

      {outcome.lifecycle_state === 'untracked' && (
        <EmptyState
          className={styles.untracked}
          message="No outcome has been recorded for this deal flag yet."
          detail="Record a purchase if you acted on this flag, or skip it with a reason."
        />
      )}

      {outcome.lifecycle_state !== 'untracked' && <OutcomeEvidence outcome={outcome} />}

      <div className={styles.forms}>
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

        {outcome.lifecycle_state === 'untracked' && (
          <SkipForm
            disabled={submitting}
            onSubmit={(reason) => void runOperation(
              () => skipOutcome(numericDealFlagId, reason),
              'Deal flag marked skipped.',
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
            correction
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
            correction
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
