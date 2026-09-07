"""Façade du module de préparation des monitions et prières universelles."""
from liturgical_drafts_themes import AELF_API_BASE, AELF_ZONES, APP_TIMEZONE, THEME_RULES
from liturgical_drafts_source import (
    build_draft, clean_html, extract_liturgical_context, fetch_liturgical_context,
    normalize_text, overall_themes, score_themes,
)
from liturgical_drafts_schedule import (
    availability_for, easter_sunday, first_advent_sunday, is_major_event,
    major_celebrations, next_sunday, unlock_for_event, unlock_for_sunday,
)
from liturgical_drafts_word import build_word_document
from liturgical_drafts_ui import persist_liturgical_state, render_liturgical_drafts_tab, saved_drafts

__all__ = [
    "AELF_API_BASE", "AELF_ZONES", "APP_TIMEZONE", "THEME_RULES",
    "availability_for", "build_draft", "build_word_document", "clean_html",
    "easter_sunday", "extract_liturgical_context", "fetch_liturgical_context",
    "first_advent_sunday", "is_major_event", "major_celebrations", "next_sunday",
    "normalize_text", "overall_themes", "persist_liturgical_state",
    "render_liturgical_drafts_tab", "saved_drafts", "score_themes",
    "unlock_for_event", "unlock_for_sunday",
]
