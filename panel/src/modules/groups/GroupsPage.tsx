/**
 * `/groups` — the Telegram group directory, as a tree of employees.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **Why a tree and not a list.** There is one group per customer — roughly a
 * thousand of them. A flat list at that scale answers no question anybody has
 * and takes the browser with it. An employee node splits the question into one
 * step ("whose?") and shows the counts without anything being opened.
 *
 * **Requests.** Opening this page issues ONE request, `GET /groups/tree`.
 * Group rows are pulled only when a node is opened, 50 at a time, and only one
 * node is open at a time — so the DOM never holds more than one page of rows
 * however many nodes an admin clicks.
 *
 * **The bucket above the tree.** Groups nobody is bound to sit OUTSIDE the
 * tree, at the top, opened by default. They are the feature's one silent
 * failure: such a group will never receive a survey and nothing anywhere
 * raises an error about it. Putting them at the bottom would be hiding the one
 * thing this page exists to surface.
 *
 * **Nothing is delivered from here.** There is no Telegram bot in this
 * deployment, so a survey is written down and stays queued. The page says that
 * in a banner instead of reporting a send that did not happen — the same
 * honesty `core/push.py` already practises about waking a phone.
 *
 * Access: `numbers:read` to look, `numbers:write` to change. The route guard
 * and the nav entry are in `router.tsx` and `AppShell.tsx` and are NOT edited
 * by this port — the wiring is listed in the hand-off report.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Info,
  Send,
  Users2,
  X,
} from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { Perm } from '@/shared/auth/permissions'
import { t } from '@/shared/i18n'
import { Page, PageHeader } from '@/shared/layout/Page'
import { cn } from '@/shared/lib/cn'
import { formatCount } from '@/shared/lib/format'
import { Badge, Button, Card } from '@/shared/ui/primitives'
import { SearchFilter } from '@/shared/ui/filters'
import { QueryBoundary } from '@/shared/ui/QueryBoundary'

import {
  conflictReason,
  treeTotals,
  useGroupTree,
  useSendSurvey,
  UNASSIGNED_KEY,
  type Group,
  type TreeAgent,
} from './api'
import { BroadcastModal } from './BroadcastModal'
import { BulkAssignModal, type BulkMode } from './BulkAssignModal'
import { DeleteGroupModal } from './DeleteGroupModal'
import { GroupList, type RowActions, type Selection } from './GroupList'
import { GroupModal } from './GroupModal'

interface Notice {
  tone: 'good' | 'warn' | 'bad'
  text: string
}

export function GroupsPage() {
  const { can } = useAuth()
  const canWrite = can(Perm.NUMBERS_WRITE)

  const [includeInactive, setIncludeInactive] = useState(false)
  const [search, setSearch] = useState<string | undefined>(undefined)
  const [agentFilter, setAgentFilter] = useState<string | undefined>(undefined)

  // ⚠️ ONE node open at a time. This single rule is what keeps the rendered
  // row count bounded no matter how many nodes an admin clicks through.
  const [openAgent, setOpenAgent] = useState<string | null>(null)
  const [unassignedOpen, setUnassignedOpen] = useState(true)

  const [selected, setSelected] = useState<Map<string, Group>>(new Map())
  const [editing, setEditing] = useState<Group | null>(null)
  const [deleting, setDeleting] = useState<Group | null>(null)
  const [bulkMode, setBulkMode] = useState<BulkMode | null>(null)
  const [broadcasting, setBroadcasting] = useState(false)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [sendingId, setSendingId] = useState<string | null>(null)

  const tree = useGroupTree()
  const send = useSendSurvey()

  const totals = useMemo(() => treeTotals(tree.data), [tree.data])

  const agents = useMemo(() => {
    const rows = tree.data?.agents ?? []
    const needle = (agentFilter ?? '').trim().toLowerCase()
    const matched = needle
      ? rows.filter((agent) => agent.full_name.toLowerCase().includes(needle))
      : rows
    return [...matched].sort((a, b) => a.full_name.localeCompare(b.full_name))
  }, [tree.data, agentFilter])

  const selection: Selection = useMemo(
    () => ({
      has: (id) => selected.has(id),
      size: selected.size,
      toggle: (group) =>
        setSelected((prev) => {
          const next = new Map(prev)
          if (next.has(group.id)) next.delete(group.id)
          else next.set(group.id, group)
          return next
        }),
      addMany: (groups) =>
        setSelected((prev) => {
          const next = new Map(prev)
          for (const group of groups) next.set(group.id, group)
          return next
        }),
    }),
    [selected],
  )

  const selectedList = useMemo(() => [...selected.values()], [selected])
  const clearSelection = () => setSelected(new Map())

  const sendSurvey = (group: Group) => {
    setNotice(null)
    setSendingId(group.id)
    send.mutate(
      { id: group.id },
      {
        // A 409 here is an ordinary state, not a fault: the group is unbound,
        // or it was asked too recently, or the feature is switched off. Each
        // gets its own sentence rather than a red "error".
        onSuccess: () => setNotice({ tone: 'warn', text: t('groups.sentQueued') }),
        onError: (error) => {
          const reason = conflictReason(error)
          if (reason === 'survey_disabled') {
            setNotice({ tone: 'warn', text: t('groups.surveysDisabledHint') })
          } else if (reason) {
            setNotice({
              tone: 'warn',
              text: t(
                reason === 'group_not_bound'
                  ? 'groups.skipReason.group_not_bound'
                  : reason === 'group_inactive'
                    ? 'groups.skipReason.group_inactive'
                    : 'groups.skipReason.survey_suppressed',
              ),
            })
          } else {
            setNotice({ tone: 'bad', text: t('common.errorTitle') })
          }
        },
        onSettled: () => setSendingId(null),
      },
    )
  }

  const actions: RowActions = {
    canWrite,
    sendingId,
    onEdit: setEditing,
    onDelete: setDeleting,
    onSend: sendSurvey,
  }

  const searching = Boolean((search ?? '').trim())

  return (
    <Page>
      <PageHeader
        title={t('groups.title')}
        description={t('groups.subtitle', {
          count: formatCount(totals.groups),
          agents: tree.data?.agents.length ?? 0,
        })}
        actions={
          canWrite ? (
            <Button onClick={() => setBroadcasting(true)}>
              <Send className="me-1 size-4" aria-hidden />
              {t('groups.broadcast')}
            </Button>
          ) : undefined
        }
      />

      {/* ⚠️ The honest banner. Nothing on this page reaches a customer, and
          saying so once at the top is better than a surprise per button. */}
      <div className="flex items-start gap-2 rounded-md border border-border bg-surface-2 px-3 py-2.5">
        <Info className="mt-px size-4 shrink-0 text-muted" aria-hidden />
        <div>
          <p className="text-xs font-medium text-text">{t('groups.notDeliveredTitle')}</p>
          <p className="mt-0.5 text-2xs leading-relaxed text-muted">
            {t('groups.notDeliveredHint')}
          </p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Tile
          icon={Users2}
          label={t('groups.tileTotal')}
          value={formatCount(totals.groups)}
          hint={t('groups.tileTotalHint')}
        />
        <Tile
          icon={AlertTriangle}
          tone={totals.unassigned > 0 ? 'warn' : 'good'}
          label={t('groups.tileUnassigned')}
          value={formatCount(totals.unassigned)}
          hint={
            totals.unassigned > 0
              ? t('groups.tileUnassignedHint')
              : t('groups.tileUnassignedOk')
          }
        />
      </div>

      {notice ? (
        <div
          role="status"
          className={cn(
            'flex items-start gap-2.5 rounded-md px-3 py-2.5 text-xs leading-relaxed',
            notice.tone === 'good' && 'bg-good/10 text-good',
            notice.tone === 'warn' && 'bg-warn/10 text-warn',
            notice.tone === 'bad' && 'bg-bad/10 text-bad',
          )}
        >
          {notice.tone === 'good' ? (
            <CheckCircle2 className="mt-px size-4 shrink-0" aria-hidden />
          ) : (
            <Info className="mt-px size-4 shrink-0" aria-hidden />
          )}
          <span className="flex-1">{notice.text}</span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label={t('common.close')}
            className="shrink-0 rounded-md p-0.5 opacity-60 hover:opacity-100"
          >
            <X className="size-3.5" aria-hidden />
          </button>
        </div>
      ) : null}

      {/* ── Outside the tree: the groups nobody is bound to ───────────────
          Opened by default when it is non-empty. These receive nothing and
          nothing raises an error about it, so they lead the page. */}
      {totals.unassigned > 0 ? (
        <Card className="overflow-hidden border-warn/40">
          <div className="flex items-center gap-2 bg-warn/[0.07] p-3">
            <button
              type="button"
              onClick={() => setUnassignedOpen((open) => !open)}
              aria-expanded={unassignedOpen}
              className="flex min-w-0 flex-1 items-center gap-3 rounded-md px-1 py-1 text-start"
            >
              <ChevronRight
                className={cn(
                  'size-4 shrink-0 text-warn transition-transform',
                  unassignedOpen && 'rotate-90',
                )}
                aria-hidden
              />
              <AlertTriangle className="size-4 shrink-0 text-warn" aria-hidden />
              <span className="min-w-0">
                <span className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-text">
                    {t('groups.unassignedTitle')}
                  </span>
                  <Badge tone="warn">{formatCount(totals.unassigned)}</Badge>
                </span>
                <span className="mt-0.5 block text-xs leading-relaxed text-muted">
                  {t('groups.unassignedHint')}
                </span>
              </span>
            </button>
          </div>

          {unassignedOpen ? (
            <div className="space-y-2 p-3">
              <GroupList
                query={{ has_agent: false, include_inactive: includeInactive }}
                emptyTitle={t('groups.nodeEmpty')}
                selection={selection}
                actions={actions}
              />
            </div>
          ) : null}
        </Card>
      ) : null}

      {/* ── The tree ──────────────────────────────────────────────────── */}
      <Card className="p-4">
        <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-text">{t('groups.treeTitle')}</h2>
            <p className="mt-0.5 text-xs text-muted">{t('groups.treeHint')}</p>
          </div>
          <label className="flex shrink-0 items-center gap-2 text-2xs text-muted">
            <input
              type="checkbox"
              checked={includeInactive}
              onChange={(event) => setIncludeInactive(event.target.checked)}
              className="size-4 accent-[hsl(var(--accent))]"
            />
            {t('groups.showInactive')}
          </label>
        </div>

        <div className="mb-3 flex flex-wrap items-center gap-3">
          <SearchFilter
            label={t('groups.searchGroups')}
            placeholder={t('groups.searchGroups')}
            value={search}
            onCommit={(next) => setSearch(next ?? undefined)}
            clearLabel={t('groups.clearSearch')}
            className="min-w-[16rem] flex-1"
          />
          <SearchFilter
            label={t('groups.searchAgents')}
            placeholder={t('groups.searchAgents')}
            value={agentFilter}
            onCommit={(next) => setAgentFilter(next ?? undefined)}
            clearLabel={t('groups.clearSearch')}
            className="min-w-[12rem]"
          />
        </div>

        {searching ? (
          <div className="space-y-2">
            <p className="text-2xs text-muted">
              {t('groups.searchResults', { query: (search ?? '').trim() })}
            </p>
            <GroupList
              query={{ search, include_inactive: includeInactive }}
              emptyTitle={t('groups.searchEmpty', { query: (search ?? '').trim() })}
              selection={selection}
              showAgent
              actions={actions}
            />
          </div>
        ) : (
          <QueryBoundary
            query={tree}
            isEmpty={() => agents.length === 0}
            emptyTitle={
              (agentFilter ?? '').trim()
                ? t('groups.noAgentMatch', { query: (agentFilter ?? '').trim() })
                : t('groups.empty')
            }
            emptyHint={(agentFilter ?? '').trim() ? undefined : t('groups.emptyHint')}
            skeletonRows={6}
          >
            {() => (
              <div className="space-y-2">
                {agents.map((agent) => (
                  <AgentNode
                    key={agent.agent_id}
                    agent={agent}
                    open={openAgent === agent.agent_id}
                    onToggle={() =>
                      setOpenAgent((current) =>
                        current === agent.agent_id ? null : agent.agent_id,
                      )
                    }
                    includeInactive={includeInactive}
                    selection={selection}
                    actions={actions}
                  />
                ))}
              </div>
            )}
          </QueryBoundary>
        )}
      </Card>

      {/* ── The selection bar ─────────────────────────────────────────── */}
      {canWrite && selected.size > 0 ? (
        <div className="sticky bottom-4 z-30">
          <Card className="flex flex-wrap items-center gap-2 p-3 shadow-pop">
            <span className="px-1 text-sm font-semibold text-text">
              {t('groups.selectedCount', { count: selected.size })}
            </span>
            <div className="ms-auto flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={() => setBulkMode('agent')}>
                {t('groups.bulkModeAgent')}
              </Button>
              <Button variant="secondary" size="sm" onClick={() => setBulkMode('clear')}>
                {t('groups.bulkModeClear')}
              </Button>
              <Button variant="ghost" size="sm" onClick={clearSelection}>
                {t('groups.clearSelection')}
              </Button>
            </div>
          </Card>
        </div>
      ) : null}

      <GroupModal group={editing} onClose={() => setEditing(null)} />
      <DeleteGroupModal group={deleting} onClose={() => setDeleting(null)} />
      {canWrite ? (
        <>
          <BulkAssignModal
            open={bulkMode !== null}
            mode={bulkMode ?? 'agent'}
            groups={selectedList}
            onClose={() => setBulkMode(null)}
            onDone={clearSelection}
          />
          <BroadcastModal open={broadcasting} onClose={() => setBroadcasting(false)} />
        </>
      ) : null}
    </Page>
  )
}

