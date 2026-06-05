import { describe, expect, it } from 'vitest'

// Minimal smoke test proving the Vitest harness runs in CI.
// Replace/extend with real component + API-client tests (see CONTRIBUTING.md).
describe('smoke', () => {
  it('runs the test harness', () => {
    expect(1 + 1).toBe(2)
  })
})
