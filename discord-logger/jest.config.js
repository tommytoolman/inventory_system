/** @type {import('ts-jest').JestConfigWithTsJest} */
module.exports = {
  preset:             'ts-jest',
  testEnvironment:    'node',
  roots:              ['<rootDir>/src'],
  testMatch:          ['**/*.test.ts'],
  collectCoverageFrom: ['src/**/*.ts', '!src/**/*.test.ts'],
  coverageDirectory:  'coverage',
  coverageReporters:  ['text', 'lcov'],
  // Silence console output during tests (failures still shown)
  silent: false,
};
