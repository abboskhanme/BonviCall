/**
 * The audio archive's URL, which is the opposite of the CSV export's.
 *
 * The export drops `limit` and `cursor` because a spreadsheet of a filtered set
 * has no pages. The archive KEEPS them, because the button sits under fifty
 * rows and hands over those fifty rows — an archive whose contents do not match
 * what the reader is looking at is one nobody can check.
 */
import { describe, expect, it } from 'vitest'

import {
  callsAudioArchiveUrl,
  callsExportUrl,
  type CallListQuery,
} from '@/modules/calls/api'

const QUERY: CallListQuery = {
  limit: 50,
  cursor: 'abc123',
  with_total: true,
  direction: 'outgoing',
  agent_id: ['agent-1'],
}

describe('the archive URL', () => {
  it('keeps the page, so the file matches the screen', () => {
    const url = callsAudioArchiveUrl(QUERY)

    expect(url).toContain('/calls/audio-archive?')
    expect(url).toContain('limit=50')
    expect(url).toContain('cursor=abc123')
  })

  it('carries the filters in force', () => {
    const url = callsAudioArchiveUrl(QUERY)

    expect(url).toContain('direction=outgoing')
    expect(url).toContain('agent_id=agent-1')
  })

  it('drops with_total, which is a list concern', () => {
    expect(callsAudioArchiveUrl(QUERY)).not.toContain('with_total')
  })

  it('is the opposite of the export, which has no pages', () => {
    const exported = callsExportUrl(QUERY)

    expect(exported).not.toContain('limit=')
    expect(exported).not.toContain('cursor=')
  })
})
