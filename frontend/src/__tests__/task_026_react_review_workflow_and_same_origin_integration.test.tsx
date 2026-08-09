import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { build, resolveConfig } from 'vite';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import type { DealFlag, Page, Sku } from '../api/types';


const CSRF_TOKEN = 'a'.repeat(64);
const REFRESHED_CSRF_TOKEN = 'b'.repeat(64);
const FRONTEND_ROOT = process.cwd();

interface ReviewFixture {
  id: number;
  raw_evidence: {
    raw_title: string;
    normalised_title: string;
    raw_price_text: string;
    source: { id: number; name: string };
    url: string;
    occurred_at: string | null;
    fetched_at: string;
  };
  derived_listing: {
    price: string | null;
    condition: string | null;
    location: string;
    resolution_method: string;
    resolution_confidence: string;
    resolved_at: string;
    reviewed_unresolved_at: string | null;
    observed_at: string | null;
    price_kind: string | null;
    trade_side: string | null;
  };
  current_sku: Pick<Sku, 'id' | 'brand' | 'model' | 'variant' | 'category'> | null;
}

const SKU: Sku = {
  id: 7,
  brand: 'NVIDIA',
  model: 'RTX 4070',
  variant: '',
  category: 'gpu',
  launch_msrp: '34995.00',
  launch_date: '2023-04-13',
};

const REVIEW: ReviewFixture = {
  id: 11,
  raw_evidence: {
    raw_title: '  ASUS RTX 4070—SUPER 12GB  ',
    normalised_title: 'asus rtx 4070 super 12gb',
    raw_price_text: 'PHP 15,500 asking',
    source: { id: 3, name: 'manual_capture' },
    url: 'https://task026.example.invalid/listing-11',
    occurred_at: '2026-08-08T03:04:05Z',
    fetched_at: '2026-08-09T04:05:06Z',
  },
  derived_listing: {
    price: '15500.00',
    condition: 'used',
    location: 'Metro Manila',
    resolution_method: 'unresolved',
    resolution_confidence: '0.0000',
    resolved_at: '2026-08-09T05:06:07Z',
    reviewed_unresolved_at: null,
    observed_at: '2026-08-08T03:04:05Z',
    price_kind: 'asking',
    trade_side: null,
  },
  current_sku: null,
};

const CONFIRMED_REVIEW: ReviewFixture = {
  ...REVIEW,
  id: 12,
  derived_listing: {
    ...REVIEW.derived_listing,
    resolution_method: 'human_confirmed',
    resolution_confidence: '1.0000',
  },
  current_sku: {
    id: SKU.id,
    brand: SKU.brand,
    model: SKU.model,
    variant: SKU.variant,
    category: SKU.category,
  },
};


function page<T>(results: T[], overrides: Partial<Page<T>> = {}): Page<T> {
  return {
    count: results.length,
    next: null,
    previous: null,
    results,
    ...overrides,
  };
}


function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}


function requestUrl(input: RequestInfo | URL): string {
  return input instanceof Request ? input.url : String(input);
}


function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}


function findCall(fetchMock: ReturnType<typeof vi.fn>, expectedPath: string) {
  const call = fetchMock.mock.calls.find(([input]) => requestUrl(input) === expectedPath);
  expect(call, `Expected request to ${expectedPath}`).toBeDefined();
  return call as [RequestInfo | URL, RequestInit];
}


function expectSafeSameOrigin(call: [RequestInfo | URL, RequestInit]) {
  expect(call[1]).toMatchObject({
    method: 'GET',
    credentials: 'same-origin',
  });
  expect(call[1].body).toBeUndefined();
  expect(new Headers(call[1].headers).has('X-CSRFToken')).toBe(false);
}


function expectUnsafeSameOriginJson(
  call: [RequestInfo | URL, RequestInit],
  body: unknown,
  csrfToken = CSRF_TOKEN,
) {
  const headers = new Headers(call[1].headers);
  expect(call[1]).toMatchObject({
    method: 'POST',
    credentials: 'same-origin',
  });
  expect(headers.get('Content-Type')).toBe('application/json');
  expect(headers.get('X-CSRFToken')).toBe(csrfToken);
  expect(JSON.parse(String(call[1].body))).toEqual(body);
}


