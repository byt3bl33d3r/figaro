import '@testing-library/jest-dom';

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// Mock ResizeObserver
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}));

// Mock nats.ws module
vi.mock('nats.ws', () => ({
  connect: vi.fn().mockResolvedValue({
    isClosed: () => false,
    closed: () => new Promise(() => {}),
    subscribe: () => ({
      [Symbol.asyncIterator]: () => ({
        next: () => new Promise(() => {}),
      }),
      unsubscribe: vi.fn(),
    }),
    jetstream: () => ({
      consumers: {
        get: vi.fn().mockRejectedValue(new Error('No stream')),
      },
    }),
    drain: vi.fn().mockResolvedValue(undefined),
  }),
  JSONCodec: () => ({
    encode: (data: unknown) => new TextEncoder().encode(JSON.stringify(data)),
    decode: (data: Uint8Array) => JSON.parse(new TextDecoder().decode(data)),
  }),
}));

// Mock fetch for API calls
global.fetch = vi.fn().mockResolvedValue({
  ok: false,
  json: () => Promise.resolve({}),
  text: () => Promise.resolve(''),
}) as unknown as typeof fetch;
