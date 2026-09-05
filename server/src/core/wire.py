"""Wire types whose Python annotation does not carry enough information.

One entry so far, and it exists because of a bug that neither side could see
alone.

Pydantic's ``int`` is unbounded, so a 64-bit value serialises perfectly in
Python and the server stores it in a ``BIGINT``. But it reaches OpenAPI as
``{"type": "integer"}`` with **no format**, and openapi-generator maps a
formatless integer to a 32-bit ``kotlin.Int``. ``System.currentTimeMillis()``
is ~1.77e12 against an ``Int.MAX_VALUE`` of 2.1e9 — three orders of magnitude
over, on every call, on every device. Free storage on a 128 GB handset is
1.28e11.

The Python was right, the database was right, and the generated client was
wrong, which is why it took someone generating a client to find it.

**When to use it.** Only where the field's *real* range exceeds 32 bits: wall
clock milliseconds, and byte counts of things measured in gigabytes. A column
that happens to be ``BIGINT`` is not a reason on its own — ``call_audio.bytes``
is ``BIGINT`` and holds a single recording, about 16 MB for a 90-minute call.
A field that cannot overflow should not claim it can, or the list stops being
auditable and the next reviewer cannot tell a real case from a habit.

``tests/test_wire_int64.py`` holds the line in both directions.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

#: An integer the client must hold in 64 bits. See the module docstring for
#: when this is the right annotation and when it is cargo cult.
Int64 = Annotated[int, Field(json_schema_extra={"format": "int64"})]
