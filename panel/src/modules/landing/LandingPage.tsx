/**
 * `/` — the public front page, and the only page in this panel with no session.
 *
 * ═══════════════════════════════════════════════════════════════════════════
 * **What it is for: getting the app onto a phone without an account.**
 *
 * Until 2026-09-14 the only way to install was `/i/<code>`, a per-agent link an
 * admin has to issue first. That is still the right path for enrolling a
 * salesperson — the code binds the handset to one registered line — but it is
 * the wrong path for everything else: showing the product to somebody,
 * reinstalling after a factory reset, putting the APK on a second device.
 * Those all used to require an admin at a keyboard.
 *
 * So this page hands out the build and nothing else. It grants no access: the
 * app it downloads is inert until an enrolment code is typed into it, which is
 * still an admin's decision and still binds one phone to one number.
 *
 * **Everything here is already public by another route.** The binary is
 * (SPEC §4.1 rule 5); the version is printed inside it. What this page adds is
 * a sentence beside the button, not a new disclosure — and the endpoint it
 * reads returns a narrow model that never names the member of staff who
 * uploaded the build.
 *
 * The dashboard moved to `/dashboard` to make room. `landingPath()` is what
 * decides where a signed-in user goes, and it is the only place that changed.
 * ═══════════════════════════════════════════════════════════════════════════
 */
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  CheckCircle2,
  Download,
  LogIn,
  Mic,
  ShieldCheck,
  Smartphone,
} from 'lucide-react'

import { useAuth } from '@/modules/auth/store'
import { t } from '@/shared/i18n'
import { landingPath } from '@/shared/auth/landing'
import { Badge, Card } from '@/shared/ui/primitives'
import { buttonClasses } from '@/shared/ui/buttonStyles'

import { downloadPath, useLatestReleases, type PublicRelease } from './api'
import { preferredVariant } from './variant'

function megabytes(bytes: number): string {
  return (bytes / (1024 * 1024)).toFixed(1)
}

const VARIANT_LABEL = {
  legacy28: 'landing.variantLegacy',
  modern34: 'landing.variantModern',
} as const

const VARIANT_HINT = {
  legacy28: 'landing.variantLegacyHint',
  modern34: 'landing.variantModernHint',
} as const