function reviewFetch(
  fetchMock: ReturnType<typeof vi.fn>,
  review = REVIEW,
  operation?: () => Promise<Response>,
) {
  fetchMock.mockImplementation((input: RequestInfo | URL) => {
    const url = requestUrl(input);
    if (url === '/api/v1/session/csrf/') {
      return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
    }
    if (url === `/api/v1/reviews/listings/${review.id}/`) {
      return Promise.resolve(jsonResponse(review));
    }
    if (url === '/api/v1/skus/?q=RTX+4070' || url === '/api/v1/skus/?q=RTX%204070') {
      return Promise.resolve(jsonResponse(page([SKU])));
    }
    if (url === `/api/v1/reviews/listings/${review.id}/confirm-sku/`) {
      return operation?.() ?? Promise.resolve(jsonResponse({
        operation: 'confirm_sku',
        listing_id: review.id,
        sku_id: SKU.id,
        resolution_method: 'human_confirmed',
        resolution_confidence: '1.0000',
        resolved_at: '2026-08-09T06:07:08Z',
        reviewed_unresolved_at: null,
        alias_status: 'not_requested',
      }));
    }
    if (url === `/api/v1/reviews/listings/${review.id}/mark-reviewed-unresolved/`) {
      return operation?.() ?? Promise.resolve(jsonResponse({
        operation: 'mark_reviewed_unresolved',
        listing_id: review.id,
        reviewed_unresolved_at: '2026-08-09T06:07:08Z',
      }));
    }
    if (url === '/api/v1/reviews/listings/') {
      return Promise.resolve(jsonResponse(page([])));
    }
    throw new Error(`Unexpected TASK_026 request: ${url}`);
  });
}


describe('TASK_026 review queue and navigation', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders the server-ordered queue with raw, derived, and curated evidence separated', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
      }
      if (url === '/api/v1/reviews/listings/') {
        return Promise.resolve(jsonResponse(page([REVIEW])));
      }
      throw new Error(`Unexpected TASK_026 request: ${url}`);
    });

    renderAt('/reviews');

    expect(screen.getByText('Loading review queue...')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Review queue' })).toBeInTheDocument();
    const article = screen.getByRole('article');
    const raw = within(article).getByRole('region', { name: 'Raw source evidence' });
    const derived = within(article).getByRole('region', { name: 'Derived listing state' });
    const current = within(article).getByRole('region', { name: 'Current curated SKU' });

    expect(within(raw).getByText('ASUS RTX 4070—SUPER 12GB', { exact: false })).toBeInTheDocument();
    expect(within(raw).getByText('asus rtx 4070 super 12gb')).toBeInTheDocument();
    expect(within(raw).getByText('PHP 15,500 asking')).toBeInTheDocument();
    expect(within(raw).getByText('manual_capture')).toBeInTheDocument();
    expect(within(derived).getByText('₱15,500.00')).toBeInTheDocument();
    expect(within(derived).getByText('Unresolved')).toBeInTheDocument();
    expect(within(derived).getByText('0.0000')).toBeInTheDocument();
    expect(within(current).getByText('No SKU currently assigned.')).toBeInTheDocument();
    expect(article).not.toHaveTextContent(/private seller|payload/i);
    expect(within(article).getByRole('link', { name: 'Review listing 11' })).toHaveAttribute(
      'href',
      '/reviews/11',
    );
    expectSafeSameOrigin(findCall(fetchMock, '/api/v1/reviews/listings/'));
    expectSafeSameOrigin(findCall(fetchMock, '/api/v1/session/csrf/'));
    expect(screen.getByRole('link', { name: 'Review' })).toHaveAttribute('href', '/reviews');
  });

  it('follows bounded queue pages and distinguishes empty, access, and failure states', async () => {
    const next = `${window.location.origin}/api/v1/reviews/listings/?page=2`;
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ csrf_token: CSRF_TOKEN }))
      .mockResolvedValueOnce(jsonResponse(page([REVIEW], { count: 1, next })))
      .mockResolvedValueOnce(jsonResponse(page([], { count: 1, previous: '/api/v1/reviews/listings/' })));
    const user = userEvent.setup();

    const first = renderAt('/reviews');
    await screen.findByRole('article');
    await user.click(screen.getByRole('button', { name: 'Next review listings' }));
    expect(await screen.findByText('No listings are waiting for review.')).toBeInTheDocument();
    expectSafeSameOrigin(findCall(fetchMock, '/api/v1/reviews/listings/?page=2'));
    first.unmount();

    fetchMock.mockReset();
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
      }
      return Promise.resolve(jsonResponse({ detail: 'Forbidden' }, 403));
    });
    const forbidden = renderAt('/reviews');
    expect(await screen.findByText('Access required')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /sign in to pricewatch ph/i })).toHaveAttribute(
      'href',
      '/auth/login/?next=%2Freviews',
    );
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
    forbidden.unmount();

    fetchMock.mockReset();
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      if (requestUrl(input) === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
      }
      return Promise.reject(new TypeError('network unavailable'));
    });
    renderAt('/reviews');
    expect(await screen.findByText('Review queue could not be loaded.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry review queue' })).toBeInTheDocument();
  });
});


