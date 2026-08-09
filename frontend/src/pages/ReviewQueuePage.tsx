import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router';

import {
  bootstrapCsrf,
  getReviewListingPage,
  isCancelledRequest,
  ReviewApiError,
} from '../api/client';
import type { Page, ReviewListing } from '../api/types';
import { AccessRequiredState, RequestFailureState } from '../components/AsyncStates';
import ReviewEvidence from '../components/ReviewEvidence';
import styles from './ReviewPages.module.css';


const REVIEW_QUEUE_PATH = '/api/v1/reviews/listings/';

type QueueState =
  | { status: 'loading' }
  | { status: 'success'; page: Page<ReviewListing> }
  | { status: 'forbidden' }
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
          setState({ status: 'forbidden' });
          return;
        }
        setState({ status: 'error' });
      }
    }

    void load();
    return () => controller.abort();
  }, [request]);

  if (state.status === 'forbidden') {
    return <AccessRequiredState />;
  }

  return (
    <section aria-labelledby="review-queue-heading">
      <header className={styles.pageHeading}>
        <div>
          <p className={styles.eyebrow}>Human review</p>
          <h1 id="review-queue-heading">Review queue</h1>
        </div>
        <p>Oldest unresolved source evidence appears first.</p>
      </header>

      {navigationState?.successMessage && (
        <p className={styles.success} role="status">{navigationState.successMessage}</p>
      )}

      {state.status === 'loading' && (
        <p className={styles.status} role="status">Loading review queue...</p>
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
        <p className={styles.status} role="status">No listings are waiting for review.</p>
      )}

      {state.status === 'success' && state.page.results.length > 0 && (
        <>
          <div className={styles.queue}>
            {state.page.results.map((review) => (
              <article className={styles.card} key={review.id}>
                <ReviewEvidence review={review} />
                <p className={styles.cardAction}>
                  <Link to={`/reviews/${review.id}`}>Review listing {review.id}</Link>
                </p>
              </article>
            ))}
          </div>
          <nav className={styles.pagination} aria-label="Review queue pages">
            <button
              type="button"
              aria-label="Previous review listings"
              disabled={state.page.previous === null}
              onClick={() => state.page.previous && setRequest((current) => ({
                url: state.page.previous ?? REVIEW_QUEUE_PATH,
                bootstrap: false,
                attempt: current.attempt + 1,
              }))}
            >
              Previous
            </button>
            <button
              type="button"
              aria-label="Next review listings"
              disabled={state.page.next === null}
              onClick={() => state.page.next && setRequest((current) => ({
                url: state.page.next ?? REVIEW_QUEUE_PATH,
                bootstrap: false,
                attempt: current.attempt + 1,
              }))}
            >
              Next
            </button>
          </nav>
        </>
      )}
    </section>
  );
}