function ReleaseCard({
  release,
  recommended,
}: {
  release: PublicRelease
  recommended: boolean
}) {
  return (
    <Card
      className={`flex flex-col gap-3 p-5 ${
        recommended ? 'border-accent/50 shadow-lift' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-text">
            {t(VARIANT_LABEL[release.variant])}
          </p>
          <p className="mt-0.5 text-2xs text-muted">{t(VARIANT_HINT[release.variant])}</p>
        </div>
        {recommended ? (
          <Badge tone="good">{t('landing.recommended')}</Badge>
        ) : null}
      </div>

      <p className="text-2xs text-muted">
        {t('landing.versionLine', {
          version: release.version,
          size: megabytes(release.size_bytes),
        })}
      </p>

      {/* A plain anchor, not a fetch: the response is a stream with a
          `Content-Disposition`, and the browser's own downloader handles a
          30 MB file better than anything this page could do with a blob. */}
      <a href={downloadPath(release)} className={buttonClasses()}>
        <Download className="size-4" aria-hidden />
        {t('landing.download')}
      </a>
    </Card>
  )
}

function Downloads() {
  const query = useLatestReleases()
  const preferred = preferredVariant(
    typeof navigator === 'undefined' ? '' : navigator.userAgent,
  )

  if (query.status === 'pending') {
    return <p className="text-sm text-muted">{t('landing.loading')}</p>
  }

  // A server error and a server with no build are different sentences. The
  // second is the ordinary state of a fresh deployment and must not read as a
  // fault: nothing is broken, nobody has published yet.
  if (query.status === 'error') {
    return <p className="text-sm text-bad">{t('landing.loadFailed')}</p>
  }

  const items = [...query.data.items].sort((a, b) =>
    a.variant === preferred ? -1 : b.variant === preferred ? 1 : 0,
  )

  if (items.length === 0) {
    return (
      <Card className="p-5">
        <p className="text-sm font-medium text-text">{t('landing.noBuildTitle')}</p>
        <p className="mt-1 text-xs text-muted">{t('landing.noBuildHint')}</p>
      </Card>
    )
  }

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {items.map((release) => (
        <ReleaseCard
          key={release.variant}
          release={release}
          recommended={items.length > 1 && release.variant === preferred}
        />
      ))}
    </div>
  )
}

const POINTS = [
  { icon: Mic, key: 'landing.pointCapture' },
  { icon: Smartphone, key: 'landing.pointFleet' },
  { icon: ShieldCheck, key: 'landing.pointPrivacy' },
] as const

export function LandingPage() {
  const status = useAuth((state) => state.status)
  const signedIn = status === 'authenticated'

  return (
    <div className="min-h-screen bg-bg">
      {/* A soft wash behind the first screenful. Purely decorative, and
          `aria-hidden` so a screen reader is not told about a gradient. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 h-[420px] bg-gradient-to-b from-accent-soft to-transparent"
      />

      <div className="relative mx-auto max-w-4xl px-5 pb-16">
        <header className="flex items-center justify-between gap-3 py-5">
          <span className="text-sm font-semibold tracking-tight text-text">
            {t('app.name')}
          </span>
          {/* One button, top right, as asked. Signed in already? Then the door
              says so — offering "Kirish" to somebody who is logged in sends
              them to a page that bounces them straight back here. */}
          <Link
            to={signedIn ? landingPath() : '/login'}
            className={buttonClasses({ size: 'sm' })}
          >
            {signedIn ? (
              <>
                {t('landing.openPanel')}
                <ArrowRight className="size-4" aria-hidden />
              </>
            ) : (
              <>
                <LogIn className="size-4" aria-hidden />
                {t('landing.signIn')}
              </>
            )}
          </Link>
        </header>

        <main className="animate-fade-up">
          <section className="pt-10 sm:pt-16">
            <Badge tone="neutral">{t('landing.eyebrow')}</Badge>
            <h1 className="mt-4 text-3xl font-semibold tracking-tight text-text sm:text-4xl">
              {t('landing.title')}
            </h1>
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted sm:text-base">
              {t('landing.subtitle')}
            </p>
          </section>

          <section className="mt-10" aria-labelledby="download-heading">
            <h2
              id="download-heading"
              className="mb-3 text-sm font-semibold text-text"
            >
              {t('landing.downloadTitle')}
            </h2>
            <Downloads />
            <p className="mt-3 text-2xs leading-relaxed text-muted">
              {t('landing.downloadNote')}
            </p>
          </section>

          <section className="mt-12 grid gap-4 sm:grid-cols-3">
            {POINTS.map(({ icon: Icon, key }) => (
              <div key={key} className="flex gap-3">
                <Icon className="mt-0.5 size-4 shrink-0 text-accent" aria-hidden />
                <p className="text-xs leading-relaxed text-muted">{t(key)}</p>
              </div>
            ))}
          </section>

          <section className="mt-12">
            <h2 className="mb-3 text-sm font-semibold text-text">
              {t('landing.stepsTitle')}
            </h2>
            <ol className="space-y-2">
              {(['landing.step1', 'landing.step2', 'landing.step3'] as const).map(
                (key) => (
                  <li key={key} className="flex gap-2.5 text-xs text-muted">
                    <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-good" aria-hidden />
                    <span className="leading-relaxed">{t(key)}</span>
                  </li>
                ),
              )}
            </ol>
          </section>
        </main>

        <footer className="mt-16 border-t border-border pt-5">
          <p className="text-2xs text-muted">{t('landing.footer')}</p>
        </footer>
      </div>
    </div>
  )
}
