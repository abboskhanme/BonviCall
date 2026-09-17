"""The analysis seam: ``AudioService.analysis_source`` (SPEC-ANALYTICS §3).

This is the only way the analysis module reaches a recording, so these tests
are what stand between a worker job and the two ways it could go wrong: reading
a file it should not have (another module holding a storage key) and paying a
provider for a file that is missing, expired or not worth sending.

The four refusals are asserted here rather than in the pipeline because the
pipeline cannot test them without the file system underneath it — and because
the 404/410 pair must keep agreeing with what playback answers the panel.
"""

from __future__ import annotations

import uuid
from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from src.core.enums import AnalysisFailure, AudioContainer
from src.core.errors import ErrorCode, GoneError, NotFoundError
from src.modules.audio.service import (
    AnalysisSource,
    AudioNotAnalysable,
    AudioService,
)

pytestmark = pytest.mark.asyncio

#: ~4 KB of pretend Opus, as the rest of the audio suite uses.
PAYLOAD = b"OggS" + bytes(range(256)) * 16


# --- The happy path: the bytes, and the facts that go with them ------------


async def test_analysis_source_hands_over_the_stored_bytes(db, audio_factory) -> None:
    """The whole file, through the storage seam, with no key in sight."""
    audio = await audio_factory(payload=PAYLOAD, duration_ms=120_000)

    source = await AudioService(db).analysis_source(audio.call_id)

    with source.open() as handle:
        assert handle.read() == PAYLOAD
    assert source.call_id == audio.call_id
    assert source.bytes == len(PAYLOAD)
    assert source.duration_ms == 120_000
    assert source.content_type == "audio/ogg"


async def test_the_source_can_be_opened_again_for_a_retry(db, audio_factory) -> None:
    """Retries are cheap now, and this is the property that makes them cheap.

    BonviZvonki re-downloaded the recording from MoiZvonki on every attempt,
    which is why its backoff comment argued about megabytes. Here a second
    attempt is a second ``open()`` of a local file — but only if each call
    really does hand back a fresh handle rather than a stream the first attempt
    has already read to the end.
    """
    audio = await audio_factory(payload=PAYLOAD)
    source = await AudioService(db).analysis_source(audio.call_id)

    with source.open() as first:
        assert first.read() == PAYLOAD
    with source.open() as second:
        assert second.read() == PAYLOAD


async def test_the_container_decides_the_media_type_and_the_extension(
    db, audio_factory
) -> None:
    """The provider SDKs infer the type from the filename, so the two agree.

    ``call_audio.container`` is an enum, which is why the content-type→
    extension map BonviZvonki needed to guess at an HTTP header is not ported.
    """
    audio = await audio_factory(payload=PAYLOAD, container=AudioContainer.MP4)

    source = await AudioService(db).analysis_source(audio.call_id)

    assert source.content_type == "audio/mp4"
    assert source.filename.endswith(".m4a")


async def test_the_filename_names_the_call_and_not_the_employee(
    db, audio_factory
) -> None:
    """This name is read by a third party in another country (§11.5).

    A downloaded recording is named after the agent, because a person saves it
    to a desktop and needs to know whose call it was. A recording sent to a
    vendor is not that: the call id is everything the request needs, and a name
    is the cheapest thing to leak by accident.
    """
    audio = await audio_factory(payload=PAYLOAD)

    source = await AudioService(db).analysis_source(audio.call_id)

    assert source.filename == f"call-{audio.call_id}.ogg"


async def test_the_source_carries_no_storage_key_and_no_path() -> None:
    """The seam only holds if nothing goes around it (SPEC §6).

    The analysis module receives a callable and never a key, so adding a
    ``storage_key`` or ``path`` field here "for convenience" is the change that
    quietly ends the rule. It fails in CI instead.
    """
    assert {field.name for field in fields(AnalysisSource)} == {
        "call_id",
        "bytes",
        "duration_ms",
        "content_type",
        "filename",
        "open",
    }


# --- The four refusals ------------------------------------------------------


async def test_a_call_with_no_audio_row_is_not_found(
    db, call_factory, audio_root
) -> None:
    """An answered call whose recording never arrived. Never queued (§2.6),
    but the pre-run check asks again, because the row can disappear between
    the two."""
    call = await call_factory()

    with pytest.raises(NotFoundError) as raised:
        await AudioService(db).analysis_source(call.id)
    assert raised.value.code == ErrorCode.AUDIO_NOT_FOUND


