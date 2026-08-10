import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import type { DealFlag, Page, PricePoint, SkuSummary } from '../api/types';


const CSRF_TOKEN = 'a'.repeat(64);
const REFRESHED_CSRF_TOKEN = 'b'.repeat(64);

interface OutcomeStateFixture {
  deal_flag_id: number;
  outcome_id: number | null;
  lifecycle_state: 'untracked' | 'skipped' | 'open' | 'closed';
  acted: boolean | null;
  skip_reason: string | null;
  bought_at: string | null;
  bought_price: string | null;
  sold_at: string | null;
  sold_price: string | null;
  days_held: number | null;
  realised_margin: string | null;
}

const SKU: SkuSummary = {
  id: 21,
  brand: 'NVIDIA',
  model: 'RTX 4070',
  variant: '',
  category: 'gpu',
};

const PRICEPOINT: PricePoint = {
  id: 9,
  sku_id: 21,
  condition: 'used',
  day: '2026-06-15',
  median: '18000.0000',
  p25: '17000.0000',
  p75: '19000.0000',
  n_listings: 5,
  mad: '1000.0000',
  window_start_day: '2026-03-17',
  window_end_day: '2026-06-15',
  calculated_at: '2026-06-15T06:00:00Z',
  calculation_contract_version: 'asking_price_baseline_v1',
};

const DEAL_FLAG: DealFlag = {
  id: 42,
  sku: SKU,
  listing: {
    id: 55,
    sku_id: 21,
    price: '12500.00',
    condition: 'used',
    resolution_confidence: '1.0000',
    resolution_method: 'exact_alias',
    resolved_at: '2026-06-15T05:00:00Z',
    observed_at: '2026-06-15T04:00:00Z',
    price_kind: 'asking',
    trade_side: null,
  },
  baseline_pricepoint: PRICEPOINT,
  score: '-3.0000',
  reason: 'asking_price_mad_v1',
  flagged_at: '2026-06-15T06:30:00Z',
};

const DEMO_DEAL_FLAG: DealFlag = {
  ...DEAL_FLAG,
  id: 77,
  listing: {
    ...DEAL_FLAG.listing,
    id: 88,
  },
};

const UNTRACKED_OUTCOME: OutcomeStateFixture = {
  deal_flag_id: DEAL_FLAG.id,
  outcome_id: null,
  lifecycle_state: 'untracked',
  acted: null,
  skip_reason: null,
  bought_at: null,
  bought_price: null,
  sold_at: null,
  sold_price: null,
  days_held: null,
  realised_margin: null,
};

const SKIPPED_OUTCOME: OutcomeStateFixture = {
  ...UNTRACKED_OUTCOME,
  outcome_id: 101,
  lifecycle_state: 'skipped',
  acted: false,
  skip_reason: 'already sold by the time I followed up',
};

const OPEN_OUTCOME: OutcomeStateFixture = {
  ...UNTRACKED_OUTCOME,
  outcome_id: 102,
  lifecycle_state: 'open',
  acted: true,
  bought_at: '2026-06-15T04:00:00Z',
  bought_price: '12500.00',
};

const CLOSED_OUTCOME: OutcomeStateFixture = {
  ...OPEN_OUTCOME,
  lifecycle_state: 'closed',
  sold_at: '2026-06-16T04:00:00Z',
  sold_price: '14000.00',
  days_held: 1,
  realised_margin: '1500.00',
};

