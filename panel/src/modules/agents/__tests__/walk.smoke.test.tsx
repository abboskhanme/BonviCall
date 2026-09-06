/* TEMPORARY — re-walking after the fixes. Deleted after the run. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeAll, describe, expect, it, vi } from 'vitest'

import { AgentDetailPage } from '@/modules/agents/AgentDetailPage'
import { CallDetailPage } from '@/modules/calls/CallDetailPage'
import { CallsPage } from '@/modules/calls/CallsPage'
import { DevicesPage } from '@/modules/devices/DevicesPage'
import { GapReportPage } from '@/modules/reports/GapReportPage'
import { useAuth } from '@/modules/auth/store'
import { api } from '@/shared/api/client'
import type { components } from '@/shared/api/types.gen'

type Call = components['schemas']['CallResponse']

beforeAll(() => {
  URL.createObjectURL = vi.fn(() => 'blob:x')
  URL.revokeObjectURL = vi.fn()
  const realFetch = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    if (typeof input === 'string' && input.startsWith('/')) {
      return realFetch(`http://backend:8000${input}`, init)
    }
    return realFetch(input, init)
  }) as typeof fetch
})

function mount(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/agents/:id" element={<AgentDetailPage />} />
          <Route path="/devices" element={<DevicesPage />} />
          <Route path="/calls" element={<CallsPage />} />
          <Route path="/calls/:id" element={<CallDetailPage />} />
          <Route path="/reports/gap" element={<GapReportPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function login(email = 'admin@bonvi.uz') {
  useAuth.setState({ status: 'idle', user: null, permissions: new Set(), loginError: null })
  expect(await useAuth.getState().login(email, 'Bonvi2026!')).toBe(true)
}

describe('re-walk', () => {
  it('1. the stuck phone now names its blocking capability', async () => {
    await login()
    const insts = await api.get<{ items: { id: string; agent_id: string; funnel_stage: string; created_at: string }[] }>('/installations')
    // The agent whose NEWEST installation is stuck.
    const byAgent = new Map<string, typeof insts.items>()
    for (const i of insts.items) byAgent.set(i.agent_id, [...(byAgent.get(i.agent_id) ?? []), i])
    let target: { agentId: string; inst: (typeof insts.items)[number] } | null = null
    for (const [agentId, list] of byAgent) {
      const newest = [...list].sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
      if (
        newest &&
        newest.funnel_stage !== 'capturing' &&
        newest.funnel_stage !== 'number_verified' &&
        newest.funnel_stage !== 'revoked'
      ) {
        target = { agentId, inst: newest }
        break
      }
    }
    console.log('>> target agent:', target?.agentId.slice(0, 8), 'newest inst:', target?.inst.id.slice(0, 8), target?.inst.funnel_stage)
    if (!target) return console.log('   (no agent whose newest install is stuck)')

    mount(`/agents/${target.agentId}`)
    await waitFor(() => expect(document.body.textContent).toContain("Ro'yxatga olish"), { timeout: 20000 })
    await new Promise((r) => setTimeout(r, 2500))
    const text = document.body.textContent ?? ''
    console.log('   HINT:', /Ilova o'rnatildi, ammo|Ruxsatlar berildi\. Endi|Kod berildi, lekin/.test(text))
    console.log('   BLOCKING section:', text.includes("Nima to'sib turibdi"))
    const blocking = [...document.querySelectorAll('li')]
      .map((li) => li.textContent?.trim() ?? '')
      .filter((txt) => txt.includes('—'))
    console.log('   BLOCKING lines:', blocking.slice(0, 5))
    // And what the server actually has, to compare against.
    const dev = await api.get<{ capabilities?: { capability: string; state: string }[] }>(
      `/devices/${target.inst.id}`,
    ).catch(() => ({ capabilities: [] }))
    console.log('   server says:', (dev.capabilities ?? []).filter((c) => c.state !== 'granted_working').map((c) => `${c.capability}=${c.state}`))
    console.log('   older attempts noted:', /eski o'rnatma bor/.test(text))
    console.log('   attest offered:', text.includes('Raqamni avtomatik tasdiqlab'))
  }, 90000)

  it('2. fleet no longer calls an unknown phone healthy', async () => {
    await login()
    const { container } = mount('/devices')
    await screen.findByRole('table', {}, { timeout: 20000 })
    await new Promise((r) => setTimeout(r, 1500))
    const rows = [...container.querySelectorAll('tbody tr')]
    console.log('=== FLEET (first 8) ===')
    rows.slice(0, 8).forEach((r) =>
      console.log('   ' + [...r.querySelectorAll('td')].map((c) => c.textContent?.trim() || '·').slice(0, 4).join(' | ')),
    )
    const healthy = rows.filter((r) => r.textContent?.includes('Yaxshi'))
    console.log('>> rows still marked healthy:', healthy.length)
    healthy.forEach((r) => console.log('    ', [...r.querySelectorAll('td')].map((c) => c.textContent?.trim()).slice(0, 5).join(' | ')))
    const banner = container.querySelector('[class*="border-warn"]')
    console.log('>> banner:', banner?.textContent?.trim().slice(0, 160))
  }, 90000)

  it('3. a call with audio plays; a call without shows its reason', async () => {
    await login()
    const page = await api.get<{ items: Call[] }>('/calls', { limit: 100 })
    const withAudio = page.items.find((c) => c.audio.available)
    const without = page.items.find((c) => !c.audio.available && c.audio.audio_missing_reason)
    console.log('>> playable:', withAudio?.id.slice(0, 8), '| missing:', without?.id.slice(0, 8), without?.audio.audio_missing_reason)

    const a = mount(`/calls/${withAudio?.id}`)
    await waitFor(() => expect(a.container.querySelector('audio')).not.toBeNull(), { timeout: 20000 })
    console.log('   player rendered, src:', a.container.querySelector('audio')?.getAttribute('src'))
    a.unmount()

    const b = mount(`/calls/${without?.id}`)
    await waitFor(() => expect(b.container.querySelectorAll('dt').length).toBeGreaterThan(2), { timeout: 20000 })
    console.log('   no player:', b.container.querySelector('audio') === null)
    console.log('   reason legible:', /Ilovaga yozib olish ruxsati berilmagan|Telefonning o'z yozib olish|Yozuv kutilmagan|yo'li ishlamadi|Yozuv yuklanmoqda/.test(b.container.textContent ?? ''))
  }, 90000)

  it('4. gap report counts the reasons correctly', async () => {
    await login()
    const { container } = mount('/reports/gap')
    await waitFor(() => expect(container.textContent).toContain('Sabab'), { timeout: 20000 })
    console.log('=== GAP ===')
    container.querySelectorAll('.grid > div').forEach((c) => {
      const txt = [...c.querySelectorAll('p')].map((p) => p.textContent?.trim()).filter(Boolean).join(' | ')
      if (txt) console.log('   ', txt)
    })
    ;[...container.querySelectorAll('tbody tr')].slice(0, 6).forEach((r) =>
      console.log('   ', [...r.querySelectorAll('td')].map((c) => c.textContent?.trim()).join(' | ')),
    )
  }, 90000)

  it('5. SALES login, for real', async () => {
    await login('sales@bonvi.uz')
    const me = useAuth.getState().user
    console.log('>> logged in as:', me?.email, me?.role, 'perms:', me?.permissions)

    const calls = mount('/calls')
    await screen.findByRole('table', {}, { timeout: 20000 })
    await new Promise((r) => setTimeout(r, 1200))
    const table = calls.container.querySelector('table')
    const header = [...(table?.querySelectorAll('thead th') ?? [])].map((c) => c.textContent?.trim())
    console.log('   /calls header:', header.join(' | '))
    console.log('   agent column hidden:', !header.includes('Xodim'))
    console.log('   rows:', table?.querySelectorAll('tbody tr').length)
    console.log('   export button offered:', screen.queryByRole('button', { name: 'CSV yuklab olish' }) !== null)
    calls.unmount()

    const dev = mount('/devices')
    await screen.findByRole('table', {}, { timeout: 20000 })
    await new Promise((r) => setTimeout(r, 1200))
    const drows = [...dev.container.querySelectorAll('tbody tr')]
    console.log('   /devices rows:', drows.length)
    const agentNames = new Set(drows.map((r) => r.querySelectorAll('td')[1]?.textContent?.trim()))
    console.log('   agents shown on /devices:', [...agentNames])
    console.log('   >> any agent-name LINKS (needs agents:read)?', dev.container.querySelectorAll('a[href^="/agents/"]').length)
  }, 90000)
})
