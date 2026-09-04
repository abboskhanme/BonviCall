import { QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'
import { BrowserRouter } from 'react-router-dom'

import { AppRouter } from './router'
import { createQueryClient } from './queryClient'

export function App() {
  // One client per app instance, created lazily so a test can mount App twice
  // without sharing a cache between the two.
  const [queryClient] = useState(createQueryClient)

  return (
    <QueryClientProvider client={queryClient}>
      {/* Opt into the v7 behaviours now: they are the defaults in React Router
          7 and turning them on later is a behaviour change to debug under
          time pressure. */}
      <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AppRouter />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
