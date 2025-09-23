 main
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: ['<rootDir>/jest.setup.ts'],
  transform: {
    '^.+\\.(t|j)sx?$': [
      'ts-jest',
      { tsconfig: '<rootDir>/tsconfig.json', useESM: true }
    ]
  },
  extensionsToTreatAsEsm: ['.ts', '.tsx'],
  moduleNameMapper: {
 main
  },
  testPathIgnorePatterns: ['/node_modules/', '/dist/']
};

export default config;
