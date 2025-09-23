import { act } from 'react-dom/test-utils';
import { createRoot, Root } from 'react-dom/client';
import { ReactElement } from 'react';

type TextMatcher = string | RegExp;

interface RoleOptions {
  name?: TextMatcher;
}

interface WaitForOptions {
  timeout?: number;
  interval?: number;
}

const mountedRoots = new Set<Root>();
const containers = new Set<HTMLElement>();

const cleanup = () => {
  mountedRoots.forEach((root) => root.unmount());
  containers.forEach((container) => {
    if (container.parentNode) {
      container.parentNode.removeChild(container);
    }
  });
  mountedRoots.clear();
  containers.clear();
};

const render = (ui: ReactElement) => {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  containers.add(container);

  act(() => {
    root.render(ui);
  });

  const rerender = (nextUi: ReactElement) => {
    act(() => {
      root.render(nextUi);
    });
  };

  const unmount = () => {
    act(() => {
      root.unmount();
    });
    mountedRoots.delete(root);
    containers.delete(container);
    if (container.parentNode) {
      container.parentNode.removeChild(container);
    }
  };

  return { container, rerender, unmount };
};

const matchesText = (text: string | null | undefined, matcher: TextMatcher | undefined) => {
  if (matcher === undefined) {
    return true;
  }
  if (typeof matcher === 'string') {
    return text?.toLowerCase().includes(matcher.toLowerCase()) ?? false;
  }
  return matcher.test(text ?? '');
};

const normalize = (value: string | null | undefined) => value?.replace(/\s+/g, ' ').trim() ?? '';

const getElements = (container: Element) => Array.from(container.querySelectorAll('*')) as HTMLElement[];

const computeRole = (element: HTMLElement) => {
  const explicitRole = element.getAttribute('role');
  if (explicitRole) {
    return explicitRole;
  }
  const tag = element.tagName.toLowerCase();
  if (tag === 'button') {
    return 'button';
  }
  if (tag === 'a' && element.hasAttribute('href')) {
    return 'link';
  }
  if (tag === 'table') {
    return 'table';
  }
  if (tag === 'tr') {
    return 'row';
  }
  if (tag === 'th') {
    return 'columnheader';
  }
  if (tag === 'td') {
    return 'cell';
  }
  if (tag === 'input') {
    const type = element.getAttribute('type') ?? 'text';
    if (type === 'checkbox') {
      return 'checkbox';
    }
    return 'textbox';
  }
  if (tag === 'textarea') {
    return 'textbox';
  }
  return undefined;
};

const getNodeText = (element: HTMLElement) => normalize(element.textContent ?? '');

const getAccessibleName = (element: HTMLElement) => {
  const labelledBy = element.getAttribute('aria-labelledby');
  if (labelledBy) {
    const labelElement = document.getElementById(labelledBy);
    if (labelElement) {
      return getNodeText(labelElement as HTMLElement);
    }
  }
  const ariaLabel = element.getAttribute('aria-label');
  if (ariaLabel) {
    return ariaLabel;
  }
  if (element.tagName.toLowerCase() === 'input') {
    const id = element.getAttribute('id');
    if (id) {
      const label = document.querySelector(`label[for="${id}"]`);
      if (label) {
        return getNodeText(label as HTMLElement);
      }
    }
  }
  if (element.tagName.toLowerCase() === 'label') {
    return getNodeText(element);
  }
  return getNodeText(element);
};

const getByText = (container: Element, matcher: TextMatcher) => {
  for (const element of getElements(container)) {
    if (matchesText(getNodeText(element), matcher)) {
      return element;
    }
  }
  throw new Error(`Unable to find element with text: ${matcher.toString()}`);
};

const getByRole = (container: Element, role: string, options?: RoleOptions) => {
  for (const element of getElements(container)) {
    const elementRole = computeRole(element);
    if (elementRole !== role) {
      continue;
    }
    if (options?.name && !matchesText(getAccessibleName(element), options.name)) {
      continue;
    }
    return element;
  }
  throw new Error(`Unable to find element with role ${role}`);
};

