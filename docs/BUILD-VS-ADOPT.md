# Build vs adopt — checking the open-source options first

**2026-09-04.** The client asked, correctly, whether an existing open-source
platform makes this easier before we write anything:
*"shunga o'xshash ochiq va mukammal ishlatdigan platformalarni tekshirib ko'rchi,
balki ishimiz osinlashar."*

**Conclusion: keep building — with one real exception, held in reserve (§4).**
Nothing off the shelf fits a SIM-phone fleet where the calls stay on the
employees' own mobile numbers.

---

## 1. ViciDial — mature, free, and a different product

<https://www.vicidial.com/> · 14,000+ installations in 100+ countries

**Architecture:** Asterisk PBX + Perl dialler daemon + PHP/JS agent interface +
MySQL/MariaDB. Agents connect over SIP or WebRTC softphones. It is a
predictive-dialler contact centre, and a genuinely serious one.

**It can use SIM cards** — via a GSM gateway (Goip, Dinstar) or a GSM PCI card
(Sangoma, OpenVox, ATCOM). ViciDial treats the gateway as an ordinary SIP trunk.

**But that puts the SIMs in a rack-mounted box in the office, not in the
salespeople's pockets.** That changes the business, not just the software:

| | Bonvi today (and BonviCall) | ViciDial + GSM gateway |
|---|---|---|
| Where the salesperson works | their own mobile, anywhere | a desk, a headset, a browser |
| What number the client sees | the salesperson's known number | the gateway's number |
| Client calls back | reaches the salesperson directly | reaches a queue |
| Recording | device-dependent | **100 % server-side, reliable** |
| iPhone | uncovered | works |
| Employee can evade it | yes | no |
| Infrastructure | one small server | 8-core / 16 GB / 200 GB for 30 agents |

This is the PBX option from `REQUIREMENTS.md` §5.1, which the client already
weighed and rejected — and the reason it was rejected is exactly right: Bonvi's
clients call salespeople on numbers they already know, and a field salesperson
does not sit at a desk.

**Verdict: not for release 1.** Reconsidered only under §4.

## 2. AndroidCallLogSync — solves the easy half

<https://github.com/MarkoBL/AndroidCallLogSync> · 21 stars · GPL-3.0 · Java

Syncs **call log metadata only** — number, type, duration, timestamp — by POST
to an endpoint you build yourself. No audio. No server.

**Verdict: no.** Call-log sync is the part of BonviCall that is already easy;
the hard part is audio capture, which this does not attempt. GPL-3.0 would also
put a licence obligation on our Android app for no benefit.

## 3. CallSync — closest in spirit, unusable in practice

<https://github.com/duadhruv/CallSync> · 6 stars · Java

Does capture **both metadata and audio**, queues offline, plays back in-app —
architecturally the same idea as BonviCall. Backend is **MSSQL + FTP**.

Two blockers:
- **No licence file.** No licence means all rights reserved: we cannot legally
  use the code, regardless of quality.
- 6 stars, 19 commits, MSSQL/FTP. `../CallSentry` is further along than this and
  we already own it outright.

**One useful signal, though:** it notes Samsung/OneUI support specifically —
independent corroboration of the S1 finding that the practical route to
two-sided audio is the handset's own recorder, not the app's microphone.

## 4. The category itself is empty — and that is the finding

A search of the space turns up MDM tools, PBX suites, CRMs with VoIP, and
hobby-scale call recorders (one is Android 8 only). **There is no mature
open-source platform for "a fleet of employee Android phones that record their
own calls and sync to a company server."** MoyZvonki is a commercial product in
that category; the open-source world has not built one.

So the honest summary: **`../CallSentry` — the throwaway prototype Bonvi already
owns, which already achieved two-sided audio on real phones — is ahead of
everything publicly available.** Building is the right call, and the prototype
is the head start.

**The exception, and it is a real one.** If M0 measures that audio cannot be
captured on most of Bonvi's actual phones, the PBX model stops being a downgrade
and becomes the only way to get audio at all. In that case **ViciDial means not
building a PBX from scratch** — it is mature, free, and it records perfectly.
That is a genuinely different project, and the decision point is M0, not now.

## 5. One tool worth a look for a different problem

<https://fleetdm.com/lp/android-mdm> — Fleet, open-source Android MDM,
self-hostable.

Not call recording, but R17 (installation and permission friction) is our top
practical risk and MDM is the standard answer to it. **Caveat, unresolved:** on
employee-owned phones MDM normally means a work profile, and S2 established that
a work profile cannot see the personal dialer's calls. It may still be worth it
for **distribution and updates only** (N33) rather than for capture. Low
priority, not on the critical path.

---

## Sources

- [ViciDial](https://www.vicidial.com/)
- [ViciDial + GSM gateway discussion](https://vicidial.org/VICIDIALforum/viewtopic.php?f=4&t=26747)
- [VICIdial setup & integration](https://kingasterisk.com/vicidial-setup-integration-guide/)
- [AndroidCallLogSync](https://github.com/MarkoBL/AndroidCallLogSync)
- [CallSync](https://github.com/duadhruv/CallSync)
- [Fleet — open-source Android MDM](https://fleetdm.com/lp/android-mdm)