describe('TASK_026 review decisions', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('searches existing SKUs and confirms with explicit alias opt-in and CSRF', async () => {
    reviewFetch(fetchMock, REVIEW, () => Promise.resolve(jsonResponse({
      operation: 'confirm_sku',
      listing_id: REVIEW.id,
      sku_id: SKU.id,
      resolution_method: 'human_confirmed',
      resolution_confidence: '1.0000',
      resolved_at: '2026-08-09T06:07:08Z',
      reviewed_unresolved_at: null,
      alias_status: 'created',
    })));
    const user = userEvent.setup();

    renderAt('/reviews/11');
    expect(await screen.findByRole('heading', { name: 'Review listing 11' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Raw source evidence' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Derived listing state' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Current curated SKU' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Curated SKU choice' })).toBeInTheDocument();

    await user.type(screen.getByRole('searchbox', { name: 'Search existing SKUs' }), 'RTX 4070');
    await user.click(screen.getByRole('button', { name: 'Search catalogue' }));
    await user.click(await screen.findByRole('radio', { name: 'NVIDIA RTX 4070' }));
    const alias = screen.getByRole('checkbox', { name: /create exact alias/i });
    expect(alias).not.toBeChecked();
    expect(screen.getByText(REVIEW.raw_evidence.raw_title.trim(), { exact: false })).toBeInTheDocument();
    await user.click(alias);
    await user.click(screen.getByRole('button', { name: 'Confirm selected SKU' }));

    expect(await screen.findByText('SKU confirmed and exact alias created.')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Review queue' })).toBeInTheDocument();
    const searchCall = fetchMock.mock.calls.find(([input]) => {
      const url = new URL(requestUrl(input), window.location.origin);
      return url.pathname === '/api/v1/skus/' && url.searchParams.get('q') === 'RTX 4070';
    });
    expect(searchCall).toBeDefined();
    expectSafeSameOrigin(searchCall as [RequestInfo | URL, RequestInit]);
    expectUnsafeSameOriginJson(
      findCall(fetchMock, '/api/v1/reviews/listings/11/confirm-sku/'),
      { sku_id: 7, create_alias: true },
    );
  });

  it('supports explicit correction from an existing current SKU without changing TASK_025 semantics', async () => {
    reviewFetch(fetchMock, CONFIRMED_REVIEW);
    const user = userEvent.setup();

    renderAt('/reviews/12');
    expect(await screen.findByText('NVIDIA RTX 4070')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Mark reviewed unresolved' })).not.toBeInTheDocument();
    await user.click(screen.getByRole('radio', { name: /keep current sku.*nvidia rtx 4070/i }));
    await user.click(screen.getByRole('button', { name: 'Confirm selected SKU' }));

    expect(await screen.findByText('SKU confirmed.')).toBeInTheDocument();
    expectUnsafeSameOriginJson(
      findCall(fetchMock, '/api/v1/reviews/listings/12/confirm-sku/'),
      { sku_id: 7, create_alias: false },
    );
  });

  it('marks an eligible row reviewed unresolved with an exact empty JSON body', async () => {
    reviewFetch(fetchMock);
    const user = userEvent.setup();

    renderAt('/reviews/11');
    await user.click(await screen.findByRole('button', { name: 'Mark reviewed unresolved' }));

    expect(await screen.findByText('Listing marked reviewed unresolved.')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Review queue' })).toBeInTheDocument();
    expectUnsafeSameOriginJson(
      findCall(fetchMock, '/api/v1/reviews/listings/11/mark-reviewed-unresolved/'),
      {},
    );
  });

  it.each([
    [
      400,
      { code: 'invalid_request', detail: 'Request validation failed.', errors: { sku_id: ['Invalid.'] } },
      'Request validation failed.',
    ],
    [
      404,
      { code: 'sku_not_found', detail: 'SKU not found.' },
      'Selected SKU no longer exists.',
    ],
    [
      409,
      { code: 'alias_conflict', detail: 'The normalized title is already an alias for a different SKU.' },
      'This normalized title is already an alias for another SKU.',
    ],
    [500, { detail: 'Failure' }, 'Review operation could not be completed.'],
  ])('keeps evidence visible for a %s confirmation failure and shows the mapped state', async (
    status,
    responseBody,
    expectedMessage,
  ) => {
    reviewFetch(fetchMock, REVIEW, () => Promise.resolve(jsonResponse(responseBody, status)));
    const user = userEvent.setup();

    renderAt('/reviews/11');
    await user.type(await screen.findByRole('searchbox', { name: 'Search existing SKUs' }), 'RTX 4070');
    await user.click(screen.getByRole('button', { name: 'Search catalogue' }));
    await user.click(await screen.findByRole('radio', { name: 'NVIDIA RTX 4070' }));
    await user.click(screen.getByRole('button', { name: 'Confirm selected SKU' }));

    expect(await screen.findByText(expectedMessage)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Raw source evidence' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Derived listing state' })).toBeInTheDocument();
  });

  it('distinguishes listing missing, stale unresolved state, permission expiry, and network failure', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
      }
      return Promise.resolve(jsonResponse({
        code: 'listing_not_found',
        detail: 'Listing not found.',
      }, 404));
    });
    const missing = renderAt('/reviews/999');
    expect(await screen.findByText('Review listing not found.')).toBeInTheDocument();
    missing.unmount();

    fetchMock.mockReset();
    reviewFetch(fetchMock, REVIEW, () => Promise.resolve(jsonResponse({
      code: 'ineligible_review_state',
      detail: 'Listing is not eligible to be marked reviewed unresolved.',
    }, 409)));
    const user = userEvent.setup();
    const stale = renderAt('/reviews/11');
    await user.click(await screen.findByRole('button', { name: 'Mark reviewed unresolved' }));
    expect(await screen.findByText('This listing changed and can no longer be marked unresolved.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload review evidence' })).toBeInTheDocument();
    stale.unmount();

    fetchMock.mockReset();
    reviewFetch(fetchMock, REVIEW, () => Promise.resolve(jsonResponse({
      code: 'permission_denied',
      detail: 'Active staff status and required permissions are required.',
    }, 403)));
    const forbidden = renderAt('/reviews/11');
    await user.click(await screen.findByRole('button', { name: 'Mark reviewed unresolved' }));
    expect(await screen.findByText('Access required')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Raw source evidence' })).not.toBeInTheDocument();
    forbidden.unmount();

    fetchMock.mockReset();
    reviewFetch(fetchMock, REVIEW, () => Promise.reject(new TypeError('network unavailable')));
    renderAt('/reviews/11');
    await user.click(await screen.findByRole('button', { name: 'Mark reviewed unresolved' }));
    expect(await screen.findByText('Review operation could not be completed.')).toBeInTheDocument();
  });

  it('invalidates protected evidence and bootstraps fresh CSRF before retrying after a mutation 403', async () => {
    let bootstrapCount = 0;
    let mutationCount = 0;
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/session/csrf/') {
        bootstrapCount += 1;
        return Promise.resolve(jsonResponse({
          csrf_token: bootstrapCount === 1 ? CSRF_TOKEN : REFRESHED_CSRF_TOKEN,
        }));
      }
      if (url === '/api/v1/reviews/listings/11/') {
        return Promise.resolve(jsonResponse(REVIEW));
      }
      if (url === '/api/v1/reviews/listings/11/mark-reviewed-unresolved/') {
        mutationCount += 1;
        if (mutationCount === 1) {
          return Promise.resolve(jsonResponse({
            code: 'permission_denied',
            detail: 'Active staff status and required permissions are required.',
          }, 403));
        }
        return Promise.resolve(jsonResponse({
          operation: 'mark_reviewed_unresolved',
          listing_id: 11,
          reviewed_unresolved_at: '2026-08-09T06:07:08Z',
        }));
      }
      if (url === '/api/v1/reviews/listings/') {
        return Promise.resolve(jsonResponse(page([])));
      }
      throw new Error(`Unexpected TASK_026 request: ${url}`);
    });
    const user = userEvent.setup();

    const first = renderAt('/reviews/11');
    await user.click(await screen.findByRole('button', { name: 'Mark reviewed unresolved' }));
    expect(await screen.findByText('Access required')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Raw source evidence' })).not.toBeInTheDocument();
    first.unmount();

    renderAt('/reviews/11');
    await user.click(await screen.findByRole('button', { name: 'Mark reviewed unresolved' }));
    expect(await screen.findByText('Listing marked reviewed unresolved.')).toBeInTheDocument();

    const bootstrapCalls = fetchMock.mock.calls.filter(
      ([input]) => requestUrl(input) === '/api/v1/session/csrf/',
    );
    const mutationCalls = fetchMock.mock.calls.filter(
      ([input]) => requestUrl(input) === '/api/v1/reviews/listings/11/mark-reviewed-unresolved/',
    ) as [RequestInfo | URL, RequestInit][];
    expect(bootstrapCalls).toHaveLength(2);
    expect(mutationCalls).toHaveLength(2);
    expectUnsafeSameOriginJson(mutationCalls[0], {}, CSRF_TOKEN);
    expectUnsafeSameOriginJson(mutationCalls[1], {}, REFRESHED_CSRF_TOKEN);
    const requestPaths = fetchMock.mock.calls.map(([input]) => requestUrl(input));
    expect(requestPaths.lastIndexOf('/api/v1/session/csrf/')).toBeLessThan(
      requestPaths.lastIndexOf('/api/v1/reviews/listings/11/mark-reviewed-unresolved/'),
    );
  });
});


