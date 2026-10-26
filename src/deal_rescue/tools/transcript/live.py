"""Live transcript lookup over Google Drive (Phase 2.3) -- now implemented.

Google Meet transcripts land in Drive as Google Docs. The flow:

1. Drive search: the newest Google Doc whose name mentions the account,
   confined to GOOGLE_DRIVE_FOLDER_ID when set
2. export as plain text
3. `parse_transcript_text()` attributes speakers; `select_excerpts()` keeps the
   lines carrying buying-signal vocabulary
4. no Doc, or Drive unreachable? fall back to the curated transcript when one
   exists (see curated.py) -- the demo stays alive without a Google login

Drive wins over curated on purpose: the demo accounts' meetings are staged as
real Docs in the configured folder, so a live run reads the same pipe a real
account would. Curated is the safety net, not the source.

Auth is the user's own Google login from `cli setup` (read-only Drive scope).
The Meet REST API was considered and skipped (spec 4.2 N5): Drive-only needs no
Meet admin scope and one fewer consent.

Never raises -- a missing Doc, a revoked login or a Drive outage all degrade to
{found: false, reason} (D4).
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from deal_rescue.gdrive import DriveClient
from deal_rescue.settings import Settings
from deal_rescue.tools.base import never_raise
from deal_rescue.tools.transcript.contract import TranscriptResult, select_excerpts
from deal_rescue.tools.transcript.curated import curated_transcript

# "Speaker Name: what they said"
SPEAKER_LINE = re.compile(r"^\s*(?P<speaker>[A-Z][\w'.\- ]{1,40}):\s*(?P<text>.+)$")
DATE_IN_TITLE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})")


def parse_transcript_text(text: str) -> list[dict[str, Any]]:
    """Doc body -> [{speaker, text}]. Unattributed lines keep speaker=None."""
    lines: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = SPEAKER_LINE.match(line)
        if match:
            lines.append(
                {"speaker": match.group("speaker").strip(), "text": match.group("text").strip()}
            )
        elif lines:
            lines[-1]["text"] = f"{lines[-1]['text']} {line}"
        else:
            lines.append({"speaker": None, "text": line})
    return lines


def meeting_date_from_title(title: str) -> date | None:
    match = DATE_IN_TITLE.search(title or "")
    if not match:
        return None
    try:
        return datetime.strptime(match.group("date"), "%Y-%m-%d").date()
    except ValueError:
        return None


class LiveTranscript:
    def __init__(self, settings: Settings, drive: DriveClient | None = None) -> None:
        self.settings = settings
        self.drive = drive or DriveClient(settings)

    @never_raise("transcript lookup failed")
    def fetch_latest(self, account_name: str, *, deal_id: str | None = None) -> dict[str, Any]:
        curated = curated_transcript(self.settings.fixtures_dir, account_name)

        try:
            doc = self.drive.find_doc(account_name)
            body = self.drive.export_text(doc["id"]) if doc else ""
        except Exception:
            if curated is not None:
                return curated
            raise  # never_raise degrades this to {found: false, reason}

        if not doc:
            if curated is not None:
                return curated
            return TranscriptResult(
                found=False, reason=f"no transcript Doc found for {account_name}"
            ).as_state()
        excerpts = select_excerpts(parse_transcript_text(body))
        return TranscriptResult(
            found=bool(excerpts),
            doc_id=doc["id"],
            doc_title=doc.get("name"),
            meeting_date=meeting_date_from_title(doc.get("name", "")),
            excerpts=excerpts,
            reason=None if excerpts else "transcript found but no relevant excerpts",
        ).as_state()
