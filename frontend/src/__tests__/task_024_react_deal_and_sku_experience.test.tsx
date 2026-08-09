import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  expectTypeOf,
  it,
  vi,
} from 'vitest';

import App from '../App';
import type {
  DealFlag,
  DecimalString,
  Listing,
  Page,
  PricePoint,
  Sku,
  UTCDateTimeString,
} from '../api/types';
import { toChartPoint } from '../charts/priceHistory';
import { formatMoneyDecimal } from '../formatting/decimal';
import { skuDisplayName } from '../formatting/sku';
import { formatDateOnly, formatManilaTimestamp } from '../formatting/time';


const SKU: Sku = {
  id: 7,
  brand: 'NVIDIA',
  model: 'RTX 4070',
  variant: '',
  category: 'gpu',
  launch_msrp: '34995.00',
  launch_date: '2023-04-13',
};

const LISTING: Listing = {
  id: 11,
  sku_id: 7,
  price: '15500.00',
  condition: 'used',
  resolution_confidence: '1.0000',
  resolution_method: 'exact_alias',
  resolved_at: '2026-08-09T04:05:06Z',
  observed_at: '2026-08-08T03:04:05Z',
  price_kind: 'asking',
  trade_side: null,
};

const PRICE_POINT: PricePoint = {
  id: 13,
  sku_id: 7,
  condition: 'used',
  day: '2026-08-08',
  median: '20000.1250',
  p25: '19000.5000',
  p75: '21000.7500',
  n_listings: 7,
  mad: '1500.2500',
  window_start_day: '2026-05-10',
  window_end_day: '2026-08-08',
  calculated_at: '2026-08-08T16:30:00Z',
  calculation_contract_version: 'asking_price_baseline_v1',
};

const DEAL: DealFlag = {
  id: 17,
  sku: {
    id: SKU.id,
    brand: SKU.brand,
    model: SKU.model,
    variant: SKU.variant,
    category: SKU.category,
  },
  listing: LISTING,
  baseline_pricepoint: PRICE_POINT,
  score: '-3.2500',
  reason: 'legacy arbitrary reason must pass through unchanged',
  flagged_at: '2026-08-09T05:06:07Z',
};

const SECOND_DEAL: DealFlag = {
  ...DEAL,
  id: 18,
  sku: {
    id: 8,
    brand: 'AMD',
    model: 'RX 7900 XT',
    variant: 'Reference',
    category: 'gpu',
  },
  listing: {
    ...LISTING,
    id: 12,
    sku_id: 8,
    price: null,
    condition: null,
    observed_at: null,
  },
  baseline_pricepoint: {
    ...PRICE_POINT,
    id: 14,
    sku_id: 8,
    median: '35000.0000',
    mad: null,
  },
  score: '-12.0000',
  reason: 'do not rewrite or use this score to reorder',
};


function page<T>(
  results: T[],
  overrides: Partial<Page<T>> = {},
): Page<T> {
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
  if (input instanceof Request) {
    return input.url;
  }
  return String(input);
}


function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}


function expectSameOriginGet(call: unknown[], expectedPath: string) {
  const [input, init] = call as [RequestInfo | URL, RequestInit];
  expect(requestUrl(input)).toBe(expectedPath);
  expect(init).toMatchObject({
    method: 'GET',
    credentials: 'same-origin',
  });
  expect(init.body).toBeUndefined();
  expect(new Headers(init.headers).has('X-CSRFToken')).toBe(false);
}


function expectRequestedPath(
  fetchMock: ReturnType<typeof vi.fn>,
  expectedPath: string,
) {
  const matches = fetchMock.mock.calls.filter(
    (call) => requestUrl(call[0]) === expectedPath,
  );
  expect(matches).toHaveLength(1);
  const match = matches[0];
  if (!match) {
    throw new Error(`Expected TASK_024 request was not made: ${expectedPath}`);
  }
  expectSameOriginGet(match, expectedPath);
}


const DEAL_FAILURE_CASES: Array<[string, () => Promise<Response>]> = [
  ['server', () => Promise.resolve(jsonResponse({ detail: 'Failure' }, 500))],
  ['network', () => Promise.reject(new TypeError('network unavailable'))],
];


