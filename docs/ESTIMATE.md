# BonviCall — Estimate

**Date:** 2026-09-04, revision 3 · **Basis:** `docs/TASKS.md` (163 active rows),
`docs/SPEC.md`, `docs/REQUIREMENTS.md` (rev. 3), `docs/RISKS.md` (17 live risks).

> **Revision 3 — re-planned against the SPEC.** The SPEC found real gaps: no
> users module existed (nothing created the accounts people log in with), no
> scheduler, no funnel state machine, no Service Worker audio bridge, and T19's
> migration covered 15 of ~30 tables. **Effort rose +79 likely hours** — but
> almost all of it is server and panel work, so `code` is now **72 %** of the
> total and the project became *more* accelerable, not less.
>
> **The structural win cost nothing.** Splitting the capture *interface* from the
> capture *route* (T71a / T71b) took the entire audio path off the critical path
> and exposed **62 hours of slack** that was previously invisible. The work was
> never blocked; the task boundary was simply in the wrong place. **CP-1 is now
> the enrolment identity chain**, not audio — which makes **W12 (the inbound
> number and receiver) the most schedule-critical thing the client owes.**

> **Revision 2 — the client removed the legal opinion, the consent/notice
> paperwork and SMS from scope: this is an internal company project.**
> The effort total moved by **+3 hours**. The hours freed by dropping those
> items were re-spent almost exactly on the callback-verification work the SMS
> removal made necessary (T141–T143, W12). **The change bought no effort — it
> bought calendar**, and a great deal of it: see §6.

**Two scenarios, because the delivery model changes the answer:**

| Scenario | Working days | Bottleneck |
|---|---|---|
| **A — one developer, 8 h/day, conventional agent use** | **76–102** (plan 88) | the code |
| **B — Claude MAX, 24/7, ~10× on coding** | **25–35** (plan 30) | **the client and the phones — not the code** |

Scenario B is the one to plan against (§5.1). Its headline finding: at 10× on
coding, **development stops being the constraint**. The project floor becomes
the field work and the client's own waits, and no subscription tier moves those.
What the range depends on is in §7 — read that before quoting either number.

---

## 1. What this estimate is and is not

It is a bottom-up estimate: every one of 140 tasks carries its own
optimistic / likely / pessimistic figure, and `O` and `L` are capped at 8 hours
per task, so nothing hides inside a "build the Android app — 3 weeks" line.

It is **not** a quote for a fixed-price contract. Three items in §7 could each
move it by more than 20 %, and two of them are unanswered questions the client
owns rather than engineering unknowns.

**Stack assumption:** `plan-stack` has not run. Estimated against the default —
FastAPI + SQLAlchemy + PostgreSQL server, React + Vite + TypeScript + Tailwind
panel, Kotlin + Compose on Android. A mainstream substitution on the server or
panel side moves the total **±10 % at most**; the Android half is
stack-invariant because N31 rules out the alternatives.

---

## 2. Raw effort, before any agent speedup

Expected value per task is `(O + 4L + P) / 6`, summed.

| Type | Tasks | O | L | P | **Expected** | Agents help? |
|---|---:|---:|---:|---:|---:|---|
| `code` | 111 | 444 | 689 | 1130 | **722 h** | yes — the only category that accelerates well |
| `field` | 18 | 78 | 124 | 238 | **135 h** | **no** — real phones, real people, wall-clock |
| `doc` | 10 | 33 | 49 | 80 | **52 h** | partly |
| `spike` | 7 | 22 | 42 | 84 | **46 h** | barely — the answer is unknown by definition |
| `ops` | 7 | 21 | 34 | 55 | **35 h** | partly |
| `wait` | 10 | 11 | 19 | 37 | **21 h** | no — chase effort only |
| **Total** | **163** | **609** | **957** | **1624** | **1,010 h** | |

1,010 hours is **126 working days for one developer with no agent help.**

Note the shape: pessimistic is **1.7× likely**. That is not padding — it is
concentrated in the audio path, the acceptance remediation buffer and the field
rows, which is exactly where this project's uncertainty actually lives.

---

## 3. Agent speedup — applied honestly

