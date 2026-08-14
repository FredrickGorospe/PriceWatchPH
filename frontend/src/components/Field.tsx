import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react';

import styles from './Field.module.css';


interface FieldShell {
  /** Visible label text. It is the control's whole accessible name. */
  label: string;
  hint?: ReactNode;
  invalid?: boolean;
  className?: string;
}

type FieldProps = FieldShell & InputHTMLAttributes<HTMLInputElement> & {
  /** Money, counts and timestamps read better in tabular monospace. */
  numeric?: boolean;
};

export default function Field({
  label,
  hint,
  invalid,
  numeric,
  className,
  ...rest
}: FieldProps) {
  return (
    <div className={[styles.field, className].filter(Boolean).join(' ')}>
      {/* The hint stays outside the label so it never joins the accessible name. */}
      <label className={styles.wrap}>
        <span className={styles.label}>{label}</span>
        <input
          className={[
            styles.control,
            numeric ? styles.numeric : null,
            invalid ? styles.error : null,
          ].filter(Boolean).join(' ')}
          {...rest}
        />
      </label>
      {hint !== undefined && <p className={styles.hint}>{hint}</p>}
    </div>
  );
}

type SelectFieldProps = FieldShell & SelectHTMLAttributes<HTMLSelectElement> & {
  children: ReactNode;
};

export function SelectField({
  label,
  hint,
  invalid,
  className,
  children,
  ...rest
}: SelectFieldProps) {
  return (
    <div className={[styles.field, className].filter(Boolean).join(' ')}>
      <label className={styles.wrap}>
        <span className={styles.label}>{label}</span>
        <select
          className={[
            styles.control,
            styles.select,
            invalid ? styles.error : null,
          ].filter(Boolean).join(' ')}
          {...rest}
        >
          {children}
        </select>
      </label>
      {hint !== undefined && <p className={styles.hint}>{hint}</p>}
    </div>
  );
}
