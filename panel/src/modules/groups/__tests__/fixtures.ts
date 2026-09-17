/**
 * Fixtures for the group directory.
 *
 * The tree is deliberately not consistent with the page by accident: the tree
 * says three bound groups and one unbound, and the tests assert against those
 * numbers rather than against whatever the page happened to render.
 */
import type { Group, GroupPage, GroupTree } from '../api'

export const AZIZ = '11111111-1111-4111-8111-111111111111'
export const DILNOZA = '22222222-2222-4222-8222-222222222222'

export function makeGroup(overrides: Partial<Group> = {}): Group {
  return {
    id: 'c1111111-1111-4111-8111-111111111111',
    chat_id: -1001234567890,
    title: 'Mijoz 1',
    agent_id: AZIZ,
    agent_name: 'Aziz',
    agent_color: '#6366f1',
    member_count: 4,
    is_active: true,
    bot_status: 'member',
    bound_by: 'auto',
    bound_at: '2026-09-01T09:00:00Z',
    last_survey_at: null,
    survey_count: 0,
    response_count: 0,
    ...overrides,
  }
}

export function makePage(overrides: Partial<GroupPage> = {}): GroupPage {
  return {
    items: [makeGroup()],
    next_cursor: null,
    has_more: false,
    ...overrides,
  }
}

/** Two employees holding three groups between them, and one group unbound. */
export function makeTree(overrides: Partial<GroupTree> = {}): GroupTree {
  return {
    agents: [
      { agent_id: AZIZ, full_name: 'Aziz', color: '#6366f1', group_count: 2, response_count: 7 },
      {
        agent_id: DILNOZA,
        full_name: 'Dilnoza',
        color: null,
        group_count: 1,
        response_count: 0,
      },
    ],
    unassigned: { group_count: 1, response_count: 0 },
    ...overrides,
  }
}
