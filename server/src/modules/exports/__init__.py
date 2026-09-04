"""Exports — the committed machine contract for BonviZvonki (UC-29, §5.4).

Owns **no table**. It holds the §2.1 cross-module read exception, declared in
``core/reads.py``: aggregate and projection SELECTs only, read-only, and never
``select(<Model>)``, so no foreign ORM entity is ever loaded and none can
escape past this boundary.
"""
