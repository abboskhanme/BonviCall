/**
 * The leaf of one tree node: that node's groups, one keyset page at a time.
 *
 * Used in three places — an employee node, the unbound bucket and the search
 * result — so it knows nothing about the node above it. It is handed a query
 * and nothing else.
 *
 * ═══ Paging is keyset, and the "previous" button is a stack ═════════════════
 * The server returns `next_cursor` and nothing else, because that is what a
 * keyset seek can answer: there is no page count and no "page 3 of 7". That is
 * the correct trade — an offset page over a table an admin is actively
 * re-binding skips and repeats rows, and this is exactly that table.
 *
 * Going BACK is therefore a stack of the cursors already used, kept here. It is
 * a few lines and it means the arrows behave the way a reader expects without
 * the server having to count a thousand rows to tell us how many pages there
 * are.
 */
import { useEffect, useState } from 'react'
import { Bot, ChevronLeft, ChevronRight, Hand, Link2, Pencil, Send, Trash2, Users2 } from 'lucide-react'

import { t, type MessageKey } from '@/shared/i18n'
import { cn } from '@/shared/lib/cn'
import { formatCount, formatDate } from '@/shared/lib/format'
import { Badge, Button } from '@/shared/ui/primitives'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'

import { canDelete, canSendSurvey, isManual, useGroupPage, type Group, type GroupsQuery } from './api'

const BOT_STATUS_LABEL: Record<string, MessageKey> = {
  member: 'groups.botStatus.member',
  administrator: 'groups.botStatus.administrator',
  left: 'groups.botStatus.left',
  kicked: 'groups.botStatus.kicked',
}

export interface Selection {
  has: (id: string) => boolean
  toggle: (group: Group) => void
  addMany: (groups: Group[]) => void
  size: number
}

export interface RowActions {
  canWrite: boolean
  sendingId: string | null
  onEdit: (group: Group) => void
  onDelete: (group: Group) => void
  onSend: (group: Group) => void
}