The rule of thumb is 3–5× on the coding phase. Applying that flat to 1,010 h
would produce a number wrong by roughly a factor of two, because **only 69 % of
this project is coding**, and one large part of that coding is the kind agents
are worst at.

| Work | Expected | Multiplier | After | Why |
|---|---:|---|---:|---|
| Server (Phase 3) | 198.7 h | **4×** | 50 h | Conventional API, RBAC, CRUD — agents are genuinely strong here |
| Panel (Phase 5) | 94.8 h | **4×** | 24 h | Same |
| Foundations + M1 (Phases 1–2) | 93.4 h | **4×** | 23 h | Schema, skeletons, thin thread |
| Wiring (Phase 6) | 25.3 h | 3× | 8 h | Sequential by design, shared files |
| **Android app (Phase 4)** | **171.0 h** | **1.75×** | **98 h** | **The honest carve-out.** OEM recorder quirks, dual-SIM subscription IDs, battery managers, foreground-service survival — this is debugging on physical hardware. An agent writes the structure; it cannot hold the phone |
| Support code (Phases 0, 7, 8, 10) | 60.9 h | 2× | 30 h | Measurement rigs, test harnesses |
| `doc` | 53.3 h | 1.5× | 36 h | Agents draft well; the Uzbek manual needs judgement |
| `ops` | 37.8 h | 1.5× | 25 h | |
| `spike` `field` `wait` | 199.5 h | **1×** | 199 h | **Does not move.** No arrangement of agents makes a 7-day acceptance run take less than 7 days |
| **Subtotal** | **1,010 h** | | **513 h** | |

**The agent team takes this project from 126 days to 64 — a 1.9× improvement
overall, not 4×.** The difference is entirely the 197 hours nobody can
accelerate. Halving the coding time *again* would move the total by about 15 %.

---

## 4. The invisible work

Standard uplifts, applied to post-speedup coding time (233 h) — with two
deliberately **not** applied, because `TASKS.md` already contains them as real
tasks and adding them again would be double-counting:

| Item | Rate | Hours | Applied? |
|---|---|---:|---|
| **Tests** | +25 % | **58 h** | **Yes.** Only 5 of 140 tasks are owned by a test or QA role. The plan builds the software; it does not prove it |
| **Client communication and revision cycles** | +20 % | **47 h** | **Yes.** The `wait` rows carry chase effort only, not the back-and-forth of showing work and changing it |
| **Unknowns** | +20 % | **47 h** | **Yes.** §7 lists items that resisted becoming bounded tasks |
| Documentation | +10 % | — | **No** — 10 `doc` tasks, 53 h, already counted in §2 |
| Deploy and configuration | +10 % | — | **No** — 7 `ops` tasks, 38 h, already counted in §2 |
| Data migration | separate | **0 h** | **None in release 1.** BonviCall starts empty; BonviZvonki's history stays where it is (§5.4). *Contingency only:* if the ZRU-547 opinion forces a hosting move after go-live, migrating the audio costs 8/16/32 h |

**Uplift: +152 h.**

---

## 5. The number

| Phase | Days | Note |
|---|---:|---|
| Requirements, SPEC, conventions, stack | *done* | already delivered |
| 0 — Spikes S1/S2 + M0 measurement | 12.6 | mostly `field`; no speedup available |
| 1 — Foundations [sequential] | 3.3 | grew: the schema is now one migration over ~30 tables |
| 2 — M1 thin thread | 1.6 | ends at the first demo: a real call in the panel |
| 3 — Server modules | 7.4 | **largest block.** Agents parallel, 5 in flight |
| 4 — Android app | 12.1 | the one agents help least |
| 5 — Web panel | 3.3 | agents parallel |
| 6 — Wiring [sequential] | 1.5 | shared files, never parallel |
| 7 — M2: the enrolment gate | 6.2 | `field` — three unaided salespeople, stopwatch |
| 8 — M3: survivability | 7.4 | `field`-heavy: reboot, doze, offline, negative proofs |
| 9 — Production | 2.2 | cannot start before the server exists (W03) |
| 10 — M4: acceptance run | 3.8 | contains **7 working days of wall-clock** |
| 11 — Documentation and handover | 2.2 | includes the Uzbek `QOLLANMA.md` |
| Tests (+25 %) | 7.9 | |
| Client communication (+20 %) | 6.3 | |
| Unknowns (+20 %) | 6.3 | |
| **TOTAL** | **87.7** | **working days** |

