import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import App from '../App';
import type { Page } from '../api/types';


function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function emptyPage(): Page<never> {
  return { count: 0, next: null, previous: null, results: [] };
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

describe('final authentication UX correction', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it('renders only the deliberate bootstrap treatment while access is unresolved', () => {
    fetchMock.mockReturnValue(new Promise<Response>(() => undefined));

    renderAt('/deals');

    expect(screen.getByText('Loading persisted deals...')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Deal feed' })).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Primary navigation' })).not.toBeInTheDocument();
    expect(screen.getByText('Checking session')).toBeInTheDocument();
  });

  it('invites an anonymous user to sign in and preserves the requested route', async () => {
    fetchMock.mockResolvedValue(jsonResponse({
      detail: 'Authentication credentials were not provided.',
    }, 403));

    renderAt('/deals');

    expect(await screen.findByRole('heading', { name: 'Sign in required' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Sign in to PriceWatch PH' })).toHaveAttribute(
      'href',
      '/auth/login/?next=%2Fdeals',
    );
    expect(screen.queryByRole('heading', { name: 'Deal feed' })).not.toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: 'Primary navigation' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument();
  });

  it('shows a permission state, not another sign-in prompt, for a known authenticated denial', async () => {
    fetchMock.mockResolvedValue(jsonResponse({
      detail: 'You do not have permission to perform this action.',
    }, 403));

    renderAt('/deals');

    expect(await screen.findByRole('heading', { name: 'Access required' })).toBeInTheDocument();
    expect(screen.getByText(/your account is signed in/i)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Sign in to PriceWatch PH' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument();
  });

  it('removes protected content immediately when sign-out begins', async () => {
    let releaseLogout: ((response: Response) => void) | undefined;
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url === '/api/v1/deal-flags/') {
        return Promise.resolve(jsonResponse(emptyPage()));
      }
      if (url === '/api/v1/session/csrf/') {
        return Promise.resolve(jsonResponse({ csrf_token: 'csrf-token' }));
      }
      if (url === '/auth/logout/') {
        return new Promise<Response>((resolve) => {
          releaseLogout = resolve;
        });
      }
      throw new Error(`Unexpected auth correction request: ${url}`);
    });
    const user = userEvent.setup();

    renderAt('/deals');
    expect(await screen.findByRole('heading', { name: 'Deal feed' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Sign out' }));

    expect(screen.getByText('Signing out securely...')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Deal feed' })).not.toBeInTheDocument();
    expect(releaseLogout).toBeTypeOf('function');
  });
});