const CLOSED_LOSS_OUTCOME: OutcomeStateFixture = {
  ...OPEN_OUTCOME,
  outcome_id: 103,
  lifecycle_state: 'closed',
  sold_at: '2026-06-15T10:00:00Z',
  sold_price: '10000.00',
  days_held: 0,
  realised_margin: '-2500.00',
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

function findCalls(fetchMock: ReturnType<typeof vi.fn>, expectedPath: string) {
  return fetchMock.mock.calls.filter(([input]) => requestUrl(input) === expectedPath);
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
  const parsedBody: unknown = JSON.parse(String(call[1].body));
  expect(parsedBody).toEqual(body);
  // Money must travel as JSON strings end to end, never a JSON number.
  if (parsedBody !== null && typeof parsedBody === 'object') {
    for (const [key, value] of Object.entries(parsedBody as Record<string, unknown>)) {
      if (key.endsWith('_price')) {
        expect(typeof value).toBe('string');
      }
    }
  }
}

type OperationSegment =
  | 'skip'
  | 'record-purchase'
  | 'record-sale'
  | 'correct-purchase'
  | 'correct-sale';

interface OutcomeFetchOptions {
  dealFlagId?: number;
  getResponse?: () => Promise<Response>;
  operations?: Partial<Record<OperationSegment, () => Promise<Response>>>;
  extraRoutes?: Record<string, () => Promise<Response>>;
}

function outcomeSuccessBody(
  operation: string,
  outcome: OutcomeStateFixture,
): Record<string, unknown> {
  return { operation, ...outcome };
}

function outcomeFetch(
  fetchMock: ReturnType<typeof vi.fn>,
  initialOutcome: OutcomeStateFixture,
  options: OutcomeFetchOptions = {},
) {
  const dealFlagId = options.dealFlagId ?? DEAL_FLAG.id;
  fetchMock.mockImplementation((input: RequestInfo | URL) => {
    const url = requestUrl(input);
    if (url === '/api/v1/session/csrf/') {
      return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
    }
    if (url === `/api/v1/deal-flags/${dealFlagId}/outcome/`) {
      return options.getResponse?.() ?? Promise.resolve(jsonResponse(initialOutcome));
    }
    const segments: OperationSegment[] = [
      'skip',
      'record-purchase',
      'record-sale',
      'correct-purchase',
      'correct-sale',
    ];
    for (const segment of segments) {
      if (url === `/api/v1/deal-flags/${dealFlagId}/outcome/${segment}/`) {
        const handler = options.operations?.[segment];
        if (handler) {
          return handler();
        }
        return Promise.reject(new Error(`Unexpected TASK_029 operation call: ${segment}`));
      }
    }
    if (url === '/api/v1/deal-flags/') {
      return Promise.resolve(jsonResponse(page([DEAL_FLAG])));
    }
    if (options.extraRoutes?.[url]) {
      return options.extraRoutes[url]();
    }
    throw new Error(`Unexpected TASK_029 request: ${url}`);
  });
}


describe('TASK_029 route and navigation', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('resolves the exact outcome workflow route for a specific deal flag', async () => {
    outcomeFetch(fetchMock, UNTRACKED_OUTCOME);

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);

    expect(
      await screen.findByRole('heading', { name: `Outcome for deal flag ${DEAL_FLAG.id}` }),
    ).toBeInTheDocument();
    expectSafeSameOrigin(findCall(fetchMock, `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/`));
  });

  it('links from the deal feed card to the outcome workflow for that deal flag, without an extra fetch', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
      }
      if (url === '/api/v1/deal-flags/') {
        return Promise.resolve(jsonResponse(page([DEAL_FLAG])));
      }
      throw new Error(`Unexpected TASK_029 deal-feed request: ${url}`);
    });
    const user = userEvent.setup();

    renderAt('/deals');
    const link = await screen.findByRole('link', { name: 'Track outcome' });
    expect(link).toHaveAttribute('href', `/deals/${DEAL_FLAG.id}/outcome`);
    // No outcome fetch is made merely by rendering the feed.
    expect(findCalls(fetchMock, `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/`)).toHaveLength(0);

    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
      }
      if (url === `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/`) {
        return Promise.resolve(jsonResponse(UNTRACKED_OUTCOME));
      }
      throw new Error(`Unexpected TASK_029 request after navigation: ${url}`);
    });
    await user.click(link);
    expect(
      await screen.findByRole('heading', { name: `Outcome for deal flag ${DEAL_FLAG.id}` }),
    ).toBeInTheDocument();
  });

  it('provides a deliberate link back to the deal feed', async () => {
    outcomeFetch(fetchMock, UNTRACKED_OUTCOME);

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    await screen.findByRole('heading', { name: `Outcome for deal flag ${DEAL_FLAG.id}` });

    expect(screen.getByRole('link', { name: 'Back to deal feed' })).toHaveAttribute('href', '/deals');
  });

  it('leaves existing deal, review, and SKU routes reachable', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
      }
      if (url === '/api/v1/deal-flags/') {
        return Promise.resolve(jsonResponse(page([])));
      }
      if (url === '/api/v1/reviews/listings/') {
        return Promise.resolve(jsonResponse(page([])));
      }
      throw new Error(`Unexpected TASK_029 compatibility request: ${url}`);
    });

    const deals = renderAt('/deals');
    expect(await screen.findByRole('heading', { name: 'Deal feed' })).toBeInTheDocument();
    deals.unmount();

    renderAt('/reviews');
    expect(await screen.findByRole('heading', { name: 'Review queue' })).toBeInTheDocument();
  });
});


