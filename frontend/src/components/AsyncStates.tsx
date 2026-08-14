import type { ReactNode } from 'react';
import { useLocation } from 'react-router';

import type { AccessDisposition } from '../api/client';
import Button from './Button';
import StatusIndicator from './StatusIndicator';
import styles from './AsyncStates.module.css';


export function AccessRequiredState({ access = 'unknown' }: { access?: AccessDisposition }) {
  const location = useLocation();
  const returnPath = `${location.pathname}${location.search}`;
  const loginUrl = `/auth/login/?next=${encodeURIComponent(returnPath)}`;

  if (access === 'unauthenticated') {
    return (
      <section className={`pw-panel ${styles.state}`} role="status" aria-labelledby="sign-in-heading">
        <div className={styles.stateHead}>
          <StatusIndicator tone="caution">Session required</StatusIndicator>
        </div>
        <h1 id="sign-in-heading">Sign in required</h1>
        <p>
          Sign in with an authorized PriceWatch PH staff account to continue.
        </p>
        <div className={styles.actions}>
          <a className={styles.primaryLink} href={loginUrl}>Sign in to PriceWatch PH</a>
        </div>
        <p className={styles.secondaryText}>
          Accounts and permissions are managed by a PriceWatch PH administrator.
        </p>
      </section>
    );
  }

  if (access === 'unauthorized') {
    return (
      <section className={`pw-panel ${styles.state}`} role="status" aria-labelledby="access-heading">
        <div className={styles.stateHead}>
          <StatusIndicator tone="negative">Permission denied</StatusIndicator>
        </div>
        <h1 id="access-heading">Access required</h1>
        <p>
          Your account is signed in, but it does not have the staff status or model
          permissions required for this area.
        </p>
        <p className={styles.secondaryText}>
          Ask a PriceWatch PH administrator to review your access, then reload this page.
        </p>
      </section>
    );
  }

  return (
    <section className={`pw-panel ${styles.state}`} role="status" aria-labelledby="access-heading">
      <div className={styles.stateHead}>
        <StatusIndicator tone="caution">Permission required</StatusIndicator>
      </div>
      <h1 id="access-heading">Access required</h1>
      <p>
        An active staff session and the required view permissions are needed to see
        this persisted evidence.
      </p>
      <div className={styles.actions}>
        <a className={styles.primaryLink} href={loginUrl}>Sign in to PriceWatch PH</a>
        <a href="/admin/login/">Django admin sign-in</a>
      </div>
      <p className={styles.secondaryText}>
        Already signed in? Request access, or reload after your permissions change.
      </p>
    </section>
  );
}

interface RequestFailureStateProps {
  title: string;
  retryLabel: string;
  onRetry: () => void;
}

export function RequestFailureState({
  title,
  retryLabel,
  onRetry,
}: RequestFailureStateProps) {
  return (
    <section className={`pw-panel ${styles.state}`} role="alert">
      <div className={styles.stateHead}>
        <StatusIndicator tone="negative">Request failed</StatusIndicator>
      </div>
      <h2>{title}</h2>
      <p>The persisted evidence is unchanged. Try the request again.</p>
      <div className={styles.actions}>
        <Button variant="primary" onClick={onRetry}>{retryLabel}</Button>
      </div>
    </section>
  );
}

interface LoadingStateProps {
  /** Exact wording stays the accessible status text for this request. */
  message: string;
  className?: string;
}

export function LoadingState({ message, className }: LoadingStateProps) {
  return (
    <div className={['pw-well', styles.transient, className].filter(Boolean).join(' ')} role="status">
      <div className={styles.transientBody}>
        <span className={styles.scanner} aria-hidden="true" />
        <p className={styles.message}>{message}</p>
      </div>
    </div>
  );
}

interface EmptyStateProps {
  message: string;
  detail?: ReactNode;
  className?: string;
}

export function EmptyState({ message, detail, className }: EmptyStateProps) {
  return (
    <div className={['pw-well', styles.transient, className].filter(Boolean).join(' ')} role="status">
      <div className={styles.transientBody}>
        <span className={styles.emptyMark} aria-hidden="true">∅</span>
        <p className={styles.message}>{message}</p>
        {detail !== undefined && <p className={styles.detail}>{detail}</p>}
      </div>
    </div>
  );
}
