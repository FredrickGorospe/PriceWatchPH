import type {
  DealFlag,
  ListingCondition,
  Page,
  PricePoint,
  ReviewListing,
  ReviewOperationResponse,
  Sku,
} from './types';


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

export class ReviewApiError extends Error {
  readonly status: number | null;
  readonly code: string | null;
  readonly detail: string | null;
  readonly errors: Record<string, string[]> | null;

  constructor(
    message: string,
    status: number | null = null,
    code: string | null = null,
    detail: string | null = null,
    errors: Record<string, string[]> | null = null,
  ) {
    super(message);
    this.name = 'ReviewApiError';
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.errors = errors;
  }
}

let csrfToken: string | null = null;

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

function reviewEndpointPath(listingId: string | number): string {
  return `/api/v1/reviews/listings/${encodeURIComponent(String(listingId))}/`;
}

async function parseJsonResponse(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ReviewApiError(
      'The server returned malformed JSON.',
      response.status,
    );
  }
}

function responseError(response: Response, value: unknown): ReviewApiError {
  const body = typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
  const code = typeof body.code === 'string' ? body.code : null;
  const detail = typeof body.detail === 'string' ? body.detail : null;
  const errors = typeof body.errors === 'object' && body.errors !== null
    ? body.errors as Record<string, string[]>
    : null;
  return new ReviewApiError(
    detail ?? 'The review request failed.',
    response.status,
    code,
    detail,
    errors,
  );
}

async function reviewGet(relativeUrl: string, signal?: AbortSignal): Promise<unknown> {
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
    throw new ReviewApiError('The review request could not reach the server.');
  }

  if (response.status === 403) {
    clearCsrfToken();
  }
  const value = await parseJsonResponse(response);
  if (!response.ok) {
    throw responseError(response, value);
  }
  return value;
}

async function unsafeJson(
  relativeUrl: string,
  body: unknown,
  token: string,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(relativeUrl, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': token,
      },
      body: JSON.stringify(body),
    });
  } catch {
    throw new ReviewApiError('The review request could not reach the server.');
  }

  if (response.status === 403) {
    clearCsrfToken();
  }
  const value = await parseJsonResponse(response);
  if (!response.ok) {
    throw responseError(response, value);
  }
  return value;
}

export function clearCsrfToken() {
  csrfToken = null;
}

export async function bootstrapCsrf(signal?: AbortSignal): Promise<string> {
  const value = await reviewGet('/api/v1/session/csrf/', signal);
  if (
    typeof value !== 'object'
    || value === null
    || Array.isArray(value)
    || typeof (value as Record<string, unknown>).csrf_token !== 'string'
  ) {
    throw new ReviewApiError('The CSRF bootstrap response was malformed.');
  }
  csrfToken = (value as { csrf_token: string }).csrf_token;
  return csrfToken;
}

async function currentCsrfToken(): Promise<string> {
  return csrfToken ?? bootstrapCsrf();
}

export async function getReviewListingPage(
  inputUrl = '/api/v1/reviews/listings/',
  signal?: AbortSignal,
): Promise<Page<ReviewListing>> {
  const relativeUrl = validatedRelativeUrl(inputUrl, '/api/v1/reviews/listings/');
  const value = await reviewGet(relativeUrl, signal);
  if (!isPage(value)) {
    throw new ReviewApiError('The review queue response was malformed.');
  }
  return value as Page<ReviewListing>;
}

export async function getReviewListing(
  listingId: string,
  signal?: AbortSignal,
): Promise<ReviewListing> {
  const value = await reviewGet(reviewEndpointPath(listingId), signal);
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    throw new ReviewApiError('The review detail response was malformed.');
  }
  return value as ReviewListing;
}

export async function searchSkus(query: string, signal?: AbortSignal): Promise<Page<Sku>> {
  const path = `/api/v1/skus/?${new URLSearchParams({ q: query })}`;
  return getSkuSearchPage(path, signal);
}

export async function getSkuSearchPage(
  inputUrl: string,
  signal?: AbortSignal,
): Promise<Page<Sku>> {
  const path = validatedRelativeUrl(inputUrl, '/api/v1/skus/');
  const value = await reviewGet(path, signal);
  if (!isPage(value)) {
    throw new ReviewApiError('The SKU search response was malformed.');
  }
  return value as Page<Sku>;
}

export async function confirmReviewSku(
  listingId: number,
  skuId: number,
  createAlias: boolean,
): Promise<ReviewOperationResponse> {
  const token = await currentCsrfToken();
  const value = await unsafeJson(
    `${reviewEndpointPath(listingId)}confirm-sku/`,
    { sku_id: skuId, create_alias: createAlias },
    token,
  );
  if (
    typeof value !== 'object'
    || value === null
    || Array.isArray(value)
    || !['not_requested', 'created', 'already_exists'].includes(
      String((value as Record<string, unknown>).alias_status),
    )
  ) {
    throw new ReviewApiError('The review operation response was malformed.');
  }
  return value as ReviewOperationResponse;
}

export async function markReviewUnresolved(listingId: number): Promise<void> {
  const token = await currentCsrfToken();
  const value = await unsafeJson(
    `${reviewEndpointPath(listingId)}mark-reviewed-unresolved/`,
    {},
    token,
  );
  if (
    typeof value !== 'object'
    || value === null
    || Array.isArray(value)
    || (value as Record<string, unknown>).operation !== 'mark_reviewed_unresolved'
  ) {
    throw new ReviewApiError('The review operation response was malformed.');
  }
}

export async function logout(): Promise<void> {
  const token = await currentCsrfToken();
  let response: Response;
  try {
    response = await fetch('/auth/logout/', {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': token,
      },
      body: JSON.stringify({}),
    });
  } catch {
    throw new ReviewApiError('Sign out could not reach the server.');
  }
  if (!response.ok) {
    if (response.status === 403) {
      clearCsrfToken();
    }
    throw new ReviewApiError('Sign out failed.', response.status);
  }
  clearCsrfToken();
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
