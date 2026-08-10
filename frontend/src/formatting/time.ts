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

const MANILA_UTC_OFFSET_MINUTES = 8 * 60; // Asia/Manila has no DST.

// Interprets a datetime-local input value as Asia/Manila wall-clock time,
// never the browser's local timezone, using only Date's UTC getters/setters.
export function manilaLocalInputToUtcInstant(localValue: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(localValue);
  if (!match) {
    return null;
  }
  const [, year, month, day, hour, minute] = match;
  const utcMillis = Date.UTC(
    Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute),
  ) - MANILA_UTC_OFFSET_MINUTES * 60 * 1000;
  const utc = new Date(utcMillis);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${utc.getUTCFullYear()}-${pad(utc.getUTCMonth() + 1)}-${pad(utc.getUTCDate())}`
    + `T${pad(utc.getUTCHours())}:${pad(utc.getUTCMinutes())}:${pad(utc.getUTCSeconds())}Z`;
}

// Reverse of manilaLocalInputToUtcInstant, for pre-filling correction forms;
// reads only UTC getters off a Date already shifted by the fixed offset.
export function utcInstantToManilaLocalInput(value: UTCDateTimeString | null): string {
  if (value === null) {
    return '';
  }
  const utcMillis = Date.parse(value);
  if (Number.isNaN(utcMillis)) {
    return '';
  }
  const manilaMillis = utcMillis + MANILA_UTC_OFFSET_MINUTES * 60 * 1000;
  const manila = new Date(manilaMillis);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${manila.getUTCFullYear()}-${pad(manila.getUTCMonth() + 1)}-${pad(manila.getUTCDate())}`
    + `T${pad(manila.getUTCHours())}:${pad(manila.getUTCMinutes())}`;
}