describe('TASK_024 frozen wire types and evidence formatting', () => {
  it('keeps Decimal and nullable legacy fields honest in TypeScript', () => {
    expectTypeOf<DealFlag['score']>().toEqualTypeOf<DecimalString>();
    expectTypeOf<Listing['price']>().toEqualTypeOf<DecimalString | null>();
    expectTypeOf<PricePoint['median']>().toEqualTypeOf<DecimalString>();
    expectTypeOf<PricePoint['mad']>().toEqualTypeOf<DecimalString | null>();
    expectTypeOf<PricePoint['calculated_at']>().toEqualTypeOf<
      UTCDateTimeString | null
    >();
  });

  it('formats authoritative money with string operations and keeps chart numbers presentation-only', () => {
    expect(formatMoneyDecimal('15500.00')).toBe('₱15,500.00');
    expect(formatMoneyDecimal('1500.2500')).toBe('₱1,500.2500');
    expect(formatMoneyDecimal(null)).toBe('Unavailable');

    const chartPoint = toChartPoint(PRICE_POINT);

    expect(chartPoint).toMatchObject({
      day: '2026-08-08',
      condition: 'used',
      median: 20000.125,
      p25: 19000.5,
      p75: 21000.75,
      range: [19000.5, 21000.75],
    });
    expect(chartPoint.evidence).toBe(PRICE_POINT);
    expect(chartPoint.evidence.median).toBe('20000.1250');
    expect(chartPoint.evidence.p25).toBe('19000.5000');
    expect(chartPoint.evidence.p75).toBe('21000.7500');
  });

  it('formats UTC instants in Manila while never constructing an instant for date-only evidence', () => {
    expect(formatManilaTimestamp('2026-08-09T05:06:07Z')).toBe(
      '09 Aug 2026, 1:06:07 PM (Asia/Manila)',
    );
    expect(formatManilaTimestamp(null)).toBe('Unavailable');

    const RealDate = globalThis.Date;
    class ThrowingDate {
      constructor() {
        throw new Error('Date-only evidence must not be converted to an instant');
      }
    }
    vi.stubGlobal('Date', ThrowingDate as unknown as DateConstructor);

    try {
      expect(formatDateOnly('2026-08-08')).toBe('08 Aug 2026');
      expect(formatDateOnly(null)).toBe('Unavailable');
    } finally {
      vi.stubGlobal('Date', RealDate);
    }
  });

  it('builds canonical SKU identity without fabricating an empty variant', () => {
    expect(skuDisplayName(SKU)).toBe('NVIDIA RTX 4070');
    expect(
      skuDisplayName({ ...SKU, variant: 'Founders Edition' }),
    ).toBe('NVIDIA RTX 4070 Founders Edition');
  });
});