describe('TASK_029 lifecycle rendering', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('shows a loading state before the initial outcome read resolves', async () => {
    let resolveOutcome: (response: Response) => void = () => {};
    outcomeFetch(fetchMock, UNTRACKED_OUTCOME, {
      getResponse: () => new Promise((resolve) => {
        resolveOutcome = resolve;
      }),
    });

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    expect(screen.getByText('Loading outcome...')).toBeInTheDocument();

    resolveOutcome(jsonResponse(UNTRACKED_OUTCOME));
    await screen.findByRole('heading', { name: `Outcome for deal flag ${DEAL_FLAG.id}` });
  });

  it('renders untracked with skip and record-purchase actions only', async () => {
    outcomeFetch(fetchMock, UNTRACKED_OUTCOME);

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    await screen.findByRole('heading', { name: `Outcome for deal flag ${DEAL_FLAG.id}` });

    expect(screen.getByText('Current state: Untracked')).toBeInTheDocument();
    expect(
      screen.getByText('No outcome has been recorded for this deal flag yet.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Skip this deal flag' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Record purchase' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Record sale' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Correct purchase' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Correct sale' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Outcome evidence' })).not.toBeInTheDocument();
  });

  it('renders skipped with the exact reason and record-purchase only, no unskip action', async () => {
    outcomeFetch(fetchMock, SKIPPED_OUTCOME);

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    await screen.findByRole('heading', { name: `Outcome for deal flag ${DEAL_FLAG.id}` });

    expect(screen.getByText('Current state: Skipped')).toBeInTheDocument();
    const evidence = screen.getByRole('region', { name: 'Outcome evidence' });
    expect(within(evidence).getByText('Skip reason')).toBeInTheDocument();
    expect(
      within(evidence).getByText('already sold by the time I followed up'),
    ).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Record purchase' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Skip this deal flag' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /unskip/i })).not.toBeInTheDocument();
  });

  it('renders open with purchase evidence, unavailable margin and days held, and the right actions', async () => {
    outcomeFetch(fetchMock, OPEN_OUTCOME);

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    await screen.findByRole('heading', { name: `Outcome for deal flag ${DEAL_FLAG.id}` });

    expect(screen.getByText('Current state: Open')).toBeInTheDocument();
    const evidence = screen.getByRole('region', { name: 'Outcome evidence' });
    expect(within(evidence).getByText('₱12,500.00')).toBeInTheDocument();
    expect(within(evidence).getByText('Not yet available (no sale recorded)')).toBeInTheDocument();
    expect(within(evidence).getByText('Realised margin (not yet realised)')).toBeInTheDocument();
    expect(within(evidence).getByText('Unavailable')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Record sale' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Correct purchase' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Skip this deal flag' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Correct sale' })).not.toBeInTheDocument();
  });

  it('renders closed with full evidence, days held, positive margin, and correction actions only', async () => {
    outcomeFetch(fetchMock, CLOSED_OUTCOME);

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    await screen.findByRole('heading', { name: `Outcome for deal flag ${DEAL_FLAG.id}` });

    expect(screen.getByText('Current state: Closed')).toBeInTheDocument();
    const evidence = screen.getByRole('region', { name: 'Outcome evidence' });
    expect(within(evidence).getByText('₱12,500.00')).toBeInTheDocument();
    expect(within(evidence).getByText('₱14,000.00')).toBeInTheDocument();
    expect(within(evidence).getByText('1 day(s) held')).toBeInTheDocument();
    expect(within(evidence).getByText('₱1,500.00')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Correct purchase' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Correct sale' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Record sale' })).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Skip this deal flag' })).not.toBeInTheDocument();
  });

  it('renders a same-Manila-day closed outcome as an explicit zero, not missing data', async () => {
    outcomeFetch(fetchMock, CLOSED_LOSS_OUTCOME);

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    await screen.findByRole('heading', { name: `Outcome for deal flag ${DEAL_FLAG.id}` });

    const evidence = screen.getByRole('region', { name: 'Outcome evidence' });
    expect(within(evidence).getByText('0 day(s) held')).toBeInTheDocument();
    expect(within(evidence).queryByText(/not yet available/i)).not.toBeInTheDocument();
  });

  it('renders a negative realised margin correctly, unclamped and without a fifth lifecycle state', async () => {
    outcomeFetch(fetchMock, CLOSED_LOSS_OUTCOME);

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    await screen.findByRole('heading', { name: `Outcome for deal flag ${DEAL_FLAG.id}` });

    const evidence = screen.getByRole('region', { name: 'Outcome evidence' });
    expect(within(evidence).getByText('₱-2,500.00')).toBeInTheDocument();
    expect(screen.queryByText('₱2,500.00')).not.toBeInTheDocument();
    expect(screen.getByText('Current state: Closed')).toBeInTheDocument();
  });
});