**Range: 76 – 102 working days.** The low end assumes agents deliver at the top
of their range and no spike surprises; the high end assumes the opposite plus
one extra N40 iteration. Both ends contain the same non-accelerable 197 hours.

---

## 5.1 Scenario B — Claude MAX, 24/7, ~10× on coding

The client reports ~10× on coding in practice, working continuously against a
Claude MAX subscription. Scenario A's 4× was a rule of thumb; this is measured
experience, so the arithmetic below uses 10×.

**What 10× does to each category:**

| Work | Scenario A | **Scenario B** | Why B differs |
|---|---:|---:|---|
| Server + panel + foundations + wiring | 102 h | **40 h** | 10×. Conventional API/UI work — this is exactly where the multiplier is real |
| **Android app** | 100 h | **44 h** | **4×, not 10×.** The code writes fast; the cycle is *build → install on a physical phone → place a real call → read logcat → repeat*. That loop is bounded by the hardware, not the model |
| Support code | 30 h | 12 h | 5× |
| `spike` | 46 h | 23 h | 2×. Reading `CallSentry`'s source is fast; reproducing S1 on a phone in default state is not |
| `doc` / `ops` | 61 h | 23 h | 5× / 3× |
| **`field` + `wait`** | **151 h** | **151 h** | **1×. Unchanged.** No subscription tier places a real call, hands a phone to a salesperson, or makes a lawyer answer sooner |
| Uplifts (tests, comms, unknowns) | 152 h | 63 h | Scale with coding time |
| Stack + SPEC | 24 h | 24 h | Needs the user's own attention |
| **Total** | **702 h** | **397 h** | |

**10× on coding produces 1.77× on the project — and the code is now not the
constraint at all.** At 24/7 the non-field work is ~11 days; the field work is
17 and cannot move. The floor is field-bound, not developer-bound. That is not pessimism about the
multiplier — it is Amdahl's law. Coding falls from 233 h to 96 h, a saving of
137 h; the 151 h of field and waiting sits underneath it and does not move.

**But 24/7 changes the divisor, and that is where the real gain is.** Scenario A
divides by an 8-hour day. Scenario B does not:

| | Hours | Effective day | Days |
|---|---:|---|---:|
| Non-field work | 262 h | 16–24 h (agents run overnight) | **11–16** |
| `field` work | 135 h | **8 h — business hours, real people, real calls** | **17** |
| | | overlapping where dependencies allow | **≈ 25–35** |

**Field work does not go 24/7 either.** Salespeople place calls during the
working day; the N40 enrolment test needs three of them awake and unaided; the
M4 acceptance run measures **7 consecutive working days** of real call traffic
and is 7 days long whether one person or a hundred agents are watching it.

### What this means in practice

**The bottleneck moves off the developer and onto the client.** In Scenario A,
the 30 working days of W02 (legal opinion) + W03 (procurement) fit comfortably
inside an 83-day build and cost nothing. **In a 30-day build they do not fit —
they become the release date.** The same is true of W01: at Scenario A speed a
week's delay on the fleet inventory is absorbed; at Scenario B speed it is a
week added to the end.

So Scenario B's schedule advice is the opposite of Scenario A's. It is not
"write code faster" — it is:

1. **Send the client requests today**, before any code. W01, W02, W04, W07, W08,
   W09 (§6). At this build speed they are the critical path from day one.
2. **Deploy to a temporary host immediately** rather than waiting for W02 → W03.
   `TASKS.md` already carries this as the W02 mitigation; in Scenario B it stops
   being a contingency and becomes the plan, at the price of a possible 8/16/32 h
   audio migration later.
3. **Book the acceptance week and the three salespeople now.** A 7-day run that
   cannot start because nobody is scheduled costs more calendar than the entire
   panel took to build.
4. **Do not compress M0 or M4.** They are the evidence the product works. At 10×
   they are a larger share of the total, which makes cutting them tempting and
   more expensive than before.

