declare module 'react' {
  export type ReactNode = any;
  export type ReactElement = any;
  export interface FC<P = {}> {
    (props: P): ReactElement | null;
  }

  export type FormEvent<T = Element> = any;

  export function createContext<T>(defaultValue: T): any;
  export function useContext<T>(context: any): T;
  export function useState<S>(initialState: S | (() => S)): [S, (value: S) => void];
  export function useEffect(effect: () => void | (() => void), deps?: any[]): void;
  export function useMemo<T>(factory: () => T, deps: any[]): T;
  export function useCallback<T extends (...args: any[]) => any>(fn: T, deps: any[]): T;
  export function useRef<T>(initialValue: T): { current: T };
  export function useReducer<R extends (state: any, action: any) => any>(
    reducer: R,
    initialState: any
  ): [ReturnType<R>, (action: Parameters<R>[1]) => void];

  export type ReactNodeArray = ReactNode[];
}

declare module 'react/jsx-runtime' {
  export const jsx: any;
  export const jsxs: any;
  export const Fragment: any;
}

declare namespace JSX {
  interface IntrinsicElements {
    [elemName: string]: any;
  }
}
