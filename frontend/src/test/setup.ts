import '@testing-library/jest-dom/vitest';


class ResizeObserverStub implements ResizeObserver {
  readonly root = null;
  readonly rootMargin = '';
  readonly thresholds = [];

  disconnect() {}

  observe() {}

  takeRecords(): ResizeObserverEntry[] {
    return [];
  }

  unobserve() {}
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = ResizeObserverStub;
}