**Floor.** Even at infinite coding speed, this project cannot finish faster than
roughly **20 working days**: M0 measurement, the enrolment gate with real
salespeople, the survivability tests, and the 7-day acceptance run are
sequential, wall-clock, and irreducible.

---

## 6. The calendar is not the effort — start the waits on day one

Eleven external waits. They cost the team **21 hours** and the calendar **a
great deal**. Started on day one they overlap the work harmlessly. Started when
the code is ready, they *become* the release date.

| Wait | Cal. days O/L/P | Blocks |
|---|---|---|
| **W01 — fleet inventory** | **3 / 8 / 20** | M0 → **the entire audio path**, the install guide, N40, acceptance. **Now the head of the only critical path** |
| W07 — acceptance handset set | 5 / 10 / 20 | M4 cannot begin. **Promoted: this was hidden behind the legal wait and is now the second-most schedule-critical thing the client owes** |
| W03 — server + storage procurement | 5 / 10 / 25 | production. **No longer blocked by anything** — buy wherever is cheapest, starting today |
| **W12 — inbound number + always-on receiver** | **3 / 7 / 15** | **new.** Number verification (UC-04) — without it nobody can enrol at all |
| W08 — three unaided salespeople booked | 2 / 5 / 15 | **M2 cannot be closed** — N40 is a measured gate, not a review |
| W06 — `plan-stack` session | 1 / 2 / 5 | **all code.** The cheapest wait to close, and it is closable this week |
| W05, W10, W11 | 1–3 typical | defaults already recorded in `ASSUMPTIONS.md` |

**Withdrawn 2026-09-04:** W02 (legal opinion, **10 / 20 / 40 days**), W04 (notice
wording, 3/10/25), W09 (SMS gateway, 3/7/15).

**This is what the scope reduction actually bought.** W02 was a 10–40
working-day approval that nothing could overlap and no amount of staffing could
shorten, and W03 sat behind it. In the 83-day plan that pair fitted inside the
slack; in the 30-day Scenario B plan **it was the release date**. Removing it
deletes roughly **20 working days of pure calendar risk** at the likely case and
40 at the pessimistic one — for zero effort saved.

**CP-2 is no longer a critical path.** Procurement, started on day one,
disappears into the slack: even at its pessimistic 25 days it finishes well
before the technical path reaches deployment. **CP-1 — the fleet inventory, the
M0 measurement, the audio path, the enrolment gate, the acceptance run — is now
the only path that sets the date.**

**W01 is the highest-leverage item in the whole schedule** — it gates the audio
path, and it is satisfied by a photo of Settings → About phone from each
salesperson.

---

## 7. What would move this number — ranked

1. **The fleet turns out to be more than six phone models.** Six are assumed.
   Each extra model adds 6/8/12 h to M0 and 2/3/5 h to the measurement rig —
   **`field` hours, which no agent touches.** Twelve models would add roughly
   70–110 h: a 60–90 % increase in the one category that cannot be compressed.
   *Closed by W01.*
2. **S1 concludes the recording route needs `targetSdk 28`.** Then the install
   friction is permanent and has no engineering fix. The fork is an assisted
   install visit per phone — recurring, roughly 1–2 h per device per event, and
   **not in this estimate** — or a recording route that does not exist. Root is
   ruled out by §5.7, so there is no third option. *Closed by T01–T03, one to
   two days of work.*
3. **A restrictive ZRU-547 opinion.** Priced as if the answer is permissive. A
   restrictive one changes hosting feasibility and adds an 8/16/32 h migration
   that assumes the data set is still small. *Closed by W02.*
4. **N40 fails twice.** One revise-and-retest cycle is budgeted. A second costs
   another 10/16/24 h; a third means the answer is a person doing device visits
   — a permanent budget line, not a project cost.
5. **S2 (work profile) turns out viable.** It would replace much of the
   enrolment and distribution work with different, unestimated work. A branch
   point, not a task with a known follow-on.
6. **UC-16's 5-second click-to-call bar** may be unachievable on doze-restricted
   MIUI/EMUI. Estimated as if it works. If it does not, that is a renegotiation
   of the requirement, not more hours.
