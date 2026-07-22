import "@testing-library/jest-dom/vitest";
import { toHaveNoViolations } from "jest-axe";
import { afterAll, afterEach, beforeAll, expect } from "vitest";

import { server } from "@/tests/mocks/server";

expect.extend(toHaveNoViolations);

// Recharts' `ResponsiveContainer` requires ResizeObserver, which jsdom
// does not implement.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;

if (typeof window !== "undefined" && !window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  });
}

beforeAll(() => server.listen({ onUnhandledRequest: "bypass" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());
