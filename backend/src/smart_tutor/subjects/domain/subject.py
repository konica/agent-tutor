"""The shared subject catalog's fixed entries (PRD §9.4)."""

from smart_tutor.shared.domain.ids import SubjectId

# Seeded by migration 0002; the fallback subject until subject detection (US-2b) assigns real ones.
GENERAL_SUBJECT_ID = SubjectId("00000000-0000-4000-8000-000000000001")
