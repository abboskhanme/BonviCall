/* TEMPORARY — final design-pass check. Deleted after the run. */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeAll, describe, expect, it, vi } from 'vitest'

import { CallDetailPage } from '@/modules/calls/CallDetailPage'
import { DevicesPage } from '@/modules/devices/DevicesPage'
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
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[path]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/calls/:id" element={<CallDetailPage />} />
          <Route path="/devices" element={<DevicesPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('final check', () => {
  it('call card: header, one-row audio, no repeated fields', async () => {
    expect(await useAuth.getState().login('admin@bonvi.uz', 'Bonvi2026!')).toBe(true)
    const page = await api.get<{ items: Call[] }>('/calls', { limit: 60 })
    const playable = page.items.find((c) => c.audio.available)
    const { container } = mount(`/calls/${playable?.id}`)
    await waitFor(() => expect(container.querySelectorAll('dt').length).toBeGreaterThan(3), { timeout: 15000 })
    await new Promise((r) => setTimeout(r, 1500))

    console.log('=== SECTIONS AND FIELD COUNTS ===')
    container.querySelectorAll('h2').forEach((h) => {
      const grid = h.parentElement?.parentElement?.querySelector('dl')
      console.log('  §', h.textContent?.trim(), '—', grid?.querySelectorAll('dt').length ?? 0, 'fields')
    })
    const labels = [...container.querySelectorAll('dt')].map((d) => d.textContent?.trim())
    const dupes = labels.filter((l, i) => labels.indexOf(l) !== i)
    console.log('>> duplicate field labels:', dupes)
    console.log('>> audio row children:', [...(container.querySelector('audio')?.parentElement?.children ?? [])].map((c) => c.tagName))
    console.log('>> total dt:', labels.length)
  }, 60000)

  it('devices: queue cell reads, no duplicated problem column', async () => {
    expect(await useAuth.getState().login('admin@bonvi.uz', 'Bonvi2026!')).toBe(true)
    const { container } = mount('/devices')
    await screen.findByRole('table', {}, { timeout: 15000 })
    await new Promise((r) => setTimeout(r, 900))
    const t = container.querySelector('table')
    console.log('=== DEVICES ===')
    t?.querySelectorAll('tbody tr').forEach((r) => {
      const c = [...r.querySelectorAll('td')].map((x) => x.textContent?.trim() || '·')
      console.log(`   ${c[0]} | holat=${c[2]} | navbat=${c[5]} | muammo=${c[7]}`)
    })
  }, 60000)
})
