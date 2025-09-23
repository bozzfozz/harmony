import { cleanup } from './dom-testing';

interface MatcherResult {
  pass: boolean;
  message: () => string;
}

const toBeInTheDocument = (received: unknown): MatcherResult => {
  const element = received as Element | null | undefined;
  const pass = Boolean(element && document.body.contains(element));
  return {
    pass,
    message: () =>
      pass
        ? 'Expected element not to be in the document'
        : 'Expected element to be in the document'
  };
};

const isDisabled = (element: Element | null | undefined) => {
  if (!element) {
    return false;
  }
  if ('disabled' in element) {
    return Boolean((element as HTMLButtonElement | HTMLInputElement).disabled);
  }
  const ariaDisabled = element.getAttribute('aria-disabled');
  return ariaDisabled === 'true';
};

const toBeDisabled = (received: unknown): MatcherResult => {
  const element = received as Element | null | undefined;
  const pass = isDisabled(element);
  return {
    pass,
    message: () => (pass ? 'Expected element to be enabled' : 'Expected element to be disabled')
  };
};

expect.extend({ toBeInTheDocument, toBeDisabled });

afterEach(() => {
  cleanup();
});

export {};
