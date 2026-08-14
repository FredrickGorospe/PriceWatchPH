import { useEffect, useState } from 'react';
import { useLocation } from 'react-router';

import {
  type AccessDisposition,
  bootstrapCsrf,
  getReviewListingPage,
  isCancelledRequest,
  ReviewApiError,
} from '../api/client';
import { useReportAuthUiState } from '../auth/AuthUiContext';
import type { Page, ReviewListing } from '../api/types';
import {
  AccessRequiredState,
  EmptyState,
  LoadingState,
  RequestFailureState,
} from '../components/AsyncStates';
import Button, { ButtonLink } from '../components/Button';
import PageHeader from '../components/PageHeader';
import ReviewEvidence from '../components/ReviewEvidence';
import StatusIndicator from '../components/StatusIndicator';
import styles from './ReviewPages.module.css';


const REVIEW_QUEUE_PATH = '/api/v1/reviews/listings/';

type QueueState =
  | { status: 'loading' }
  | { status: 'success'; page: Page<ReviewListing> }
  | { status: 'forbidden'; access: AccessDisposition }
  | { status: 'error' };

interface QueueRequest {
  url: string;
  bootstrap: boolean;
  attempt: number;
}

interface ReviewNavigationState {
  successMessage?: string;
}

export default function ReviewQueuePage() {
  const location = useLocation();
  const navigationState = location.state as ReviewNavigationState | null;
  const [request, setRequest] = useState<QueueRequest>({
    url: REVIEW_QUEUE_PATH,
    // A successful in-app mutation already has a valid in-memory token.
    bootstrap: navigationState?.successMessage === undefined,
    attempt: 0,
  });
  const [state, setState] = useState<QueueState>({ status: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: 'loading' });

    async function load() {
      try {
        if (request.bootstrap) {
          await bootstrapCsrf(controller.signal);
        }
        const page = await getReviewListingPage(request.url, controller.signal);
        setState({ status: 'success', page });
      } catch (error) {
        if (isCancelledRequest(error)) {
          return;
        }
        if (error instanceof ReviewApiError && error.status === 403) {
          setState({ status: 'forbidden', access: error.access });
          return;
        }
        setState({ status: 'error' });
      }
    }

    void load();
    return () => controller.abort();
  }, [request]);

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
    return <LoadingState message="Loading review queue..." />;
  }

  const queueDepth = state.status === 'success' ? state.page.count : null;

  return (
    <section aria-labelledby="review-queue-heading">
      <PageHeader
        eyebrow="Human review"
        title="Review queue"
        titleId="review-queue-heading"
        description="Oldest unresolved source evidence appears first."
        aside={queueDepth === null ? undefined : (
          <StatusIndicator tone={queueDepth === 0 ? 'neutral' : 'caution'}>
            {`${queueDepth} awaiting review`}
          </StatusIndicator>
        )}
      />

      {navigationState?.successMessage && (
        <p className={styles.success} role="status">{navigationState.successMessage}</p>
      )}

      {state.status === 'error' && (
        <RequestFailureState
          title="Review queue could not be loaded."
          retryLabel="Retry review queue"
          onRetry={() => setRequest((current) => ({
            url: REVIEW_QUEUE_PATH,
            bootstrap: true,
            attempt: current.attempt + 1,
          }))}
        />
      )}

      {state.status === 'success' && state.page.results.length === 0 && (
        <EmptyState
          message="No listings are waiting for review."
          detail="Every ingested listing has been resolved or already reviewed."
        />
      )}

      {state.status === 'success' && state.page.results.length > 0 && (
        <>
          <div className={styles.queue}>
            {state.page.results.map((review) => (
              <article className={`pw-panel ${styles.card}`} key={review.id}>
                <div className={styles.cardHead}>
                  <h2 className={styles.cardTitle}>Listing {review.id}</h2>
                  <ButtonLink variant="primary" small to={`/reviews/${review.id}`}>
                    Review listing {review.id}
                  </ButtonLink>
                </div>
                <ReviewEvidence review={review} />
              </article>
            ))}
          </div>
          <nav className={styles.pagination} aria-label="Review queue pages">
            <Button
              small
              aria-label="Previous review listings"
              disabled={state.page.previous === null}
              onClick={() => state.page.previous && setRequest((current) => ({
                url: state.page.previous ?? REVIEW_QUEUE_PATH,
                bootstrap: false,
                attempt: current.attempt + 1,
              }))}
            >
              Previous
            </Button>
            <Button
              small
              aria-label="Next review listings"
              disabled={state.page.next === null}
              onClick={() => state.page.next && setRequest((current) => ({
                url: state.page.next ?? REVIEW_QUEUE_PATH,
                bootstrap: false,
                attempt: current.attempt + 1,
              }))}
            >
              Next
            </Button>
          </nav>
        </>
      )}
    </section>
  );
}
