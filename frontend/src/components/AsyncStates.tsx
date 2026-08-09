import styles from './AsyncStates.module.css';


export function AccessRequiredState() {
  return (
    <section className={styles.state} role="status" aria-labelledby="access-heading">
      <p className={styles.eyebrow}>Permission required</p>
      <h1 id="access-heading">Access required</h1>
      <p>
        An active staff session and the required view permissions are needed to see
        this persisted evidence.
      </p>
      <p>
        <a className={styles.primaryLink} href="/admin/login/">Django admin sign-in</a>
      </p>
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
    <section className={styles.state} role="alert">
      <p className={styles.eyebrow}>Request failed</p>
      <h2>{title}</h2>
      <p>The persisted evidence is unchanged. Try the request again.</p>
      <button className={styles.primaryButton} type="button" onClick={onRetry}>
        {retryLabel}
      </button>
    </section>
  );
}
