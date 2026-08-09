import type { DealFlag, ListingCondition, Page, PricePoint, Sku } from './types';


export type ApiErrorKind =
  | 'forbidden'
  | 'not-found'
  | 'server'
  | 'network'
  | 'malformed'
  | 'aborted';

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;

  constructor(kind: ApiErrorKind, message: string, status: number | null = null) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
  }
}

function endpointPathForSku(skuId: string): string {
  return `/api/v1/skus/${encodeURIComponent(skuId)}/`;
}

function historyPathForSku(skuId: string): string {
  return `/api/v1/skus/${encodeURIComponent(skuId)}/price-points/`;
}

function validatedRelativeUrl(input: string, expectedPath: string): string {
  let url: URL;

  try {
    url = new URL(input, window.location.origin);
  } catch {
    throw new ApiError('malformed', 'The API supplied an invalid pagination link.');
  }

  if (
    url.origin !== window.location.origin
    || url.pathname !== expectedPath
    || url.hash !== ''
  ) {
    throw new ApiError(
      'malformed',
      'The API supplied a pagination link outside the expected endpoint.',
    );
  }

  return `${url.pathname}${url.search}`;
}

async function requestJson(
  relativeUrl: string,
  signal?: AbortSignal,
): Promise<unknown> {
  let response: Response;

  try {
    response = await fetch(relativeUrl, {
      method: 'GET',
      credentials: 'same-origin',
      signal,
    });
  } catch (error) {
    if (signal?.aborted || (error instanceof DOMException && error.name === 'AbortError')) {
      throw new ApiError('aborted', 'The request was cancelled.');
    }
    throw new ApiError('network', 'The API request could not reach the server.');
  }

  if (response.status === 403) {
    throw new ApiError('forbidden', 'The API requires staff access.', 403);
  }
  if (response.status === 404) {
    throw new ApiError('not-found', 'The requested API resource does not exist.', 404);
  }
  if (!response.ok) {
    throw new ApiError('server', 'The API request failed.', response.status);
  }

  try {
    return await response.json();
  } catch {
    throw new ApiError('malformed', 'The API returned malformed JSON.', response.status);
  }
}

function isPage(value: unknown): value is Page<unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    Number.isInteger(candidate.count)
    && (candidate.count as number) >= 0
    && Array.isArray(candidate.results)
    && (candidate.next === null || typeof candidate.next === 'string')
    && (candidate.previous === null || typeof candidate.previous === 'string')
  );
}

async function requestPage<T>(
  inputUrl: string,
  expectedPath: string,
  signal?: AbortSignal,
): Promise<Page<T>> {
  const relativeUrl = validatedRelativeUrl(inputUrl, expectedPath);
  const value = await requestJson(relativeUrl, signal);

  if (!isPage(value)) {
    throw new ApiError('malformed', 'The API returned an invalid page envelope.');
  }

  return value as Page<T>;
}

export function isCancelledRequest(error: unknown): boolean {
  return error instanceof ApiError && error.kind === 'aborted';
}

export function getDealFlagPage(
  inputUrl = '/api/v1/deal-flags/',
  signal?: AbortSignal,
): Promise<Page<DealFlag>> {
  return requestPage<DealFlag>(inputUrl, '/api/v1/deal-flags/', signal);
}

export async function getSku(skuId: string, signal?: AbortSignal): Promise<Sku> {
  const path = endpointPathForSku(skuId);
  const value = await requestJson(path, signal);

  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new ApiError('malformed', 'The API returned an invalid SKU response.');
  }

  return value as Sku;
}

export async function getCompletePricePointHistory(
  skuId: string,
  condition: ListingCondition | '',
  signal?: AbortSignal,
): Promise<PricePoint[]> {
  const endpointPath = historyPathForSku(skuId);
  let nextUrl = condition === ''
    ? endpointPath
    : `${endpointPath}?condition=${condition}`;
  const visited = new Set<string>();
  const results: PricePoint[] = [];

  while (nextUrl) {
    const normalizedUrl = validatedRelativeUrl(nextUrl, endpointPath);

    // A repeated link is malformed evidence, not a reason to spin indefinitely.
    if (visited.has(normalizedUrl)) {
      throw new ApiError('malformed', 'The API returned a repeated pagination link.');
    }
    visited.add(normalizedUrl);

    const page = await requestPage<PricePoint>(normalizedUrl, endpointPath, signal);
    results.push(...page.results);
    nextUrl = page.next ?? '';
  }

  return results;
}
