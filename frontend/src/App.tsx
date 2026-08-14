import { useState } from 'react';
import { Navigate, NavLink, Route, Routes, useLocation } from 'react-router';

import { logout } from './api/client';
import { AuthUiProvider, useAuthUi, useReportAuthUiState } from './auth/AuthUiContext';
import { LoadingState } from './components/AsyncStates';
import Button, { ButtonLink } from './components/Button';
import StatusIndicator from './components/StatusIndicator';
import DealFeedPage from './pages/DealFeedPage';
import OutcomeWorkflowPage from './pages/OutcomeWorkflowPage';
import ReviewDetailPage from './pages/ReviewDetailPage';
import ReviewQueuePage from './pages/ReviewQueuePage';
import SkuDetailPage from './pages/SkuDetailPage';
import styles from './App.module.css';


function NotFoundPage() {
  useReportAuthUiState('public');

  return (
    <section className={`pw-panel ${styles.notFound}`} aria-labelledby="not-found-heading">
      <p className={styles.eyebrow}>404</p>
      <h1 id="not-found-heading">Page not found</h1>
      <p>The requested PriceWatch PH page is not part of this experience.</p>
      <ButtonLink variant="primary" to="/deals">Return to deals</ButtonLink>
    </section>
  );
}

function SignOutButton({
  onStart,
  onFailure,
}: {
  onStart: () => void;
  onFailure: () => void;
}) {
  const [busy, setBusy] = useState(false);

  async function signOut() {
    setBusy(true);
    onStart();
    try {
      await logout();
      window.location.assign('/auth/login/');
    } catch {
      setBusy(false);
      onFailure();
    }
  }

  return (
    <Button small disabled={busy} onClick={signOut}>
      Sign out
    </Button>
  );
}

function navLinkClass({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink;
}

function AppShell() {
  const location = useLocation();
  const { state: authState } = useAuthUi();
  const [signingOut, setSigningOut] = useState(false);
  const returnPath = `${location.pathname}${location.search}`;
  const loginUrl = `/auth/login/?next=${encodeURIComponent(returnPath)}`;

  return (
    <div className={styles.app}>
      <a className={styles.skipLink} href="#workspace">Skip to content</a>
      <header className={`pw-frost-bar ${styles.header}`}>
        <div className={styles.headerInner}>
          <NavLink className={styles.brand} to="/deals" aria-label="PriceWatch PH home">
            <span className={styles.brandMark} aria-hidden="true">PW</span>
            <span className={styles.brandText}>
              <span>PriceWatch PH</span>
              <span className={styles.brandSub}>Market instrument</span>
            </span>
          </NavLink>
          <div className={styles.headerControls}>
            {(authState === 'authorized' || authState === 'public') && !signingOut && (
              <>
                <nav className={styles.navRail} aria-label="Primary navigation">
                  <NavLink className={navLinkClass} to="/deals">Deals</NavLink>
                  <NavLink className={navLinkClass} to="/reviews">Review</NavLink>
                </nav>
                {authState === 'authorized' && (
                  <SignOutButton
                    onStart={() => setSigningOut(true)}
                    onFailure={() => setSigningOut(false)}
                  />
                )}
              </>
            )}
            {authState === 'unauthenticated' && !signingOut && (
              <a className={styles.signInLink} href={loginUrl}>Sign in</a>
            )}
            {authState === 'unauthorized' && !signingOut && (
              <>
                <StatusIndicator tone="negative">Restricted account</StatusIndicator>
                <SignOutButton
                  onStart={() => setSigningOut(true)}
                  onFailure={() => setSigningOut(false)}
                />
              </>
            )}
            {(authState === 'unknown' || signingOut) && (
              <span className={styles.authState} role="status">
                {signingOut ? 'Closing session' : 'Checking session'}
              </span>
            )}
          </div>
        </div>
      </header>
      <main className={styles.main} id="workspace">
        {signingOut ? (
          <LoadingState message="Signing out securely..." />
        ) : (
          <Routes>
            <Route path="/" element={<Navigate to="/deals" replace />} />
            <Route path="/deals" element={<DealFeedPage />} />
            <Route path="/deals/:dealFlagId/outcome" element={<OutcomeWorkflowPage />} />
            <Route path="/skus/:skuId" element={<SkuDetailPage />} />
            <Route path="/reviews" element={<ReviewQueuePage />} />
            <Route path="/reviews/:listingId" element={<ReviewDetailPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        )}
      </main>
      <footer className={styles.footer}>
        <span>Persisted Philippine PC component pricing evidence</span>
        <span className={styles.footerNote}>Timestamps displayed in Asia/Manila</span>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <AuthUiProvider>
      <AppShell />
    </AuthUiProvider>
  );
}
