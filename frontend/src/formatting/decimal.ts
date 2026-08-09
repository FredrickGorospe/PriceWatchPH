import type { DecimalString } from '../api/types';


export function formatMoneyDecimal(value: DecimalString | null): string {
  if (value === null) {
    return 'Unavailable';
  }

  const match = /^([+-]?)(\d+)(\.\d+)?$/.exec(value);
  if (!match) {
    return value;
  }

  const [, sign, integral, fractional = ''] = match;
  const grouped = integral.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `₱${sign}${grouped}${fractional}`;
}
