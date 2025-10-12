import * as React from 'react';

jest.mock('@radix-ui/react-tooltip', () => {
  const renderChildren = (children?: React.ReactNode) =>
    React.createElement(React.Fragment, null, children);
  const MockProvider = ({ children }: { children?: React.ReactNode }) => renderChildren(children);
  const MockRoot = ({ children }: { children?: React.ReactNode }) => renderChildren(children);
  const MockPortal = ({ children }: { children?: React.ReactNode }) => renderChildren(children);
  const MockTrigger = React.forwardRef<HTMLElement, { children?: React.ReactNode; asChild?: boolean }>((props, ref) => {
    const { children, asChild: _asChild, ...rest } = props;
    if (React.isValidElement(children)) {
      return React.cloneElement(children, { ref, ...rest });
    }
    return React.createElement('span', { ref, ...rest }, children);
  });
  const MockContent = React.forwardRef<
    HTMLDivElement,
    { children?: React.ReactNode; sideOffset?: number; role?: string }
  >((props, ref) => {
    const { children, sideOffset: _sideOffset, role, ...rest } = props;
    return React.createElement('div', { ref, role: role ?? 'tooltip', ...rest }, children);
  });

  MockProvider.displayName = 'MockTooltipProvider';
  MockRoot.displayName = 'MockTooltipRoot';
  MockPortal.displayName = 'MockTooltipPortal';
  MockTrigger.displayName = 'MockTooltipTrigger';
  MockContent.displayName = 'MockTooltipContent';

  return {
    __esModule: true,
    Provider: MockProvider,
    Root: MockRoot,
    Trigger: MockTrigger,
    Portal: MockPortal,
    Content: MockContent
  };
});

const globalProcess = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process;
if (globalProcess) {
  globalProcess.env = {
    ...globalProcess.env,
    VITE_API_BASE_URL: globalProcess.env?.VITE_API_BASE_URL ?? globalProcess.env?.VITE_API_URL ?? 'http://127.0.0.1:8080',
    VITE_API_URL: globalProcess.env?.VITE_API_URL ?? 'http://127.0.0.1:8080',
    VITE_API_BASE_PATH: globalProcess.env?.VITE_API_BASE_PATH ?? '',
    VITE_API_TIMEOUT_MS: globalProcess.env?.VITE_API_TIMEOUT_MS ?? '8000'
  };
}

const importMetaEnv = {
  VITE_API_BASE_URL: globalProcess?.env?.VITE_API_BASE_URL ?? 'http://127.0.0.1:8080',
  VITE_API_BASE_PATH: globalProcess?.env?.VITE_API_BASE_PATH ?? '',
  VITE_API_TIMEOUT_MS: globalProcess?.env?.VITE_API_TIMEOUT_MS ?? '8000',
  VITE_REQUIRE_AUTH: globalProcess?.env?.VITE_REQUIRE_AUTH,
  VITE_AUTH_HEADER_MODE: globalProcess?.env?.VITE_AUTH_HEADER_MODE,
  VITE_USE_OPENAPI_CLIENT: globalProcess?.env?.VITE_USE_OPENAPI_CLIENT,
  VITE_LIBRARY_POLL_INTERVAL_MS: globalProcess?.env?.VITE_LIBRARY_POLL_INTERVAL_MS
};

(globalThis as typeof globalThis & { __HARMONY_IMPORT_META_ENV__?: Record<string, unknown> }).__HARMONY_IMPORT_META_ENV__ = {
  ...(globalThis as typeof globalThis & { __HARMONY_IMPORT_META_ENV__?: Record<string, unknown> }).__HARMONY_IMPORT_META_ENV__,
  ...importMetaEnv
};

