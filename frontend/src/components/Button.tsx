import type { ButtonHTMLAttributes } from 'react';
import { Link } from 'react-router';
import type { LinkProps } from 'react-router';

import styles from './Button.module.css';


export type ButtonVariant = 'primary' | 'secondary' | 'caution' | 'ghost';

interface ButtonShape {
  variant?: ButtonVariant;
  small?: boolean;
  block?: boolean;
}

function classNames(
  { variant = 'secondary', small, block }: ButtonShape,
  extra?: string,
): string {
  return [
    styles.button,
    styles[variant],
    small ? styles.small : null,
    block ? styles.block : null,
    extra,
  ].filter(Boolean).join(' ');
}

type ButtonProps = ButtonShape & ButtonHTMLAttributes<HTMLButtonElement>;

export default function Button({
  variant,
  small,
  block,
  className,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button className={classNames({ variant, small, block }, className)} type={type} {...rest} />
  );
}

type ButtonLinkProps = ButtonShape & LinkProps;

// Router navigation that is visually a control: same physical affordance, but
// it stays an anchor so middle-click and copy-link keep working.
export function ButtonLink({
  variant,
  small,
  block,
  className,
  ...rest
}: ButtonLinkProps) {
  return <Link className={classNames({ variant, small, block }, className)} {...rest} />;
}