7. **N4's remedy is a purchase, not a task.** A model that cannot record means
   Bonvi buys that person a handset or accepts they are uncovered. The cost
   depends entirely on W01 and is not in this estimate.

**Not estimated at all:** release-2 coupling to BonviZvonki — the ingest adapter
and the one-month parallel run live in that repository (§5.4, R13). W10 exists
only to make sure someone books it there.

---

## 8. Two things worth saying plainly

**The first demo is cheap; the last 20 % is not.** A real call appearing in the
panel — Phases 1–2 — is about **7 working days** in, and it is genuinely
demonstrable. Everything after it is the difference between a demo and something
fifteen salespeople depend on: enrolment a non-technical person can complete
alone, capture that survives a reboot, proof that private calls never leave the
phone, and a 7-day run showing the numbers hold. That gap is roughly 75 days,
and it is where projects like this are usually abandoned.

**Adding people would not compress this much.** 197 hours are field and waiting,
and the technical critical path runs through six `field` links that must happen
in order on real hardware. A second developer would help most on Phase 4
(Android) and barely anywhere else.

---

## 9. Cost

### 9.1 Development

Two scenarios (§5, §5.1). The day rate is Bonvi's own number, so the tables are
read off rather than computed here.

**Scenario B — Claude MAX, 24/7 (the one to plan against): 30 working days.**

| Day rate | 25 days | **30 days (plan)** | 35 days |
|---|---:|---:|---:|
| $150 | $3,750 | **$4,500** | $5,250 |
| $200 | $5,000 | **$6,000** | $7,000 |
| $300 | $7,500 | **$9,000** | $10,500 |
| $400 | $10,000 | **$12,000** | $14,000 |

**Plus the subscription:** Claude MAX for the ~6–8 weeks the build runs. At the
published tiers that is roughly **$200–400 total** — small enough that it does
not belong in the same conversation as the day rate, and it replaces most of
what a second developer would have cost.

**Scenario A — conventional, 8 h/day: 83 working days**, for comparison and as
the fallback if the 10× does not hold on the Android half:

| Day rate | 72 days | **83 days** | 97 days |
|---|---:|---:|---:|
| $150 | $10,800 | **$12,450** | $14,550 |
| $200 | $14,400 | **$16,600** | $19,400 |
| $300 | $21,600 | **$24,900** | $29,100 |
| $400 | $28,800 | **$33,200** | $38,800 |

**What does not scale with the rate.** In Scenario B, **151 of the 380 hours —
40 % — are field and waiting work**: placing real calls on real phones, three
salespeople with a stopwatch, a 7-day acceptance run, a lawyer's turnaround.
That share costs the same at any rate and at any subscription tier. It is why
the 10× coding gain lands as a 2.8× reduction in the total rather than a 10×
one, and why the schedule advice in §5.1 is about the client, not the code.

### 9.2 Recurring cost of running it — this is the number that matters

BonviCall is **cheap to run**, and that is the entire commercial argument. It
stores and serves; it does not transcribe or score. There is no ASR bill and no
LLM bill in this project — those stay in BonviZvonki.

| Item | Monthly | Note |
|---|---|---|
| Server (4 vCPU / 8 GB / ≥ 320 GB SSD) | **$25–40** | **Free choice as of 2026-09-04** — the jurisdiction constraint is withdrawn, so host wherever is cheapest. This line used to be $60–120 if the audio had been forced to stay in Uzbekistan |
| Backup storage | $5–15 | Audio is the asset the project exists to own; it needs a second copy |
| Receiver SIM (W12, for callback verification) | ≈ 10–20 k so'm ($1–2) | Replaces the withdrawn SMS gateway line |
| Domain + TLS | ≈ $1 | Let's Encrypt |
| **Total** | **≈ $35–70 / month** | ≈ 0.4–0.9 mln so'm — **down from $45–140**, because hosting is no longer constrained |

At 15 agents that is **$2.5–5 per employee per month**, and it does not grow with
call volume — only with stored hours, at ≈ 17 GB/month.

### 9.3 One-off costs outside the development fee

