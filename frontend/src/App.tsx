import { Link, Navigate, Route, Routes } from 'react-router';

import DealFeedPage from './pages/DealFeedPage';
import SkuDetailPage from './pages/SkuDetailPage';
import styles from './App.module.css';


function NotFoundPage() {
  return (
    <section className={styles.notFound} aria-labelledby="not-found-heading">
      <p className={styles.eyebrow}>404</p>
      <h1 id="not-found-heading">Page not found</h1>
      <p>The requested PriceWatch PH page is not part of this experience.</p>
      <Link className={styles.primaryLink} to="/deals">Return to deals</Link>
    </section>
  );
}

export default function App() {
  return (
    <div className={styles.app}>
      <header className={styles.header}>
        <div className={styles.headerInner}>
          <Link className={styles.brand} to="/deals" aria-label="PriceWatch PH home">
            <span className={styles.brandMark} aria-hidden="true">PW</span>
            <span>PriceWatch PH</span>
          </Link>
          <nav aria-label="Primary navigation">
            <Link className={styles.navLink} to="/deals">Deals</Link>
          </nav>
        </div>
      </header>
      <main className={styles.main}>
        <Routes>
          <Route path="/" element={<Navigate to="/deals" replace />} />
          <Route path="/deals" element={<DealFeedPage />} />
          <Route path="/skus/:skuId" element={<SkuDetailPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
      <footer className={styles.footer}>
        Persisted Philippine PC component pricing evidence
      </footer>
    </div>
  );
}
