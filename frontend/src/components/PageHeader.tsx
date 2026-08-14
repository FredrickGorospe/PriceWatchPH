import type { ReactNode } from 'react';

import styles from './PageHeader.module.css';


interface PageHeaderProps {
  eyebrow: string;
  title: string;
  titleId: string;
  /** Rendered at h1 unless the page already owns the document heading. */
  level?: 1 | 2;
  description?: ReactNode;
  aside?: ReactNode;
}

export default function PageHeader({
  eyebrow,
  title,
  titleId,
  level = 1,
  description,
  aside,
}: PageHeaderProps) {
  const Heading = level === 1 ? 'h1' : 'h2';

  return (
    <header className={styles.header}>
      <div className={styles.identity}>
        <p className={styles.eyebrow}>{eyebrow}</p>
        <Heading className={styles.title} id={titleId}>{title}</Heading>
      </div>
      {description !== undefined && <p className={styles.description}>{description}</p>}
      {aside !== undefined && <div className={styles.aside}>{aside}</div>}
    </header>
  );
}