export function GroupList({
  query,
  enabled = true,
  emptyTitle,
  selection,
  showAgent = false,
  actions,
}: {
  /** Do not pass `cursor` — paging is this component's own state. */
  query: GroupsQuery
  enabled?: boolean
  emptyTitle: string
  selection: Selection
  showAgent?: boolean
  actions: RowActions
}) {
  // The cursor for the page on screen, and the ones behind it.
  const [cursor, setCursor] = useState<string | null>(null)
  const [history, setHistory] = useState<(string | null)[]>([])

  // A filter change restarts the seek. Without this, "page 3" of the old
  // filter is applied to the new one and the list reads as empty.
  const signature = JSON.stringify(query)
  useEffect(() => {
    setCursor(null)
    setHistory([])
  }, [signature])

  const page = useGroupPage({ ...query, cursor: cursor ?? undefined }, enabled)

  return (
    <QueryBoundary
      query={page}
      isEmpty={(data) => data.items.length === 0}
      emptyTitle={emptyTitle}
      skeletonRows={4}
    >
      {(data) => (
        <div className="space-y-1.5">
          {data.items.map((group) => (
            <GroupRow
              key={group.id}
              group={group}
              selected={selection.has(group.id)}
              onSelect={() => selection.toggle(group)}
              showAgent={showAgent}
              actions={actions}
            />
          ))}

          {actions.canWrite && data.items.length > 1 ? (
            <div className="px-1 pt-1">
              <Button variant="ghost" size="sm" onClick={() => selection.addMany(data.items)}>
                {t('groups.selectAll')}
              </Button>
            </div>
          ) : null}

          {history.length > 0 || data.has_more ? (
            <div className="flex items-center justify-between gap-3 px-1 pt-1">
              <span className="text-2xs tabular-nums text-muted">
                {t('groups.pageNumber', { page: history.length + 1 })}
              </span>
              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  className="size-7 p-0"
                  disabled={history.length === 0}
                  aria-label={t('groups.prevPage')}
                  onClick={() => {
                    setCursor(history[history.length - 1] ?? null)
                    setHistory((stack) => stack.slice(0, -1))
                  }}
                >
                  <ChevronLeft className="size-3.5" aria-hidden />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  className="size-7 p-0"
                  disabled={!data.has_more}
                  aria-label={t('groups.nextPage')}
                  onClick={() => {
                    setHistory((stack) => [...stack, cursor])
                    setCursor(data.next_cursor)
                  }}
                >
                  <ChevronRight className="size-3.5" aria-hidden />
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </QueryBoundary>
  )
}

function GroupRow({
  group,
  selected,
  onSelect,
  showAgent,
  actions,
}: {
  group: Group
  selected: boolean
  onSelect: () => void
  showAgent: boolean
  actions: RowActions
}) {
  const { canWrite, sendingId, onEdit, onDelete, onSend } = actions
  const sendable = canSendSurvey(group)
  const removable = canDelete(group)
  const sending = sendingId === group.id

  return (
    <div
      className={cn(
        'flex items-center gap-3 rounded-md border border-border bg-surface p-2.5',
        selected && 'border-accent bg-accent-soft',
        !group.is_active && 'opacity-60',
      )}
    >
      {canWrite ? (
        <input
          type="checkbox"
          checked={selected}
          onChange={onSelect}
          aria-label={t('groups.selectRow', { title: group.title })}
          className="size-4 shrink-0 cursor-pointer accent-[hsl(var(--accent))]"
        />
      ) : null}

      <span className={cn('shrink-0', group.agent_id ? 'text-accent' : 'text-muted')}>
        <Users2 className="size-4" aria-hidden />
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="truncate text-xs font-medium text-text">{group.title}</span>
          {isManual(group) ? (
            <Badge tone="accent">
              <Hand className="me-1 size-3" aria-hidden />
              {t('groups.manual')}
            </Badge>
          ) : null}
          {!group.is_active ? <Badge>{t('groups.inactive')}</Badge> : null}
          {removable ? (
            <Badge tone="bad">
              <Bot className="me-1 size-3" aria-hidden />
              {t(BOT_STATUS_LABEL[group.bot_status] ?? 'groups.botStatus.member')}
            </Badge>
          ) : null}
        </div>

        <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-2xs text-muted">
          <span className="tabular-nums">{group.chat_id}</span>
          {showAgent ? (
            <span>
              ·{' '}
              {group.agent_name ? (
                <span className="text-text">{group.agent_name}</span>
              ) : (
                <span className="text-warn">{t('groups.noAgent')}</span>
              )}
            </span>
          ) : null}
          {group.member_count !== null ? (
            <span className="tabular-nums">
              · {t('groups.membersShort', { count: group.member_count })}
            </span>
          ) : null}
          <span>
            · {group.last_survey_at ? formatDate(group.last_survey_at) : t('groups.never')}
          </span>
          {group.survey_count > 0 ? (
            <span className="tabular-nums">
              ·{' '}
              {t('groups.surveyCounts', {
                surveys: formatCount(group.survey_count),
                responses: formatCount(group.response_count),
              })}
            </span>
          ) : null}
        </div>
      </div>

      {canWrite ? (
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            disabled={!sendable || sending}
            title={sendable ? t('groups.sendSurvey') : t('groups.sendBlocked')}
            onClick={() => onSend(group)}
          >
            <Send className="size-3.5" aria-hidden />
            <span className="ms-1 max-xl:hidden">
              {sending ? t('groups.sending') : t('groups.sendSurvey')}
            </span>
          </Button>

          <Button
            variant="ghost"
            size="sm"
            className="size-8 p-0"
            title={group.agent_id ? t('groups.edit') : t('groups.bind')}
            aria-label={group.agent_id ? t('groups.edit') : t('groups.bind')}
            onClick={() => onEdit(group)}
          >
            {group.agent_id ? (
              <Pencil className="size-3.5" aria-hidden />
            ) : (
              <Link2 className="size-3.5" aria-hidden />
            )}
          </Button>

          {/* Offered only once the bot is out of the chat — the server refuses
              anything else with 409, because a chat the bot is still in is
              re-registered on its next message. */}
          {removable ? (
            <Button
              variant="ghost"
              size="sm"
              className="size-8 p-0 text-bad"
              title={t('groups.delete')}
              aria-label={t('groups.delete')}
              onClick={() => onDelete(group)}
            >
              <Trash2 className="size-3.5" aria-hidden />
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