describe('TASK_024 deal feed', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('lands on the server-ordered deal feed and displays only approved persisted evidence', async () => {
    fetchMock.mockResolvedValue(jsonResponse(page([DEAL, SECOND_DEAL])));

    renderAt('/');

    expect(screen.getByText('Loading persisted deals...')).toBeInTheDocument();
    const articles = await screen.findAllByRole('article');

    expect(articles).toHaveLength(2);
    expect(within(articles[0]).getByText('NVIDIA RTX 4070')).toBeInTheDocument();
    expect(within(articles[1]).getByText('AMD RX 7900 XT Reference')).toBeInTheDocument();
    expect(within(articles[0]).getByText('GPU')).toBeInTheDocument();
    expect(within(articles[0]).getByText('Used')).toBeInTheDocument();
    expect(within(articles[0]).getByText('₱15,500.00')).toBeInTheDocument();
    expect(within(articles[0]).getByText('-3.2500')).toBeInTheDocument();
    expect(
      within(articles[0]).getByText(
        'legacy arbitrary reason must pass through unchanged',
      ),
    ).toBeInTheDocument();
    expect(within(articles[0]).getByText('₱20,000.1250')).toBeInTheDocument();
    expect(within(articles[0]).getByText('₱1,500.2500')).toBeInTheDocument();
    expect(within(articles[0]).getByText('7')).toBeInTheDocument();
    expect(within(articles[0]).getByText('08 Aug 2026')).toBeInTheDocument();
    expect(
      within(articles[0]).getByText('08 Aug 2026, 11:04:05 AM (Asia/Manila)'),
    ).toBeInTheDocument();
    expect(
      within(articles[0]).getByText('09 Aug 2026, 1:06:07 PM (Asia/Manila)'),
    ).toBeInTheDocument();
    expect(within(articles[1]).getAllByText('Unavailable').length).toBeGreaterThan(0);
    expect(within(articles[1]).getByText('Unknown condition')).toBeInTheDocument();

    const skuLink = within(articles[0]).getByRole('link', {
      name: 'NVIDIA RTX 4070',
    });
    expect(skuLink).toHaveAttribute('href', '/skus/7');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expectSameOriginGet(fetchMock.mock.calls[0], '/api/v1/deal-flags/');
  });

  it('uses API next and previous links without page-size or client ranking', async () => {
    const first = page([DEAL], {
      count: 2,
      next: `${window.location.origin}/api/v1/deal-flags/?page=2`,
    });
    const second = page([SECOND_DEAL], {
      count: 2,
      previous: `${window.location.origin}/api/v1/deal-flags/`,
    });
    fetchMock
      .mockResolvedValueOnce(jsonResponse(first))
      .mockResolvedValueOnce(jsonResponse(second))
      .mockResolvedValueOnce(jsonResponse(first));
    const user = userEvent.setup();

    renderAt('/deals');
    await screen.findByText('NVIDIA RTX 4070');
    expect(screen.getByText('Showing 1–1 of 2')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous deals' })).toBeDisabled();

    await user.click(screen.getByRole('button', { name: 'Next deals' }));

    await screen.findByText('AMD RX 7900 XT Reference');
    expect(screen.queryByText('NVIDIA RTX 4070')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next deals' })).toBeDisabled();
    expectSameOriginGet(fetchMock.mock.calls[1], '/api/v1/deal-flags/?page=2');
    expect(requestUrl(fetchMock.mock.calls[1][0])).not.toContain('page_size');

    await user.click(screen.getByRole('button', { name: 'Previous deals' }));
    await screen.findByText('NVIDIA RTX 4070');
    expectSameOriginGet(fetchMock.mock.calls[2], '/api/v1/deal-flags/');
  });

  it('navigates from baseline SKU identity to its canonical detail and history', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/deal-flags/') {
        return Promise.resolve(jsonResponse(page([DEAL])));
      }
      if (url === '/api/v1/skus/7/') {
        return Promise.resolve(jsonResponse(SKU));
      }
      if (url === '/api/v1/skus/7/price-points/') {
        return Promise.resolve(jsonResponse(page([])));
      }
      throw new Error(`Unexpected TASK_024 request: ${url}`);
    });
    const user = userEvent.setup();

    renderAt('/deals');
    await user.click(
      await screen.findByRole('link', { name: 'NVIDIA RTX 4070' }),
    );

    expect(
      await screen.findByRole('heading', { name: 'NVIDIA RTX 4070' }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(
        'No persisted price history is available for this selection.',
      ),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expectRequestedPath(fetchMock, '/api/v1/deal-flags/');
    expectRequestedPath(fetchMock, '/api/v1/skus/7/');
    expectRequestedPath(fetchMock, '/api/v1/skus/7/price-points/');
  });

  it('distinguishes an honest empty feed from a loading or failure state', async () => {
    fetchMock.mockResolvedValue(jsonResponse(page([])));

    renderAt('/deals');

    expect(
      await screen.findByText('No persisted deal flags are available.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /run pricing/i })).not.toBeInTheDocument();
  });

  it('uses one honest access state for every TASK_023 403', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'Forbidden' }, 403));

    renderAt('/deals');

    expect(await screen.findByText('Access required')).toBeInTheDocument();
    expect(
      screen.getByText(/active staff session and the required view permissions/i),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /django admin sign-in/i })).toHaveAttribute(
      'href',
      '/admin/login/',
    );
    expect(screen.queryByRole('article')).not.toBeInTheDocument();
  });

  it.each(DEAL_FAILURE_CASES)(
    'shows a retryable %s failure without calling a different endpoint',
    async (_kind, failure) => {
      fetchMock
        .mockImplementationOnce(failure)
        .mockResolvedValueOnce(jsonResponse(page([DEAL])));
      const user = userEvent.setup();

      renderAt('/deals');

      expect(
        await screen.findByText('Deal feed could not be loaded.'),
      ).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'Retry deal feed' }));
      expect(await screen.findByText('NVIDIA RTX 4070')).toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expectSameOriginGet(fetchMock.mock.calls[0], '/api/v1/deal-flags/');
      expectSameOriginGet(fetchMock.mock.calls[1], '/api/v1/deal-flags/');
    },
  );

  it('has no review route, action, or navigation in TASK_024', async () => {
    renderAt('/review');

    expect(screen.getByText('Page not found')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Deals' })).toHaveAttribute(
      'href',
      '/deals',
    );
    expect(screen.queryByText(/review queue/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /confirm/i })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});