function AgentNode({
  agent,
  open,
  onToggle,
  includeInactive,
  selection,
  actions,
}: {
  agent: TreeAgent
  open: boolean
  onToggle: () => void
  includeInactive: boolean
  selection: Selection
  actions: RowActions
}) {
  return (
    <div className={cn('overflow-hidden rounded-md bg-surface-2/50', open && 'bg-surface-2')}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-3 p-2.5 text-start"
      >
        <ChevronRight
          className={cn('size-4 shrink-0 text-muted transition-transform', open && 'rotate-90')}
          aria-hidden
        />
        {/* An initial in a token-coloured disc, NOT the per-agent colour.
            `agents.color` is a hex string the server stores for decoration,
            and painting with it needs either `style={{background}}` or a hex
            literal in a class — both forbidden (CONVENTIONS-CLIENT.md §11),
            and `style={{...}}` appears nowhere else in this panel. The name
            beside it is the identification; the disc is furniture. */}
        <span
          aria-hidden
          className="grid size-7 shrink-0 place-items-center rounded-full bg-accent-soft text-2xs font-semibold text-accent"
        >
          {agent.full_name.trim().slice(0, 1).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-text">
            {agent.full_name}
          </span>
          <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-2xs text-muted">
            <span className="tabular-nums">
              {t('groups.groupCount', { count: agent.group_count })}
            </span>
            <span aria-hidden>·</span>
            <span className="tabular-nums">
              {t('groups.responseCount', { count: agent.response_count })}
            </span>
          </span>
        </span>
      </button>

      {/* ⚠️ The list is mounted only when the node is open. A closed node
          costs zero requests, which is the whole reason the page scales. */}
      {open ? (
        <div className="space-y-2 border-t border-border px-3 pb-3 pt-2.5">
          {agent.group_count === 0 ? (
            <p className="rounded-md bg-surface px-3 py-2.5 text-2xs text-muted">
              {t('groups.agentEmpty')}
            </p>
          ) : (
            <>
              <p className="text-2xs text-muted">{t('groups.selectHint')}</p>
              <GroupList
                query={{ agent_id: agent.agent_id, include_inactive: includeInactive }}
                emptyTitle={t('groups.nodeEmpty')}
                selection={selection}
                actions={actions}
              />
            </>
          )}
        </div>
      ) : null}
    </div>
  )
}

function Tile({
  icon: Icon,
  label,
  value,
  hint,
  tone = 'accent',
}: {
  icon: typeof Users2
  label: string
  value: string
  hint: string
  tone?: 'accent' | 'good' | 'warn'
}) {
  return (
    <Card className="p-4">
      <div className="mb-2 flex items-center gap-2">
        <Icon
          className={cn(
            'size-4',
            tone === 'accent' && 'text-accent',
            tone === 'good' && 'text-good',
            tone === 'warn' && 'text-warn',
          )}
          aria-hidden
        />
        <span className="text-2xs font-medium uppercase tracking-wide text-muted">{label}</span>
      </div>
      <p
        className={cn(
          'text-2xl font-semibold tabular-nums leading-none',
          tone === 'warn' ? 'text-warn' : 'text-text',
        )}
      >
        {value}
      </p>
      <p className="mt-2 text-2xs leading-relaxed text-muted">{hint}</p>
    </Card>
  )
}

export { UNASSIGNED_KEY }
