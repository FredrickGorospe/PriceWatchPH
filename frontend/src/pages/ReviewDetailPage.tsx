import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router';

import {
  bootstrapCsrf,
  confirmReviewSku,
  getReviewListing,
  getSkuSearchPage,
  isCancelledRequest,
  markReviewUnresolved,
  ReviewApiError,
  searchSkus,
} from '../api/client';
import type { Page, ReviewListing, Sku } from '../api/types';
import { AccessRequiredState, RequestFailureState } from '../components/AsyncStates';
import ReviewEvidence from '../components/ReviewEvidence';
import { skuDisplayName } from '../formatting/sku';
import styles from './ReviewPages.module.css';


type DetailState =
  | { status: 'loading' }
  | { status: 'success'; review: ReviewListing }
  | { status: 'forbidden' }
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
          setState({ status: 'forbidden' });
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
        setState({ status: 'forbidden' });
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
        setState({ status: 'forbidden' });
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
        setState({ status: 'forbidden' });
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
        setState({ status: 'forbidden' });
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

  if (state.status === 'forbidden') {
    return <AccessRequiredState />;
  }
  if (state.status === 'missing') {
    return <p className={styles.status} role="status">Review listing not found.</p>;
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
    return <p className={styles.status} role="status">Loading review evidence...</p>;
  }

  const review = state.review;
  const canMarkUnresolved = review.current_sku === null
    && ['unresolved', 'fuzzy_match'].includes(review.derived_listing.resolution_method);

  return (
    <article aria-labelledby="review-detail-heading">
      <header className={styles.pageHeading}>
        <div>
          <p className={styles.eyebrow}>Human review</p>
          <h1 id="review-detail-heading">Review listing {review.id}</h1>
        </div>
      </header>

      <ReviewEvidence review={review} />

      <section className={styles.choice} aria-label="Curated SKU choice">
        <h2>Curated SKU choice</h2>
        {review.current_sku !== null && (
          <label className={styles.option}>
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
          <label>
            <span>Search existing SKUs</span>
            <input
              type="search"
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
            />
          </label>
          <button type="button" onClick={() => void runSearch()}>Search catalogue</button>
        </div>

        {searchState.status === 'loading' && <p role="status">Searching catalogue...</p>}
        {searchState.status === 'error' && <p role="alert">{searchState.message}</p>}
        {searchState.status === 'success' && searchState.page.results.length === 0 && (
          <p role="status">No matching SKUs found.</p>
        )}
        {searchState.status === 'success' && searchState.page.results.length > 0 && (
          <div className={styles.results}>
            {searchState.page.results.map((sku) => (
              <label className={styles.option} key={sku.id}>
                <input
                  type="radio"
                  name="sku-choice"
                  checked={selectedSku?.id === sku.id}
                  onChange={() => setSelectedSku(sku)}
                />
                {skuDisplayName(sku)}
              </label>
            ))}
            <div className={styles.searchPagination}>
              <button
                type="button"
                disabled={searchState.page.previous === null}
                onClick={() => searchState.page.previous
                  && void loadSearchPage(searchState.page.previous)}
              >
                Previous SKU results
              </button>
              <button
                type="button"
                disabled={searchState.page.next === null}
                onClick={() => searchState.page.next
                  && void loadSearchPage(searchState.page.next)}
              >
                Next SKU results
              </button>
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
          <div role="alert">
            <p>{operation.message}</p>
            {operation.fieldErrors && (
              <ul>
                {Object.entries(operation.fieldErrors).flatMap(([field, messages]) => (
                  messages.map((message) => <li key={`${field}-${message}`}>{field}: {message}</li>)
                ))}
              </ul>
            )}
            {operation.reload && (
              <button type="button" onClick={() => setAttempt((value) => value + 1)}>
                Reload review evidence
              </button>
            )}
          </div>
        )}

        <div className={styles.actions}>
          <button
            type="button"
            disabled={operation.status === 'submitting'}
            onClick={() => void confirm(review)}
          >
            Confirm selected SKU
          </button>
          {canMarkUnresolved && (
            <button
              type="button"
              disabled={operation.status === 'submitting'}
              onClick={() => void markUnresolved(review)}
            >
              Mark reviewed unresolved
            </button>
          )}
        </div>
      </section>
    </article>
  );
}
