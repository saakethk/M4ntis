import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { formatRangeSubtitle, isRangeValid, snapToAvailableDay } from '../src/features/editor/backtestRange.ts'

describe('backtestRange', () => {
  const days = ['2024-01-02', '2024-01-03', '2024-01-05']

  it('snaps to the nearest day with data', () => {
    const snapped = snapToAvailableDay('2024-01-06', days)
    assert.equal(snapped.date, '2024-01-05')
    assert.match(snapped.hint ?? '', /No data/)
  })

  it('validates custom ranges against available days', () => {
    assert.equal(isRangeValid('2024-01-02', '2024-01-03', days, false), true)
    assert.equal(isRangeValid('2024-01-06', '2024-01-06', days, false), false)
    assert.equal(isRangeValid('2024-01-05', '2024-01-02', days, false), false)
    assert.equal(isRangeValid(null, null, days, true), true)
  })

  it('formats a subtitle for the report header', () => {
    assert.equal(formatRangeSubtitle('2024-01-02', '2024-06-28'), 'Jan 2 – Jun 28, 2024')
  })
})
