/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Source: contract/openapi-panel-v1.json
 * Regenerate: make types   (panel: npm run gen:types)
 *
 * Hand-editing this file is a CONVENTIONS.md §1 violation: the Pydantic schemas
 * are the source of truth and a hand-written copy drifts silently.
 */

export interface paths {
    "/api/v1/activity": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Activity Report
         * @description Who called whom, how many went unanswered, and who was called back.
         *
         *     ⚠️ There is no single "unanswered" number. An unanswered INCOMING call is
         *     the company failing to pick up; an unanswered OUTGOING call is a customer
         *     who was busy. Measured over 7 days of real data: 983 and 1047. Adding them
         *     doubles the figure, destroys its meaning and blames the employee for it.
         *
         *     A ``sales`` caller sees only their own row, and the ``agent_id`` filter in
         *     the URL is ignored for them rather than merged.
         */
        get: operations["activity_report_api_v1_activity_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/activity/missed-clients": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Missed Clients
         * @description Proves the number in the table, customer by customer.
         *
         *     ⚠️ Same window and same logic as the summary — otherwise "9 in the table,
         *     8 in the list" and nobody trusts either.
         *
         *     An agent this caller may not read is a 404, and so is an agent that does
         *     not exist: the two answers are identical on purpose.
         */
        get: operations["missed_clients_api_v1_activity_missed_clients_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Agents */
        get: operations["list_agents_api_v1_agents_get"];
        put?: never;
        /** Create Agent */
        post: operations["create_agent_api_v1_agents_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agents/{agent_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Agent */
        get: operations["get_agent_api_v1_agents__agent_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Update Agent */
        patch: operations["update_agent_api_v1_agents__agent_id__patch"];
        trace?: never;
    };
    "/api/v1/agents/{agent_id}/archive": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Archive Agent
         * @description 409 while the agent still holds an open number assignment.
         */
        post: operations["archive_agent_api_v1_agents__agent_id__archive_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/agents/import": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Import Agents
         * @description A one-off roster import, dry-run by default (T59).
         *
         *     ~33 people, pasted out of a spreadsheet. The diff is shown before anything
         *     is written, because a roster import that half-succeeded is harder to
         *     recover from than one that did not run.
         */
        post: operations["import_agents_api_v1_agents_import_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/alerts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Alerts
         * @description Severity, cause, agent, device, first/last seen and the repeat count.
         *
         *     ``agent_id`` is what the agent's own card reads. The alerts page shows the
         *     open list and nothing else since 2026-09-14 — an inbox that never empties
         *     is an inbox nobody works — so one person's closed history is answered here
         *     instead of by a second page.
         */
        get: operations["list_alerts_api_v1_alerts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/alerts/{alert_id}/ack": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Acknowledge Alert
         * @description Admin only. An alert can be acknowledged, never deleted.
         */
        post: operations["acknowledge_alert_api_v1_alerts__alert_id__ack_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analysis/calls": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Analysed Calls
         * @description A cursor page, newest conversation first (§7.3).
         *
         *     Keyset and not offset, through the same ``cursor`` idiom as the calls list:
         *     no row that existed when paging started is skipped or returned twice, which
         *     an OFFSET cannot give while the pipeline keeps finishing calls underneath.
         *
         *     The sort is fixed at ``started_at DESC``. There is one ordering a reader of
         *     this page wants — the newest conversation — and a sort control that can
         *     disagree with the cursor is a way to lose rows for no gain.
         */
        get: operations["list_analysed_calls_api_v1_analysis_calls_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analysis/calls/{call_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Call Analysis
         * @description One call's state, transcript and score, plus the call's own facts.
         *
         *     A call the pipeline has never touched answers 200 with all three null —
         *     **not 404** — because the page must tell "not analysed" from "no such
         *     call". A call belonging to another agent is the 404.
         */
        get: operations["get_call_analysis_api_v1_analysis_calls__call_id__get"];
        put?: never;
        /**
         * Queue Call Analysis
         * @description Queue one call; the worker picks it up within two minutes.
         *
         *     **Never runs a provider call inside the request.** An LLM round trip behind
         *     an HTTP request is how a panel times out and a user presses the button
         *     again — and each press would be a second bill.
         *
         *     Returns 200 with the state row whether it was created or already there, so
         *     a re-press is indistinguishable from the first press. The four ways this
         *     answers 409 — the feature is off, the call is not analysable, the month's
         *     cap is reached, no provider is configured — are decided in the service.
         */
        post: operations["queue_call_analysis_api_v1_analysis_calls__call_id__post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analysis/rubric": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Active Rubric
         * @description The rubric new scores are produced against.
         *
         *     Answers 200 even when nothing has been published: the response is then the
         *     rubric pinned in ``rubric_default.py`` with ``stored: false``, which is
         *     exactly what such a database scores with. Reading does **not** create the
         *     row — BonviZvonki's version did, which made this GET a write.
         */
        get: operations["get_active_rubric_api_v1_analysis_rubric_get"];
        /**
         * Publish Rubric
         * @description Publish the next version and make it active.
         *
         *     422 ``validation_error`` with a ``reason`` in the detail when the rubric
         *     cannot produce a comparable score — the blocks not totalling 100 is the
         *     first of those reasons, and the rubric is **not saved**.
         */
        put: operations["publish_rubric_api_v1_analysis_rubric_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analysis/rubric/prompt": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Rubric Prompt
         * @description What is actually sent to the model, assembled from the active rubric.
         *
         *     Read-only, and the sections say which single one is editable. An admin who
         *     cannot see this text edits blind; an admin who could edit all of it could
         *     break the response format and stop every score from validating.
         */
        get: operations["get_rubric_prompt_api_v1_analysis_rubric_prompt_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analysis/rubric/versions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Rubric Versions
         * @description Every published version, newest first.
         *
         *     Not paged: a rubric is published a handful of times a year, and the history
         *     is the audit trail of "who changed how people are scored, and when" — which
         *     is worth reading whole.
         */
        get: operations["list_rubric_versions_api_v1_analysis_rubric_versions_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analysis/rubric/versions/{version}/activate": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Activate Rubric Version
         * @description Go back to an earlier version — the undo for a bad edit.
         *
         *     The version keeps its own number rather than being re-published under a new
         *     one, so scores written before and after the round trip carry the same label
         *     and really were produced by the same criteria.
         */
        post: operations["activate_rubric_version_api_v1_analysis_rubric_versions__version__activate_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analysis/status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Analysis Status
         * @description What is waiting, what broke, and what the month has cost (§7.5).
         *
         *     Declared **above** ``/calls/{call_id}``: the two do not collide, but the
         *     literal route staying above the parameterised one is the habit that keeps
         *     them from colliding the day a path is renamed.
         *
         *     Not paged. ``recent_failures`` is capped at twenty server-side, and none of
         *     the four fields below it is a list of rows to walk (§6.2).
         */
        get: operations["analysis_status_api_v1_analysis_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analytics/agents": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Analytics Agent Ranking
         * @description Agents by average score, with the places gained since the last period.
         */
        get: operations["analytics_agent_ranking_api_v1_analytics_agents_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analytics/blocks": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Analytics Block Breakdown
         * @description Each rubric block's average, against the maximum the rubric gives it.
         */
        get: operations["analytics_block_breakdown_api_v1_analytics_blocks_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analytics/distribution": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Analytics Score Distribution
         * @description Scored calls per ten-point band — always ten bands, empty ones included.
         */
        get: operations["analytics_score_distribution_api_v1_analytics_distribution_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analytics/overview": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Analytics Overview
         * @description The KPI cards, each with its change against the previous equal window.
         *
         *     ``calls`` counts **scored** conversations and ``call_types`` accounts for
         *     every other one: without that pairing, "6" in a month of 22,000 calls reads
         *     as a system that lost the rest.
         */
        get: operations["analytics_overview_api_v1_analytics_overview_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analytics/red-flags": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Analytics Red Flag Breakdown
         * @description How often each kind of breach was found, commonest first.
         */
        get: operations["analytics_red_flag_breakdown_api_v1_analytics_red_flags_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/analytics/timeseries": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Analytics Timeseries
         * @description Calls and average score per day, week or month.
         *
         *     Every period in the window is returned, empty ones included: a categorical
         *     axis draws five points the same way over a week and over a quarter, so
         *     omitting the quiet days makes the period filter look broken.
         */
        get: operations["analytics_timeseries_api_v1_analytics_timeseries_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/app/download/{version_code}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Download Version
         * @description The APK itself. **Public** (SPEC §4.1 rule 5), rate-limited.
         *
         *     The install landing page sends a salesperson's browser here and that
         *     browser has no session. The binary is a client and holds no secret; the
         *     enrolment code is the secret, and it guards the page that links here.
         *
         *     ``variant`` is what makes the answer unambiguous: both flavours of one
         *     release carry the same ``version_code`` (SPEC §7.2), so the code alone
         *     named two files and the caller got whichever the database returned first.
         *     Omitted, it hands out ``legacy28`` — the fleet's build, and the one that
         *     installs on every supported Android.
         */
        get: operations["download_version_api_v1_app_download__version_code__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/app/latest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Latest Releases
         * @description The current published build of each variant. **Public**, rate-limited.
         *
         *     What the site's front page reads, so that somebody sent to this server can
         *     install the app without an account. It is the same permission decision SPEC
         *     §4.1 rule 5 already made for the APK itself: the binary is a client and
         *     holds no secret, and a version number beside it tells an attacker nothing
         *     the file would not.
         *
         *     It answers an EMPTY list before the first publish, and that is a real
         *     answer rather than a 404 — a fresh server has no build, and the page says
         *     so in Uzbek instead of offering a button that goes nowhere.
         *
         *     ``PublicReleaseResponse`` is a narrow model on purpose: the admin-facing
         *     one names the member of staff who uploaded the build.
         */
        get: operations["latest_releases_api_v1_app_latest_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/app/min-version": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        /**
         * Set Min Version
         * @description Raise or lower the floor, having stated what it costs.
         *
         *     409 ``stranded_count_mismatch`` when the number moved since the impact was
         *     read. That is not pedantry — it is the case where the admin is deciding
         *     against a picture that is no longer true.
         */
        put: operations["set_min_version_api_v1_app_min_version_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/app/min-version/impact": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Min Version Impact
         * @description Who a proposed minimum would strand — read this before changing it.
         *
         *     Deliberately a ``GET`` with the candidate in the query string, so it can be
         *     called repeatedly while an admin tries numbers, and so the panel can show
         *     the cost live beside the input rather than after the fact.
         */
        get: operations["min_version_impact_api_v1_app_min_version_impact_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/app/versions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Versions
         * @description Every build, newest first. Both variants — they ship in lockstep.
         */
        get: operations["list_versions_api_v1_app_versions_get"];
        put?: never;
        /**
         * Upload Version
         * @description Store a build. **Uploaded is not published** — this reaches nobody yet.
         *
         *     ``multipart/form-data`` rather than the JSON everything else uses, because
         *     the payload is a binary the admin picked in a file dialog. It is the only
         *     such endpoint in the product.
         */
        post: operations["upload_version_api_v1_app_versions_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/app/versions/{version_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Discard Version
         * @description Take back a build that reached nobody.
         *
         *     Unpublished only. A published build stays: it is the distribution record,
         *     and a phone may be downloading it right now. This exists because an upload
         *     with a mistyped version code would otherwise hold that code for ever — the
         *     unique constraint refuses the corrected re-upload.
         */
        delete: operations["discard_version_api_v1_app_versions__version_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/app/versions/{version_id}/publish": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Publish Version
         * @description Make it current for its variant. Every phone is offered it from now on.
         */
        post: operations["publish_version_api_v1_app_versions__version_id__publish_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/assignments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Agent Assignments
         * @description Every line an agent has held, in one request.
         *
         *     The agent detail page renders this as a timeline — the one place the
         *     time-boxed mapping becomes visible to a person.
         */
        get: operations["list_agent_assignments_api_v1_assignments_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/assignments/{assignment_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Close Assignment
         * @description Close a holding period. Calls already attributed keep their agent.
         */
        patch: operations["close_assignment_api_v1_assignments__assignment_id__patch"];
        trace?: never;
    };
    "/api/v1/audit": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Audit
         * @description Who, what, which object, when, from which IP.
         */
        get: operations["list_audit_api_v1_audit_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Login
         * @description Public, rate-limited. A wrong e-mail and a wrong password give the same answer.
         *
         *     Two windows, both SPEC §4.0 and both counting **failures only**
         *     (``core/ratelimit.py`` says why): 20 an hour from one address, and 10 in
         *     five minutes against one login from that address. Somebody who knows their
         *     own password is never refused by either, however often they sign in.
         */
        post: operations["login_api_v1_auth_login_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/logout": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Logout
         * @description End this session. Idempotent — logging out twice is not an error.
         */
        post: operations["logout_api_v1_auth_logout_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Me
         * @description The caller and their resolved permissions.
         *
         *     The panel's ``can()`` reads this list. It never holds a role-to-permission
         *     map: a second copy of the matrix is a second thing to forget to update.
         */
        get: operations["me_api_v1_auth_me_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Change Password
         * @description Self-service change. Succeeding revokes every other session.
         */
        post: operations["change_password_api_v1_auth_password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/auth/refresh": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Refresh
         * @description Rotate the session. Reuse of a spent token revokes the whole chain.
         */
        post: operations["refresh_api_v1_auth_refresh_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Calls
         * @description A cursor page. Default and guaranteed-stable sort is ``received_at DESC``.
         *
         *     Keyset, not offset: no row that existed when paging started is skipped or
         *     returned twice, which is what UC-19 asks for and what an OFFSET cannot give
         *     while calls keep arriving. **Every sort pairs with ``id``**, or paging
         *     duplicates the rows whose sort values tie — and duration ties constantly.
         */
        get: operations["list_calls_api_v1_calls_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/{call_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Call
         * @description 404 for a call that belongs to another agent.
         */
        get: operations["get_call_api_v1_calls__call_id__get"];
        put?: never;
        post?: never;
        /**
         * Delete Call
         * @description **405 for every role, including admin** (UC-26, T45).
         *
         *     The route exists precisely so that the refusal is explicit and testable.
         *     Without it a DELETE would 405 from the router with FastAPI's own body, and
         *     "nobody can delete a call" would be an absence rather than a decision.
         *     Only the retention job removes audio, and it never removes a call.
         *
         *     **No permission dependency on purpose.** T45 asserts 405 for all five
         *     roles, so the refusal has to outrank authorisation: a role that cannot read
         *     calls getting 403 here would mean the answer depends on who is asking, and
         *     it does not.
         *     A caller with no token still gets 401 — that is the principal dependency.
         */
        delete: operations["delete_call_api_v1_calls__call_id__delete"];
        options?: never;
        head?: never;
        /**
         * Update Call Note
         * @description The note and nothing else — every other field is the device's.
         */
        patch: operations["update_call_note_api_v1_calls__call_id__patch"];
        trace?: never;
    };
    "/api/v1/calls/{call_id}/audio": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Stream Audio
         * @description Stream a recording. 200 whole, 206 partial, 410 once retention took it.
         */
        get: operations["stream_audio_api_v1_calls__call_id__audio_get"];
        put?: never;
        post?: never;
        /**
         * Delete Call Audio
         * @description 405 for every role, for the same reason (UC-26).
         */
        delete: operations["delete_call_audio_api_v1_calls__call_id__audio_delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/audio-archive": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Download Audio Archive
         * @description The recordings of **the page the reader is looking at**, as one ZIP.
         *
         *     Deliberately a page and not a filter. The button sits under fifty rows and
         *     hands over those fifty rows; "everything since January" is a different
         *     product decision, and one whose size nobody can see before pressing it.
         *     It therefore takes the same ``cursor``, ``limit`` and sort as the list, so
         *     the archive and the screen cannot disagree about which calls they mean.
         *
         *     ``limit`` is clamped exactly as the list clamps it, so hand-editing the URL
         *     widens nothing.
         *
         *     Every recording it contains is one this principal may already download one
         *     at a time: the page comes from the same scoped query, so own-scope means
         *     own recordings. **One audit row per archive**, not one per file — the
         *     question this action answers is "who took a copy, and of what", and seven
         *     hundred rows would bury the log the way open alerts once buried the alerts
         *     page.
         */
        get: operations["download_audio_archive_api_v1_calls_audio_archive_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/export": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Export Calls
         * @description Streaming CSV for the same filter as the list (T48, UC-22).
         *
         *     UTF-8 **with a BOM** and a ``;`` delimiter: Excel in a ru/uz locale renders
         *     a comma-separated UTF-8 file as one column, and the person who opens it has
         *     no way to know that is what happened.
         *
         *     A ``sales`` export is own-rows-only and carries no other agent's name,
         *     because the same scoped query builds it.
         */
        get: operations["export_calls_api_v1_calls_export_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/calls/stats": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Call Stats
         * @description Calls per day (or per month) per class, for the dashboard's chart.
         *
         *     Declared **above** ``/{call_id}``: that route takes a UUID, so a request
         *     for ``/calls/stats`` matched against it answers 422 rather than reaching
         *     this one.
         *
         *     A preset window is the server's arithmetic and not the caller's — the
         *     browser asking for "a year" in its own timezone would draw a chart whose
         *     edges disagree with every other date in the product (D-10) — so
         *     ``date_from``/``date_to`` are read only for ``period=custom``, and both are
         *     required there. The granularity of a custom range is derived from its span,
         *     not chosen: two dates are the question, and a second control before an
         *     answer is one decision too many.
         *
         *     Own-scope applies exactly as it does to the list, because it is the same
         *     query.
         */
        get: operations["call_stats_api_v1_calls_stats_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/commands/{command_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Command
         * @description Status, latency and the failure reason — UC-16 requires the reason.
         */
        get: operations["get_command_api_v1_commands__command_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/devices": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Devices
         * @description Every device the caller may see, most recently heard from first.
         */
        get: operations["list_devices_api_v1_devices_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/devices/{installation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Device
         * @description One device, **with its capability matrix** (UC-17's device page).
         *
         *     The response model is the detail one, not the list one: declaring the list
         *     model here silently stripped ``capabilities`` and ``capturing``, which are
         *     the two things the page exists to show. Another agent's phone is 404, like
         *     every other scoped read.
         */
        get: operations["get_device_api_v1_devices__installation_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/devices/{installation_id}/commands": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Commands
         * @description History with ``latency_ms``, which is how UC-16's bar is measured.
         */
        get: operations["list_commands_api_v1_devices__installation_id__commands_get"];
        put?: never;
        /**
         * Issue Command
         * @description 202: accepted for delivery, not yet done.
         *
         *     Issuing a command reaches into an employee's personally owned phone, so it
         *     is audited under ``command_issued`` — the only action in the product that
         *     acts on hardware the company does not own.
         */
        post: operations["issue_command_api_v1_devices__installation_id__commands_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/enrolment-codes": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Codes */
        get: operations["list_codes_api_v1_enrolment_codes_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/enrolment-codes/{code_id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Revoke Code */
        post: operations["revoke_code_api_v1_enrolment_codes__code_id__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/enrolment/attempts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Attempts
         * @description Where UC-01's failures appear, with timestamps.
         *
         *     A stalled enrolment must be an event, not silence — this is the list an
         *     admin watches during a rollout.
         */
        get: operations["list_attempts_api_v1_enrolment_attempts_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/enrolment/receiver-status": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Receiver Status
         * @description The banner at the top of the rollout page.
         *
         *     If every receiver is down nobody can enrol, and the page says so **before**
         *     anyone tries. Absence of enrolment must be an event, not a quiet stall.
         */
        get: operations["receiver_status_api_v1_enrolment_receiver_status_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/installations": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Installations */
        get: operations["list_installations_api_v1_installations_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/installations/{installation_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Installation */
        get: operations["get_installation_api_v1_installations__installation_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/installations/{installation_id}/attest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Attest Installation
         * @description Admin attestation (T142) — weaker than proven, and shown as such.
         *
         *     The reason is mandatory and lands in the audit log. The funnel stage
         *     becomes ``verified_by_admin``, which the panel renders differently from
         *     ``number_verified`` everywhere it appears.
         */
        post: operations["attest_installation_api_v1_installations__installation_id__attest_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/installations/{installation_id}/revoke": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Revoke Installation
         * @description Stop capture and kill every issued token (UC-08).
         *
         *     The response carries what was still queued at last contact, because the
         *     admin's next question is always "did we lose anything".
         */
        post: operations["revoke_installation_api_v1_installations__installation_id__revoke_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/line-directory": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Entries */
        get: operations["list_entries_api_v1_line_directory_get"];
        put?: never;
        /**
         * Create Entry
         * @description Add a rule and re-run the classification in the same transaction.
         */
        post: operations["create_entry_api_v1_line_directory_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/line-directory/{entry_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /**
         * Delete Entry
         * @description Deactivate a rule and re-run the classification.
         */
        delete: operations["delete_entry_api_v1_line_directory__entry_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/numbers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Numbers */
        get: operations["list_numbers_api_v1_numbers_get"];
        put?: never;
        /**
         * Create Number
         * @description The number is normalised first, so three formats are one row (N37).
         */
        post: operations["create_number_api_v1_numbers_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/numbers/{number_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get Number */
        get: operations["get_number_api_v1_numbers__number_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /** Update Number */
        patch: operations["update_number_api_v1_numbers__number_id__patch"];
        trace?: never;
    };
    "/api/v1/numbers/{number_id}/assignments": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Assignments
         * @description Full history — this is where the time-boxed mapping becomes visible.
         */
        get: operations["list_assignments_api_v1_numbers__number_id__assignments_get"];
        put?: never;
        /**
         * Create Assignment
         * @description 409 ``number_already_assigned``, with the current holder in ``detail``.
         */
        post: operations["create_assignment_api_v1_numbers__number_id__assignments_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/numbers/{number_id}/enrolment-code": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Issue Enrolment Code
         * @description Single-use, 24 h. The agent is frozen at issue.
         */
        post: operations["issue_enrolment_code_api_v1_numbers__number_id__enrolment_code_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports/data-usage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Data Usage Report
         * @description Per-device cellular traffic against the cap (N14, R14).
         *
         *     The employee pays for this, so it is a first-class report rather than a
         *     debug counter — an unexplained data charge on a personal phone is exactly
         *     what gets an app uninstalled.
         */
        get: operations["data_usage_report_api_v1_reports_data_usage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports/gap": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Gap Report
         * @description Calls without audio by reason, agent and handset model, plus the deltas.
         *
         *     The denominator is **answered** calls: an unanswered call in it makes the
         *     percentage meaningless, which is why ``not_expected`` is a reason rather
         *     than a gap.
         */
        get: operations["gap_report_api_v1_reports_gap_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/reports/storage": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Storage Report
         * @description Current GB and 30-day growth, without a ``du`` over 200 GB (N18).
         */
        get: operations["storage_report_api_v1_reports_storage_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/settings": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List Settings */
        get: operations["list_settings_api_v1_settings_get"];
        /**
         * Update Setting
         * @description 409 ``retention_confirmation_required`` when the change deletes data.
         *
         *     Shortening retention removes recordings that still exist. Refusing without
         *     an explicit confirmation is the difference between a policy change and an
         *     accident nobody can undo.
         */
        put: operations["update_setting_api_v1_settings_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/users": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Users
         * @description Panel accounts only — **not** agents. Never returns a hash or a token.
         */
        get: operations["list_users_api_v1_users_get"];
        put?: never;
        /**
         * Create User
         * @description Create a login. ``role='sales'`` requires ``agent_id`` (409 otherwise).
         */
        post: operations["create_user_api_v1_users_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/api/v1/users/{user_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Get User */
        get: operations["get_user_api_v1_users__user_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        /**
         * Update User
         * @description Guarded: no self-demotion, and never the last active admin.
         */
        patch: operations["update_user_api_v1_users__user_id__patch"];
        trace?: never;
    };
    "/api/v1/users/{user_id}/password": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Set Password
         * @description An admin sets a password. Every session of that user dies with it.
         */
        post: operations["set_password_api_v1_users__user_id__password_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/healthz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Healthz
         * @description Liveness. Touches nothing, so a slow database cannot restart the app.
         */
        get: operations["healthz_healthz_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/readyz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Readyz
         * @description Readiness: the database answers and the audio root is writable.
         */
        get: operations["readyz_readyz_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * ActivityDayRow
         * @description One local day's volume. Empty days are present, never trimmed.
         */
        ActivityDayRow: {
            /** Format: date */
            day: string;
            inbound: number;
            inbound_answered: number;
            missed: number;
            outbound: number;
            outbound_no_answer: number;
        };
        /**
         * ActivityHourRow
         * @description One hour of the LOCAL day, summed across the window.
         *
         *     Asia/Tashkent, never UTC: "customers cannot get through at lunchtime" is
         *     visible at 12:00 and becomes a meaningless 07:00 in UTC. Identical shape to
         *     the daily row, because one chart draws both cuts.
         */
        ActivityHourRow: {
            hour: number;
            inbound: number;
            inbound_answered: number;
            missed: number;
            missed_rate: number | null;
            outbound: number;
            outbound_no_answer: number;
        };
        /**
         * ActivityResponse
         * @description The whole report: window, chart series, per-agent rows and the total.
         */
        ActivityResponse: {
            agents: components["schemas"]["AgentActivityRow"][];
            /** @description Company-wide median minutes to contact. Computed over calls, never as an average of the agents' medians — a median of medians ignores volume. */
            callback_median_minutes: number | null;
            /** @description A later call counts as a callback only inside this many hours. */
            callback_window_hours: number;
            /** Format: date */
            date_from: string;
            /**
             * Format: date
             * @description Inclusive: the last day the window covers.
             */
            date_to: string;
            /** @description Calendar days covered, Asia/Tashkent. */
            days: number;
            days_series: components["schemas"]["ActivityDayRow"][];
            hours_series: components["schemas"]["ActivityHourRow"][];
            /** @description The company row. Its customer counts are computed separately, not summed: one customer who called two employees is one person. */
            total: components["schemas"]["AgentActivityRow"];
        };
        /**
         * ActorType
         * @description Who did the audited thing (SPEC §3.8).
         * @enum {string}
         */
        ActorType: "user" | "service" | "device" | "system";
        /**
         * AgentActivityRow
         * @description One employee over the window. The company total uses the same shape.
         */
        AgentActivityRow: {
            /** Format: uuid */
            agent_id: string;
            agent_name: string;
            /** @description How long this employee keeps a customer waiting (median minutes). A different question from the rate: 100 % returned three hours later is a good rate and a bad service. */
            callback_median_minutes: number | null;
            /** @description Reached as a percent of unreached customers, per CUSTOMER. */
            callback_rate: number | null;
            clients_reached: number;
            /** @description THE HEADLINE: lost business, counted in people rather than calls. */
            clients_unreached: number;
            inbound_answered: number;
            /** @description Calls customers made to the employee. */
            inbound_total: number;
            /** @description INCOMING and not answered — the company's responsibility, and the point of this report. `rejected` counts here with `missed`: the phone rang and there was no conversation. */
            missed: number;
            /** @description Missed events carrying a usable number. `missed_open` divides by this, because a number nobody has cannot be called back. */
            missed_addressable: number;
            /** @description Missed EVENTS followed by contact. */
            missed_called_back: number;
            /** @description Distinct customers who could not get through; repeat attempts count once. Measured: 1.8 attempts per customer on average. */
            missed_clients: number;
            missed_open: number;
            /** @description Missed as a percent of incoming. Null when there were none. */
            missed_rate: number | null;
            outbound_answered: number;
            /** @description The customer did not pick up. NOT a missed call and never added to one: measured over 7 days, 983 incoming unanswered against 1047 outgoing, so combining them doubles the figure and blames the employee for it. */
            outbound_no_answer: number;
            /** @description Calls the employee made to customers. */
            outbound_total: number;
            talk_seconds: number;
            total: number;
        };
        /** AgentListResponse */
        AgentListResponse: {
            items: components["schemas"]["AgentResponse"][];
            total: number;
        };
        /**
         * AgentRankingResponse
         * @description The leaderboard (BonviZvonki ``GET /analytics/agents``).
         */
        AgentRankingResponse: {
            /** Format: date */
            date_from: string;
            /** Format: date */
            date_to: string;
            items: components["schemas"]["AgentRankRowOut"][];
            /** @description Agents with at least one scored call. */
            total: number;
        };
        /**
         * AgentRankRowOut
         * @description One agent's standing over the window.
         */
        AgentRankRowOut: {
            /** Format: uuid */
            agent_id: string;
            agent_name: string;
            ai_score: string | null;
            avg_duration_sec: number;
            calls: number;
            /** @description 1 is the highest average score. */
            rank: number;
            /** @description Places gained against the previous period; positive means moved up. Null for an agent who scored nothing in that period. */
            rank_delta: number | null;
            red_flags: number;
        };
        /** AgentResponse */
        AgentResponse: {
            archived_at: string | null;
            color: string;
            /** Format: date-time */
            created_at: string;
            employee_code: string | null;
            full_name: string;
            hired_at: string | null;
            /** Format: uuid */
            id: string;
            is_active: boolean;
            note: string | null;
        };
        /**
         * AlertKind
         * @description Every cause that can raise an alert (SPEC §10.3).
         *
         *     SPEC §3.1 says "24 values"; §10.3's table groups the three
         *     ``permission_lost_*`` causes on one line and pairs
         *     ``retention_job_failed``/``backup_failed`` on another. Expanded, release 1's
         *     closed set was the first 27 below — the count in §3.1 is a count of table
         *     rows.
         *
         *     The last two arrive with the analysis module (SPEC-ANALYTICS §2.1, §5,
         *     migration 011) and each exists because the nearest existing value would
         *     point an admin at the wrong subsystem: a stalled AI pipeline raising
         *     ``retention_job_failed`` sends somebody to look at deletion, and a monthly
         *     cap stopping the queue is not a failure at all — it is the safety rail
         *     working, and it needs a name that says so.
         * @enum {string}
         */
        AlertKind: "capture_disabled" | "permission_lost_microphone" | "permission_lost_phone_state" | "permission_lost_call_log" | "battery_optimisation_reenabled" | "app_force_stopped" | "install_disappeared" | "recording_route_lost" | "service_not_running" | "device_offline" | "device_silent" | "fleet_silent" | "capture_rate_regression" | "queue_full" | "storage_low" | "poisoned_record" | "auth_expired" | "credential_replay" | "installation_rebound" | "callback_receiver_down" | "enrolment_stalled" | "attribution_out_of_range" | "attribution_discarded_spike" | "retention_job_failed" | "backup_failed" | "storage_capacity_low" | "min_version_refusals" | "analysis_job_failed" | "analysis_cost_cap_reached";
        /** AlertListResponse */
        AlertListResponse: {
            items: components["schemas"]["AlertResponse"][];
            /** @description Neither acknowledged nor resolved. */
            open_count: number;
            total: number;
        };
        /**
         * AlertResponse
         * @description One open or acknowledged alert, as the inbox renders it.
         */
        AlertResponse: {
            acknowledged_at: string | null;
            acknowledged_by: string | null;
            agent_id: string | null;
            /** @description What to do about it. Derived from `kind`, not stored. */
            body_uz: string | null;
            detail: {
                [key: string]: unknown;
            } | null;
            device_model: string | null;
            /** Format: date-time */
            first_seen_at: string;
            /** Format: uuid */
            id: string;
            installation_id: string | null;
            /** @description Status of the installation this alert is about. New alerts are not raised against a superseded phone and its open ones are closed when it is replaced — this is here so a page can also tell at a glance, without a second query, for alerts raised before that rule existed. */
            installation_status?: components["schemas"]["InstallationStatus"] | null;
            kind: components["schemas"]["AlertKind"];
            /** Format: date-time */
            last_seen_at: string;
            number_id: string | null;
            /** @description Repeats bump this rather than inserting a row: a phone reporting every two minutes must not produce 720 rows a day. */
            occurrence_count: number;
            resolved_at: string | null;
            severity: components["schemas"]["AlertSeverity"];
            /** @description What happened, in Uzbek. Derived from `kind`, not stored. */
            title_uz: string;
        };
        /**
         * AlertSeverity
         * @enum {string}
         */
        AlertSeverity: "info" | "warning" | "critical";
        /**
         * AnalysisCallHeader
         * @description Which conversation this is (§7.4).
         *
         *     Carried in the analysis response on purpose: the detail page must say
         *     *whose call, when, with whom and how long* without sending the reader to
         *     the calls section to find out. The analysis section is a section of its own
         *     (§7), so a link there is a navigation away from the page, not a tooltip.
         *
         *     ``agent_name`` is resolved server-side for the same reason
         *     ``CallResponse`` resolves it — a name lookup per row in the browser is the
         *     N+1 problem with a different owner.
         */
        AnalysisCallHeader: {
            /** Format: uuid */
            agent_id: string;
            agent_name: string;
            /** Format: uuid */
            call_id: string;
            /** @description Why a call was or was not scored: only `external` is scored, and `unknown` means the line directory cannot tell yet (§2.6). */
            call_type: components["schemas"]["CallType"];
            direction: components["schemas"]["CallDirection"];
            disposition: components["schemas"]["CallDisposition"];
            duration_sec: number;
            /** @description As the device saw it. NULL when the caller withheld it. */
            remote_number: string | null;
            /**
             * Format: date-time
             * @description When the conversation happened. The list sorts on this (§7.3).
             */
            started_at: string;
        };
        /**
         * AnalysisFailure
         * @description Why a call stopped. Closed, and ``NOT NULL`` whenever the stage is
         *     ``skipped`` or ``failed`` (a CHECK on ``call_analysis_state``).
         *
         *     ``stage`` says whether the row is terminal; this says why. The three groups
         *     below are not decoration — only the transient ones are re-queued by
         *     ``analysis_retry_transient``, and getting that membership wrong is how 885
         *     rate-limited calls stayed permanently failed in BonviZvonki after the quota
         *     they were waiting on had reset.
         * @enum {string}
         */
        AnalysisFailure: "no_audio" | "audio_expired" | "call_too_short" | "call_type_unknown" | "call_type_internal" | "provider_rate_limit" | "provider_cooldown" | "provider_unavailable" | "provider_network" | "interrupted" | "timeout" | "transcript_empty" | "score_invalid" | "ai_not_configured" | "provider_auth" | "provider_model" | "sdk_missing" | "audio_too_large" | "internal";
        /**
         * AnalysisFailureRow
         * @description One recent failure, with enough to act on it (§7.5).
         */
        AnalysisFailureRow: {
            attempts: number;
            /** Format: uuid */
            call_id: string;
            code: components["schemas"]["AnalysisFailure"];
            detail: string | null;
            last_run_at: string | null;
            /** @description Which half was running: transcribe | score. */
            stage: string | null;
            /** Format: date-time */
            started_at: string;
        };
        /**
         * AnalysisListItem
         * @description One row of the scored-call list (§7.3).
         *
         *     The columns §7.3 names and nothing more. No transcript text: a list of
         *     fifty conversations is not a place to ship fifty transcripts, and the
         *     detail page is one click away.
         */
        AnalysisListItem: {
            call: components["schemas"]["AnalysisCallHeader"];
            failure_code: components["schemas"]["AnalysisFailure"] | null;
            needs_review: boolean;
            /** @description NULL until the call is scored — a queued row still has a place in the list. */
            overall_score: number | null;
            /** @description Sorted and de-duplicated, for the chips. The quotes stay on the detail page: a customer's words do not belong in a list payload. */
            red_flag_types: string[];
            scored_at: string | null;
            stage: components["schemas"]["AnalysisStage"];
        };
        /**
         * AnalysisListResponse
         * @description A cursor page of analysed calls, newest conversation first (§7.3).
         */
        AnalysisListResponse: {
            has_more: boolean;
            items: components["schemas"]["AnalysisListItem"][];
            next_cursor: string | null;
            /** @description Counted only when asked, exactly as /calls does it. */
            total?: number | null;
        };
        /**
         * AnalysisMonthResponse
         * @description This Tashkent calendar month's spend against the caps (§4.5, §11.1).
         *
         *     Tashkent and not UTC because the person reading the bill lives there: a
         *     month turning over at 05:00 local would put the first five hours of every
         *     month into the previous one's cap.
         */
        AnalysisMonthResponse: {
            /** @description Measured ASR input — the billing unit. */
            audio_minutes: number;
            /** @description State rows that reached `completed` this month. */
            calls: number;
            /** @description The cap that actually protects the account until a price is entered, because an unpriced month can never reach the money one. */
            cap_calls: number;
            cap_micro_usd: number;
            completion_tokens: number;
            cost_micro_usd: number;
            /**
             * Format: date
             * @description First day of the current Asia/Tashkent month. Named like every other window in this API; §6.2 sketched it as `from`, which is not a Python identifier.
             */
            date_from: string;
            /** @description Whether any vendor price has been entered. **False is what stops the panel rendering $0.00 and implying the feature is free** — a cost of zero because nobody typed a price is not a free feature. */
            priced: boolean;
            prompt_tokens: number;
        };
        /**
         * AnalysisStage
         * @description Where one call stands in the analysis pipeline (SPEC-ANALYTICS §2.4).
         *
         *     The state row *is* the status: there is no ``calls.status`` column and
         *     nothing on ``calls`` is written by the analysis module.
         *
         *     BonviZvonki's ``locked`` is deliberately absent. Locking is the claim query
         *     (``FOR UPDATE SKIP LOCKED``) plus the worker's advisory lock, and neither
         *     survives a crash — a persisted ``locked`` would, leaving a row that no
         *     dispatch picks up and no operator can explain.
         * @enum {string}
         */
        AnalysisStage: "queued" | "transcribing" | "scoring" | "completed" | "skipped" | "failed";
        /**
         * AnalysisStageCounts
         * @description Calls per stage. One field per ``AnalysisStage`` member, always present.
         *
         *     A fixed object rather than a map, so a stage with nothing in it is a
         *     visible zero instead of an absent key the panel has to default. The six
         *     fields are pinned against the enum by a test.
         */
        AnalysisStageCounts: {
            /** @default 0 */
            completed: number;
            /** @default 0 */
            failed: number;
            /** @default 0 */
            queued: number;
            /** @default 0 */
            scoring: number;
            /**
             * @description **Not a failure** and the panel must not paint it as one (§2.4).
             * @default 0
             */
            skipped: number;
            /** @default 0 */
            transcribing: number;
        };
        /**
         * AnalysisStateResponse
         * @description ``call_analysis_state`` as the panel reads it (§6.2).
         *
         *     Also the whole answer to ``POST /analysis/calls/{id}``: queueing returns
         *     the state and nothing else, so a first press and a re-press are
         *     indistinguishable (§5's shape, applied to a panel write).
         */
        AnalysisStateResponse: {
            /** @description Requests that reached a provider, i.e. that cost money. */
            asr_calls: number;
            attempts: number;
            /** @description Measured units x the admin-entered price. 0 also means **not priced** — see `AnalysisMonthResponse.priced` (§11.1). */
            cost_micro_usd: number;
            /** @description Why the call stopped. Present exactly when the stage is `failed` or `skipped` — a database CHECK, not a habit. The Uzbek headline is keyed off this in the panel's uz.json. */
            failure_code: components["schemas"]["AnalysisFailure"] | null;
            /** @description The provider's own message, redacted. Technical English beside the code, never the sentence a user reads. */
            failure_detail: string | null;
            /** @description `transcribe` or `score` — which half spent money before stopping. */
            failure_stage: string | null;
            last_run_at: string | null;
            llm_calls: number;
            /** Format: date-time */
            queued_at: string;
            scored_at: string | null;
            stage: components["schemas"]["AnalysisStage"];
            transcribed_at: string | null;
        };
        /**
         * AnalysisStatusResponse
         * @description The operational view: what is waiting, what broke, what it cost (§7.5).
         *
         *     This is where an admin answers "why has nothing been scored since
         *     Tuesday". It exists in phase 1 because without it that question has no
         *     answer short of opening the database.
         */
        AnalysisStatusResponse: {
            /** @description Only the roles currently sitting out; empty is the normal state. */
            cooldowns: components["schemas"]["ProviderCooldownResponse"][];
            enabled: boolean;
            month: components["schemas"]["AnalysisMonthResponse"];
            /** @description Skips by reason, so '412 calls are waiting on the line directory' is visible rather than silent (§2.6). */
            not_analysable: components["schemas"]["NotAnalysableCount"][];
            /** @description Newest first, capped at 20 server-side. Not a paged list (§6.2). */
            recent_failures: components["schemas"]["AnalysisFailureRow"][];
            stages: components["schemas"]["AnalysisStageCounts"];
            /** @description Failed on a transient code and inside the nightly retry's reach, so it will be tried again by itself. Separate from `stages.failed` on purpose: one of them needs a person and the other does not. */
            waiting_retry: number;
        };
        /**
         * AnalyticsOverviewResponse
         * @description The KPI cards (BonviZvonki ``GET /analytics/overview``).
         */
        AnalyticsOverviewResponse: {
            ai_score: components["schemas"]["ScoreMetricOut"];
            /** @description Mean call length over the scored calls, rounded half up. */
            avg_duration_sec: number;
            call_types: components["schemas"]["CallTypeCountsOut"];
            /** @description **Scored** calls — the join to call_scores is an inner one. A call the pipeline skipped or has not reached is not in it; call_types below is what accounts for the difference. */
            calls: components["schemas"]["CountMetricOut"];
            /** @description Every call in the window, scored or not. */
            calls_total: number;
            /** @description The window every delta_percent above is measured against. */
            compared_with: components["schemas"]["AnalyticsWindow"];
            /** Format: date */
            date_from: string;
            /** Format: date */
            date_to: string;
            /** @description Scored calls carrying at least one red flag, not flags found. */
            red_flags: components["schemas"]["CountMetricOut"];
        };
        /**
         * AnalyticsTimeseriesResponse
         * @description The trend (BonviZvonki ``GET /analytics/timeseries``).
         */
        AnalyticsTimeseriesResponse: {
            /** @enum {string} */
            bucket: "day" | "week" | "month";
            /** Format: date */
            date_from: string;
            /** Format: date */
            date_to: string;
            /** @description True when every period in the window is present, empty ones included. False past the 550-period ceiling, where only periods with data are returned — the panel then draws what it was given rather than pretending the axis is complete. */
            filled: boolean;
            points: components["schemas"]["TimeseriesPointOut"][];
        };
        /**
         * AnalyticsWindow
         * @description The window a report was computed over, echoed back.
         *
         *     On every response, because five of the six are opened without naming a
         *     window at all — the caller asked for "the last 30 days" and the page has to
         *     be able to say which days those were.
         */
        AnalyticsWindow: {
            /** Format: date */
            date_from: string;
            /** Format: date */
            date_to: string;
        };
        /**
         * AppVariant
         * @description The ``targetSdk`` product flavour (D-06).
         *
         *     Reported on every heartbeat, stored on every call, so capture rate is
         *     measurable per variant and not only per handset model.
         * @enum {string}
         */
        AppVariant: "legacy28" | "modern34";
        /** AppVersionListResponse */
        AppVersionListResponse: {
            items: components["schemas"]["AppVersionResponse"][];
            /** @description Whether a signing fingerprint is configured. False means uploads are accepted without the key check — see docs/APK-SIGNING.md. */
            signing_sha256_configured: boolean;
            total: number;
        };
        /**
         * AppVersionResponse
         * @description One build in the distribution record.
         */
        AppVersionResponse: {
            /** @description Computed server-side, never accepted. */
            apk_sha256: string;
            /** Format: date-time */
            created_at: string;
            created_by: string | null;
            /**
             * @description Who uploaded it, resolved server-side. The id alone would make every page re-solve it through `GET /users`, which a manager cannot read — so a manager would see a bare uuid.
             * @default
             */
            created_by_name: string;
            /** Format: uuid */
            id: string;
            is_current: boolean;
            is_mandatory: boolean;
            min_api_level: number;
            /** @description NULL means uploaded but not published — reaches nobody. */
            published_at: string | null;
            release_notes_uz: string | null;
            /** Format: int64 */
            size_bytes: number;
            variant: components["schemas"]["AppVariant"];
            version: string;
            version_code: number;
        };
        /**
         * AssignmentListResponse
         * @description Full history for a number — this is the timeline the agent page renders.
         */
        AssignmentListResponse: {
            items: components["schemas"]["AssignmentResponse"][];
            total: number;
        };
        /** AssignmentResponse */
        AssignmentResponse: {
            /** Format: uuid */
            agent_id: string;
            /** Format: date-time */
            created_at: string;
            /** Format: uuid */
            id: string;
            note: string | null;
            /** Format: uuid */
            number_id: string;
            /** Format: date-time */
            valid_from: string;
            valid_to: string | null;
        };
        /**
         * AttestRequest
         * @description ``POST /api/v1/installations/{id}/attest`` (T142).
         *
         *     Attestation is deliberately weaker evidence than a proven binding, and the
         *     reason is mandatory: an unexplained attestation is indistinguishable from a
         *     mistake six months later.
         */
        AttestRequest: {
            reason: string;
        };
        /**
         * AudioMissingReason
         * @description Why a call has no audio. Closed, ``NOT NULL`` whenever audio is absent (N5).
         *
         *     UC-14 names six; SPEC §3.9 justifies the other four one by one. The gap
         *     report's denominator excludes ``pending_upload`` and ``not_expected``,
         *     which is what keeps "% of answered calls with audio" honest.
         * @enum {string}
         */
        AudioMissingReason: "pending_upload" | "not_expected" | "recording_route_unavailable" | "oem_recorder_off" | "no_permission" | "capture_returned_silence" | "app_not_running" | "upload_expired" | "queue_space_exhausted" | "attribution_failed";
        /**
         * AuditAction
         * @description Every auditable action (UC-24, N27).
         *
         *     SPEC §3.16 was written against this set after the fact and added two values
         *     to it. Both earn their place by being separately *filterable*:
         *
         *     * ``retention_changed`` is technically a ``setting_updated``, but it is the
         *       one setting whose change destroys data — "who shortened retention, and
         *       when" must be one filter, not a JSONB dig through every settings change.
         *     * ``command_issued`` is a person reaching into an employee's **personally
         *       owned** phone. It is the only action in the product that acts on somebody
         *       else's hardware, and this log is the only place that is visible.
         *
         *     Adding a value is a migration, which is the point: the list is closed so
         *     that "everything that happened" is answerable from one column.
         * @enum {string}
         */
        AuditAction: "login_succeeded" | "login_failed" | "logout" | "password_changed" | "password_reset" | "user_created" | "user_updated" | "user_deactivated" | "agent_created" | "agent_updated" | "agent_archived" | "agents_imported" | "number_created" | "number_updated" | "assignment_created" | "assignment_closed" | "calls_reattributed" | "enrolment_code_issued" | "enrolment_code_revoked" | "installation_attested" | "installation_self_declared" | "installation_revoked" | "installation_rebound" | "command_issued" | "call_note_updated" | "calls_exported" | "audio_play" | "audio_download" | "audio_deleted" | "alert_acknowledged" | "setting_updated" | "retention_changed" | "line_directory_updated" | "supported_model_updated" | "app_version_uploaded" | "app_version_published" | "service_token_created" | "service_token_revoked" | "export_read";
        /** AuditListResponse */
        AuditListResponse: {
            items: components["schemas"]["AuditResponse"][];
            total: number;
        };
        /**
         * AuditResponse
         * @description One thing that happened. Immutable, by database trigger.
         */
        AuditResponse: {
            action: components["schemas"]["AuditAction"];
            actor_service_token_id: string | null;
            actor_type: components["schemas"]["ActorType"];
            actor_user_id: string | null;
            /** Format: date-time */
            at: string;
            /** @description Before/after values and counts. Never a password, a token or an enrolment code (N26). Open by nature — this is a server-side record, not a device payload, so §8's allow-list does not apply. */
            detail?: {
                [key: string]: unknown;
            } | null;
            /** Format: uuid */
            id: string;
            ip: string | null;
            object_id: string | null;
            object_type: string;
            user_agent: string | null;
        };
        /**
         * BlockBreakdownResponse
         * @description The radar chart (BonviZvonki ``GET /analytics/blocks``).
         *
         *     A block the rubric does not name is **left out** rather than sent with a
         *     null percentage: we do not know what to divide it by, and a bar with no
         *     scale is worse than a missing one.
         */
        BlockBreakdownResponse: {
            /** Format: date */
            date_from: string;
            /** Format: date */
            date_to: string;
            items: components["schemas"]["BlockScoreOut"][];
        };
        /**
         * BlockScoreOut
         * @description One rubric block, averaged over the window.
         */
        BlockScoreOut: {
            /** @description The rubric's own key. An open vocabulary on purpose: scores are written under a pinned rubric_version, so a block a later rubric adds must still be readable. The panel renders an unknown key as the key. */
            block: string;
            /** @description From the rubric, never a second constant. The two were once typed separately, diverged 25 against 15, and the radar chart drew 106 % in front of a manager. */
            max: number;
            /** @description score/max. The radar chart's axis, which is why it is bounded. */
            percent: string;
            score: string;
            /** @description Calls this block's average is taken over. */
            scored_calls: number;
        };
        /** Body_upload_version_api_v1_app_versions_post */
        Body_upload_version_api_v1_app_versions_post: {
            /**
             * Format: binary
             * @description The signed APK.
             */
            apk: string;
            /** @default false */
            is_mandatory: boolean;
            /** @default 26 */
            min_api_level: number;
            release_notes_uz?: string | null;
            variant: components["schemas"]["AppVariant"];
            version: string;
            version_code: number;
        };
        /**
         * CallAnalysisResponse
         * @description Everything the detail page needs, in one request (§6.2, §7.4).
         *
         *     ``state``, ``transcript`` and ``score`` are **independently nullable**. A
         *     call the pipeline has never touched answers 200 with all three null — not
         *     404, because the page must be able to tell "not analysed" from "no such
         *     call", and only one of those two is worth an error.
         *
         *     ``enabled`` is repeated here rather than left to ``/analysis/status`` for
         *     the same reason: deciding what to render must not cost two round trips to
         *     learn a boolean.
         */
        CallAnalysisResponse: {
            call: components["schemas"]["AnalysisCallHeader"];
            /** Format: uuid */
            call_id: string;
            /** @description `analysis.enabled`. False plus a null state means the page says 'o'chirilgan' and offers no button — pressing it would 409 (§7.4). */
            enabled: boolean;
            score: components["schemas"]["ScoreResponse"] | null;
            state: components["schemas"]["AnalysisStateResponse"] | null;
            transcript: components["schemas"]["TranscriptResponse"] | null;
        };
        /**
         * CallAudioSummary
         * @description What the call list and the detail page need to know about the audio.
         *
         *     ``capture_route`` is here and not folded into "audio: yes/no" because
         *     ``S1-RECORDING.md`` is explicit that ``app_voice_recognition`` and
         *     ``app_mic`` must stay distinguishable: the per-model capture rate is the M0
         *     baseline, and UC-23's regression alert compares against it. Collapsing the
         *     routes would make "which mechanism actually works on this handset" an
         *     unanswerable question.
         */
        CallAudioSummary: {
            /** @description Closed enum, never free text (N5). */
            audio_missing_reason?: components["schemas"]["AudioMissingReason"] | null;
            /** @description Playable now — stored and not yet expired. */
            available: boolean;
            /** @description Which strategy produced it (S1, M0, UC-23). */
            capture_route?: components["schemas"]["CaptureRoute"] | null;
            /** @description The folder name only, never a path from the phone. */
            capture_route_detail?: string | null;
            /**
             * @description The file's length disagrees with the call log (UC-14).
             * @default false
             */
            duration_mismatch: boolean;
            duration_ms?: number | null;
            /** @description Removed by retention; playback answers 410 (UC-26). */
            expired_at?: string | null;
            /** @description Path to stream from, present only when the recording is available. A path and never a signed or public URL (N20): the endpoint is token-protected, and the panel reaches it through the Service Worker bridge because a plain <audio src> cannot send an Authorization header (T153, N43). */
            url?: string | null;
        };
        /**
         * CallDirection
         * @description Ours, not BonviZvonki's ``inbound``/``outbound``.
         *
         *     The export (SPEC §4.9) maps ours onto theirs in exactly one place, so the
         *     two vocabularies never leak into each other.
         * @enum {string}
         */
        CallDirection: "incoming" | "outgoing";
        /**
         * CallDisposition
         * @description UC-11's five classes are direction x disposition.
         *
         *     ``missed`` and ``rejected`` are incoming-only, ``no_answer`` is
         *     outgoing-only — enforced by a CHECK, so the invalid combinations are
         *     unrepresentable rather than merely unused.
         * @enum {string}
         */
        CallDisposition: "answered" | "missed" | "rejected" | "no_answer";
        /**
         * CallListResponse
         * @description A cursor page of calls (SPEC §4.0).
         *
         *     ``total`` is computed only when the caller asks: a COUNT(*) over a filtered
         *     500k table is affordable once per filter change and not once per page.
         */
        CallListResponse: {
            has_more: boolean;
            items: components["schemas"]["CallResponse"][];
            next_cursor: string | null;
            total?: number | null;
        };
        /**
         * CallResponse
         * @description A call as the panel reads it.
         *
         *     Carries the display fields, not only ids. Making the browser look up an
         *     agent's name per row is the N+1 problem relocated to the client, and the
         *     ``device_model`` filter would otherwise exist server-side for a column the
         *     panel cannot show.
         */
        CallResponse: {
            /** Format: uuid */
            agent_id: string;
            /** @description Resolved server-side; the panel renders it. */
            agent_name: string;
            answered_at: string | null;
            app_variant: components["schemas"]["AppVariant"];
            app_version: string;
            audio: components["schemas"]["CallAudioSummary"];
            audio_duration_mismatch: boolean;
            audio_missing_reason: components["schemas"]["AudioMissingReason"] | null;
            call_type: components["schemas"]["CallType"];
            clock_skew_sec: number;
            contact_name: string | null;
            /** @description 'Xiaomi Redmi Note 12'. The device_model filter needs it. */
            device_model?: string | null;
            device_timezone: string;
            direction: components["schemas"]["CallDirection"];
            disposition: components["schemas"]["CallDisposition"];
            duration_sec: number;
            ended_at: string | null;
            has_audio: boolean;
            /** Format: uuid */
            id: string;
            /** Format: uuid */
            installation_id: string;
            note: string | null;
            /** @description The registered line the call happened on. */
            number_e164: string;
            /** Format: uuid */
            number_id: string;
            /**
             * Format: date-time
             * @description Authoritative for ordering (N36).
             */
            received_at: string;
            reconciled_with_call_log: boolean;
            remote_number: string | null;
            remote_number_key: string | null;
            ring_sec: number | null;
            /** Format: int64 */
            seq: number;
            source: components["schemas"]["CallSource"];
            /** Format: date-time */
            started_at: string;
        };
        /**
         * CallSentiment
         * @description The model's reading of how the conversation went.
         * @enum {string}
         */
        CallSentiment: "positive" | "neutral" | "negative";
        /**
         * CallSource
         * @description How the record reached us.
         * @enum {string}
         */
        CallSource: "live_capture" | "call_log_recovery" | "provider";
        /**
         * CallStatsBucket
         * @description One point on the x-axis: UC-11's five classes, counted.
         *
         *     Every bucket in the window is returned, including the empty ones. A chart
         *     that receives only the days something happened draws a straight line
         *     through a silent week, which is the one thing this chart exists to show.
         */
        CallStatsBucket: {
            /**
             * Format: date
             * @description Asia/Tashkent calendar date, inclusive.
             */
            date_from: string;
            /**
             * Format: date
             * @description Inclusive, and equal to date_from for a daily bucket. The last bucket is clipped to today, so a part-month is not drawn as a whole one.
             */
            date_to: string;
            /** @default 0 */
            incoming_answered: number;
            /** @default 0 */
            missed: number;
            /** @default 0 */
            no_answer: number;
            /** @default 0 */
            outgoing_answered: number;
            /** @default 0 */
            rejected: number;
            /**
             * @description Every call in the bucket, which is what the same filter returns from /calls — not necessarily the sum of the five classes.
             * @default 0
             */
            total: number;
        };
        /**
         * CallStatsResponse
         * @description ``GET /api/v1/calls/stats`` — the call flow the dashboard draws.
         */
        CallStatsResponse: {
            buckets: components["schemas"]["CallStatsBucket"][];
            /** Format: date */
            date_from: string;
            /** Format: date */
            date_to: string;
            /** @enum {string} */
            granularity: "day" | "month";
            /** @enum {string} */
            period: "week" | "month" | "year" | "custom";
        };
        /**
         * CallType
         * @description Internal vs external (UC-25). ``unknown`` is the mandatory default.
         *
         *     An empty line directory yields ``unknown``, never ``external``:
         *     BonviZvonki defaulted to external and 82 of 98 calls were mislabelled.
         * @enum {string}
         */
        CallType: "internal" | "external" | "unknown";
        /**
         * CallTypeCountsOut
         * @description Calls by type, over the window. **Every key is always present.**
         *
         *     A fixed object rather than a map, so a type with nothing in it is a visible
         *     zero instead of an absent key the panel defaults for itself — which is how
         *     the two lists drift apart. The fields are pinned against ``CallType`` by a
         *     test.
         *
         *     **Deliberately not narrowed to scored calls.** This is the breakdown that
         *     explains the headline: the ``calls`` metric counts *scored* conversations,
         *     and without this row a manager who sees "6" in a month of 22,000 calls
         *     concludes the system lost the rest. Measured in BonviZvonki: 72 against
         *     22,026 for the same period.
         */
        CallTypeCountsOut: {
            /** @default 0 */
            external: number;
            /** @default 0 */
            internal: number;
            /** @default 0 */
            unknown: number;
        };
        /**
         * Capability
         * @description One row per installation per capability (UC-03, §7.8).
         *
         *     Every one of these is verified by exercising it, never by reading a
         *     permission flag — that is what makes ``granted_not_working`` expressible.
         * @enum {string}
         */
        Capability: "phone_state" | "call_log" | "microphone" | "contacts" | "notifications" | "call_phone" | "battery_exemption" | "storage_access" | "oem_autostart" | "foreground_service" | "oem_recorder" | "subscription_resolution";
        /**
         * CapabilityState
         * @description ``granted_not_working`` is the OEM-permission-manager case UC-03 names.
         * @enum {string}
         */
        CapabilityState: "granted_working" | "granted_not_working" | "denied" | "denied_permanently" | "not_applicable" | "unknown";
        /**
         * CapabilityStateResponse
         * @description One capability's current state, as the panel's matrix renders it.
         *
         *     A **required** capability the phone has never reported appears here as
         *     ``unknown`` with null timestamps, rather than being absent. Absence made
         *     the page show every row green while ``capturing`` was false, with nothing
         *     on screen saying which capability was missing — and a phone stuck part-way
         *     through E2 is exactly that shape.
         */
        CapabilityStateResponse: {
            capability: components["schemas"]["Capability"];
            /** @description Null until there is a state to have changed from. */
            changed_at?: string | null;
            /** @description Null when this capability has never been checked. */
            checked_at?: string | null;
            detail: string | null;
            state: components["schemas"]["CapabilityState"];
        };
        /**
         * CaptureRoute
         * @description Which mechanism produced the recording (S1, the M0 baseline).
         *
         *     ``NONE`` may only appear with ``has_audio = false``.
         * @enum {string}
         */
        CaptureRoute: "oem_file_harvest" | "app_voice_call" | "app_voice_recognition" | "app_voice_communication" | "app_mic" | "none";
        /**
         * ChangePasswordRequest
         * @description ``POST /api/v1/auth/password`` — the user's own password.
         */
        ChangePasswordRequest: {
            /** @description Wrong value gives 401. */
            current_password: string;
            /** @description Minimum 10 characters and no other composition rule (SPEC §4.7): a rule people cannot follow is a rule they write on a sticky note. */
            new_password: string;
        };
        /**
         * CloseAssignmentRequest
         * @description ``PATCH /api/v1/assignments/{id}`` — end a holding period.
         */
        CloseAssignmentRequest: {
            note?: string | null;
            /**
             * Format: date-time
             * @description Must be after valid_from.
             */
            valid_to: string;
        };
        /**
         * CommandFailureReason
         * @description Why a command did not happen. UC-16 requires the panel to say which.
         * @enum {string}
         */
        CommandFailureReason: "device_offline" | "no_permission" | "os_refused" | "ack_timeout" | "discarded_stale" | "unsupported" | "busy";
        /**
         * CommandKind
         * @description Server-to-device commands. No ``send_sms`` — SMS is out of scope.
         * @enum {string}
         */
        CommandKind: "dial" | "config" | "logout" | "ping" | "recheck";
        /** CommandListResponse */
        CommandListResponse: {
            items: components["schemas"]["CommandResponse"][];
            total: number;
        };
        /** CommandResponse */
        CommandResponse: {
            acked_at: string | null;
            /** Format: date-time */
            created_at: string;
            /** Format: date-time */
            expires_at: string;
            failure_reason: components["schemas"]["CommandFailureReason"] | null;
            /** Format: uuid */
            id: string;
            /** Format: uuid */
            installation_id: string;
            kind: components["schemas"]["CommandKind"];
            /** @description acked_at - created_at, stored so UC-16's five-second bar is **measured** rather than assumed. R3 flags that bar as possibly unachievable on doze-restricted OEMs; this column is what turns that into a conversation with evidence. */
            latency_ms: number | null;
            result_call_id: string | null;
            sent_at: string | null;
            status: components["schemas"]["CommandStatus"];
        };
        /**
         * CommandStatus
         * @enum {string}
         */
        CommandStatus: "pending" | "sent" | "acknowledged" | "failed" | "expired";
        /**
         * CountMetricOut
         * @description A count, with its change against the previous period of equal length.
         */
        CountMetricOut: {
            /** @description Percent change. Null when the previous period was zero or has no value — 'up from nothing' is not a percentage. */
            delta_percent: string | null;
            value: number;
        };
        /**
         * CreateAgentRequest
         * @description ``POST /api/v1/agents``. Creating an agent never creates a login.
         */
        CreateAgentRequest: {
            color?: string | null;
            /** @description The roster import key; unique where set. */
            employee_code?: string | null;
            full_name: string;
            hired_at?: string | null;
            note?: string | null;
        };
        /**
         * CreateAssignmentRequest
         * @description ``POST /api/v1/numbers/{id}/assignments`` — hand a line to an agent.
         */
        CreateAssignmentRequest: {
            /** Format: uuid */
            agent_id: string;
            note?: string | null;
            /** @description Defaults to now. The period is [valid_from, valid_to). */
            valid_from?: string | null;
            /** @description NULL means open-ended — they hold it now. */
            valid_to?: string | null;
        };
        /**
         * CreateCommandRequest
         * @description ``POST /api/v1/devices/{installation_id}/commands``.
         */
        CreateCommandRequest: {
            kind: components["schemas"]["CommandKind"];
            /** @description For kind='dial'. Named, not a free-form payload map (§8). */
            number?: string | null;
            reason?: string | null;
        };
        /**
         * CreateDirectoryEntryRequest
         * @description ``POST /api/v1/line-directory`` — an admin extra for UC-25.
         */
        CreateDirectoryEntryRequest: {
            kind: components["schemas"]["DirectoryRuleKind"];
            label?: string | null;
            /** @description Digits to match. UC-25's '*700' is the suffix rule '700'. */
            pattern: string;
        };
        /**
         * CreateNumberRequest
         * @description ``POST /api/v1/numbers``.
         *
         *     The number is normalised to E.164 before it is stored, so the same line
         *     typed three ways is one row — the uniqueness lives on the generated
         *     ``phone_key`` column, not on this string.
         */
        CreateNumberRequest: {
            /** @description Any format; normalised here. */
            e164: string;
            label?: string | null;
            /** @description beeline | ucell | mobiuz | uzmobile | other. A reporting axis (R19). */
            operator?: string | null;
            /**
             * @description R10: which SIM relationships are not Bonvi's to keep.
             * @default company
             */
            sim_owner: string;
        };
        /**
         * CreateUserRequest
         * @description ``POST /api/v1/users`` — creates a **login**, not a salesperson.
         */
        CreateUserRequest: {
            /** @description Required when role='sales' — it is what own-scope narrowing filters on, and the database has a CHECK saying so. */
            agent_id?: string | null;
            /** Format: email */
            email: string;
            full_name: string;
            password: string;
            role: components["schemas"]["UserRole"];
        };
        /**
         * CurrentUserResponse
         * @description ``GET /api/v1/auth/me`` — what the panel's ``can()`` reads.
         *
         *     The permission list is resolved server-side and sent whole. The panel never
         *     holds a role-to-permission map: a second copy of the matrix is a second
         *     thing to forget to update.
         */
        CurrentUserResponse: {
            /** @description Set for a 'sales' account; what own-scope filters on. */
            agent_id?: string | null;
            email: string;
            full_name: string;
            /** Format: uuid */
            id: string;
            /** @description The panel forces the change before anything else loads. */
            must_change_password: boolean;
            /** @description Resolved from the role, sorted. */
            permissions: string[];
            role: components["schemas"]["UserRole"];
        };
        /** DataUsageResponse */
        DataUsageResponse: {
            /** Format: int64 */
            cap_bytes_month: number;
            items: components["schemas"]["DataUsageRowOut"][];
            total: number;
        };
        /**
         * DataUsageRowOut
         * @description One installation's traffic against the cap the employee pays for.
         */
        DataUsageRowOut: {
            agent_name: string;
            /** Format: int64 */
            cap_bytes_month: number;
            /** Format: int64 */
            cellular_bytes_month: number;
            /** Format: uuid */
            installation_id: string;
            /** @description Past N14's cap: the app stops uploading audio over cellular. */
            over_cap: boolean;
            requests_month: number;
            /** Format: int64 */
            wifi_bytes_month: number;
        };
        /**
         * DeviceDetailResponse
         * @description Device health plus its capability matrix (UC-17's device page).
         */
        DeviceDetailResponse: {
            /** Format: uuid */
            agent_id: string;
            android_release: string | null;
            api_level: number | null;
            app_variant: components["schemas"]["AppVariant"] | null;
            app_version: string | null;
            battery_charging: boolean | null;
            battery_level: number | null;
            battery_optimisation_exempt: boolean | null;
            /** @description When this installation was bound to the number. */
            bound_at?: string | null;
            /** @description Empty for a phone that has never reported — not missing. */
            capabilities?: components["schemas"]["CapabilityStateResponse"][];
            capture_enabled: boolean | null;
            /**
             * @description UC-03's never-false-ready rule: every required capability working, a verified installation and a live service. One function computes it, so the phone and the panel cannot disagree.
             * @default false
             */
            capturing: boolean;
            cellular_bytes_month: number | null;
            clock_skew_sec: number | null;
            /** @description When the row was created. With `installation_status` it is what distinguishes a live binding from one superseded an hour ago. */
            created_at?: string | null;
            device_timezone: string | null;
            free_storage_bytes: number | null;
            /** Format: uuid */
            installation_id: string;
            installation_status: components["schemas"]["InstallationStatus"];
            /** @description Derived, never stored: last_heartbeat_at is inside the alerts.device_offline_minutes window. Storing it would need a job to keep it false, and it would be wrong between runs. */
            is_online: boolean;
            last_call_at: string | null;
            last_heartbeat_at: string | null;
            manufacturer: string | null;
            model: string | null;
            network_type: components["schemas"]["NetworkType"] | null;
            /** @description Bound and never sent a heartbeat. Kept distinct from ``is_online: false`` because the next action differs: never started is a person waiting for help right now; worked once and stopped is a phone in a lift or a battery manager to argue with. */
            never_reported: boolean;
            /** Format: uuid */
            number_id: string;
            parked_records: number | null;
            power_save_mode: boolean | null;
            queue_bytes: number | null;
            queue_oldest_at: string | null;
            queue_records: number | null;
            recording_route: components["schemas"]["CaptureRoute"] | null;
            recording_route_ok: boolean | null;
            service_running: boolean | null;
            updated_at: string | null;
            /** @description Shown separately from is_online on purpose: a socket can be alive while capture is dead, and conflating the two is how a broken phone looks fine. */
            ws_connected?: boolean | null;
        };
        /** DeviceHealthListResponse */
        DeviceHealthListResponse: {
            items: components["schemas"]["DeviceHealthResponse"][];
            total: number;
        };
        /**
         * DeviceHealthResponse
         * @description Every UC-17 field, plus the identity the panel needs to name a person.
         */
        DeviceHealthResponse: {
            /** Format: uuid */
            agent_id: string;
            android_release: string | null;
            api_level: number | null;
            app_variant: components["schemas"]["AppVariant"] | null;
            app_version: string | null;
            battery_charging: boolean | null;
            battery_level: number | null;
            battery_optimisation_exempt: boolean | null;
            /** @description When this installation was bound to the number. */
            bound_at?: string | null;
            capture_enabled: boolean | null;
            /** @description Whether this phone is recording **right now**: every required capability working, the installation verified, the service alive (UC-03). Never null — a phone that has told us nothing is not recording, and a null here reads as 'no problem' to any check asking whether it is false. */
            capturing: boolean;
            cellular_bytes_month: number | null;
            clock_skew_sec: number | null;
            /** @description When the row was created. With `installation_status` it is what distinguishes a live binding from one superseded an hour ago. */
            created_at?: string | null;
            device_timezone: string | null;
            free_storage_bytes: number | null;
            /** Format: uuid */
            installation_id: string;
            installation_status: components["schemas"]["InstallationStatus"];
            /** @description Derived, never stored: last_heartbeat_at is inside the alerts.device_offline_minutes window. Storing it would need a job to keep it false, and it would be wrong between runs. */
            is_online: boolean;
            last_call_at: string | null;
            last_heartbeat_at: string | null;
            manufacturer: string | null;
            model: string | null;
            network_type: components["schemas"]["NetworkType"] | null;
            /** @description Bound and never sent a heartbeat. Kept distinct from ``is_online: false`` because the next action differs: never started is a person waiting for help right now; worked once and stopped is a phone in a lift or a battery manager to argue with. */
            never_reported: boolean;
            /** Format: uuid */
            number_id: string;
            parked_records: number | null;
            power_save_mode: boolean | null;
            queue_bytes: number | null;
            queue_oldest_at: string | null;
            queue_records: number | null;
            recording_route: components["schemas"]["CaptureRoute"] | null;
            recording_route_ok: boolean | null;
            service_running: boolean | null;
            updated_at: string | null;
            /** @description Shown separately from is_online on purpose: a socket can be alive while capture is dead, and conflating the two is how a broken phone looks fine. */
            ws_connected?: boolean | null;
        };
        /** DirectoryEntryListResponse */
        DirectoryEntryListResponse: {
            items: components["schemas"]["DirectoryEntryResponse"][];
            total: number;
        };
        /** DirectoryEntryResponse */
        DirectoryEntryResponse: {
            /** Format: date-time */
            created_at: string;
            /** Format: uuid */
            id: string;
            is_active: boolean;
            kind: components["schemas"]["DirectoryRuleKind"];
            label: string | null;
            pattern: string;
        };
        /**
         * DirectoryRuleKind
         * @description UC-25's ``*700`` is a ``suffix`` rule.
         * @enum {string}
         */
        DirectoryRuleKind: "exact" | "prefix" | "suffix";
        /**
         * EnrolmentAttemptKind
         * @description ``step_timing`` carries the per-screen durations that make N40 measurable.
         * @enum {string}
         */
        EnrolmentAttemptKind: "code_redeem" | "msisdn_check" | "callback_start" | "callback_match" | "admin_attest" | "step_timing";
        /** EnrolmentAttemptListResponse */
        EnrolmentAttemptListResponse: {
            items: components["schemas"]["EnrolmentAttemptResponse"][];
            total: number;
        };
        /**
         * EnrolmentAttemptResponse
         * @description Where UC-01's failures appear, with timestamps.
         */
        EnrolmentAttemptResponse: {
            agent_id: string | null;
            app_version: string | null;
            /** Format: date-time */
            created_at: string;
            device_model: string | null;
            duration_ms: number | null;
            /** Format: uuid */
            id: string;
            installation_id: string | null;
            kind: components["schemas"]["EnrolmentAttemptKind"];
            number_id: string | null;
            outcome: components["schemas"]["EnrolmentOutcome"];
            step: string | null;
        };
        /** EnrolmentCodeListResponse */
        EnrolmentCodeListResponse: {
            items: components["schemas"]["EnrolmentCodeResponse"][];
            total: number;
        };
        /**
         * EnrolmentCodeResponse
         * @description The code plus everything the admin has to pass on.
         */
        EnrolmentCodeResponse: {
            /** Format: uuid */
            agent_id: string;
            attempt_count: number;
            code: string;
            /** Format: date-time */
            created_at: string;
            /** Format: date-time */
            expires_at: string;
            /** Format: uuid */
            id: string;
            /** Format: uuid */
            number_id: string;
            redeemed_at: string | null;
            revoked_at: string | null;
        };
        /**
         * EnrolmentOutcome
         * @description Every way an enrolment step can end. The funnel's evidence base.
         * @enum {string}
         */
        EnrolmentOutcome: "ok" | "code_not_found" | "code_already_used" | "code_expired" | "code_revoked" | "number_mismatch" | "msisdn_empty" | "no_caller_id" | "timeout" | "receiver_down" | "already_bound" | "rejected";
        /**
         * ErrorBody
         * @description The body of every non-2xx answer (N35, SPEC §4.0).
         *
         *     A model rather than a fragment hand-written in the exporter, so the shape
         *     clients generate against is the shape ``main.error_envelope`` builds.
         *     ``tests/test_conformance.py`` drives real requests through both.
         */
        ErrorBody: {
            /** @description The stable machine value. Clients branch on this. */
            code: string;
            /**
             * @description Machine-readable context; its shape follows `code`.
             * @default null
             */
            detail: unknown;
            /** @description Uzbek, for a person. Never branched on (§4.0). */
            message: string;
            /** @description Echoed from X-Request-Id; quote it in a bug report. */
            request_id: string;
        };
        /**
         * ErrorResponse
         * @description ``{"error": {...}}`` — the envelope itself, and the only error shape.
         */
        ErrorResponse: {
            error: components["schemas"]["ErrorBody"];
        };
        /**
         * FunnelStage
         * @description Where an agent is in the rollout (UC-17, SPEC §10.1).
         *
         *     ``verified_by_admin`` is visibly distinct from ``number_verified`` because
         *     attested is weaker evidence than proven, and the identity anchor must never
         *     degrade silently (T142).
         * @enum {string}
         */
        FunnelStage: "invited" | "installed" | "permitted" | "number_verified" | "verified_by_admin" | "self_declared" | "capturing" | "needs_assisted_install" | "install_disappeared" | "revoked";
        /** GapByAgentOut */
        GapByAgentOut: {
            /** Format: uuid */
            agent_id: string;
            agent_name: string;
            answered_calls: number;
            calls_with_audio: number;
            /** @description Percent. NUMERIC, never float. */
            capture_rate: string | null;
        };
        /** GapByModelOut */
        GapByModelOut: {
            answered_calls: number;
            /** @description Part of the M0 baseline's identity. */
            api_level: number;
            /** @description Capture rate is per variant, not only per model (D-06). */
            app_variant: components["schemas"]["AppVariant"];
            /** @description From the M0 baseline (T14). */
            baseline_rate: string | null;
            calls_with_audio: number;
            capture_rate: string | null;
            /** @description Below the threshold raises N4's alert. */
            delta_pp: string | null;
            manufacturer: string;
            model: string;
            regression: boolean;
        };
        /**
         * GapByReasonOut
         * @description Why audio is missing, and how often. The closed enum, never free text.
         */
        GapByReasonOut: {
            calls: number;
            /** @description ``pending_upload`` and ``not_expected`` are excluded from the denominator: an unanswered call in it makes '% of answered calls with audio' meaningless (SPEC §3.9). */
            counts_against_capture_rate: boolean;
            reason: components["schemas"]["AudioMissingReason"];
        };
        /**
         * GapReportResponse
         * @description UC-23. Totals reconcile exactly with ``/calls?has_audio=false``.
         */
        GapReportResponse: {
            answered_calls: number;
            by_agent: components["schemas"]["GapByAgentOut"][];
            by_model: components["schemas"]["GapByModelOut"][];
            by_reason: components["schemas"]["GapByReasonOut"][];
            calls_with_audio: number;
            capture_rate: string | null;
            /** @description Matches the filtered call list, because the same rows are counted. */
            missing_total: number;
            open_deltas: components["schemas"]["OpenDeltaOut"][];
        };
        /**
         * HealthResponse
         * @description Process liveness.
         */
        HealthResponse: {
            /** @description Always 'ok' when the process is serving. */
            status: string;
        };
        /**
         * ImportAgentsRequest
         * @description ``POST /api/v1/agents/import`` — CSV text, not a file upload.
         *
         *     A one-off for ~33 people (T59), not a live integration. Text rather than a
         *     multipart file because the realistic input is a paste out of a spreadsheet,
         *     and asking somebody to save a file first is a step that fails.
         */
        ImportAgentsRequest: {
            /** @description Header row plus data: full_name[,employee_code[,hired_at]]. */
            csv: string;
            /**
             * @description Default true, deliberately: the diff is shown before anything is written, because a roster import that half-succeeded is worse than one that did not run.
             * @default true
             */
            dry_run: boolean;
        };
        /** ImportAgentsResponse */
        ImportAgentsResponse: {
            created: number;
            dry_run: boolean;
            errors: number;
            rows: components["schemas"]["ImportRowResult"][];
            skipped: number;
            updated: number;
        };
        /**
         * ImportRowResult
         * @description What would happen, or did happen, to one roster line.
         */
        ImportRowResult: {
            /** @description create | update | skip | error */
            action: string;
            employee_code: string | null;
            full_name: string;
            line: number;
            /** @description Why it was skipped or refused. */
            reason?: string | null;
        };
        /** InstallationListResponse */
        InstallationListResponse: {
            items: components["schemas"]["InstallationResponse"][];
            total: number;
        };
        /**
         * InstallationResponse
         * @description One installation, as the panel reads it.
         */
        InstallationResponse: {
            /** Format: uuid */
            agent_id: string;
            app_variant: components["schemas"]["AppVariant"] | null;
            app_version: string | null;
            attest_reason: string | null;
            bound_at: string | null;
            /** Format: date-time */
            created_at: string;
            /** Format: uuid */
            device_id: string;
            /** Format: date-time */
            funnel_changed_at: string;
            funnel_stage: components["schemas"]["FunnelStage"];
            /** Format: uuid */
            id: string;
            /** Format: uuid */
            number_id: string;
            replaced_at: string | null;
            revoke_confirmed_at: string | null;
            revoke_pending_bytes: number | null;
            revoke_pending_records: number | null;
            revoked_at: string | null;
            sim_slot: number | null;
            sim_subscription_id: number | null;
            status: components["schemas"]["InstallationStatus"];
            verification_method: components["schemas"]["VerificationMethod"] | null;
            verified_at: string | null;
        };
        /**
         * InstallationStatus
         * @description Lifecycle of one app installation bound to one registered number.
         * @enum {string}
         */
        InstallationStatus: "pending" | "active" | "replaced" | "revoked" | "revoked_pending_confirmation";
        /**
         * LoginRequest
         * @description ``POST /api/v1/auth/login`` — public, rate-limited.
         */
        LoginRequest: {
            /** @description The login identifier, matched verbatim against ``users.email``. Case-insensitive; the column is CITEXT. */
            email: string;
            /** @description Never logged, never echoed. */
            password: string;
        };
        /**
         * LoginResponse
         * @description The user *and* their access token, so the panel needs one round trip.
         */
        LoginResponse: {
            access_token: string;
            /** @description Set for a 'sales' account; what own-scope filters on. */
            agent_id?: string | null;
            email: string;
            expires_in: number;
            full_name: string;
            /** Format: uuid */
            id: string;
            /** @description The panel forces the change before anything else loads. */
            must_change_password: boolean;
            /** @description Resolved from the role, sorted. */
            permissions: string[];
            role: components["schemas"]["UserRole"];
            /** @default bearer */
            token_type: string;
        };
        /**
         * MissedClientRow
         * @description One unreached customer — the detail that proves the number.
         *
         *     A row reading "15 missed, 100 % called back" looks wrong until this list
         *     shows the 15 events came from 9 customers and every one was spoken to.
         */
        MissedClientRow: {
            attempts: number;
            /** @description True — the customer tried again and was answered; false — somebody called them back. */
            contact_inbound: boolean | null;
            /** @description Resolved on the handset from the employee's own contacts. Decoration, never identity — there is no customer catalogue. */
            contact_name: string | null;
            /** @description Null — still not contacted. */
            contacted_at: string | null;
            /** @description Who spoke to them. May be a different employee. */
            contacted_by: string | null;
            /** Format: date-time */
            first_missed_at: string;
            /** Format: date-time */
            last_missed_at: string;
            minutes_to_contact: number | null;
            /** @description The last-9 matching key (`calls.remote_number_key`, N37). */
            phone_key: string;
        };
        /** MissedClientsResponse */
        MissedClientsResponse: {
            /** Format: uuid */
            agent_id: string;
            agent_name: string;
            callback_window_hours: number;
            clients: components["schemas"]["MissedClientRow"][];
            /** Format: date */
            date_from: string;
            /** Format: date */
            date_to: string;
            unreached: number;
        };
        /**
         * NetworkType
         * @enum {string}
         */
        NetworkType: "wifi" | "cellular" | "none";
        /**
         * NotAnalysableCount
         * @description One reason calls are being skipped, and how many (§7.5).
         */
        NotAnalysableCount: {
            calls: number;
            code: components["schemas"]["AnalysisFailure"];
        };
        /** NumberListResponse */
        NumberListResponse: {
            items: components["schemas"]["NumberResponse"][];
            total: number;
        };
        /** NumberResponse */
        NumberResponse: {
            /** Format: date-time */
            created_at: string;
            e164: string;
            /** Format: uuid */
            id: string;
            is_active: boolean;
            label: string | null;
            operator: string | null;
            /** @description Last 9 digits, generated by the database (N37). */
            phone_key: string;
            sim_owner: string;
        };
        /**
         * OpenDeltaOut
         * @description A device whose own call-log count never reconciled (N3, §4.1 B).
         */
        OpenDeltaOut: {
            agent_name: string;
            delta: number;
            device_counted: number;
            /** Format: uuid */
            installation_id: string;
            /** Format: date */
            period_date: string;
            /** @description Never folded into either side of the rate — the fail-closed rule made visible. */
            subscription_unknown_count: number;
            uploaded_count: number;
        };
        /**
         * OutcomeSignalOut
         * @description What the conversation ended in, when it said so.
         */
        OutcomeSignalOut: {
            /** @description The model's own 0..1 confidence in this signal. A float inside a JSONB document, which §10's no-float rule is about columns. */
            confidence: number;
            evidence: string | null;
            products_mentioned: string[];
            quantity_mentioned: number | null;
            /** @description The rubric's outcome vocabulary; see `RedFlagOut.type`. */
            type: string;
        };
        /**
         * PromptSection
         * @description One named part of the assembled system prompt.
         *
         *     Sent with ``editable`` because the admin edits exactly one of them and has to
         *     see the rest: without the surrounding context they repeat an instruction that
         *     is already there (and pay for the tokens) or contradict it.
         */
        PromptSection: {
            editable: boolean;
            key: string;
            text: string;
        };
        /**
         * ProviderCooldownResponse
         * @description A role sitting out a quota or an outage.
         *
         *     The first thing an operator needs when the queue goes quiet, which is why
         *     the cooldown is a table and not a cache key with a TTL (§1.3).
         */
        ProviderCooldownResponse: {
            detail: string | null;
            /** @description A daily quota and a 503 read very differently. */
            reason_code: components["schemas"]["AnalysisFailure"];
            /** @description asr | llm. One cooldown per role. */
            role: string;
            seconds_left: number;
            /** Format: date-time */
            started_at: string;
            /** Format: date-time */
            until_at: string;
        };
        /**
         * PublicReleaseListResponse
         * @description The current build of each variant. Empty before the first publish.
         *
         *     ``total`` can only ever be 0, 1 or 2 — there are two variants — and it is
         *     here anyway, because every list response in this API carries the same two
         *     fields and a generated client that has to special-case one of them is worse
         *     than a field that is always ``len(items)``.
         */
        PublicReleaseListResponse: {
            items: components["schemas"]["PublicReleaseResponse"][];
            total: number;
        };
        /**
         * PublicReleaseResponse
         * @description One published build, as an anonymous visitor may see it.
         *
         *     A deliberately NARROW copy of :class:`AppVersionResponse` rather than a
         *     reuse of it. That model carries ``created_by`` and ``created_by_name`` —
         *     which member of staff uploaded the build — and a public page has no
         *     business naming an employee. Widening this model is how that would happen
         *     by accident, so it lists its fields rather than inheriting them.
         *
         *     Everything here is already public by another route: the bytes and their
         *     SHA-256 come back from ``GET /api/v1/app/download/{version_code}``, which
         *     SPEC §4.1 rule 5 makes public, and the version is printed inside the APK.
         */
        PublicReleaseResponse: {
            /** @description So a download can be checked against what the server holds. */
            apk_sha256: string;
            min_api_level: number;
            published_at: string | null;
            release_notes_uz: string | null;
            /** Format: int64 */
            size_bytes: number;
            variant: components["schemas"]["AppVariant"];
            version: string;
            version_code: number;
        };
        /**
         * PublishRubricRequest
         * @description `PUT /analysis/rubric` — **publish the next version**, never edit this one.
         *
         *     There is no update endpoint and no rubric id in this body, and that is the
         *     design: the version that scored yesterday's calls has to stay exactly as it
         *     was, or `call_scores.rubric_version` stops meaning anything.
         */
        PublishRubricRequest: {
            blocks: components["schemas"]["RubricBlock"][];
            /** @description Why it was published — the only place that reason survives. */
            description?: string | null;
            /** @description Free text, added to the prompt of EVERY call, which is why it is capped: its length converts directly into money. */
            extra_rules?: string | null;
            /** @description What to call this version. Required, and the server invents nothing: display text belongs to the panel's Uzbek catalogue (§14). */
            name: string;
            red_flags: components["schemas"]["RubricRedFlag"][];
        };
        /**
         * QueueCallRequest
         * @description ``POST /analysis/calls/{call_id}`` — the panel's button (§6.2).
         */
        QueueCallRequest: {
            /**
             * @description Clear the existing transcript and score so both are recomputed. **The only way to spend money twice on one call**, which is why it is a body field and not a query parameter somebody pastes.
             * @default false
             */
            force: boolean;
        };
        /**
         * ReadyResponse
         * @description Dependency readiness, one flag per dependency.
         */
        ReadyResponse: {
            /** @description A trivial query succeeded. */
            database: boolean;
            /** @description 'ok' when every dependency is usable. */
            status: string;
            /** @description The audio root exists and is writable. */
            storage: boolean;
        };
        /**
         * ReceiverStatus
         * @description No heartbeat for 3 min -> degraded, 5 min -> down + a critical alert.
         * @enum {string}
         */
        ReceiverStatus: "up" | "degraded" | "down";
        /**
         * ReceiverStatusResponse
         * @description The banner at the top of the rollout page (SPEC §9.4).
         *
         *     **If every receiver is down, nobody in the fleet can enrol**, so this is
         *     the page's most important sentence and it says so before anyone tries. It
         *     carries a real type for the same reason: an untyped body reaches the
         *     contract as a free-form map, and the panel then has to parse defensively
         *     exactly where it can least afford to guess.
         */
        ReceiverStatusResponse: {
            /**
             * @description More than one is a configuration change, not code.
             * @default 0
             */
            active_receivers: number;
            /**
             * @description Is the callback route part of this deployment (`enrolment.callback_enabled`)? When false the panel says nothing about receivers: a route nobody installed is not an outage.
             * @default true
             */
            callback_enabled: boolean;
            /** @description False means the rollout is stopped, not slow. */
            enrolment_possible: boolean;
            /** @description The number screen E5 shows the agent. */
            receiver_msisdn?: string | null;
            /** @description Which gateway, for the admin to go and look at. */
            receiver_name?: string | null;
            /** @description up | degraded | down. Down is 5 minutes without a heartbeat. Null when the callback route is not part of this deployment. */
            status?: components["schemas"]["ReceiverStatus"] | null;
        };
        /**
         * ReclassifyResponse
         * @description A directory change is only half done until the calls agree with it.
         */
        ReclassifyResponse: {
            /** @description Calls whose call_type changed as a result of this edit. */
            calls_reclassified: number;
            entry: components["schemas"]["DirectoryEntryResponse"];
        };
        /**
         * RedFlagBreakdownResponse
         * @description The breach breakdown (BonviZvonki ``GET /analytics/red-flags``).
         */
        RedFlagBreakdownResponse: {
            /** Format: date */
            date_from: string;
            /** Format: date */
            date_to: string;
            items: components["schemas"]["RedFlagCountOut"][];
            /** @description Every occurrence counted, across all types. */
            total: number;
        };
        /**
         * RedFlagCountOut
         * @description One kind of breach, and how often it was found.
         */
        RedFlagCountOut: {
            /** @description Occurrences, not calls — one call can carry the same type twice. */
            count: number;
            /** @description The rubric's key; open, like the block keys. */
            type: string;
        };
        /**
         * RedFlagOut
         * @description One incident, with the evidence for it.
         *
         *     Every incident is returned, including repeats of one type: a manager
         *     confirming an accusation needs the time and the quote of both. ``counted``
         *     marks the one that actually moved the score — the penalty is charged once
         *     per type, and the array's penalties sum to the total applied.
         */
        RedFlagOut: {
            counted: boolean;
            label: string;
            penalty: number;
            quote: string;
            severity: string;
            /** @description '[MM:SS]' into the recording, when the model located it. */
            timestamp: string | null;
            /** @description The rubric's red-flag key. A string and not a closed enum on purpose: the rubric is versioned (`rubric_version`) and phase 2 reads it from a row, so a score written under v1 must stay readable after v2 adds a flag. The panel renders an unknown key as the key. */
            type: string;
        };
        /**
         * RevokeRequest
         * @description ``POST /api/v1/installations/{id}/revoke`` (UC-08).
         */
        RevokeRequest: {
            reason?: string | null;
        };
        /**
         * RevokeResponse
         * @description What was still queued when contact was lost.
         *
         *     Bonvi does not own the handset, so a revoke that claims a completed wipe
         *     would be lying. ``revoke_confirmed_at`` stays NULL until the phone comes
         *     back and says the local audio is gone.
         */
        RevokeResponse: {
            confirmed: boolean;
            /** Format: uuid */
            installation_id: string;
            pending_bytes: number | null;
            pending_records: number | null;
            /** Format: date-time */
            revoked_at: string;
            status: components["schemas"]["InstallationStatus"];
        };
        /**
         * RubricBlock
         * @description One block: a heading, a maximum, and the criteria that add up to it.
         */
        RubricBlock: {
            criteria: components["schemas"]["RubricCriterion"][];
            /** @description The key `call_scores.blocks` is keyed by. Changing it on a published rubric orphans the bars of every score written under the old one. */
            key: string;
            label: string;
            /** @description Block maximum. All blocks total exactly 100. */
            max: number;
        };
        /**
         * RubricCriterion
         * @description One criterion inside a block.
         */
        RubricCriterion: {
            /** @description What earns the points; goes into the prompt verbatim. */
            description?: string | null;
            /** @description Short key, e.g. `A2`. The model answers per criterion under it. */
            id: string;
            label: string;
            /**
             * @description Whether the model may mark this criterion `na` — not applicable to this conversation — and have it left out of the arithmetic entirely. **Defaults to false on purpose**: a criterion nobody thought about must be assessed, not quietly droppable. Most Bonvi customers are returning ones who state their order in a sentence; without this flag the full sales script is applied to a 30-second call and the employee scores 40 for doing everything right.
             * @default false
             */
            optional: boolean;
            /** @description This criterion's own maximum. The block's criteria must sum to its `max`. */
            points: number;
        };
        /**
         * RubricPromptResponse
         * @description What is actually sent to the model, assembled from the active rubric.
         *
         *     **Assembled by the server, never rebuilt in the panel.** Two copies of this
         *     text would drift, and then the screen would show one prompt while the model
         *     received another — a bug with no symptom.
         */
        RubricPromptResponse: {
            /** @description A rough count paid on every call: Uzbek and Russian run at roughly 3.3 characters per token. An order of magnitude, not an invoice. */
            approx_tokens: number;
            char_count: number;
            /** @description `prompt.MAX_EXTRA_RULES`, so the editor's counter cannot disagree with what the server accepts. */
            extra_rules_limit: number;
            full_text: string;
            rubric_label: string;
            rubric_version: number;
            sections: components["schemas"]["PromptSection"][];
        };
        /**
         * RubricRedFlag
         * @description One rule whose breach costs points, with the penalty it costs.
         */
        RubricRedFlag: {
            description?: string | null;
            label: string;
            /** @description Negative, always: a red flag subtracts. Zero is legal and means 'record it, but do not charge for it'. */
            penalty: number;
            /** @description The key the model must answer with. `[a-z][a-z0-9_]{1,31}` — checked again in the service, because a key the model cannot reproduce makes every answer fail validation and stops all scoring. */
            type: string;
            /**
             * @description Whether this flag takes the whole score to 0. The heaviest sanction in the product — swearing at a customer — and the panel never sets it on a NEW flag: one miscategorised rule would zero an employee's month.
             * @default false
             */
            zeroes_score: boolean;
        };
        /**
         * RubricResponse
         * @description The active rubric, or a single version of it.
         */
        RubricResponse: {
            blocks: components["schemas"]["RubricBlock"][];
            created_at: string | null;
            description: string | null;
            /** @description The admin's own instructions, appended to the prompt as a section of their own. Versioned with the rubric, so a score can say which instructions produced it. */
            extra_rules: string | null;
            /** @description `prompt.MAX_EXTRA_RULES`. Sent with the rubric so the editor's counter cannot disagree with what the server accepts — BonviZvonki wrote the number into its page as well and had two copies of one limit. */
            extra_rules_limit: number;
            /** @description NULL when nothing has been published and this is the pinned default. */
            id: string | null;
            is_active: boolean;
            /** @description `v3` — **exactly the string `call_scores.rubric_version` holds**, so a score can be traced back to the criteria that produced it. */
            label: string;
            name: string;
            red_flags: components["schemas"]["RubricRedFlag"][];
            /** @description False means no row exists yet and this is `rubric_default.DEFAULT_RUBRIC`, which is what an unseeded database still scores with. The editor says so rather than pretending somebody published it. */
            stored: boolean;
            version: number;
        };
        /**
         * RubricVersionListResponse
         * @description Every published version, newest first (SPEC §4.0's list shape).
         */
        RubricVersionListResponse: {
            items: components["schemas"]["RubricVersionSummary"][];
            total: number;
        };
        /**
         * RubricVersionSummary
         * @description One line of the version history. Nothing is ever deleted from it.
         */
        RubricVersionSummary: {
            /** Format: date-time */
            created_at: string;
            is_active: boolean;
            label: string;
            name: string;
            version: number;
        };
        /**
         * ScoreBucketOut
         * @description One ten-point band of the histogram.
         */
        ScoreBucketOut: {
            calls: number;
            /** @description Inclusive. The top band is 90-100 rather than 90-99: a perfect score belongs in the highest bar, not in an eleventh one of its own. */
            ceiling: number;
            floor: number;
        };
        /**
         * ScoreDistributionResponse
         * @description The histogram (BonviZvonki ``GET /analytics/distribution``).
         *
         *     Always ten bands, empty ones included — the same decision
         *     :class:`CallTypeCountsOut` makes, and for the same reason: a histogram with
         *     holes in it reads as a filter that ate rows.
         */
        ScoreDistributionResponse: {
            /** Format: date */
            date_from: string;
            /** Format: date */
            date_to: string;
            items: components["schemas"]["ScoreBucketOut"][];
            scored_calls: number;
        };
        /**
         * ScoreMetricOut
         * @description An average score out of 100, to one decimal place.
         */
        ScoreMetricOut: {
            delta_percent: string | null;
            /** @description Null when nothing was scored. */
            value: string | null;
        };
        /**
         * ScoreResponse
         * @description One call's verdict and the evidence for it (§7.4's score block).
         */
        ScoreResponse: {
            /** @description {blocks: {...evidence per criterion...}, meta: {...}} — how the number was reached, so 'why 78?' is answerable without paying to re-run. `meta.applicable_max` is what lets a header read '68 / 75' honestly when criteria did not apply (§7.4). */
            block_details: {
                [key: string]: unknown;
            };
            /** @description FLAT {block_key: points}, already normalised to the criteria that applied. **Never recomputed in the panel.** Keyed by the rubric's own block keys, so it is a map rather than four named fields: a rubric change must not need a server release to render. */
            blocks: {
                [key: string]: number;
            };
            coaching_note: string | null;
            completion_tokens: number | null;
            confidence_pct: number;
            /** @description NULL while the price is unset — null means not priced, never free. */
            cost_micro_usd: number | null;
            model: string;
            needs_review: boolean;
            outcome_signal: components["schemas"]["OutcomeSignalOut"] | null;
            /** @description 0-100, recomputed by the validator. */
            overall_score: number;
            prompt_tokens: number | null;
            provider: string;
            red_flags: components["schemas"]["RedFlagOut"][];
            /** @description [{code, params}]. The panel renders the sentence from uz.json, so the column holds a machine reason and never display copy (§1.6). */
            review_reasons: {
                [key: string]: unknown;
            }[];
            /** @description Stamped per score: a rubric change never re-bases old numbers. */
            rubric_version: string;
            /** Format: date-time */
            scored_at: string;
            sentiment: components["schemas"]["CallSentiment"] | null;
            transcript_quality: components["schemas"]["TranscriptQuality"];
        };
        /**
         * SetMinimumVersionRequest
         * @description ``PUT /api/v1/app/min-version``.
         *
         *     ``acknowledged_stranded`` must equal the count the impact endpoint returns
         *     right now. Not ceremony: it fails exactly when the number moved between
         *     looking and deciding, which is when the admin's picture is stale.
         */
        SetMinimumVersionRequest: {
            /** @description The stranded count you just saw. Must still be true. */
            acknowledged_stranded: number;
            version_code: number;
        };
        /** SetMinimumVersionResponse */
        SetMinimumVersionResponse: {
            stranded_count: number;
            version_code: number;
        };
        /**
         * SetPasswordRequest
         * @description ``POST /api/v1/users/{id}/password`` — an admin resetting somebody else's.
         */
        SetPasswordRequest: {
            password: string;
        };
        /** SettingListResponse */
        SettingListResponse: {
            items: components["schemas"]["SettingResponse"][];
            total: number;
        };
        /** SettingResponse */
        SettingResponse: {
            description_uz: string | null;
            key: string;
            /** Format: date-time */
            updated_at: string;
            updated_by: string | null;
            value: unknown;
            value_type: string;
        };
        /**
         * StoragePointOut
         * @description One day of the growth curve.
         */
        StoragePointOut: {
            /** Format: int64 */
            audio_bytes_total: number;
            audio_files: number;
            /** Format: int64 */
            bytes_added: number;
            /** Format: int64 */
            bytes_deleted: number;
            /** Format: date */
            period_date: string;
        };
        /**
         * StorageReportResponse
         * @description N18: current usage, 30-day growth, and the projection it implies.
         */
        StorageReportResponse: {
            /** Format: int64 */
            audio_bytes_total: number;
            audio_files: number;
            /** Format: int64 */
            bytes_added_30d: number;
            history: components["schemas"]["StoragePointOut"][];
            /**
             * Format: int64
             * @description Today's total plus a year at the last 30 days' rate. The provision is 250 GB, and this is what says whether that is enough.
             */
            projected_bytes_12m: number;
        };
        /**
         * StrandedInstallationOut
         * @description One phone a proposed minimum version would refuse.
         */
        StrandedInstallationOut: {
            agent_name: string;
            app_version: string | null;
            app_version_code: number | null;
            device: string;
            /** Format: uuid */
            installation_id: string;
            last_heartbeat_at: string | null;
            status: components["schemas"]["InstallationStatus"];
        };
        /**
         * TimeseriesPointOut
         * @description One period of the trend line.
         *
         *     ``period_start`` and not BonviZvonki's ``date``: in the weekly bucket the
         *     value is the Monday and in the monthly one the first of the month, so
         *     "date" invites a reader to plot it as the day something happened.
         */
        TimeseriesPointOut: {
            /** @description Null where nothing was scored in the period — a gap, not a zero. */
            ai_score: string | null;
            calls: number;
            /**
             * Format: date
             * @description The period's first day, in Asia/Tashkent (Monday for a week).
             */
            period_start: string;
        };
        /**
         * TranscriptQuality
         * @description The model's own assessment of the transcript it was handed.
         *
         *     A column rather than a derived value because the review rule reads it: a
         *     score computed from a transcript the model itself called ``low`` is one a
         *     person should look at before it reaches an employee's average.
         * @enum {string}
         */
        TranscriptQuality: "high" | "medium" | "low";
        /**
         * TranscriptResponse
         * @description One call's transcript (§7.4's transcript block).
         *
         *     ``audio_bytes`` and ``asr_ms`` are stored but not returned: they are cost
         *     measurement (§11.1), they belong to the month's figures on the status page,
         *     and a per-call byte count is not something the detail page renders.
         */
        TranscriptResponse: {
            audio_duration_ms: number | null;
            /** @description What was asked of the provider, or NULL when it detected it. */
            language: string | null;
            model: string;
            provider: string;
            /** @description Verbatim, in the '[MM:SS] SPEAKER_n: ...' form. The timestamps are not decoration — phase 2's click-a-line-to-seek reads them. */
            text: string;
            /** Format: date-time */
            transcribed_at: string;
            /** @description Real spoken words, service tokens stripped (`rules.count_words`). Stored so the review rule and the panel agree on one number. */
            word_count: number;
        };
        /**
         * UpdateAgentRequest
         * @description ``PATCH /api/v1/agents/{id}``. Absent fields are unchanged.
         */
        UpdateAgentRequest: {
            color?: string | null;
            employee_code?: string | null;
            full_name?: string | null;
            hired_at?: string | null;
            is_active?: boolean | null;
            note?: string | null;
        };
        /**
         * UpdateCallNoteRequest
         * @description ``PATCH /api/v1/calls/{id}`` — the note and nothing else.
         */
        UpdateCallNoteRequest: {
            note?: string | null;
        };
        /**
         * UpdateNumberRequest
         * @description ``PATCH /api/v1/numbers/{id}``. The number itself is not editable.
         */
        UpdateNumberRequest: {
            is_active?: boolean | null;
            label?: string | null;
            operator?: string | null;
            sim_owner?: string | null;
        };
        /**
         * UpdateSettingRequest
         * @description ``PUT /api/v1/settings``.
         *
         *     ``confirm`` exists for one case: lowering the retention period below
         *     ``retention.confirm_below_months`` destroys recordings that still exist.
         *     Without it the server changes nothing and returns 409 (SPEC §3.11).
         */
        UpdateSettingRequest: {
            /**
             * @description Required when the change would delete data that still exists.
             * @default false
             */
            confirm: boolean;
            key: string;
            value: unknown;
        };
        /**
         * UpdateUserRequest
         * @description ``PATCH /api/v1/users/{id}``. Every field optional; absent means unchanged.
         */
        UpdateUserRequest: {
            agent_id?: string | null;
            full_name?: string | null;
            is_active?: boolean | null;
            role?: components["schemas"]["UserRole"] | null;
        };
        /**
         * UploadReleaseResponse
         * @description What the upload found in the file, alongside the row it created.
         */
        UploadReleaseResponse: {
            /** @description SHA-256 of the signing certificate, read from the APK's v2/v3 signing block. Compare it against docs/APK-SIGNING.md by eye if no fingerprint is configured yet — a build signed by another key cannot be installed as an update, only as an uninstall that destroys the phone's unsent queue. */
            signer_sha256: string;
            /** @description True when it was checked against the configured fingerprint. */
            signer_verified: boolean;
            version: components["schemas"]["AppVersionResponse"];
        };
        /**
         * UserListResponse
         * @description A page of accounts. Small table, so no cursor: the panel shows them all.
         */
        UserListResponse: {
            items: components["schemas"]["UserResponse"][];
            total: number;
        };
        /**
         * UserResponse
         * @description A panel account. Never carries the hash.
         */
        UserResponse: {
            agent_id: string | null;
            /** Format: date-time */
            created_at: string;
            email: string;
            full_name: string;
            /** Format: uuid */
            id: string;
            is_active: boolean;
            last_login_at: string | null;
            must_change_password: boolean;
            role: components["schemas"]["UserRole"];
        };
        /**
         * UserRole
         * @description A panel login's role (SPEC §3.2).
         *
         *     ``service`` is deliberately absent: machine access is a ``service_tokens``
         *     row, because a machine has no password, no session and no navigation. The
         *     authorisation registry in ``core/permissions.py`` covers both and a test
         *     asserts these three are a subset of it.
         *
         *     ``viewer`` was removed on 2026-09-05 with the TV board — see
         *     ``core.permissions.Role``.
         * @enum {string}
         */
        UserRole: "admin" | "manager" | "sales";
        /**
         * VerificationMethod
         * @description How we proved the phone holds the registered number (UC-04, T142).
         *
         *     Ordered strongest to weakest, and the order is load-bearing: SPEC §9.3
         *     requires the identity anchor to degrade visibly, so every place that
         *     renders a binding renders which of these it rests on.
         *
         *     ``self_declared`` is the weakest. It says only that whoever held the
         *     single-use code an admin issued for this number typed it into this handset
         *     — no line was proven. It exists because on this fleet the two proving
         *     routes are frequently both unavailable: Uzbek SIMs leave
         *     ``getLine1Number()`` empty, and the callback route needs a receiver line.
         *     Without it those handsets have no path to ``active`` at all, which is
         *     strictly worse: an unenrolled phone reports nothing, so nobody can even see
         *     that it is unverified. Governed by ``enrolment.allow_self_declared``.
         * @enum {string}
         */
        VerificationMethod: "sim_msisdn" | "callback" | "admin_attested" | "self_declared";
        /**
         * VersionGateImpactResponse
         * @description What raising the floor would cost, **before** it is raised (N34, UC-28).
         *
         *     These are personally owned handsets. A stranded phone drains its queue,
         *     is then refused, and stays refused until somebody physically reaches that
         *     salesperson — so this is not a preview of a config change, it is the cost
         *     of a decision, and the panel shows it before the button.
         */
        VersionGateImpactResponse: {
            current_min_version_code: number;
            stranded: components["schemas"]["StrandedInstallationOut"][];
            stranded_count: number;
            /** @description Active phones that have never reported a version code. The gate lets these through, so they are not counted as stranded — but each one might be below the floor and we cannot say. */
            unknown_version_count: number;
            /** @description The minimum being considered. */
            version_code: number;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    activity_report_api_v1_activity_get: {
        parameters: {
            query?: {
                agent_id?: string[] | null;
                /** @description Asia/Tashkent calendar date. Overrides `days`. */
                date_from?: string | null;
                /** @description Asia/Tashkent calendar date, INCLUSIVE. */
                date_to?: string | null;
                /** @description Last N calendar days (1 / 7 / 15 / 30). */
                days?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ActivityResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    missed_clients_api_v1_activity_missed_clients_get: {
        parameters: {
            query: {
                /** @description The employee to explain. */
                agent_id: string;
                /** @description Asia/Tashkent calendar date. Overrides `days`. */
                date_from?: string | null;
                /** @description Asia/Tashkent calendar date, INCLUSIVE. */
                date_to?: string | null;
                /** @description Last N calendar days (1 / 7 / 15 / 30). */
                days?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["MissedClientsResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_agents_api_v1_agents_get: {
        parameters: {
            query?: {
                include_archived?: boolean;
                q?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    create_agent_api_v1_agents_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateAgentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_agent_api_v1_agents__agent_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                agent_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    update_agent_api_v1_agents__agent_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                agent_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateAgentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    archive_agent_api_v1_agents__agent_id__archive_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                agent_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    import_agents_api_v1_agents_import_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ImportAgentsRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ImportAgentsResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_alerts_api_v1_alerts_get: {
        parameters: {
            query?: {
                agent_id?: string | null;
                limit?: number;
                open_only?: boolean;
                severity?: components["schemas"]["AlertSeverity"] | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AlertListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    acknowledge_alert_api_v1_alerts__alert_id__ack_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                alert_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AlertResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_analysed_calls_api_v1_analysis_calls_get: {
        parameters: {
            query?: {
                agent_id?: string[] | null;
                cursor?: string | null;
                date_from?: string | null;
                date_to?: string | null;
                limit?: number;
                needs_review?: boolean | null;
                score_band?: ("excellent" | "good" | "average" | "poor")[] | null;
                stage?: components["schemas"]["AnalysisStage"][] | null;
                with_total?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnalysisListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_call_analysis_api_v1_analysis_calls__call_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CallAnalysisResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    queue_call_analysis_api_v1_analysis_calls__call_id__post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                call_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["QueueCallRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnalysisStateResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_active_rubric_api_v1_analysis_rubric_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RubricResponse"];
                };
            };
        };
    };
    publish_rubric_api_v1_analysis_rubric_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PublishRubricRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RubricResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_rubric_prompt_api_v1_analysis_rubric_prompt_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RubricPromptResponse"];
                };
            };
        };
    };
    list_rubric_versions_api_v1_analysis_rubric_versions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RubricVersionListResponse"];
                };
            };
        };
    };
    activate_rubric_version_api_v1_analysis_rubric_versions__version__activate_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                version: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RubricResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    analysis_status_api_v1_analysis_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnalysisStatusResponse"];
                };
            };
        };
    };
    analytics_agent_ranking_api_v1_analytics_agents_get: {
        parameters: {
            query?: {
                agent_id?: string[] | null;
                call_type?: components["schemas"]["CallType"] | null;
                date_from?: string | null;
                date_to?: string | null;
                /** @description Last N Asia/Tashkent calendar days, today included. Ignored once both dates are given. */
                days?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AgentRankingResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    analytics_block_breakdown_api_v1_analytics_blocks_get: {
        parameters: {
            query?: {
                agent_id?: string[] | null;
                call_type?: components["schemas"]["CallType"] | null;
                date_from?: string | null;
                date_to?: string | null;
                /** @description Last N Asia/Tashkent calendar days, today included. Ignored once both dates are given. */
                days?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BlockBreakdownResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    analytics_score_distribution_api_v1_analytics_distribution_get: {
        parameters: {
            query?: {
                agent_id?: string[] | null;
                call_type?: components["schemas"]["CallType"] | null;
                date_from?: string | null;
                date_to?: string | null;
                /** @description Last N Asia/Tashkent calendar days, today included. Ignored once both dates are given. */
                days?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ScoreDistributionResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    analytics_overview_api_v1_analytics_overview_get: {
        parameters: {
            query?: {
                agent_id?: string[] | null;
                call_type?: components["schemas"]["CallType"] | null;
                date_from?: string | null;
                date_to?: string | null;
                /** @description Last N Asia/Tashkent calendar days, today included. Ignored once both dates are given. */
                days?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnalyticsOverviewResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    analytics_red_flag_breakdown_api_v1_analytics_red_flags_get: {
        parameters: {
            query?: {
                agent_id?: string[] | null;
                call_type?: components["schemas"]["CallType"] | null;
                date_from?: string | null;
                date_to?: string | null;
                /** @description Last N Asia/Tashkent calendar days, today included. Ignored once both dates are given. */
                days?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RedFlagBreakdownResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    analytics_timeseries_api_v1_analytics_timeseries_get: {
        parameters: {
            query?: {
                agent_id?: string[] | null;
                bucket?: "day" | "week" | "month";
                call_type?: components["schemas"]["CallType"] | null;
                date_from?: string | null;
                date_to?: string | null;
                /** @description Last N Asia/Tashkent calendar days, today included. Ignored once both dates are given. */
                days?: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AnalyticsTimeseriesResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    download_version_api_v1_app_download__version_code__get: {
        parameters: {
            query?: {
                variant?: components["schemas"]["AppVariant"] | null;
            };
            header?: never;
            path: {
                version_code: number;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    latest_releases_api_v1_app_latest_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PublicReleaseListResponse"];
                };
            };
        };
    };
    set_min_version_api_v1_app_min_version_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetMinimumVersionRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SetMinimumVersionResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    min_version_impact_api_v1_app_min_version_impact_get: {
        parameters: {
            query: {
                version_code: number;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["VersionGateImpactResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_versions_api_v1_app_versions_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppVersionListResponse"];
                };
            };
        };
    };
    upload_version_api_v1_app_versions_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "multipart/form-data": components["schemas"]["Body_upload_version_api_v1_app_versions_post"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UploadReleaseResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    discard_version_api_v1_app_versions__version_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                version_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    publish_version_api_v1_app_versions__version_id__publish_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                version_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AppVersionResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_agent_assignments_api_v1_assignments_get: {
        parameters: {
            query: {
                agent_id: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssignmentListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    close_assignment_api_v1_assignments__assignment_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                assignment_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CloseAssignmentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssignmentResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_audit_api_v1_audit_get: {
        parameters: {
            query?: {
                action?: components["schemas"]["AuditAction"] | null;
                actor_user_id?: string | null;
                limit?: number;
                object_id?: string | null;
                object_type?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AuditListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    login_api_v1_auth_login_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    logout_api_v1_auth_logout_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
        };
    };
    me_api_v1_auth_me_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CurrentUserResponse"];
                };
            };
        };
    };
    change_password_api_v1_auth_password_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ChangePasswordRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    refresh_api_v1_auth_refresh_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginResponse"];
                };
            };
        };
    };
    list_calls_api_v1_calls_get: {
        parameters: {
            query?: {
                agent_id?: string[] | null;
                app_variant?: components["schemas"]["AppVariant"] | null;
                audio_missing_reason?: components["schemas"]["AudioMissingReason"][] | null;
                call_type?: components["schemas"]["CallType"] | null;
                capture_route?: components["schemas"]["CaptureRoute"][] | null;
                cursor?: string | null;
                date_from?: string | null;
                date_to?: string | null;
                device_model?: string | null;
                direction?: components["schemas"]["CallDirection"] | null;
                disposition?: components["schemas"]["CallDisposition"] | null;
                has_audio?: boolean | null;
                installation_id?: string | null;
                limit?: number;
                max_duration_sec?: number | null;
                min_duration_sec?: number | null;
                number_id?: string[] | null;
                order?: "asc" | "desc";
                q?: string | null;
                remote_number?: string | null;
                sort?: "received_at" | "started_at" | "duration_sec";
                with_total?: boolean;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CallListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_call_api_v1_calls__call_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CallResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    delete_call_api_v1_calls__call_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": null;
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    update_call_note_api_v1_calls__call_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                call_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateCallNoteRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CallResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    stream_audio_api_v1_calls__call_id__audio_get: {
        parameters: {
            query?: {
                download?: boolean;
            };
            header?: {
                Range?: string | null;
            };
            path: {
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    delete_call_audio_api_v1_calls__call_id__audio_delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                call_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": null;
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    download_audio_archive_api_v1_calls_audio_archive_get: {
        parameters: {
            query?: {
                agent_id?: string[] | null;
                app_variant?: components["schemas"]["AppVariant"] | null;
                audio_missing_reason?: components["schemas"]["AudioMissingReason"][] | null;
                call_type?: components["schemas"]["CallType"] | null;
                capture_route?: components["schemas"]["CaptureRoute"][] | null;
                cursor?: string | null;
                date_from?: string | null;
                date_to?: string | null;
                device_model?: string | null;
                direction?: components["schemas"]["CallDirection"] | null;
                disposition?: components["schemas"]["CallDisposition"] | null;
                has_audio?: boolean | null;
                installation_id?: string | null;
                limit?: number;
                max_duration_sec?: number | null;
                min_duration_sec?: number | null;
                number_id?: string[] | null;
                order?: "asc" | "desc";
                q?: string | null;
                remote_number?: string | null;
                sort?: "received_at" | "started_at" | "duration_sec";
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    export_calls_api_v1_calls_export_get: {
        parameters: {
            query?: {
                agent_id?: string[] | null;
                app_variant?: components["schemas"]["AppVariant"] | null;
                audio_missing_reason?: components["schemas"]["AudioMissingReason"][] | null;
                call_type?: components["schemas"]["CallType"] | null;
                capture_route?: components["schemas"]["CaptureRoute"][] | null;
                date_from?: string | null;
                date_to?: string | null;
                device_model?: string | null;
                direction?: components["schemas"]["CallDirection"] | null;
                disposition?: components["schemas"]["CallDisposition"] | null;
                has_audio?: boolean | null;
                installation_id?: string | null;
                max_duration_sec?: number | null;
                min_duration_sec?: number | null;
                number_id?: string[] | null;
                q?: string | null;
                remote_number?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    call_stats_api_v1_calls_stats_get: {
        parameters: {
            query?: {
                date_from?: string | null;
                date_to?: string | null;
                period?: "week" | "month" | "year" | "custom";
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CallStatsResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_command_api_v1_commands__command_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                command_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CommandResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_devices_api_v1_devices_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeviceHealthListResponse"];
                };
            };
        };
    };
    get_device_api_v1_devices__installation_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                installation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DeviceDetailResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_commands_api_v1_devices__installation_id__commands_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                installation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CommandListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    issue_command_api_v1_devices__installation_id__commands_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                installation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateCommandRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CommandResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_codes_api_v1_enrolment_codes_get: {
        parameters: {
            query?: {
                active_only?: boolean;
                number_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnrolmentCodeListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    revoke_code_api_v1_enrolment_codes__code_id__revoke_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                code_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnrolmentCodeResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_attempts_api_v1_enrolment_attempts_get: {
        parameters: {
            query?: {
                installation_id?: string | null;
                number_id?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnrolmentAttemptListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    receiver_status_api_v1_enrolment_receiver_status_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReceiverStatusResponse"];
                };
            };
        };
    };
    list_installations_api_v1_installations_get: {
        parameters: {
            query?: {
                agent_id?: string | null;
                status?: components["schemas"]["InstallationStatus"] | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstallationListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_installation_api_v1_installations__installation_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                installation_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstallationResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    attest_installation_api_v1_installations__installation_id__attest_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                installation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["AttestRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InstallationResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    revoke_installation_api_v1_installations__installation_id__revoke_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                installation_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RevokeRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RevokeResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_entries_api_v1_line_directory_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DirectoryEntryListResponse"];
                };
            };
        };
    };
    create_entry_api_v1_line_directory_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateDirectoryEntryRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReclassifyResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    delete_entry_api_v1_line_directory__entry_id__delete: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                entry_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReclassifyResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_numbers_api_v1_numbers_get: {
        parameters: {
            query?: {
                is_active?: boolean | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NumberListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    create_number_api_v1_numbers_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateNumberRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NumberResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_number_api_v1_numbers__number_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                number_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NumberResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    update_number_api_v1_numbers__number_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                number_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateNumberRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NumberResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_assignments_api_v1_numbers__number_id__assignments_get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                number_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssignmentListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    create_assignment_api_v1_numbers__number_id__assignments_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                number_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateAssignmentRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AssignmentResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    issue_enrolment_code_api_v1_numbers__number_id__enrolment_code_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                number_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EnrolmentCodeResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    data_usage_report_api_v1_reports_data_usage_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["DataUsageResponse"];
                };
            };
        };
    };
    gap_report_api_v1_reports_gap_get: {
        parameters: {
            query?: {
                date_from?: string | null;
                date_to?: string | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GapReportResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    storage_report_api_v1_reports_storage_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StorageReportResponse"];
                };
            };
        };
    };
    list_settings_api_v1_settings_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingListResponse"];
                };
            };
        };
    };
    update_setting_api_v1_settings_put: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateSettingRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SettingResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    list_users_api_v1_users_get: {
        parameters: {
            query?: {
                is_active?: boolean | null;
                role?: components["schemas"]["UserRole"] | null;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserListResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    create_user_api_v1_users_post: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["CreateUserRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            201: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    get_user_api_v1_users__user_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    update_user_api_v1_users__user_id__patch: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["UpdateUserRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["UserResponse"];
                };
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    set_password_api_v1_users__user_id__password_post: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                user_id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SetPasswordRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            204: {
                headers: {
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description Validation error, in the standard envelope */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    healthz_healthz_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
        };
    };
    readyz_readyz_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReadyResponse"];
                };
            };
        };
    };
}