const getAllByRole = (container: Element, role: string, options?: RoleOptions) => {
  const elements = getElements(container).filter((element) => {
    const elementRole = computeRole(element);
    if (elementRole !== role) {
      return false;
    }
    if (options?.name && !matchesText(getAccessibleName(element), options.name)) {
      return false;
    }
    return true;
  });
  if (elements.length === 0) {
    throw new Error(`Unable to find elements with role ${role}`);
  }
  return elements;
};

const getByLabelText = (container: Element, matcher: TextMatcher) => {
  const labels = Array.from(container.querySelectorAll('label')) as HTMLLabelElement[];
  for (const label of labels) {
    if (!matchesText(getNodeText(label), matcher)) {
      continue;
    }
    const htmlFor = label.getAttribute('for');
    if (htmlFor) {
      const input = container.querySelector(`#${htmlFor}`);
      if (input) {
        return input as HTMLElement;
      }
    }
    const control = label.querySelector('input,textarea,select,button');
    if (control) {
      return control as HTMLElement;
    }
  }
  throw new Error(`Unable to find label with text ${matcher.toString()}`);
};

const getByPlaceholderText = (container: Element, matcher: TextMatcher) => {
  const inputs = Array.from(container.querySelectorAll('input,textarea')) as HTMLElement[];
  for (const input of inputs) {
    const placeholder = input.getAttribute('placeholder') ?? '';
    if (matchesText(placeholder, matcher)) {
      return input;
    }
  }
  throw new Error(`Unable to find element with placeholder ${matcher.toString()}`);
};

const waitFor = async (callback: () => void, options: WaitForOptions = {}) => {
  const { timeout = 2000, interval = 50 } = options;
  const start = Date.now();
  while (true) {
    try {
      callback();
      return;
    } catch (error) {
      if (Date.now() - start > timeout) {
        throw error;
      }
      await new Promise((resolve) => setTimeout(resolve, interval));
    }
  }
};

const findBy = async <T,>(getter: () => T) => {
  let result: T | undefined;
  await waitFor(() => {
    result = getter();
  });
  return result as T;
};

const buildQueries = (container: Element) => ({
  getByText: (matcher: TextMatcher) => getByText(container, matcher),
  getByRole: (role: string, options?: RoleOptions) => getByRole(container, role, options),
  getAllByRole: (role: string, options?: RoleOptions) => getAllByRole(container, role, options),
  getByLabelText: (matcher: TextMatcher) => getByLabelText(container, matcher),
  getByPlaceholderText: (matcher: TextMatcher) => getByPlaceholderText(container, matcher),
  findByText: (matcher: TextMatcher) => findBy(() => getByText(container, matcher)),
  findByRole: (role: string, options?: RoleOptions) => findBy(() => getByRole(container, role, options)),
  findByLabelText: (matcher: TextMatcher) => findBy(() => getByLabelText(container, matcher))
});

const screen = buildQueries(document.body);

const within = (element: Element) => buildQueries(element);

const fireEvent = (element: Element, event: Event) => {
  element.dispatchEvent(event);
};

const userEvent = {
  click: async (element: Element) => {
    await act(async () => {
      fireEvent(element, new MouseEvent('click', { bubbles: true }));
    });
  },
  type: async (element: HTMLInputElement | HTMLTextAreaElement, text: string) => {
    for (const char of text) {
      await act(async () => {
        const nextValue = (element.value ?? '') + char;
        element.value = nextValue;
        fireEvent(element, new InputEvent('input', { bubbles: true, data: char }));
      });
    }
  },
  clear: async (element: HTMLInputElement | HTMLTextAreaElement) => {
    await act(async () => {
      element.value = '';
      fireEvent(element, new InputEvent('input', { bubbles: true, data: '' }));
    });
  }
};

export { render, screen, within, waitFor, cleanup, userEvent };
