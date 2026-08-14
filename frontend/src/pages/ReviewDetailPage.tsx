import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router';

import {
  type AccessDisposition,
  bootstrapCsrf,
  confirmReviewSku,
  getReviewListing,
  getSkuSearchPage,
  isCancelledRequest,
  markReviewUnresolved,
  ReviewApiError,
  searchSkus,
} from '../api/client';
import { useReportAuthUiState } from '../auth/AuthUiContext';
import type { Page, ReviewListing, Sku } from '../api/types';
import {
  AccessRequiredState,
  EmptyState,
  LoadingState,
  RequestFailureState,
} from '../components/AsyncStates';
import Button from '../components/Button';
import Field from '../components/Field';
import PageHeader from '../components/PageHeader';
import ReviewEvidence from '../components/ReviewEvidence';
import StatusIndicator from '../components/StatusIndicator';
import { categoryLabel, skuDisplayName } from '../formatting/sku';
import styles from './ReviewPages.module.css';


type DetailState =
  | { status: 'loading' }
  | { status: 'success'; review: ReviewListing }
  | { status: 'forbidden'; access: AccessDisposition }
  | { status: 'missing' }
  | { status: 'error' };

type SearchState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'success'; page: Page<Sku> }
  | { status: 'error'; message: string };

interface OperationState {
  status: 'idle' | 'submitting' | 'error';
  message?: string;
  reload?: boolean;
  fieldErrors?: Record<string, string[]>;
}

function mappedOperationError(error: ReviewApiError): {
  message: string;
  reload?: boolean;
  clearSelection?: boolean;
} {
  if (error.code === 'sku_not_found') {
    return { message: 'Selected SKU no longer exists.', clearSelection: true };
  }
  if (error.code === 'listing_not_found') {
    return { message: 'Review listing not found.' };
  }
  if (error.code === 'ineligible_review_state') {
    return {
      message: 'This listing changed and can no longer be marked unresolved.',
      reload: true,
    };
  }
  if (error.code === 'alias_conflict') {
    return { message: 'This normalized title is already an alias for another SKU.' };
  }
  if (error.code === 'invalid_request') {
    return { message: error.detail ?? 'Request validation failed.' };
  }
  return { message: 'Review operation could not be completed.' };
}

