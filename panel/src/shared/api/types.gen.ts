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
         * @description Public. A wrong e-mail and a wrong password give the same answer.
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
         * ActorType
         * @description Who did the audited thing (SPEC §3.8).
         * @enum {string}
         */
        ActorType: "user" | "service" | "device" | "system";
        /** AgentListResponse */
        AgentListResponse: {
            /** Items */
            items: components["schemas"]["AgentResponse"][];
            /** Total */
            total: number;
        };
        /** AgentResponse */
        AgentResponse: {
            /** Archived At */
            archived_at: string | null;
            /** Color */
            color: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Employee Code */
            employee_code: string | null;
            /** Full Name */
            full_name: string;
            /** Hired At */
            hired_at: string | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Is Active */
            is_active: boolean;
            /** Note */
            note: string | null;
        };
        /**
         * AlertKind
         * @description Every cause that can raise an alert (SPEC §10.3).
         *
         *     SPEC §3.1 says "24 values"; §10.3's table groups the three
         *     ``permission_lost_*`` causes on one line and pairs
         *     ``retention_job_failed``/``backup_failed`` on another. Expanded, the closed
         *     set is the 27 below — the count in §3.1 is a count of table rows.
         * @enum {string}
         */
        AlertKind: "capture_disabled" | "permission_lost_microphone" | "permission_lost_phone_state" | "permission_lost_call_log" | "battery_optimisation_reenabled" | "app_force_stopped" | "install_disappeared" | "recording_route_lost" | "service_not_running" | "device_offline" | "device_silent" | "fleet_silent" | "capture_rate_regression" | "queue_full" | "storage_low" | "poisoned_record" | "auth_expired" | "credential_replay" | "installation_rebound" | "callback_receiver_down" | "enrolment_stalled" | "attribution_out_of_range" | "attribution_discarded_spike" | "retention_job_failed" | "backup_failed" | "storage_capacity_low" | "min_version_refusals";
        /** AlertListResponse */
        AlertListResponse: {
            /** Items */
            items: components["schemas"]["AlertResponse"][];
            /**
             * Open Count
             * @description Neither acknowledged nor resolved.
             */
            open_count: number;
            /** Total */
            total: number;
        };
        /**
         * AlertResponse
         * @description One open or acknowledged alert, as the inbox renders it.
         */
        AlertResponse: {
            /** Acknowledged At */
            acknowledged_at: string | null;
            /** Acknowledged By */
            acknowledged_by: string | null;
            /** Agent Id */
            agent_id: string | null;
            /**
             * Body Uz
             * @description What to do about it. Derived from `kind`, not stored.
             */
            body_uz: string | null;
            /** Detail */
            detail: Record<string, unknown> | null;
            /** Device Model */
            device_model: string | null;
            /**
             * First Seen At
             * Format: date-time
             */
            first_seen_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Installation Id */
            installation_id: string | null;
            kind: components["schemas"]["AlertKind"];
            /**
             * Last Seen At
             * Format: date-time
             */
            last_seen_at: string;
            /** Number Id */
            number_id: string | null;
            /**
             * Occurrence Count
             * @description Repeats bump this rather than inserting a row: a phone reporting every two minutes must not produce 720 rows a day.
             */
            occurrence_count: number;
            /** Resolved At */
            resolved_at: string | null;
            severity: components["schemas"]["AlertSeverity"];
            /**
             * Title Uz
             * @description What happened, in Uzbek. Derived from `kind`, not stored.
             */
            title_uz: string;
        };
        /**
         * AlertSeverity
         * @enum {string}
         */
        AlertSeverity: "info" | "warning" | "critical";
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
            /** Items */
            items: components["schemas"]["AppVersionResponse"][];
            /**
             * Signing Sha256 Configured
             * @description Whether a signing fingerprint is configured. False means uploads are accepted without the key check — see docs/APK-SIGNING.md.
             */
            signing_sha256_configured: boolean;
            /** Total */
            total: number;
        };
        /**
         * AppVersionResponse
         * @description One build in the distribution record.
         */
        AppVersionResponse: {
            /**
             * Apk Sha256
             * @description Computed server-side, never accepted.
             */
            apk_sha256: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Created By */
            created_by: string | null;
            /**
             * Created By Name
             * @description Who uploaded it, resolved server-side. The id alone would make every page re-solve it through `GET /users`, which a manager cannot read — so a manager would see a bare uuid.
             * @default
             */
            created_by_name: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Is Current */
            is_current: boolean;
            /** Is Mandatory */
            is_mandatory: boolean;
            /** Min Api Level */
            min_api_level: number;
            /**
             * Published At
             * @description NULL means uploaded but not published — reaches nobody.
             */
            published_at: string | null;
            /** Release Notes Uz */
            release_notes_uz: string | null;
            /**
             * Size Bytes
             * Format: int64
             */
            size_bytes: number;
            variant: components["schemas"]["AppVariant"];
            /** Version */
            version: string;
            /** Version Code */
            version_code: number;
        };
        /**
         * AssignmentListResponse
         * @description Full history for a number — this is the timeline the agent page renders.
         */
        AssignmentListResponse: {
            /** Items */
            items: components["schemas"]["AssignmentResponse"][];
            /** Total */
            total: number;
        };
        /** AssignmentResponse */
        AssignmentResponse: {
            /**
             * Agent Id
             * Format: uuid
             */
            agent_id: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Note */
            note: string | null;
            /**
             * Number Id
             * Format: uuid
             */
            number_id: string;
            /**
             * Valid From
             * Format: date-time
             */
            valid_from: string;
            /** Valid To */
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
            /** Reason */
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
            /** Items */
            items: components["schemas"]["AuditResponse"][];
            /** Total */
            total: number;
        };
        /**
         * AuditResponse
         * @description One thing that happened. Immutable, by database trigger.
         */
        AuditResponse: {
            action: components["schemas"]["AuditAction"];
            /** Actor Service Token Id */
            actor_service_token_id: string | null;
            actor_type: components["schemas"]["ActorType"];
            /** Actor User Id */
            actor_user_id: string | null;
            /**
             * At
             * Format: date-time
             */
            at: string;
            /**
             * Detail
             * @description Before/after values and counts. Never a password, a token or an enrolment code (N26). Open by nature — this is a server-side record, not a device payload, so §8's allow-list does not apply.
             */
            detail?: Record<string, unknown> | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Ip */
            ip: string | null;
            /** Object Id */
            object_id: string | null;
            /** Object Type */
            object_type: string;
            /** User Agent */
            user_agent: string | null;
        };
        /** Body_upload_version_api_v1_app_versions_post */
        Body_upload_version_api_v1_app_versions_post: {
            /**
             * Apk
             * Format: binary
             * @description The signed APK.
             */
            apk: string;
            /**
             * Is Mandatory
             * @default false
             */
            is_mandatory: boolean;
            /**
             * Min Api Level
             * @default 26
             */
            min_api_level: number;
            /** Release Notes Uz */
            release_notes_uz?: string | null;
            variant: components["schemas"]["AppVariant"];
            /** Version */
            version: string;
            /** Version Code */
            version_code: number;
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
            /**
             * Available
             * @description Playable now — stored and not yet expired.
             */
            available: boolean;
            /** @description Which strategy produced it (S1, M0, UC-23). */
            capture_route?: components["schemas"]["CaptureRoute"] | null;
            /**
             * Capture Route Detail
             * @description The folder name only, never a path from the phone.
             */
            capture_route_detail?: string | null;
            /**
             * Duration Mismatch
             * @description The file's length disagrees with the call log (UC-14).
             * @default false
             */
            duration_mismatch: boolean;
            /** Duration Ms */
            duration_ms?: number | null;
            /**
             * Expired At
             * @description Removed by retention; playback answers 410 (UC-26).
             */
            expired_at?: string | null;
            /**
             * Url
             * @description Path to stream from, present only when the recording is available. A path and never a signed or public URL (N20): the endpoint is token-protected, and the panel reaches it through the Service Worker bridge because a plain <audio src> cannot send an Authorization header (T153, N43).
             */
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
            /** Has More */
            has_more: boolean;
            /** Items */
            items: components["schemas"]["CallResponse"][];
            /** Next Cursor */
            next_cursor: string | null;
            /** Total */
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
            /**
             * Agent Id
             * Format: uuid
             */
            agent_id: string;
            /**
             * Agent Name
             * @description Resolved server-side; the panel renders it.
             */
            agent_name: string;
            /** Answered At */
            answered_at: string | null;
            app_variant: components["schemas"]["AppVariant"];
            /** App Version */
            app_version: string;
            audio: components["schemas"]["CallAudioSummary"];
            /** Audio Duration Mismatch */
            audio_duration_mismatch: boolean;
            audio_missing_reason: components["schemas"]["AudioMissingReason"] | null;
            call_type: components["schemas"]["CallType"];
            /** Clock Skew Sec */
            clock_skew_sec: number;
            /** Contact Name */
            contact_name: string | null;
            /**
             * Device Model
             * @description 'Xiaomi Redmi Note 12'. The device_model filter needs it.
             */
            device_model?: string | null;
            /** Device Timezone */
            device_timezone: string;
            direction: components["schemas"]["CallDirection"];
            disposition: components["schemas"]["CallDisposition"];
            /** Duration Sec */
            duration_sec: number;
            /** Ended At */
            ended_at: string | null;
            /** Has Audio */
            has_audio: boolean;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Installation Id
             * Format: uuid
             */
            installation_id: string;
            /** Note */
            note: string | null;
            /**
             * Number E164
             * @description The registered line the call happened on.
             */
            number_e164: string;
            /**
             * Number Id
             * Format: uuid
             */
            number_id: string;
            /**
             * Received At
             * Format: date-time
             * @description Authoritative for ordering (N36).
             */
            received_at: string;
            /** Reconciled With Call Log */
            reconciled_with_call_log: boolean;
            /** Remote Number */
            remote_number: string | null;
            /** Remote Number Key */
            remote_number_key: string | null;
            /** Ring Sec */
            ring_sec: number | null;
            /**
             * Seq
             * Format: int64
             */
            seq: number;
            source: components["schemas"]["CallSource"];
            /**
             * Started At
             * Format: date-time
             */
            started_at: string;
        };
        /**
         * CallSource
         * @description How the record reached us.
         * @enum {string}
         */
        CallSource: "live_capture" | "call_log_recovery" | "provider";
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
         */
        CapabilityStateResponse: {
            capability: components["schemas"]["Capability"];
            /**
             * Changed At
             * Format: date-time
             */
            changed_at: string;
            /**
             * Checked At
             * Format: date-time
             */
            checked_at: string;
            /** Detail */
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
            /**
             * Current Password
             * @description Wrong value gives 401.
             */
            current_password: string;
            /**
             * New Password
             * @description Minimum 10 characters and no other composition rule (SPEC §4.7): a rule people cannot follow is a rule they write on a sticky note.
             */
            new_password: string;
        };
        /**
         * CloseAssignmentRequest
         * @description ``PATCH /api/v1/assignments/{id}`` — end a holding period.
         */
        CloseAssignmentRequest: {
            /** Note */
            note?: string | null;
            /**
             * Valid To
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
            /** Items */
            items: components["schemas"]["CommandResponse"][];
            /** Total */
            total: number;
        };
        /** CommandResponse */
        CommandResponse: {
            /** Acked At */
            acked_at: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            failure_reason: components["schemas"]["CommandFailureReason"] | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Installation Id
             * Format: uuid
             */
            installation_id: string;
            kind: components["schemas"]["CommandKind"];
            /**
             * Latency Ms
             * @description acked_at - created_at, stored so UC-16's five-second bar is **measured** rather than assumed. R3 flags that bar as possibly unachievable on doze-restricted OEMs; this column is what turns that into a conversation with evidence.
             */
            latency_ms: number | null;
            /** Result Call Id */
            result_call_id: string | null;
            /** Sent At */
            sent_at: string | null;
            status: components["schemas"]["CommandStatus"];
        };
        /**
         * CommandStatus
         * @enum {string}
         */
        CommandStatus: "pending" | "sent" | "acknowledged" | "failed" | "expired";
        /**
         * CreateAgentRequest
         * @description ``POST /api/v1/agents``. Creating an agent never creates a login.
         */
        CreateAgentRequest: {
            /** Color */
            color?: string | null;
            /**
             * Employee Code
             * @description The roster import key; unique where set.
             */
            employee_code?: string | null;
            /** Full Name */
            full_name: string;
            /** Hired At */
            hired_at?: string | null;
            /** Note */
            note?: string | null;
        };
        /**
         * CreateAssignmentRequest
         * @description ``POST /api/v1/numbers/{id}/assignments`` — hand a line to an agent.
         */
        CreateAssignmentRequest: {
            /**
             * Agent Id
             * Format: uuid
             */
            agent_id: string;
            /** Note */
            note?: string | null;
            /**
             * Valid From
             * @description Defaults to now. The period is [valid_from, valid_to).
             */
            valid_from?: string | null;
            /**
             * Valid To
             * @description NULL means open-ended — they hold it now.
             */
            valid_to?: string | null;
        };
        /**
         * CreateCommandRequest
         * @description ``POST /api/v1/devices/{installation_id}/commands``.
         */
        CreateCommandRequest: {
            kind: components["schemas"]["CommandKind"];
            /**
             * Number
             * @description For kind='dial'. Named, not a free-form payload map (§8).
             */
            number?: string | null;
            /** Reason */
            reason?: string | null;
        };
        /**
         * CreateDirectoryEntryRequest
         * @description ``POST /api/v1/line-directory`` — an admin extra for UC-25.
         */
        CreateDirectoryEntryRequest: {
            kind: components["schemas"]["DirectoryRuleKind"];
            /** Label */
            label?: string | null;
            /**
             * Pattern
             * @description Digits to match. UC-25's '*700' is the suffix rule '700'.
             */
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
            /**
             * E164
             * @description Any format; normalised here.
             */
            e164: string;
            /** Label */
            label?: string | null;
            /**
             * Operator
             * @description beeline | ucell | mobiuz | uzmobile | other. A reporting axis (R19).
             */
            operator?: string | null;
            /**
             * Sim Owner
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
            /**
             * Agent Id
             * @description Required when role='sales' — it is what own-scope narrowing filters on, and the database has a CHECK saying so.
             */
            agent_id?: string | null;
            /**
             * Email
             * Format: email
             */
            email: string;
            /** Full Name */
            full_name: string;
            /** Password */
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
            /**
             * Agent Id
             * @description Set for a 'sales' account; what own-scope filters on.
             */
            agent_id?: string | null;
            /** Email */
            email: string;
            /** Full Name */
            full_name: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Must Change Password
             * @description The panel forces the change before anything else loads.
             */
            must_change_password: boolean;
            /**
             * Permissions
             * @description Resolved from the role, sorted.
             */
            permissions: string[];
            role: components["schemas"]["UserRole"];
        };
        /** DataUsageResponse */
        DataUsageResponse: {
            /**
             * Cap Bytes Month
             * Format: int64
             */
            cap_bytes_month: number;
            /** Items */
            items: components["schemas"]["DataUsageRowOut"][];
            /** Total */
            total: number;
        };
        /**
         * DataUsageRowOut
         * @description One installation's traffic against the cap the employee pays for.
         */
        DataUsageRowOut: {
            /** Agent Name */
            agent_name: string;
            /**
             * Cap Bytes Month
             * Format: int64
             */
            cap_bytes_month: number;
            /**
             * Cellular Bytes Month
             * Format: int64
             */
            cellular_bytes_month: number;
            /**
             * Installation Id
             * Format: uuid
             */
            installation_id: string;
            /**
             * Over Cap
             * @description Past N14's cap: the app stops uploading audio over cellular.
             */
            over_cap: boolean;
            /** Requests Month */
            requests_month: number;
            /**
             * Wifi Bytes Month
             * Format: int64
             */
            wifi_bytes_month: number;
        };
        /**
         * DeviceDetailResponse
         * @description Device health plus its capability matrix (UC-17's device page).
         */
        DeviceDetailResponse: {
            /**
             * Agent Id
             * Format: uuid
             */
            agent_id: string;
            /** Android Release */
            android_release: string | null;
            /** Api Level */
            api_level: number | null;
            app_variant: components["schemas"]["AppVariant"] | null;
            /** App Version */
            app_version: string | null;
            /** Battery Charging */
            battery_charging: boolean | null;
            /** Battery Level */
            battery_level: number | null;
            /** Battery Optimisation Exempt */
            battery_optimisation_exempt: boolean | null;
            /**
             * Capabilities
             * @description Empty for a phone that has never reported — not missing.
             */
            capabilities?: components["schemas"]["CapabilityStateResponse"][];
            /** Capture Enabled */
            capture_enabled: boolean | null;
            /**
             * Capturing
             * @description UC-03's never-false-ready rule: every required capability working, a verified installation and a live service. One function computes it, so the phone and the panel cannot disagree.
             * @default false
             */
            capturing: boolean;
            /** Cellular Bytes Month */
            cellular_bytes_month: number | null;
            /** Clock Skew Sec */
            clock_skew_sec: number | null;
            /** Device Timezone */
            device_timezone: string | null;
            /** Free Storage Bytes */
            free_storage_bytes: number | null;
            /**
             * Installation Id
             * Format: uuid
             */
            installation_id: string;
            installation_status: components["schemas"]["InstallationStatus"];
            /**
             * Is Online
             * @description Derived, never stored: last_heartbeat_at is inside the alerts.device_offline_minutes window. Storing it would need a job to keep it false, and it would be wrong between runs.
             */
            is_online: boolean;
            /** Last Call At */
            last_call_at: string | null;
            /** Last Heartbeat At */
            last_heartbeat_at: string | null;
            /** Manufacturer */
            manufacturer: string | null;
            /** Model */
            model: string | null;
            network_type: components["schemas"]["NetworkType"] | null;
            /**
             * Never Reported
             * @description Bound and never sent a heartbeat. Kept distinct from ``is_online: false`` because the next action differs: never started is a person waiting for help right now; worked once and stopped is a phone in a lift or a battery manager to argue with.
             */
            never_reported: boolean;
            /**
             * Number Id
             * Format: uuid
             */
            number_id: string;
            /** Parked Records */
            parked_records: number | null;
            /** Power Save Mode */
            power_save_mode: boolean | null;
            /** Queue Bytes */
            queue_bytes: number | null;
            /** Queue Oldest At */
            queue_oldest_at: string | null;
            /** Queue Records */
            queue_records: number | null;
            recording_route: components["schemas"]["CaptureRoute"] | null;
            /** Recording Route Ok */
            recording_route_ok: boolean | null;
            /** Service Running */
            service_running: boolean | null;
            /** Updated At */
            updated_at: string | null;
            /**
             * Ws Connected
             * @description Shown separately from is_online on purpose: a socket can be alive while capture is dead, and conflating the two is how a broken phone looks fine.
             */
            ws_connected?: boolean | null;
        };
        /** DeviceHealthListResponse */
        DeviceHealthListResponse: {
            /** Items */
            items: components["schemas"]["DeviceHealthResponse"][];
            /** Total */
            total: number;
        };
        /**
         * DeviceHealthResponse
         * @description Every UC-17 field, plus the identity the panel needs to name a person.
         */
        DeviceHealthResponse: {
            /**
             * Agent Id
             * Format: uuid
             */
            agent_id: string;
            /** Android Release */
            android_release: string | null;
            /** Api Level */
            api_level: number | null;
            app_variant: components["schemas"]["AppVariant"] | null;
            /** App Version */
            app_version: string | null;
            /** Battery Charging */
            battery_charging: boolean | null;
            /** Battery Level */
            battery_level: number | null;
            /** Battery Optimisation Exempt */
            battery_optimisation_exempt: boolean | null;
            /** Capture Enabled */
            capture_enabled: boolean | null;
            /** Cellular Bytes Month */
            cellular_bytes_month: number | null;
            /** Clock Skew Sec */
            clock_skew_sec: number | null;
            /** Device Timezone */
            device_timezone: string | null;
            /** Free Storage Bytes */
            free_storage_bytes: number | null;
            /**
             * Installation Id
             * Format: uuid
             */
            installation_id: string;
            installation_status: components["schemas"]["InstallationStatus"];
            /**
             * Is Online
             * @description Derived, never stored: last_heartbeat_at is inside the alerts.device_offline_minutes window. Storing it would need a job to keep it false, and it would be wrong between runs.
             */
            is_online: boolean;
            /** Last Call At */
            last_call_at: string | null;
            /** Last Heartbeat At */
            last_heartbeat_at: string | null;
            /** Manufacturer */
            manufacturer: string | null;
            /** Model */
            model: string | null;
            network_type: components["schemas"]["NetworkType"] | null;
            /**
             * Never Reported
             * @description Bound and never sent a heartbeat. Kept distinct from ``is_online: false`` because the next action differs: never started is a person waiting for help right now; worked once and stopped is a phone in a lift or a battery manager to argue with.
             */
            never_reported: boolean;
            /**
             * Number Id
             * Format: uuid
             */
            number_id: string;
            /** Parked Records */
            parked_records: number | null;
            /** Power Save Mode */
            power_save_mode: boolean | null;
            /** Queue Bytes */
            queue_bytes: number | null;
            /** Queue Oldest At */
            queue_oldest_at: string | null;
            /** Queue Records */
            queue_records: number | null;
            recording_route: components["schemas"]["CaptureRoute"] | null;
            /** Recording Route Ok */
            recording_route_ok: boolean | null;
            /** Service Running */
            service_running: boolean | null;
            /** Updated At */
            updated_at: string | null;
            /**
             * Ws Connected
             * @description Shown separately from is_online on purpose: a socket can be alive while capture is dead, and conflating the two is how a broken phone looks fine.
             */
            ws_connected?: boolean | null;
        };
        /** DirectoryEntryListResponse */
        DirectoryEntryListResponse: {
            /** Items */
            items: components["schemas"]["DirectoryEntryResponse"][];
            /** Total */
            total: number;
        };
        /** DirectoryEntryResponse */
        DirectoryEntryResponse: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Is Active */
            is_active: boolean;
            kind: components["schemas"]["DirectoryRuleKind"];
            /** Label */
            label: string | null;
            /** Pattern */
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
            /** Items */
            items: components["schemas"]["EnrolmentAttemptResponse"][];
            /** Total */
            total: number;
        };
        /**
         * EnrolmentAttemptResponse
         * @description Where UC-01's failures appear, with timestamps.
         */
        EnrolmentAttemptResponse: {
            /** Agent Id */
            agent_id: string | null;
            /** App Version */
            app_version: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Device Model */
            device_model: string | null;
            /** Duration Ms */
            duration_ms: number | null;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Installation Id */
            installation_id: string | null;
            kind: components["schemas"]["EnrolmentAttemptKind"];
            /** Number Id */
            number_id: string | null;
            outcome: components["schemas"]["EnrolmentOutcome"];
            /** Step */
            step: string | null;
        };
        /** EnrolmentCodeListResponse */
        EnrolmentCodeListResponse: {
            /** Items */
            items: components["schemas"]["EnrolmentCodeResponse"][];
            /** Total */
            total: number;
        };
        /**
         * EnrolmentCodeResponse
         * @description The code plus everything the admin has to pass on.
         */
        EnrolmentCodeResponse: {
            /**
             * Agent Id
             * Format: uuid
             */
            agent_id: string;
            /** Attempt Count */
            attempt_count: number;
            /** Code */
            code: string;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Expires At
             * Format: date-time
             */
            expires_at: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Number Id
             * Format: uuid
             */
            number_id: string;
            /** Redeemed At */
            redeemed_at: string | null;
            /** Revoked At */
            revoked_at: string | null;
        };
        /**
         * EnrolmentOutcome
         * @description Every way an enrolment step can end. The funnel's evidence base.
         * @enum {string}
         */
        EnrolmentOutcome: "ok" | "code_not_found" | "code_already_used" | "code_expired" | "code_revoked" | "number_mismatch" | "msisdn_empty" | "no_caller_id" | "timeout" | "receiver_down" | "already_bound" | "rejected";
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
            /**
             * Agent Id
             * Format: uuid
             */
            agent_id: string;
            /** Agent Name */
            agent_name: string;
            /** Answered Calls */
            answered_calls: number;
            /** Calls With Audio */
            calls_with_audio: number;
            /**
             * Capture Rate
             * @description Percent. NUMERIC, never float.
             */
            capture_rate: string | null;
        };
        /** GapByModelOut */
        GapByModelOut: {
            /** Answered Calls */
            answered_calls: number;
            /**
             * Api Level
             * @description Part of the M0 baseline's identity.
             */
            api_level: number;
            /** @description Capture rate is per variant, not only per model (D-06). */
            app_variant: components["schemas"]["AppVariant"];
            /**
             * Baseline Rate
             * @description From the M0 baseline (T14).
             */
            baseline_rate: string | null;
            /** Calls With Audio */
            calls_with_audio: number;
            /** Capture Rate */
            capture_rate: string | null;
            /**
             * Delta Pp
             * @description Below the threshold raises N4's alert.
             */
            delta_pp: string | null;
            /** Manufacturer */
            manufacturer: string;
            /** Model */
            model: string;
            /** Regression */
            regression: boolean;
        };
        /**
         * GapByReasonOut
         * @description Why audio is missing, and how often. The closed enum, never free text.
         */
        GapByReasonOut: {
            /** Calls */
            calls: number;
            /**
             * Counts Against Capture Rate
             * @description ``pending_upload`` and ``not_expected`` are excluded from the denominator: an unanswered call in it makes '% of answered calls with audio' meaningless (SPEC §3.9).
             */
            counts_against_capture_rate: boolean;
            reason: components["schemas"]["AudioMissingReason"];
        };
        /**
         * GapReportResponse
         * @description UC-23. Totals reconcile exactly with ``/calls?has_audio=false``.
         */
        GapReportResponse: {
            /** Answered Calls */
            answered_calls: number;
            /** By Agent */
            by_agent: components["schemas"]["GapByAgentOut"][];
            /** By Model */
            by_model: components["schemas"]["GapByModelOut"][];
            /** By Reason */
            by_reason: components["schemas"]["GapByReasonOut"][];
            /** Calls With Audio */
            calls_with_audio: number;
            /** Capture Rate */
            capture_rate: string | null;
            /**
             * Missing Total
             * @description Matches the filtered call list, because the same rows are counted.
             */
            missing_total: number;
            /** Open Deltas */
            open_deltas: components["schemas"]["OpenDeltaOut"][];
        };
        /**
         * HealthResponse
         * @description Process liveness.
         */
        HealthResponse: {
            /**
             * Status
             * @description Always 'ok' when the process is serving.
             */
            status: string;
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
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
            /**
             * Csv
             * @description Header row plus data: full_name[,employee_code[,hired_at]].
             */
            csv: string;
            /**
             * Dry Run
             * @description Default true, deliberately: the diff is shown before anything is written, because a roster import that half-succeeded is worse than one that did not run.
             * @default true
             */
            dry_run: boolean;
        };
        /** ImportAgentsResponse */
        ImportAgentsResponse: {
            /** Created */
            created: number;
            /** Dry Run */
            dry_run: boolean;
            /** Errors */
            errors: number;
            /** Rows */
            rows: components["schemas"]["ImportRowResult"][];
            /** Skipped */
            skipped: number;
            /** Updated */
            updated: number;
        };
        /**
         * ImportRowResult
         * @description What would happen, or did happen, to one roster line.
         */
        ImportRowResult: {
            /**
             * Action
             * @description create | update | skip | error
             */
            action: string;
            /** Employee Code */
            employee_code: string | null;
            /** Full Name */
            full_name: string;
            /** Line */
            line: number;
            /**
             * Reason
             * @description Why it was skipped or refused.
             */
            reason?: string | null;
        };
        /** InstallationListResponse */
        InstallationListResponse: {
            /** Items */
            items: components["schemas"]["InstallationResponse"][];
            /** Total */
            total: number;
        };
        /**
         * InstallationResponse
         * @description One installation, as the panel reads it.
         */
        InstallationResponse: {
            /**
             * Agent Id
             * Format: uuid
             */
            agent_id: string;
            app_variant: components["schemas"]["AppVariant"] | null;
            /** App Version */
            app_version: string | null;
            /** Attest Reason */
            attest_reason: string | null;
            /** Bound At */
            bound_at: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /**
             * Device Id
             * Format: uuid
             */
            device_id: string;
            /**
             * Funnel Changed At
             * Format: date-time
             */
            funnel_changed_at: string;
            funnel_stage: components["schemas"]["FunnelStage"];
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Number Id
             * Format: uuid
             */
            number_id: string;
            /** Replaced At */
            replaced_at: string | null;
            /** Revoke Confirmed At */
            revoke_confirmed_at: string | null;
            /** Revoke Pending Bytes */
            revoke_pending_bytes: number | null;
            /** Revoke Pending Records */
            revoke_pending_records: number | null;
            /** Revoked At */
            revoked_at: string | null;
            /** Sim Slot */
            sim_slot: number | null;
            /** Sim Subscription Id */
            sim_subscription_id: number | null;
            status: components["schemas"]["InstallationStatus"];
            verification_method: components["schemas"]["VerificationMethod"] | null;
            /** Verified At */
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
            /**
             * Email
             * Format: email
             * @description Case-insensitive; the column is CITEXT.
             */
            email: string;
            /**
             * Password
             * @description Never logged, never echoed.
             */
            password: string;
        };
        /**
         * LoginResponse
         * @description The user *and* their access token, so the panel needs one round trip.
         */
        LoginResponse: {
            /** Access Token */
            access_token: string;
            /**
             * Agent Id
             * @description Set for a 'sales' account; what own-scope filters on.
             */
            agent_id?: string | null;
            /** Email */
            email: string;
            /** Expires In */
            expires_in: number;
            /** Full Name */
            full_name: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /**
             * Must Change Password
             * @description The panel forces the change before anything else loads.
             */
            must_change_password: boolean;
            /**
             * Permissions
             * @description Resolved from the role, sorted.
             */
            permissions: string[];
            role: components["schemas"]["UserRole"];
            /**
             * Token Type
             * @default bearer
             */
            token_type: string;
        };
        /**
         * NetworkType
         * @enum {string}
         */
        NetworkType: "wifi" | "cellular" | "none";
        /** NumberListResponse */
        NumberListResponse: {
            /** Items */
            items: components["schemas"]["NumberResponse"][];
            /** Total */
            total: number;
        };
        /** NumberResponse */
        NumberResponse: {
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** E164 */
            e164: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Is Active */
            is_active: boolean;
            /** Label */
            label: string | null;
            /** Operator */
            operator: string | null;
            /**
             * Phone Key
             * @description Last 9 digits, generated by the database (N37).
             */
            phone_key: string;
            /** Sim Owner */
            sim_owner: string;
        };
        /**
         * OpenDeltaOut
         * @description A device whose own call-log count never reconciled (N3, §4.1 B).
         */
        OpenDeltaOut: {
            /** Agent Name */
            agent_name: string;
            /** Delta */
            delta: number;
            /** Device Counted */
            device_counted: number;
            /**
             * Installation Id
             * Format: uuid
             */
            installation_id: string;
            /**
             * Period Date
             * Format: date
             */
            period_date: string;
            /**
             * Subscription Unknown Count
             * @description Never folded into either side of the rate — the fail-closed rule made visible.
             */
            subscription_unknown_count: number;
            /** Uploaded Count */
            uploaded_count: number;
        };
        /**
         * ReadyResponse
         * @description Dependency readiness, one flag per dependency.
         */
        ReadyResponse: {
            /**
             * Database
             * @description A trivial query succeeded.
             */
            database: boolean;
            /**
             * Status
             * @description 'ok' when every dependency is usable.
             */
            status: string;
            /**
             * Storage
             * @description The audio root exists and is writable.
             */
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
             * Active Receivers
             * @description More than one is a configuration change, not code.
             * @default 0
             */
            active_receivers: number;
            /**
             * Enrolment Possible
             * @description False means the rollout is stopped, not slow.
             */
            enrolment_possible: boolean;
            /**
             * Receiver Msisdn
             * @description The number screen E5 shows the agent.
             */
            receiver_msisdn?: string | null;
            /**
             * Receiver Name
             * @description Which gateway, for the admin to go and look at.
             */
            receiver_name?: string | null;
            /** @description up | degraded | down. Down is 5 minutes without a heartbeat. */
            status: components["schemas"]["ReceiverStatus"];
        };
        /**
         * PublicReleaseListResponse
         * @description The current build of each variant. Empty before the first publish.
         *
         *     `total` can only ever be 0, 1 or 2 — there are two variants — and it is
         *     here anyway, because every list response in this API carries the same two
         *     fields and a generated client that has to special-case one of them is worse
         *     than a field that is always `len(items)`.
         */
        PublicReleaseListResponse: {
            /** Items */
            items: components["schemas"]["PublicReleaseResponse"][];
            /** Total */
            total: number;
        };
        /**
         * PublicReleaseResponse
         * @description One published build, as an anonymous visitor may see it.
         *
         *     A deliberately NARROW copy of `AppVersionResponse` rather than a
         *     reuse of it. That model carries `created_by` and `created_by_name` —
         *     which member of staff uploaded the build — and a public page has no
         *     business naming an employee.
         */
        PublicReleaseResponse: {
            /**
             * Apk Sha256
             * @description So a download can be checked against what the server holds.
             */
            apk_sha256: string;
            /** Min Api Level */
            min_api_level: number;
            /**
             * Published At
             * Format: date-time
             */
            published_at: string | null;
            /** Release Notes Uz */
            release_notes_uz: string | null;
            /**
             * Size Bytes
             * Format: int64
             */
            size_bytes: number;
            variant: components["schemas"]["AppVariant"];
            /** Version */
            version: string;
            /** Version Code */
            version_code: number;
        };
        /**
         * ReclassifyResponse
         * @description A directory change is only half done until the calls agree with it.
         */
        ReclassifyResponse: {
            /**
             * Calls Reclassified
             * @description Calls whose call_type changed as a result of this edit.
             */
            calls_reclassified: number;
            entry: components["schemas"]["DirectoryEntryResponse"];
        };
        /**
         * RevokeRequest
         * @description ``POST /api/v1/installations/{id}/revoke`` (UC-08).
         */
        RevokeRequest: {
            /** Reason */
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
            /** Confirmed */
            confirmed: boolean;
            /**
             * Installation Id
             * Format: uuid
             */
            installation_id: string;
            /** Pending Bytes */
            pending_bytes: number | null;
            /** Pending Records */
            pending_records: number | null;
            /**
             * Revoked At
             * Format: date-time
             */
            revoked_at: string;
            status: components["schemas"]["InstallationStatus"];
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
            /**
             * Acknowledged Stranded
             * @description The stranded count you just saw. Must still be true.
             */
            acknowledged_stranded: number;
            /** Version Code */
            version_code: number;
        };
        /** SetMinimumVersionResponse */
        SetMinimumVersionResponse: {
            /** Stranded Count */
            stranded_count: number;
            /** Version Code */
            version_code: number;
        };
        /**
         * SetPasswordRequest
         * @description ``POST /api/v1/users/{id}/password`` — an admin resetting somebody else's.
         */
        SetPasswordRequest: {
            /** Password */
            password: string;
        };
        /** SettingListResponse */
        SettingListResponse: {
            /** Items */
            items: components["schemas"]["SettingResponse"][];
            /** Total */
            total: number;
        };
        /** SettingResponse */
        SettingResponse: {
            /** Description Uz */
            description_uz: string | null;
            /** Key */
            key: string;
            /**
             * Updated At
             * Format: date-time
             */
            updated_at: string;
            /** Updated By */
            updated_by: string | null;
            /** Value */
            value: unknown;
            /** Value Type */
            value_type: string;
        };
        /**
         * StoragePointOut
         * @description One day of the growth curve.
         */
        StoragePointOut: {
            /**
             * Audio Bytes Total
             * Format: int64
             */
            audio_bytes_total: number;
            /** Audio Files */
            audio_files: number;
            /**
             * Bytes Added
             * Format: int64
             */
            bytes_added: number;
            /**
             * Bytes Deleted
             * Format: int64
             */
            bytes_deleted: number;
            /**
             * Period Date
             * Format: date
             */
            period_date: string;
        };
        /**
         * StorageReportResponse
         * @description N18: current usage, 30-day growth, and the projection it implies.
         */
        StorageReportResponse: {
            /**
             * Audio Bytes Total
             * Format: int64
             */
            audio_bytes_total: number;
            /** Audio Files */
            audio_files: number;
            /**
             * Bytes Added 30D
             * Format: int64
             */
            bytes_added_30d: number;
            /** History */
            history: components["schemas"]["StoragePointOut"][];
            /**
             * Projected Bytes 12M
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
            /** Agent Name */
            agent_name: string;
            /** App Version */
            app_version: string | null;
            /** App Version Code */
            app_version_code: number | null;
            /** Device */
            device: string;
            /**
             * Installation Id
             * Format: uuid
             */
            installation_id: string;
            /** Last Heartbeat At */
            last_heartbeat_at: string | null;
            status: components["schemas"]["InstallationStatus"];
        };
        /**
         * UpdateAgentRequest
         * @description ``PATCH /api/v1/agents/{id}``. Absent fields are unchanged.
         */
        UpdateAgentRequest: {
            /** Color */
            color?: string | null;
            /** Employee Code */
            employee_code?: string | null;
            /** Full Name */
            full_name?: string | null;
            /** Hired At */
            hired_at?: string | null;
            /** Is Active */
            is_active?: boolean | null;
            /** Note */
            note?: string | null;
        };
        /**
         * UpdateCallNoteRequest
         * @description ``PATCH /api/v1/calls/{id}`` — the note and nothing else.
         */
        UpdateCallNoteRequest: {
            /** Note */
            note?: string | null;
        };
        /**
         * UpdateNumberRequest
         * @description ``PATCH /api/v1/numbers/{id}``. The number itself is not editable.
         */
        UpdateNumberRequest: {
            /** Is Active */
            is_active?: boolean | null;
            /** Label */
            label?: string | null;
            /** Operator */
            operator?: string | null;
            /** Sim Owner */
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
             * Confirm
             * @description Required when the change would delete data that still exists.
             * @default false
             */
            confirm: boolean;
            /** Key */
            key: string;
            /** Value */
            value: unknown;
        };
        /**
         * UpdateUserRequest
         * @description ``PATCH /api/v1/users/{id}``. Every field optional; absent means unchanged.
         */
        UpdateUserRequest: {
            /** Agent Id */
            agent_id?: string | null;
            /** Full Name */
            full_name?: string | null;
            /** Is Active */
            is_active?: boolean | null;
            role?: components["schemas"]["UserRole"] | null;
        };
        /**
         * UploadReleaseResponse
         * @description What the upload found in the file, alongside the row it created.
         */
        UploadReleaseResponse: {
            /**
             * Signer Sha256
             * @description SHA-256 of the signing certificate, read from the APK's v2/v3 signing block. Compare it against docs/APK-SIGNING.md by eye if no fingerprint is configured yet — a build signed by another key cannot be installed as an update, only as an uninstall that destroys the phone's unsent queue.
             */
            signer_sha256: string;
            /**
             * Signer Verified
             * @description True when it was checked against the configured fingerprint.
             */
            signer_verified: boolean;
            version: components["schemas"]["AppVersionResponse"];
        };
        /**
         * UserListResponse
         * @description A page of accounts. Small table, so no cursor: the panel shows them all.
         */
        UserListResponse: {
            /** Items */
            items: components["schemas"]["UserResponse"][];
            /** Total */
            total: number;
        };
        /**
         * UserResponse
         * @description A panel account. Never carries the hash.
         */
        UserResponse: {
            /** Agent Id */
            agent_id: string | null;
            /**
             * Created At
             * Format: date-time
             */
            created_at: string;
            /** Email */
            email: string;
            /** Full Name */
            full_name: string;
            /**
             * Id
             * Format: uuid
             */
            id: string;
            /** Is Active */
            is_active: boolean;
            /** Last Login At */
            last_login_at: string | null;
            /** Must Change Password */
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
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
        /**
         * VerificationMethod
         * @description How we proved the phone holds the registered number (UC-04, T142).
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
            /** Current Min Version Code */
            current_min_version_code: number;
            /** Stranded */
            stranded: components["schemas"]["StrandedInstallationOut"][];
            /** Stranded Count */
            stranded_count: number;
            /**
             * Unknown Version Count
             * @description Active phones that have never reported a version code. The gate lets these through, so they are not counted as stranded — but each one might be below the floor and we cannot say.
             */
            unknown_version_count: number;
            /**
             * Version Code
             * @description The minimum being considered.
             */
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_alerts_api_v1_alerts_get: {
        parameters: {
            query?: {
                limit?: number;
                open_only?: boolean;
                severity?: components["schemas"]["AlertSeverity"] | null;
                /** Agent Id */
                agent_id?: string | null;
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    download_version_api_v1_app_download__version_code__get: {
        parameters: {
            query?: never;
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
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
