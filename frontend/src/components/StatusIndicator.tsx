import type { ReactNode } from 'react';

import styles from './StatusIndicator.module.css';


export type Tone = 'accent' | 'positive' | 'caution' | 'negative' | 'neutral';

interface StatusIndicatorProps {
  tone: Tone;
  children: ReactNode;
  /** Drops the bezel so the lamp can sit inside an existing instrument face. */
  bare?: boolean;
  className?: string;
}

// The lamp is decorative reinforcement only: the state is always written out
// as text beside it, so status never depends on colour alone.
export default function StatusIndicator({
  tone,
  children,
  bare,
  className,
}: StatusIndicatorProps) {
  const classes = [styles.indicator, styles[tone], bare ? styles.bare : null, className]
    .filter(Boolean)
    .join(' ');

  return (
    <span className={classes}>
      <span className={styles.lamp} aria-hidden="true" />
      <span className={styles.label}>{children}</span>
    </span>
  );
}