export default function ReviewDetailPage() {
  const { listingId = '' } = useParams();
  const navigate = useNavigate();
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<DetailState>({ status: 'loading' });
  const [searchText, setSearchText] = useState('');
  const [searchState, setSearchState] = useState<SearchState>({ status: 'idle' });
  const [selectedSku, setSelectedSku] = useState<Sku | null>(null);
  const [createAlias, setCreateAlias] = useState(false);
  const [operation, setOperation] = useState<OperationState>({ status: 'idle' });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });
    setOperation({ status: 'idle' });

    async function load() {
      try {
        await bootstrapCsrf(controller.signal);
        const review = await getReviewListing(listingId, controller.signal);
        setState({ status: 'success', review });
      } catch (error) {
        if (isCancelledRequest(error)) {
          return;
        }
        if (error instanceof ReviewApiError && error.status === 403) {
          setState({ status: 'forbidden', access: error.access });
          return;
        }
        if (
          error instanceof ReviewApiError
          && error.status === 404
          && error.code === 'listing_not_found'
        ) {
          setState({ status: 'missing' });
          return;
        }
        setState({ status: 'error' });
      }
    }

    void load();
    return () => controller.abort();
  }, [attempt, listingId]);

  async function runSearch() {
    const query = searchText.trim();
    if (query.length < 2) {
      setSearchState({ status: 'error', message: 'Enter at least two characters.' });
      return;
    }
    setSearchState({ status: 'loading' });
    try {
      setSearchState({ status: 'success', page: await searchSkus(query) });
    } catch (error) {
      if (error instanceof ReviewApiError && error.status === 403) {
        setState({ status: 'forbidden', access: error.access });
        return;
      }
      setSearchState({ status: 'error', message: 'SKU search could not be loaded.' });
    }
  }

  async function loadSearchPage(url: string) {
    setSearchState({ status: 'loading' });
    try {
      setSearchState({ status: 'success', page: await getSkuSearchPage(url) });
    } catch (error) {
      if (error instanceof ReviewApiError && error.status === 403) {
        setState({ status: 'forbidden', access: error.access });
        return;
      }
      setSearchState({ status: 'error', message: 'SKU search could not be loaded.' });
    }
  }

  async function markUnresolved(review: ReviewListing) {
    setOperation({ status: 'submitting' });
    try {
      await markReviewUnresolved(review.id);
      navigate('/reviews', {
        state: { successMessage: 'Listing marked reviewed unresolved.' },
      });
    } catch (error) {
      if (error instanceof ReviewApiError && error.status === 403) {
        setState({ status: 'forbidden', access: error.access });
        return;
      }
      const mapped = error instanceof ReviewApiError
        ? mappedOperationError(error)
        : { message: 'Review operation could not be completed.' };
      setOperation({ status: 'error', message: mapped.message, reload: mapped.reload });
    }
  }

  async function confirm(review: ReviewListing) {
    const skuId = selectedSku?.id ?? review.current_sku?.id;
    if (skuId === undefined) {
      setOperation({ status: 'error', message: 'Select an existing SKU first.' });
      return;
    }

    setOperation({ status: 'submitting' });
    try {
      const result = await confirmReviewSku(review.id, skuId, createAlias);
      const successMessage = result.alias_status === 'created'
        ? 'SKU confirmed and exact alias created.'
        : result.alias_status === 'already_exists'
          ? 'SKU confirmed; the exact alias already existed.'
          : 'SKU confirmed.';
      navigate('/reviews', { state: { successMessage } });
    } catch (error) {
      if (error instanceof ReviewApiError && error.status === 403) {
        setState({ status: 'forbidden', access: error.access });
        return;
      }
      const mapped = error instanceof ReviewApiError
        ? mappedOperationError(error)
        : { message: 'Review operation could not be completed.' };
      if (mapped.clearSelection) {
        setSelectedSku(null);
      }
      setOperation({
        status: 'error',
        message: mapped.message,
        reload: mapped.reload,
        fieldErrors: error instanceof ReviewApiError
          ? error.errors ?? undefined
          : undefined,
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
    return <EmptyState message="Review listing not found." />;
  }
  if (state.status === 'error') {
    return (
      <RequestFailureState
        title="Review listing could not be loaded."
        retryLabel="Retry review listing"
        onRetry={() => setAttempt((value) => value + 1)}
      />
    );
  }
  if (state.status === 'loading') {
    return <LoadingState message="Loading review evidence..." />;
  }

  const review = state.review;
  const canMarkUnresolved = review.current_sku === null
    && ['unresolved', 'fuzzy_match'].includes(review.derived_listing.resolution_method);
  const submitting = operation.status === 'submitting';
  const selectionSummary = selectedSku !== null
    ? skuDisplayName(selectedSku)
    : review.current_sku !== null
      ? skuDisplayName(review.current_sku)
      : null;

  return (
    <article aria-labelledby="review-detail-heading">
      <PageHeader
        eyebrow="Human review"
        title={`Review listing ${review.id}`}
        titleId="review-detail-heading"
        aside={(
          <StatusIndicator tone={review.current_sku === null ? 'caution' : 'positive'}>
            {review.current_sku === null ? 'Needs a SKU' : 'SKU assigned'}
          </StatusIndicator>
        )}
      />

      <ReviewEvidence review={review} />

      <section className={`pw-panel ${styles.choice}`} aria-label="Curated SKU choice">
        <div className={styles.choiceHead}>
          <h2>Curated SKU choice</h2>
          <p className={styles.choiceHint}>
            Pick the canonical SKU this raw listing really is, then confirm.
          </p>
        </div>

        {review.current_sku !== null && (
          <label className={`pw-well-soft ${styles.option}`}>
            <input
              type="radio"
              name="sku-choice"
              checked={selectedSku === null}
              onChange={() => setSelectedSku(null)}
            />
            Keep current SKU: {skuDisplayName(review.current_sku)}
          </label>
        )}

        <div className={styles.searchControls}>
          <Field
            className={styles.searchField}
            label="Search existing SKUs"
            type="search"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
                void runSearch();
              }
            }}
          />
          <Button className={styles.searchButton} onClick={() => void runSearch()}>
            Search catalogue
          </Button>
        </div>

        {searchState.status === 'loading' && (
          <p className={styles.inlineStatus} role="status">Searching catalogue...</p>
        )}
        {searchState.status === 'error' && (
          <p className={styles.inlineAlert} role="alert">{searchState.message}</p>
        )}
        {searchState.status === 'success' && searchState.page.results.length === 0 && (
          <p className={styles.inlineStatus} role="status">No matching SKUs found.</p>
        )}
        {searchState.status === 'success' && searchState.page.results.length > 0 && (
          <div className={styles.results}>
            {searchState.page.results.map((sku) => (
              <label
                className={`pw-well-soft ${styles.option} ${
                  selectedSku?.id === sku.id ? styles.optionSelected : ''
                }`}
                key={sku.id}
              >
                <input
                  type="radio"
                  name="sku-choice"
                  checked={selectedSku?.id === sku.id}
                  onChange={() => setSelectedSku(sku)}
                />
                {skuDisplayName(sku)}
                <span className={styles.optionMeta} aria-hidden="true">
                  {categoryLabel(sku.category)}
                </span>
              </label>
            ))}
            <div className={styles.searchPagination}>
              <Button
                small
                variant="ghost"
                disabled={searchState.page.previous === null}
                onClick={() => searchState.page.previous
                  && void loadSearchPage(searchState.page.previous)}
              >
                Previous SKU results
              </Button>
              <Button
                small
                variant="ghost"
                disabled={searchState.page.next === null}
                onClick={() => searchState.page.next
                  && void loadSearchPage(searchState.page.next)}
              >
                Next SKU results
              </Button>
            </div>
          </div>
        )}

        <label className={styles.aliasOption}>
          <input
            type="checkbox"
            checked={createAlias}
            onChange={(event) => setCreateAlias(event.target.checked)}
          />
          Create exact alias from the immutable raw title shown above
        </label>

        {operation.status === 'error' && (
          <div className={styles.operationAlert} role="alert">
            <StatusIndicator tone="negative">Operation failed</StatusIndicator>
            <p>{operation.message}</p>
            {operation.fieldErrors && (
              <ul className={styles.fieldErrors}>
                {Object.entries(operation.fieldErrors).flatMap(([field, messages]) => (
                  messages.map((message) => <li key={`${field}-${message}`}>{field}: {message}</li>)
                ))}
              </ul>
            )}
            {operation.reload && (
              <Button small onClick={() => setAttempt((value) => value + 1)}>
                Reload review evidence
              </Button>
            )}
          </div>
        )}

        {/* Frosted action rail: the primary action is never scrolled away. */}
        <div className={`pw-frost ${styles.actions}`}>
          <p className={styles.actionsSummary}>
            {selectionSummary === null
              ? 'No SKU selected yet.'
              : `Confirming: ${selectionSummary}`}
          </p>
          <div className={styles.actionsButtons}>
            {canMarkUnresolved && (
              <Button
                variant="caution"
                disabled={submitting}
                onClick={() => void markUnresolved(review)}
              >
                Mark reviewed unresolved
              </Button>
            )}
            <Button
              variant="primary"
              disabled={submitting}
              onClick={() => void confirm(review)}
            >
              Confirm selected SKU
            </Button>
          </div>
        </div>
      </section>
    </article>
  );
}
