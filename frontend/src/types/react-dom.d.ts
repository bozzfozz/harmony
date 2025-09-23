declare module 'react-dom/client' {
  export interface Root {
    render(element: any): void;
    unmount(): void;
  }
  export function createRoot(container: Element | DocumentFragment): Root;
}

declare module 'react-dom/test-utils' {
  export function act(callback: () => void | Promise<void>): Promise<void> | void;
}
