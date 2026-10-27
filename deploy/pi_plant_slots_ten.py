"""Farmer-entered NFT planting dates, independent of camera classifications."""

import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path


SLOT_COUNT = 10
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


def validate_slot(value):
    if type(value) is not int or not 1 <= value <= SLOT_COUNT:
        raise ValueError("Plant slot must be an integer from 1 to 10")
    return value


def validate_planting_date(value, today=None):
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
        raise ValueError("Planting date must be YYYY-MM-DD")
    try:
        planted = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid planting date") from exc
    if planted > (today or date.today()):
        raise ValueError("Planting date cannot be in the future")
    return value


class PlantSlotStore:
    """Store dates by fixed NFT position; swaps move dates, not camera boxes."""

    def __init__(self, database_path):
        self.path = Path(database_path)

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=2)
        try:
            with connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS plant_slots_v2 (
                    slot INTEGER PRIMARY KEY CHECK(slot BETWEEN 1 AND 10),
                    planted_on TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )""")
                yield connection
        finally:
            connection.close()

    def list(self, today=None):
        today = today or date.today()
        with self._connect() as connection:
            planted = dict(connection.execute("SELECT slot, planted_on FROM plant_slots_v2"))
        return {
            "as_of": today.isoformat(),
            "slot_count": SLOT_COUNT,
            "slots": [
                {"slot": slot, "planted_on": planted.get(slot),
                 "days_growing": (today - date.fromisoformat(planted[slot])).days
                 if slot in planted else None}
                for slot in range(1, SLOT_COUNT + 1)
            ],
        }

    def set_date(self, slot, planted_on):
        slot = validate_slot(slot)
        planted_on = validate_planting_date(planted_on)
        updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute("""INSERT INTO plant_slots_v2(slot, planted_on, updated_at)
                VALUES (?, ?, ?) ON CONFLICT(slot) DO UPDATE SET
                planted_on=excluded.planted_on, updated_at=excluded.updated_at""",
                (slot, planted_on, updated_at))
        return self.list()

    def clear(self, slot):
        slot = validate_slot(slot)
        with self._connect() as connection:
            connection.execute("DELETE FROM plant_slots_v2 WHERE slot=?", (slot,))
        return self.list()

    def swap(self, first, second):
        first, second = validate_slot(first), validate_slot(second)
        if first == second:
            raise ValueError("Choose two different plant slots")
        updated_at = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            planted = dict(connection.execute(
                "SELECT slot, planted_on FROM plant_slots_v2 WHERE slot IN (?, ?)",
                (first, second),
            ))
            connection.execute("DELETE FROM plant_slots_v2 WHERE slot IN (?, ?)", (first, second))
            for target, source in ((first, second), (second, first)):
                if source in planted:
                    connection.execute(
                        "INSERT INTO plant_slots_v2(slot, planted_on, updated_at) VALUES (?, ?, ?)",
                        (target, planted[source], updated_at),
                    )
        return self.list()