describe('TASK_026 auth and existing product integration', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('posts logout with CSRF and navigates the browser to the product login', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
      }
      if (url === '/api/v1/reviews/listings/') {
        return Promise.resolve(jsonResponse(page([])));
      }
      if (url === '/auth/logout/') {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      throw new Error(`Unexpected TASK_026 request: ${url}`);
    });
    const user = userEvent.setup();

    renderAt('/reviews');
    await screen.findByRole('heading', { name: 'Review queue' });
    const realWindow = window;
    let navigatedTo: string | null = null;
    const testLocation = {
      origin: realWindow.location.origin,
      pathname: realWindow.location.pathname,
      search: realWindow.location.search,
      get href() {
        return realWindow.location.href;
      },
      set href(value: string) {
        navigatedTo = value;
      },
      assign(value: string) {
        navigatedTo = value;
      },
      replace(value: string) {
        navigatedTo = value;
      },
    };
    vi.stubGlobal('window', new Proxy(realWindow, {
      get(target, property) {
        if (property === 'location') {
          return testLocation;
        }
        const value = Reflect.get(target, property, target);
        return typeof value === 'function' ? value.bind(target) : value;
      },
    }));
    await user.click(screen.getByRole('button', { name: 'Sign out' }));

    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => requestUrl(input) === '/auth/logout/')).toBe(true);
    });
    expectUnsafeSameOriginJson(findCall(fetchMock, '/auth/logout/'), {});
    expect(navigatedTo).toBe('/auth/login/');
  });

  it('links persisted deals to the correction route while preserving baseline SKU navigation', async () => {
    const deal: DealFlag = {
      id: 17,
      sku: { id: 7, brand: 'NVIDIA', model: 'RTX 4070', variant: '', category: 'gpu' },
      listing: {
        id: 12,
        sku_id: 7,
        price: '15500.00',
        condition: 'used',
        resolution_confidence: '1.0000',
        resolution_method: 'human_confirmed',
        resolved_at: '2026-08-09T04:05:06Z',
        observed_at: '2026-08-08T03:04:05Z',
        price_kind: 'asking',
        trade_side: null,
      },
      baseline_pricepoint: {
        id: 13,
        sku_id: 7,
        condition: 'used',
        day: '2026-08-08',
        median: '20000.0000',
        p25: '19000.0000',
        p75: '21000.0000',
        n_listings: 7,
        mad: '1500.0000',
        window_start_day: '2026-05-10',
        window_end_day: '2026-08-08',
        calculated_at: '2026-08-08T16:30:00Z',
        calculation_contract_version: 'asking_price_baseline_v1',
      },
      score: '-3.2500',
      reason: 'asking_price_mad_v1',
      flagged_at: '2026-08-09T05:06:07Z',
    };
    fetchMock.mockResolvedValue(jsonResponse(page([deal])));

    renderAt('/deals');

    const article = await screen.findByRole('article');
    expect(within(article).getByRole('link', { name: 'NVIDIA RTX 4070' })).toHaveAttribute(
      'href',
      '/skus/7',
    );
    expect(within(article).getByRole('link', { name: 'Review or correct SKU' })).toHaveAttribute(
      'href',
      '/reviews/12',
    );
  });
});


