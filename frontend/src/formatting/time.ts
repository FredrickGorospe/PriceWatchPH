import type { ISODateString, UTCDateTimeString } from '../api/types';


const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
] as const;

const manilaFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: 'Asia/Manila',
  year: 'numeric',
  month: 'short',
  day: '2-digit',
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
  hour12: true,
});

export function formatDateOnly(value: ISODateString | null): string {
  if (value === null) {
    return 'Unavailable';
  }

  // Date-only evidence is already bucketed in Manila and must never become an instant.
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    return value;
  }

  const [, year, monthText, day] = match;
  const month = MONTHS[Number.parseInt(monthText, 10) - 1];
  return month ? `${day} ${month} ${year}` : value;
}

export function formatManilaTimestamp(value: UTCDateTimeString | null): string {
  if (value === null) {
    return 'Unavailable';
  }

  const parts = new Map(
    manilaFormatter
      .formatToParts(new Date(value))
      .map((part) => [part.type, part.value]),
  );

  return [
    `${parts.get('day')} ${parts.get('month')} ${parts.get('year')}`,
    `${parts.get('hour')}:${parts.get('minute')}:${parts.get('second')} ${parts.get('dayPeriod')?.toUpperCase()}`,
  ].join(', ') + ' (Asia/Manila)';
}