describe('TASK_029 lifecycle transitions', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('skips an untracked deal flag with CSRF and updates the page from the response', async () => {
    outcomeFetch(fetchMock, UNTRACKED_OUTCOME, {
      operations: {
        skip: () => Promise.resolve(jsonResponse(
          outcomeSuccessBody('skip', SKIPPED_OUTCOME),
        )),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    const reasonInput = await screen.findByLabelText('Reason');
    await user.type(reasonInput, 'already sold by the time I followed up');
    await user.click(screen.getByRole('button', { name: 'Skip deal flag' }));

    expect(await screen.findByText('Deal flag marked skipped.')).toBeInTheDocument();
    expect(screen.getByText('Current state: Skipped')).toBeInTheDocument();
    expectUnsafeSameOriginJson(
      findCall(fetchMock, `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/skip/`),
      { skip_reason: 'already sold by the time I followed up' },
    );
  });

  it('records a purchase from untracked with an explicit-offset Manila-local timestamp and string price', async () => {
    outcomeFetch(fetchMock, UNTRACKED_OUTCOME, {
      operations: {
        'record-purchase': () => Promise.resolve(jsonResponse(
          outcomeSuccessBody('record_purchase', OPEN_OUTCOME),
        )),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    const purchaseRegion = await screen.findByRole('region', { name: 'Record purchase' });
    const timestampInput = within(purchaseRegion).getByLabelText('Purchased at (Asia/Manila)');
    const priceInput = within(purchaseRegion).getByLabelText('Purchase price');
    await user.type(timestampInput, '2026-06-15T12:00');
    await user.type(priceInput, '12500.00');
    await user.click(within(purchaseRegion).getByRole('button', { name: 'Record purchase' }));

    expect(await screen.findByText('Purchase recorded.')).toBeInTheDocument();
    expect(screen.getByText('Current state: Open')).toBeInTheDocument();
    expectUnsafeSameOriginJson(
      findCall(fetchMock, `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/record-purchase/`),
      { bought_at: '2026-06-15T04:00:00Z', bought_price: '12500.00' },
    );
  });

  it('transitions a skipped deal flag to open via record-purchase, clearing the skip reason', async () => {
    outcomeFetch(fetchMock, SKIPPED_OUTCOME, {
      operations: {
        'record-purchase': () => Promise.resolve(jsonResponse(
          outcomeSuccessBody('record_purchase', OPEN_OUTCOME),
        )),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    const purchaseRegion = await screen.findByRole('region', { name: 'Record purchase' });
    await user.type(
      within(purchaseRegion).getByLabelText('Purchased at (Asia/Manila)'),
      '2026-06-15T12:00',
    );
    await user.type(within(purchaseRegion).getByLabelText('Purchase price'), '12500.00');
    await user.click(within(purchaseRegion).getByRole('button', { name: 'Record purchase' }));

    expect(await screen.findByText('Purchase recorded.')).toBeInTheDocument();
    expect(screen.getByText('Current state: Open')).toBeInTheDocument();
    expect(screen.queryByText('already sold by the time I followed up')).not.toBeInTheDocument();
  });

  it('records a sale from open and displays the returned days held and realised margin', async () => {
    outcomeFetch(fetchMock, OPEN_OUTCOME, {
      operations: {
        'record-sale': () => Promise.resolve(jsonResponse(
          outcomeSuccessBody('record_sale', CLOSED_OUTCOME),
        )),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    const saleRegion = await screen.findByRole('region', { name: 'Record sale' });
    await user.type(within(saleRegion).getByLabelText('Sold at (Asia/Manila)'), '2026-06-16T12:00');
    await user.type(within(saleRegion).getByLabelText('Sale price'), '14000.00');
    await user.click(within(saleRegion).getByRole('button', { name: 'Record sale' }));

    expect(await screen.findByText('Sale recorded.')).toBeInTheDocument();
    expect(screen.getByText('Current state: Closed')).toBeInTheDocument();
    const evidence = screen.getByRole('region', { name: 'Outcome evidence' });
    expect(within(evidence).getByText('1 day(s) held')).toBeInTheDocument();
    expect(within(evidence).getByText('₱1,500.00')).toBeInTheDocument();
    expectUnsafeSameOriginJson(
      findCall(fetchMock, `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/record-sale/`),
      { sold_at: '2026-06-16T04:00:00Z', sold_price: '14000.00' },
    );
  });

  it('corrects the purchase from open, pre-filled with the current evidence', async () => {
    outcomeFetch(fetchMock, OPEN_OUTCOME, {
      operations: {
        'correct-purchase': () => Promise.resolve(jsonResponse(
          outcomeSuccessBody('correct_purchase', {
            ...OPEN_OUTCOME,
            bought_at: '2026-06-14T04:00:00Z',
            bought_price: '11000.00',
          }),
        )),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    const correctionRegion = await screen.findByRole('region', { name: 'Correct purchase' });
    const timestampInput = within(correctionRegion).getByLabelText('Purchased at (Asia/Manila)');
    const priceInput = within(correctionRegion).getByLabelText('Purchase price');
    await waitFor(() => expect(timestampInput).toHaveValue('2026-06-15T12:00'));
    expect(priceInput).toHaveValue('12500.00');

    await user.clear(timestampInput);
    await user.type(timestampInput, '2026-06-14T12:00');
    await user.clear(priceInput);
    await user.type(priceInput, '11000.00');
    await user.click(within(correctionRegion).getByRole('button', { name: 'Correct purchase' }));

    expect(await screen.findByText('Purchase evidence corrected.')).toBeInTheDocument();
    expectUnsafeSameOriginJson(
      findCall(fetchMock, `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/correct-purchase/`),
      { bought_at: '2026-06-14T04:00:00Z', bought_price: '11000.00' },
    );
  });

  it('corrects the purchase from closed without disturbing sale evidence, and stays closed', async () => {
    outcomeFetch(fetchMock, CLOSED_OUTCOME, {
      operations: {
        'correct-purchase': () => Promise.resolve(jsonResponse(
          outcomeSuccessBody('correct_purchase', {
            ...CLOSED_OUTCOME,
            bought_at: '2026-06-13T04:00:00Z',
            bought_price: '11000.00',
            days_held: 3,
            realised_margin: '3000.00',
          }),
        )),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    const correctionRegion = await screen.findByRole('region', { name: 'Correct purchase' });
    const timestampInput = within(correctionRegion).getByLabelText('Purchased at (Asia/Manila)');
    await waitFor(() => expect(timestampInput).toHaveValue('2026-06-15T12:00'));
    await user.clear(timestampInput);
    await user.type(timestampInput, '2026-06-13T12:00');
    const priceInput = within(correctionRegion).getByLabelText('Purchase price');
    await user.clear(priceInput);
    await user.type(priceInput, '11000.00');
    await user.click(within(correctionRegion).getByRole('button', { name: 'Correct purchase' }));

    expect(await screen.findByText('Purchase evidence corrected.')).toBeInTheDocument();
    expect(screen.getByText('Current state: Closed')).toBeInTheDocument();
    const evidence = screen.getByRole('region', { name: 'Outcome evidence' });
    expect(within(evidence).getByText('3 day(s) held')).toBeInTheDocument();
    expect(within(evidence).getByText('₱3,000.00')).toBeInTheDocument();
  });

  it('corrects the sale from closed, pre-filled with the current sale evidence', async () => {
    outcomeFetch(fetchMock, CLOSED_OUTCOME, {
      operations: {
        'correct-sale': () => Promise.resolve(jsonResponse(
          outcomeSuccessBody('correct_sale', {
            ...CLOSED_OUTCOME,
            sold_at: '2026-06-18T04:00:00Z',
            sold_price: '13000.00',
            days_held: 3,
            realised_margin: '500.00',
          }),
        )),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    const correctionRegion = await screen.findByRole('region', { name: 'Correct sale' });
    const timestampInput = within(correctionRegion).getByLabelText('Sold at (Asia/Manila)');
    await waitFor(() => expect(timestampInput).toHaveValue('2026-06-16T12:00'));
    expect(within(correctionRegion).getByLabelText('Sale price')).toHaveValue('14000.00');

    await user.clear(timestampInput);
    await user.type(timestampInput, '2026-06-18T12:00');
    const priceInput = within(correctionRegion).getByLabelText('Sale price');
    await user.clear(priceInput);
    await user.type(priceInput, '13000.00');
    await user.click(within(correctionRegion).getByRole('button', { name: 'Correct sale' }));

    expect(await screen.findByText('Sale evidence corrected.')).toBeInTheDocument();
    const evidence = screen.getByRole('region', { name: 'Outcome evidence' });
    expect(within(evidence).getByText('₱500.00')).toBeInTheDocument();
    expectUnsafeSameOriginJson(
      findCall(fetchMock, `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/correct-sale/`),
      { sold_at: '2026-06-18T04:00:00Z', sold_price: '13000.00' },
    );
  });
});


describe('TASK_029 pending state and duplicate submission', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('disables every action button while a mutation is pending and prevents a duplicate submit', async () => {
    let resolveSkip: (response: Response) => void = () => {};
    outcomeFetch(fetchMock, UNTRACKED_OUTCOME, {
      operations: {
        skip: () => new Promise((resolve) => {
          resolveSkip = resolve;
        }),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    const reasonInput = await screen.findByLabelText('Reason');
    await user.type(reasonInput, 'no longer available');
    const skipButton = screen.getByRole('button', { name: 'Skip deal flag' });
    const purchaseButton = screen.getByRole('button', { name: 'Record purchase' });

    await user.click(skipButton);
    expect(skipButton).toBeDisabled();
    expect(purchaseButton).toBeDisabled();

    await user.click(skipButton);
    expect(findCalls(fetchMock, `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/skip/`)).toHaveLength(1);

    resolveSkip(jsonResponse(outcomeSuccessBody('skip', SKIPPED_OUTCOME)));
    await screen.findByText('Deal flag marked skipped.');
  });
});


describe('TASK_029 error and access states', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('shows access required for a 403 on the initial read', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
      }
      return Promise.resolve(jsonResponse({
        code: 'permission_denied',
        detail: 'Active staff status and required permissions are required.',
      }, 403));
    });

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);

    expect(await screen.findByText('Access required')).toBeInTheDocument();
  });

  it('shows access required for a 403 during a mutation', async () => {
    outcomeFetch(fetchMock, UNTRACKED_OUTCOME, {
      operations: {
        skip: () => Promise.resolve(jsonResponse({
          code: 'permission_denied',
          detail: 'Active staff status and required permissions are required.',
        }, 403)),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    await user.type(await screen.findByLabelText('Reason'), 'no longer available');
    await user.click(screen.getByRole('button', { name: 'Skip deal flag' }));

    expect(await screen.findByText('Access required')).toBeInTheDocument();
  });

  it('shows a dedicated not-found state for a missing deal flag', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
      }
      return Promise.resolve(jsonResponse({
        code: 'deal_flag_not_found',
        detail: 'Deal flag not found.',
      }, 404));
    });

    renderAt('/deals/999999/outcome');

    expect(await screen.findByText('Deal flag not found.')).toBeInTheDocument();
    expect(
      screen.queryByRole('heading', { name: /Outcome for deal flag/ }),
    ).not.toBeInTheDocument();
  });

  it('shows field errors and keeps the form visible for a 400 validation failure', async () => {
    outcomeFetch(fetchMock, UNTRACKED_OUTCOME, {
      operations: {
        'record-purchase': () => Promise.resolve(jsonResponse({
          code: 'invalid_request',
          detail: 'Request validation failed.',
          errors: { bought_price: ['Enter a valid number.'] },
        }, 400)),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    const purchaseRegion = await screen.findByRole('region', { name: 'Record purchase' });
    await user.type(
      within(purchaseRegion).getByLabelText('Purchased at (Asia/Manila)'),
      '2026-06-15T12:00',
    );
    await user.type(within(purchaseRegion).getByLabelText('Purchase price'), '12500.00');
    await user.click(within(purchaseRegion).getByRole('button', { name: 'Record purchase' }));

    expect(await screen.findByText('Request validation failed.')).toBeInTheDocument();
    expect(screen.getByText(/bought_price/)).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Record purchase' })).toBeInTheDocument();
    expect(within(purchaseRegion).getByLabelText('Purchase price')).toHaveValue('12500.00');
  });

  it('surfaces a lifecycle conflict with a reload affordance and does not change state', async () => {
    outcomeFetch(fetchMock, OPEN_OUTCOME, {
      operations: {
        'record-sale': () => Promise.resolve(jsonResponse({
          code: 'ineligible_outcome_state',
          detail: 'Outcome is not in an eligible state for this operation.',
        }, 409)),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    const saleRegion = await screen.findByRole('region', { name: 'Record sale' });
    await user.type(within(saleRegion).getByLabelText('Sold at (Asia/Manila)'), '2026-06-16T12:00');
    await user.type(within(saleRegion).getByLabelText('Sale price'), '14000.00');
    await user.click(within(saleRegion).getByRole('button', { name: 'Record sale' }));

    expect(
      await screen.findByText('Outcome is not in an eligible state for this operation.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload outcome' })).toBeInTheDocument();
    expect(screen.getByText('Current state: Open')).toBeInTheDocument();
  });

  it('shows a dedicated operational-error state for an invalid persisted outcome on read, not a lifecycle', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
      }
      return Promise.resolve(jsonResponse({
        code: 'invalid_outcome_state',
        detail: 'Outcome is in an invalid persisted state and must be corrected manually.',
      }, 409));
    });

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);

    expect(
      await screen.findByText(
        'Outcome is in an invalid persisted state and must be corrected manually.',
      ),
    ).toBeInTheDocument();
    for (const forbidden of ['Untracked', 'Skipped', 'Open', 'Closed']) {
      expect(screen.queryByText(`Current state: ${forbidden}`)).not.toBeInTheDocument();
    }
    expect(screen.getByRole('link', { name: 'Back to deal feed' })).toHaveAttribute('href', '/deals');
  });

  it('shows a dedicated operational-error state for an invalid persisted outcome discovered during a mutation', async () => {
    outcomeFetch(fetchMock, OPEN_OUTCOME, {
      operations: {
        'record-sale': () => Promise.resolve(jsonResponse({
          code: 'invalid_outcome_state',
          detail: 'Outcome is in an invalid persisted state and must be corrected manually.',
        }, 409)),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    const saleRegion = await screen.findByRole('region', { name: 'Record sale' });
    await user.type(within(saleRegion).getByLabelText('Sold at (Asia/Manila)'), '2026-06-16T12:00');
    await user.type(within(saleRegion).getByLabelText('Sale price'), '14000.00');
    await user.click(within(saleRegion).getByRole('button', { name: 'Record sale' }));

    expect(
      await screen.findByText(
        'Outcome is in an invalid persisted state and must be corrected manually.',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText('Current state: Open')).not.toBeInTheDocument();
  });

  it('shows a generic failure state with retry for a network failure on the initial read', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      if (requestUrl(input) === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: CSRF_TOKEN }));
      }
      return Promise.reject(new TypeError('network unavailable'));
    });

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);

    expect(await screen.findByText('Outcome could not be loaded.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry outcome' })).toBeInTheDocument();
  });

  it('shows a generic inline failure for a network failure during a mutation, without raw error detail', async () => {
    outcomeFetch(fetchMock, UNTRACKED_OUTCOME, {
      operations: {
        skip: () => Promise.reject(new TypeError('network unavailable')),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    await user.type(await screen.findByLabelText('Reason'), 'no longer available');
    await user.click(screen.getByRole('button', { name: 'Skip deal flag' }));

    expect(await screen.findByText('Outcome operation could not be completed.')).toBeInTheDocument();
    expect(screen.queryByText(/TypeError/)).not.toBeInTheDocument();
    expect(screen.queryByText(/network unavailable/)).not.toBeInTheDocument();
  });
});


describe('TASK_029 CSRF and session integration', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('bootstraps CSRF on load and reuses the cached token for a mutation', async () => {
    outcomeFetch(fetchMock, UNTRACKED_OUTCOME, {
      operations: {
        skip: () => Promise.resolve(jsonResponse(outcomeSuccessBody('skip', SKIPPED_OUTCOME))),
      },
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    expectSafeSameOrigin(findCall(fetchMock, '/api/v1/session/csrf/'));
    await user.type(await screen.findByLabelText('Reason'), 'no longer available');
    await user.click(screen.getByRole('button', { name: 'Skip deal flag' }));
    await screen.findByText('Deal flag marked skipped.');

    expect(findCalls(fetchMock, '/api/v1/session/csrf/')).toHaveLength(1);
    expectUnsafeSameOriginJson(
      findCall(fetchMock, `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/skip/`),
      { skip_reason: 'no longer available' },
      CSRF_TOKEN,
    );
  });

  it('re-bootstraps CSRF after a token-clearing 403 and lets a retried mutation succeed', async () => {
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
      if (url === `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/`) {
        return Promise.resolve(jsonResponse(UNTRACKED_OUTCOME));
      }
      if (url === `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/skip/`) {
        mutationCount += 1;
        if (mutationCount === 1) {
          return Promise.resolve(jsonResponse({
            code: 'permission_denied',
            detail: 'Active staff status and required permissions are required.',
          }, 403));
        }
        return Promise.resolve(jsonResponse(outcomeSuccessBody('skip', SKIPPED_OUTCOME)));
      }
      throw new Error(`Unexpected TASK_029 CSRF-retry request: ${url}`);
    });
    const user = userEvent.setup();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    await user.type(await screen.findByLabelText('Reason'), 'no longer available');
    await user.click(screen.getByRole('button', { name: 'Skip deal flag' }));
    expect(await screen.findByText('Access required')).toBeInTheDocument();

    renderAt(`/deals/${DEAL_FLAG.id}/outcome`);
    await user.type(await screen.findByLabelText('Reason'), 'no longer available');
    await user.click(screen.getByRole('button', { name: 'Skip deal flag' }));

    expect(await screen.findByText('Deal flag marked skipped.')).toBeInTheDocument();
    // Two skip/ requests exist in this scenario (the rejected original attempt and
    // the retry) - the retried request, not the first, is the one that must carry
    // the freshly re-bootstrapped token.
    const skipCalls = findCalls(fetchMock, `/api/v1/deal-flags/${DEAL_FLAG.id}/outcome/skip/`);
    expectUnsafeSameOriginJson(
      skipCalls.at(-1) as [RequestInfo | URL, RequestInit],
      { skip_reason: 'no longer available' },
      REFRESHED_CSRF_TOKEN,
    );
  });
});


describe('TASK_029 TASK_027 demo compatibility', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('treats an untracked demo deal flag exactly like any other, with no special-case branching', async () => {
    outcomeFetch(fetchMock, { ...UNTRACKED_OUTCOME, deal_flag_id: DEMO_DEAL_FLAG.id }, {
      dealFlagId: DEMO_DEAL_FLAG.id,
    });

    renderAt(`/deals/${DEMO_DEAL_FLAG.id}/outcome`);

    expect(
      await screen.findByRole('heading', { name: `Outcome for deal flag ${DEMO_DEAL_FLAG.id}` }),
    ).toBeInTheDocument();
    expect(screen.getByText('Current state: Untracked')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Skip this deal flag' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Record purchase' })).toBeInTheDocument();
  });
});