describe('TASK_026 Vite development and production integration', () => {
  it('keeps root development routes and builds production assets under the static prefix', async () => {
    const configFile = join(FRONTEND_ROOT, 'vite.config.ts');
    const development = await resolveConfig(
      { root: FRONTEND_ROOT, configFile, logLevel: 'silent' },
      'serve',
    );
    const production = await resolveConfig(
      { root: FRONTEND_ROOT, configFile, logLevel: 'silent' },
      'build',
    );

    expect(development.base).toBe('/');
    expect(production.base).toBe('/static/frontend/');
    const proxyPaths = Object.keys(development.server.proxy ?? {});
    expect(proxyPaths).toEqual(expect.arrayContaining([
      '/api',
      '/admin',
      '/auth',
      '/static',
    ]));
    const proxy = development.server.proxy ?? {};
    const apiProxy = proxy['/api'];
    expect(apiProxy).toBeDefined();
    const djangoTarget = typeof apiProxy === 'string' ? apiProxy : apiProxy?.target;
    for (const path of ['/admin', '/auth', '/static']) {
      const configured = proxy[path];
      expect(typeof configured === 'string' ? configured : configured?.target).toBe(djangoTarget);
    }

    const outDir = await mkdtemp(join(tmpdir(), 'pricewatchph-task026-vite-'));
    try {
      await build({
        root: FRONTEND_ROOT,
        configFile,
        logLevel: 'silent',
        build: { outDir, emptyOutDir: true },
      });
      const index = await readFile(join(outDir, 'index.html'), 'utf8');
      const assetUrls = [...index.matchAll(/(?:src|href)="([^"]+)"/g)]
        .map((match) => match[1]);
      expect(assetUrls.length).toBeGreaterThan(0);
      expect(assetUrls.every(
        (url) => url.startsWith('/static/frontend/assets/'),
      )).toBe(true);
    } finally {
      await rm(outDir, { recursive: true, force: true });
    }
  });
});