async def test_an_unknown_call_is_not_found(db, audio_root) -> None:
    with pytest.raises(NotFoundError):
        await AudioService(db).analysis_source(uuid.uuid4())


async def test_audio_removed_by_retention_is_gone_not_missing(
    db, audio_factory
) -> None:
    """A twelve-month-old call cannot be analysed and never will be.

    410 rather than 404 is what lets the pipeline write ``audio_expired``
    instead of ``no_audio`` — the panel shows a different sentence for each,
    and only one of them means "the capture is broken".
    """
    audio = await audio_factory(payload=PAYLOAD)
    audio.recorded_at = datetime.now(UTC) - timedelta(days=800)
    await db.flush()
    assert await AudioService(db).apply_retention() == 1

    with pytest.raises(GoneError) as raised:
        await AudioService(db).analysis_source(audio.call_id)
    assert raised.value.code == ErrorCode.AUDIO_EXPIRED


async def test_a_row_whose_file_is_gone_is_refused_before_any_provider_call(
    db, audio_factory, audio_root
) -> None:
    """The row exists, the bytes do not, and ``deleted_at`` is null.

    A database restored in front of an unrestored disk looks exactly like this.
    Discovering it mid-stream would mean a provider request that was already
    paid for, failing with a message about a truncated upload.
    """
    audio = await audio_factory(payload=PAYLOAD)
    (audio_root / audio.storage_key).unlink()

    with pytest.raises(NotFoundError) as raised:
        await AudioService(db).analysis_source(audio.call_id)
    assert raised.value.code == ErrorCode.AUDIO_NOT_FOUND


async def test_audio_under_the_duration_floor_is_refused_as_too_short(
    db, audio_factory
) -> None:
    """The cheapest protection there is: short calls are the most numerous and
    the least scorable (§11.2)."""
    audio = await audio_factory(payload=PAYLOAD, duration_ms=8_000)

    with pytest.raises(AudioNotAnalysable) as raised:
        await AudioService(db).analysis_source(
            audio.call_id, min_duration_ms=30_000
        )
    assert raised.value.failure is AnalysisFailure.CALL_TOO_SHORT
    assert "8000" in raised.value.detail


async def test_audio_exactly_at_the_duration_floor_is_accepted(
    db, audio_factory
) -> None:
    """The floor is "below this", not "at most this" — a 30-second call is
    what ``analysis.min_duration_sec = 30`` admits."""
    audio = await audio_factory(payload=PAYLOAD, duration_ms=30_000)

    source = await AudioService(db).analysis_source(
        audio.call_id, min_duration_ms=30_000
    )
    assert source.duration_ms == 30_000


async def test_an_unknown_duration_is_never_treated_as_short(
    db, audio_factory
) -> None:
    """``call_audio.duration_ms`` is nullable. A null is an absent
    measurement, not a small one, and skipping on it would silently drop every
    recording whose device reported no duration."""
    audio = await audio_factory(payload=PAYLOAD, duration_ms=None)

    source = await AudioService(db).analysis_source(
        audio.call_id, min_duration_ms=30_000
    )
    assert source.duration_ms is None


async def test_audio_over_the_size_ceiling_is_refused_before_it_is_read(
    db, audio_factory
) -> None:
    """The size is known from the file, so oversized audio costs nothing.

    In BonviZvonki the cap could only be discovered by buffering the stream up
    to it. Here the refusal happens before a byte is allocated, and the
    provider is never called at all.
    """
    audio = await audio_factory(payload=PAYLOAD)

    with pytest.raises(AudioNotAnalysable) as raised:
        await AudioService(db).analysis_source(audio.call_id, max_bytes=1_024)
    assert raised.value.failure is AnalysisFailure.AUDIO_TOO_LARGE


async def test_without_limits_nothing_is_judged(db, audio_factory) -> None:
    """This module holds no analysis policy: a caller that passes no limits
    gets the file, and the decision stays where the settings are read."""
    audio = await audio_factory(payload=PAYLOAD, duration_ms=1)

    source = await AudioService(db).analysis_source(audio.call_id)

    assert source.bytes == len(PAYLOAD)
