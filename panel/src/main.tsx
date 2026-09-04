import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from '@/app/App'
import { initTheme } from '@/shared/theme/store'

import './index.css'

// Before the first paint, so a user who chose dark does not see a white flash.
initTheme()

const container = document.getElementById('root')
if (!container) throw new Error('#root is missing from index.html')

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