describe('TASK_024 canonical SKU and complete persisted history', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('loads every history page before rendering the chart and authoritative evidence table', async () => {
    let releaseLastPage: ((response: Response) => void) | undefined;
    const lastPage = new Promise<Response>((resolve) => {
      releaseLastPage = resolve;
    });
    const laterPoint: PricePoint = {
      ...PRICE_POINT,
      id: 15,
      day: '2026-08-09',
      median: '20500.0000',
      p25: '19500.0000',
      p75: '21500.0000',
    };
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/skus/7/') {
        return Promise.resolve(jsonResponse(SKU));
      }
      if (url === '/api/v1/skus/7/price-points/') {
        return Promise.resolve(
          jsonResponse(
            page([PRICE_POINT], {
              count: 2,
              next: `${window.location.origin}/api/v1/skus/7/price-points/?page=2`,
            }),
          ),
        );
      }
      if (url === '/api/v1/skus/7/price-points/?page=2') {
        return lastPage;
      }
      throw new Error(`Unexpected TASK_024 request: ${url}`);
    });

    renderAt('/skus/7');

    expect(await screen.findByRole('heading', { name: 'NVIDIA RTX 4070' })).toBeInTheDocument();
    expect(screen.getByText('GPU')).toBeInTheDocument();
    expect(screen.getByText('₱34,995.00')).toBeInTheDocument();
    expect(screen.getByText('13 Apr 2023')).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(3);
    });
    expect(screen.getByText('Loading complete price history...')).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Price history chart' })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('table', { name: 'Persisted price history evidence' }),
    ).not.toBeInTheDocument();

    releaseLastPage?.(jsonResponse(page([laterPoint], { count: 2 })));

    expect(await screen.findByText('2 persisted price points loaded.')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'Price history chart' })).toHaveAccessibleDescription(
      /presentation-only chart/i,
    );
    const table = screen.getByRole('table', {
      name: 'Persisted price history evidence',
    });
    expect(within(table).getByText('₱20,000.1250')).toBeInTheDocument();
    expect(within(table).getByText('₱19,000.5000')).toBeInTheDocument();
    expect(within(table).getByText('₱21,000.7500')).toBeInTheDocument();
    expect(within(table).getByText('₱1,500.2500')).toBeInTheDocument();
    expect(within(table).getByText('asking_price_baseline_v1')).toBeInTheDocument();
    expect(within(table).getByText('09 Aug 2026')).toBeInTheDocument();
    expectRequestedPath(fetchMock, '/api/v1/skus/7/');
    expectRequestedPath(fetchMock, '/api/v1/skus/7/price-points/');
    expectRequestedPath(fetchMock, '/api/v1/skus/7/price-points/?page=2');
  });

  it('refetches all pages for the exact selected condition and never sends general filters', async () => {
    const usedLater: PricePoint = {
      ...PRICE_POINT,
      id: 16,
      day: '2026-08-10',
    };
    let allHistoryRequests = 0;
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/skus/7/') {
        return Promise.resolve(jsonResponse(SKU));
      }
      if (url === '/api/v1/skus/7/price-points/') {
        allHistoryRequests += 1;
        return Promise.resolve(jsonResponse(page([])));
      }
      if (url === '/api/v1/skus/7/price-points/?condition=used') {
        return Promise.resolve(
          jsonResponse(
            page([PRICE_POINT], {
              count: 2,
              next: `${window.location.origin}/api/v1/skus/7/price-points/?condition=used&page=2`,
            }),
          ),
        );
      }
      if (url === '/api/v1/skus/7/price-points/?condition=used&page=2') {
        return Promise.resolve(jsonResponse(page([usedLater], { count: 2 })));
      }
      throw new Error(`Unexpected TASK_024 request: ${url}`);
    });
    const user = userEvent.setup();

    renderAt('/skus/7');
    expect(
      await screen.findByText('No persisted price history is available for this selection.'),
    ).toBeInTheDocument();

    await user.selectOptions(screen.getByRole('combobox', { name: 'Condition' }), 'used');

    expect(await screen.findByText('2 persisted price points loaded.')).toBeInTheDocument();
    expect(allHistoryRequests).toBe(1);
    expectRequestedPath(fetchMock, '/api/v1/skus/7/price-points/?condition=used');
    expectRequestedPath(
      fetchMock,
      '/api/v1/skus/7/price-points/?condition=used&page=2',
    );
    for (const call of fetchMock.mock.calls) {
      expect(requestUrl(call[0])).not.toContain('page_size');
      expect(requestUrl(call[0])).not.toContain('ordering');
      expect(requestUrl(call[0])).not.toContain('search');
    }
  });

  it('renders all-null legacy audit metadata as unavailable without invention', async () => {
    const legacy: PricePoint = {
      ...PRICE_POINT,
      mad: null,
      window_start_day: null,
      window_end_day: null,
      calculated_at: null,
      calculation_contract_version: null,
    };
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/skus/7/') {
        return Promise.resolve(jsonResponse(SKU));
      }
      if (url === '/api/v1/skus/7/price-points/') {
        return Promise.resolve(jsonResponse(page([legacy])));
      }
      throw new Error(`Unexpected TASK_024 request: ${url}`);
    });

    renderAt('/skus/7');

    const table = await screen.findByRole('table', {
      name: 'Persisted price history evidence',
    });
    expect(within(table).getAllByText('Unavailable')).toHaveLength(5);
    expect(within(table).queryByText(/asking_price_baseline_v1/i)).not.toBeInTheDocument();
  });

  it('discards partial history and renders a retryable error if any later page fails', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/skus/7/') {
        return Promise.resolve(jsonResponse(SKU));
      }
      if (url === '/api/v1/skus/7/price-points/') {
        return Promise.resolve(
          jsonResponse(
            page([PRICE_POINT], {
              count: 2,
              next: `${window.location.origin}/api/v1/skus/7/price-points/?page=2`,
            }),
          ),
        );
      }
      if (url === '/api/v1/skus/7/price-points/?page=2') {
        return Promise.resolve(jsonResponse({ detail: 'Failure' }, 500));
      }
      throw new Error(`Unexpected TASK_024 request: ${url}`);
    });

    renderAt('/skus/7');

    expect(await screen.findByText('Price history could not be loaded.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry price history' })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: 'Price history chart' })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('table', { name: 'Persisted price history evidence' }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText('₱20,000.1250')).not.toBeInTheDocument();
  });

  it('distinguishes missing SKU, forbidden SKU, and server failure', async () => {
    let status = 404;
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (
        url === '/api/v1/skus/999/'
        || url === '/api/v1/skus/999/price-points/'
        || url === '/api/v1/skus/7/'
        || url === '/api/v1/skus/7/price-points/'
      ) {
        return Promise.resolve(jsonResponse({ detail: 'Failure' }, status));
      }
      throw new Error(`Unexpected TASK_024 request: ${url}`);
    });

    const missing = renderAt('/skus/999');
    expect(await screen.findByText('SKU not found')).toBeInTheDocument();
    missing.unmount();

    status = 403;
    const forbidden = renderAt('/skus/7');
    expect(await screen.findByText('Access required')).toBeInTheDocument();
    forbidden.unmount();

    status = 500;
    renderAt('/skus/7');
    expect(await screen.findByText('SKU could not be loaded.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry SKU' })).toBeInTheDocument();
  });

  it('never issues mutation, RawListing, review, outcome, or pricing-computation requests', async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/skus/7/') {
        return Promise.resolve(jsonResponse(SKU));
      }
      if (url === '/api/v1/skus/7/price-points/') {
        return Promise.resolve(jsonResponse(page([PRICE_POINT])));
      }
      throw new Error(`Out-of-scope request: ${url}`);
    });

    renderAt('/skus/7');
    await screen.findByText('1 persisted price point loaded.');

    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const call of fetchMock.mock.calls) {
      const url = requestUrl(call[0]);
      expect(url).toMatch(/^\/api\/v1\/skus\/7\/(?:price-points\/)?$/);
      expect(url).not.toMatch(/raw|review|outcome|price-listings|score|build/i);
      expectSameOriginGet(call, url);
    }
    expect(screen.queryByText(/raw title|seller|payload|source url/i)).not.toBeInTheDocument();
  });
});
