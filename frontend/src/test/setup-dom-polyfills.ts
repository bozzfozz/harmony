// Pointer capture polyfills for jsdom
if (!('hasPointerCapture' in HTMLElement.prototype)) {
  // @ts-expect-error jsdom lacks this API
  (HTMLElement.prototype as any).hasPointerCapture = () => false;
}

if (!('setPointerCapture' in HTMLElement.prototype)) {
  // @ts-expect-error jsdom lacks this API
  (HTMLElement.prototype as any).setPointerCapture = () => {};
}

if (!('releasePointerCapture' in HTMLElement.prototype)) {
  // @ts-expect-error jsdom lacks this API
  (HTMLElement.prototype as any).releasePointerCapture = () => {};
}

// PointerEvent polyfill
(function setupPointerEventPolyfill() {
  const g = globalThis as typeof globalThis & { PointerEvent?: typeof PointerEvent };

  if (typeof g.PointerEvent === 'undefined') {
    class MockPointerEvent extends MouseEvent {
      pointerId: number;
      pointerType: string;
      isPrimary: boolean;

      constructor(type: string, init?: MouseEventInit & { pointerId?: number; pointerType?: string; isPrimary?: boolean }) {
        super(type, init);
        this.pointerId = init?.pointerId ?? 1;
        this.pointerType = init?.pointerType ?? 'mouse';
        this.isPrimary = init?.isPrimary ?? true;
      }
    }

    g.PointerEvent = MockPointerEvent as unknown as typeof PointerEvent;
  }
})();

// Optional: common web API stubs used by UI libs
if (typeof (globalThis as typeof globalThis & { ResizeObserver?: unknown }).ResizeObserver === 'undefined') {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }

  (globalThis as typeof globalThis & { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
}

if (typeof (window as typeof window & { matchMedia?: typeof window.matchMedia }).matchMedia === 'undefined') {
  (window as typeof window & { matchMedia?: typeof window.matchMedia }).matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return false;
    }
  });
}
