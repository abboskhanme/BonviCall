"""A tiny, genuinely decodable Ogg Opus file, built without a codec.

The demo needs audio so that the upload chain, the attribution gate, Range
playback and the retention job have data behind them. A blob of random bytes
would exercise all of those — the server never decodes audio — but it would
give the panel's player a file it cannot open, and "the player is broken" and
"the demo audio is fake" look identical on screen.

So this writes a **real** Ogg Opus stream: the two mandatory header pages
(``OpusHead``, ``OpusTags``) followed by audio pages of encoded silence. It is
byte-for-byte openable by libopus; it was built by comparing against a file
written by libsndfile 1.2.2 and matching it field by field.

Not production code: nothing on the server or the phone builds Ogg. The device
transcodes with ``MediaCodec`` (SPEC §7.6) and the server never re-encodes.
"""

from __future__ import annotations

import struct

#: Opus always reports 48 kHz granule positions regardless of the input rate.
OPUS_GRANULE_RATE = 48_000

#: 20 ms per packet, the frame size the app targets (SPEC §7.6).
FRAME_MS = 20
SAMPLES_PER_FRAME = OPUS_GRANULE_RATE * FRAME_MS // 1000

#: One 20 ms packet of libopus-encoded mono silence, lifted verbatim from a
#: file written by libsndfile 1.2.2 (``sf.write(zeros, 48000, subtype="OPUS")``)
#: and verified to be the payload it emits for every steady-state silent frame.
#:
#: The first byte is the TOC — config 31 (CELT, fullband, 20 ms), mono, one
#: frame per packet — and ``fffe`` is the CELT range-coder payload. Hand-rolling
#: this as a bare TOC with a zero-length frame *looks* right, and RFC 6716 §3.4
#: does permit zero-length frames, but libopus rejects such a stream when it is
#: opened. Do not "simplify" it back.
SILENT_PACKET_20MS = bytes.fromhex("f8fffe")

#: The decoder discards this many samples at the start. libsndfile writes 312
#: for a 20 ms stream and the header must agree with the encoder that made the
#: packets above.
PRE_SKIP = 312

#: An Ogg page carries at most 255 lacing values. Our packets are three bytes,
#: so one lacing value each: at most 255 packets, 5.1 seconds, per page.
MAX_SEGMENTS = 255


def _crc_table() -> list[int]:
    """Ogg's CRC-32: polynomial 0x04c11db7, MSB-first, no reflection, no xor.

    Deliberately not ``zlib.crc32``, which is the reflected Ethernet variant
    and produces a different value — a file with the wrong CRC is rejected by
    every strict demuxer and silently accepted by some, which is the worst
    combination for a fixture.
    """
    table = []
    for index in range(256):
        remainder = index << 24
        for _ in range(8):
            if remainder & 0x8000_0000:
                remainder = ((remainder << 1) ^ 0x04C1_1DB7) & 0xFFFF_FFFF
            else:
                remainder = (remainder << 1) & 0xFFFF_FFFF
        table.append(remainder)
    return table


_CRC = _crc_table()


def _crc32(data: bytes) -> int:
    remainder = 0
    for byte in data:
        remainder = ((remainder << 8) & 0xFFFF_FFFF) ^ _CRC[((remainder >> 24) & 0xFF) ^ byte]
    return remainder


def _lacing(packets: list[bytes]) -> bytes:
    """The segment table: each packet as 255-byte runs, then its remainder.

    A packet whose length is an exact multiple of 255 needs a trailing zero, or
    the demuxer joins it to the next one.
    """
    values = bytearray()
    for packet in packets:
        length = len(packet)
        while length >= 255:
            values.append(255)
            length -= 255
        values.append(length)
    return bytes(values)


def _page(
    serial: int, sequence: int, header_type: int, granule: int, packets: list[bytes]
) -> bytes:
    """One Ogg page. The CRC is computed over the page with its field zeroed."""
    segments = _lacing(packets)
    if len(segments) > MAX_SEGMENTS:
        raise ValueError("too many segments for one page")
    header = (
        b"OggS"
        + bytes([0, header_type])
        + struct.pack("<q", granule)
        + struct.pack("<I", serial)
        + struct.pack("<I", sequence)
        + struct.pack("<I", 0)  # CRC placeholder
        + bytes([len(segments)])
        + segments
    )
    page = header + b"".join(packets)
    checksum = _crc32(page)
    return page[:22] + struct.pack("<I", checksum) + page[26:]


def _opus_head(channels: int, input_sample_rate: int) -> bytes:
    return (
        b"OpusHead"
        + bytes([1, channels])
        + struct.pack("<H", PRE_SKIP)
        + struct.pack("<I", input_sample_rate)
        + struct.pack("<h", 0)  # output gain
        + bytes([0])  # channel mapping family 0
    )


def _opus_tags() -> bytes:
    vendor = b"BonviCall demo"
    return b"OpusTags" + struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)


def ogg_opus_silence(duration_ms: int, serial: int = 0x424F_4E56) -> bytes:
    """A valid Ogg Opus stream of ``duration_ms`` of silence.

    ~50 bytes per second of audio, so a five-second clip is under a kilobyte
    and a hundred of them cost less than the demo's call metadata.
    """
    frames = max(1, duration_ms // FRAME_MS)

    pages = [
        _page(serial, 0, 0x02, 0, [_opus_head(1, OPUS_GRANULE_RATE)]),  # BOS
        _page(serial, 1, 0x00, 0, [_opus_tags()]),
    ]

    sequence = 2
    written = 0
    while written < frames:
        batch = min(MAX_SEGMENTS, frames - written)
        written += batch
        last = written == frames
        pages.append(
            _page(
                serial,
                sequence,
                0x04 if last else 0x00,  # EOS on the final page
                # Granule counts decodable samples at 48 kHz. libsndfile does
                # not add the pre-skip here and neither do we; adding it makes
                # the reported duration run long by 6.5 ms.
                written * SAMPLES_PER_FRAME,
                [SILENT_PACKET_20MS] * batch,
            )
        )
        sequence += 1
    return b"".join(pages)


def estimated_bytes(duration_sec: int) -> int:
    """Roughly what ``ogg_opus_silence`` will produce, for sizing a demo.

    About 205 bytes per second: 150 bytes of packets plus the 282-byte page
    header every 5.1 seconds.
    """
    frames = max(1, duration_sec * 1000 // FRAME_MS)
    pages = -(-frames // MAX_SEGMENTS)
    return 49 + 42 + frames * len(SILENT_PACKET_20MS) + pages * (27 + MAX_SEGMENTS)
