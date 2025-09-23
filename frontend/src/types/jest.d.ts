declare function describe(name: string, fn: () => void): void;
declare function it(name: string, fn: () => void | Promise<void>): void;
declare function test(name: string, fn: () => void | Promise<void>): void;
declare function beforeAll(fn: () => void | Promise<void>): void;
declare function beforeEach(fn: () => void | Promise<void>): void;
declare function afterAll(fn: () => void | Promise<void>): void;
declare function afterEach(fn: () => void | Promise<void>): void;
declare const expect: any;

declare const jest: {
  fn: (...args: unknown[]) => (...fnArgs: unknown[]) => unknown;
};
