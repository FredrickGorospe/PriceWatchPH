import type { ReactNode } from 'react';

import type { Tone } from './StatusIndicator';
import indicatorStyles from './StatusIndicator.module.css';
import styles from './MetricReadout.module.css';


export type ReadoutTone = 'positive' | 'caution' | 'negative' | 'accent' | 'muted';

interface ReadoutListProps {
  /**
   * `grid` for dense audit evidence, `strip` for the dominant readouts on an
   * instrument face, `pair` for two-up recorded values.
   */
  layout?: 'grid' | 'strip' | 'pair';
  children: ReactNode;
  className?: string;
  'aria-label'?: string;
}

export function ReadoutList({
  layout = 'grid',
  children,
  className,
  ...rest
}: ReadoutListProps) {
  return (
    <dl className={[styles.list, styles[layout], className].filter(Boolean).join(' ')} {...rest}>
      {children}
    </dl>
  );
}

interface MetricReadoutProps {
  label: string;
  children: ReactNode;
  size?: 'sm' | 'md' | 'lg';
  tone?: ReadoutTone;
  /** Machine-produced values (money, scores, identifiers) read better mono. */
  mono?: boolean;
  /** Seats an indicator lamp beside the value; the value itself still says it. */
  lamp?: Tone;
  hint?: ReactNode;
  className?: string;
}

export default function MetricReadout({
  label,
  children,
  size = 'sm',
  tone,
  mono,
  lamp,
  hint,
  className,
}: MetricReadoutProps) {
  const classes = [
    styles.readout,
    styles[size],
    tone ? styles[tone] : null,
    className,
  ].filter(Boolean).join(' ');

  return (
    <div className={classes}>
      <dt className={styles.label}>{label}</dt>
      <dd
        className={[
          styles.value,
          mono ? styles.mono : null,
          lamp ? styles.lamped : null,
        ].filter(Boolean).join(' ')}
      >
        {lamp !== undefined && (
          <span className={`${indicatorStyles[lamp]} ${styles.lampSlot}`} aria-hidden="true">
            <span className={indicatorStyles.lamp} />
          </span>
        )}
        {children}
        {hint !== undefined && <span className={styles.hint}>{hint}</span>}
      </dd>
    </div>
  );
}
