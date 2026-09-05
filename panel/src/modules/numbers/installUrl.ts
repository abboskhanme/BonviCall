/**
 * The install link an admin sends to a salesperson.
 *
 * Same-origin by construction, and the same origin `/i/{code}` is served from
 * — the SERVER answers that path with plain HTML (SPEC §8.1), because it is
 * the first thing a non-technical person opens on their own phone over mobile
 * data, and a React bundle there fails to a blank screen.
 *
 * The server does not return this URL: `EnrolmentCodeResponse` carries the
 * code alone, so the link is composed here. One place, so the two callers
 * cannot drift.
 */
export function installUrl(code: string): string {
  return `${window.location.origin}/i/${code}`
}