| Item | Estimate | Depends on |
|---|---|---|
| **Replacement handsets** | **$0 – $1,000+** | **W01.** Any employee whose phone cannot record needs one that can (N4), at roughly $150–250 each. Unknowable until the fleet list arrives — **the single largest uncosted item in the project** |
| **Callback receiver (W12)** | **$50 – $150** | New, and load-bearing: number verification needs an inbound number whose caller ID the server can read. An office SIM in a GSM gateway, or a dedicated Android phone left plugged in. Plus a few thousand so'm a month for the SIM |
| Acceptance handset set (W07) | $0 if borrowed | One phone per fleet model for the 7-day run. Overlaps with the first line |
| ~~Legal opinion~~ | **$0** | **Withdrawn 2026-09-04** — out of scope |
| ~~SMS gateway~~ | **$0** | **Withdrawn 2026-09-04** — out of scope |

### 9.4 Maintenance after go-live — budget it, do not discover it

R9 is not a one-off risk: Android tightens foreground services, background
starts and permissions with roughly every release, and the fleet updates itself.
If S1 confirms the recording route depends on a low `targetSdk`, that clock runs
faster.

**Budget 2–4 days per quarter — 8–16 days per year.** A platform that captures
nothing for six weeks because nobody was watching costs more than the
maintenance would have.

### 9.5 Payback — the missing number has been found, and it is bad news

**MoyZvonki costs 230 ₽ per device per month with recording. 15 employees =
3,450 ₽/month ≈ $37/month**, −20 % on annual payment ≈ **$30/month**.
Source: `../BonviZvonki/docs/PLAN.md` §5.1, which had it all along.

**BonviCall's own running cost is $35–70/month (§9.2). That is the same or
more.** So:

```
payback = development cost / (MoyZvonki $37 − BonviCall $35..70)
        = development cost / (roughly zero, possibly negative)
```

**This project does not pay for itself by cancelling the MoyZvonki
subscription at 15 employees.** The stated justification L2 — "stop paying
MoyZvonki" — does not survive contact with the actual invoice, and it should be
struck rather than quietly carried.

**Where the crossover is.** MoyZvonki scales linearly at ≈ $2.47 per device;
BonviCall's cost is essentially flat (a server) plus slow storage growth.
Break-even is around **20 devices**. Below that MoyZvonki is cheaper; above it
BonviCall wins by an increasing margin, and at 40 agents it is roughly half the
price.

**What the project is actually worth, then** — these are real and none of them
is about the subscription:

| Value | Evidence |
|---|---|
| **Audio retention: 30 days → 12 months** | MoyZvonki deletes recordings after 30 days (`PLAN.md` §5.1: *"Bu bizning arxivimiz emas"* — this is not our archive). BonviZvonki must copy every recording immediately or lose it forever. **This is the strongest argument by a distance** |
| **The recordings are Bonvi's** | No vendor holds the company's conversations, and no vendor can raise a price against them |
| **Data quality** | Employee identity comes from Bonvi's own registry, not from a provider whose employee names arrive as place names (`STATUS.md`) |
| **Headroom** | The economics improve with every hire; MoyZvonki's get worse |

**Recommendation: re-argue the project on retention and ownership, not on
cost.** The cost case is honestly weak at today's headcount, and presenting it
as the reason would not survive the first finance question.

### 9.6 One finding that changes how this should be read

`../BonviZvonki/docs/PLAN.md` records two things about the incumbent worth
knowing before signing anything:

- **MoyZvonki records from the phone** (§7.2: "MoyZvonki telefondan yozib
  oladi"), and its own documentation says recording availability is
  **"telefon modeliga bog'liq"** — dependent on the phone model (§5.1 open
  questions).
- **MoyZvonki keeps audio for 30 days only** (§5.1: "bizning arxivimiz emas" —
  it is not our archive).

So the architecture chosen for BonviCall is **the same one Bonvi already runs**,
and the device-dependence in R1 is a constraint the company is already living
with rather than a new risk this project introduces. That materially strengthens
the case for (a) over a PBX — and it means someone at Bonvi already knows which
phones record and which do not, which may answer W01 faster than a survey.
