"""SqliteSaver checkpointing — an interrupted tournament resumes where it
stopped, without re-paying completed calls."""

from __future__ import annotations

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from ..config import SETTINGS


def get_checkpointer() -> SqliteSaver:
    conn = sqlite3.connect(str(SETTINGS.checkpoint_db), check_same_thread=False)
    return SqliteSaver(conn)
