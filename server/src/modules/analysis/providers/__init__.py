"""Vendor clients behind one interface (SPEC-ANALYTICS §1.1, §4.1).

A subpackage rather than a flat set of files, so that a vendor SDK never sits
in the module's top-level namespace. Nothing here is imported at start-up
beyond the pure protocol definitions: each client imports its SDK inside the
call, so a missing package is a clear error at call time and not a server that
will not start.
"""
