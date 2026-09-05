/**
 * Downloading a streamed file that needs an `Authorization` header.
 *
 * A plain `<a download>` does not work: the browser follows the link without
 * the header and gets 401. So the response is fetched, turned into a blob and
 * handed to a synthetic link — the same shape as the audio download, and for
 * the same reason.
 *
 * **The filename comes from the server's `Content-Disposition`.** Building it
 * here would put the naming rule in two places and the two would drift; SPEC
 * §4.8 fixes it server-side precisely so an exported file and a downloaded
 * recording agree about how they are named.
 */
import { tokenStore } from '@/shared/api/client'
import { filenameFrom } from './audio'

export async function downloadExport(path: string): Promise<void> {
  const token = tokenStore.get()
  const response = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    credentials: 'include',
    cache: 'no-store',
  })
  if (!response.ok) throw new Error(String(response.status))

  const objectUrl = URL.createObjectURL(await response.blob())
  try {
    const link = document.createElement('a')
    link.href = objectUrl
    link.download = filenameFrom(response.headers.get('content-disposition'))
    document.body.appendChild(link)
    link.click()
    link.remove()
  } finally {
    // Not revoking leaves the whole file in memory until the tab closes.
    URL.revokeObjectURL(objectUrl)
  }
}
