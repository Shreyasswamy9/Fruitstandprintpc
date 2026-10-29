"""Plain-language explanations for IPP/CUPS state reasons."""
from __future__ import annotations

REASONS = {
    "none": "No problems reported.",
    "media-empty": "Out of paper.",
    "media-needed": "Paper needs to be loaded.",
    "media-low": "Paper is running low.",
    "media-jam": "Paper jam.",
    "toner-low": "Toner is running low.",
    "toner-empty": "Toner is empty.",
    "marker-supply-low": "Ink or toner is running low.",
    "marker-supply-empty": "Ink or toner is empty.",
    "marker-waste-almost-full": "The waste toner/ink container is almost full.",
    "marker-waste-full": "The waste toner/ink container is full.",
    "cover-open": "A cover or door is open.",
    "door-open": "A door is open.",
    "input-tray-missing": "A paper tray is missing or not fully inserted.",
    "output-area-full": "The output tray is full.",
    "output-area-almost-full": "The output tray is almost full.",
    "offline": "The printer is offline.",
    "offline-report": "CUPS reports the printer as offline or unreachable.",
    "connecting-to-device": "CUPS is trying to connect to the printer.",
    "timed-out": "The printer stopped responding.",
    "paused": "The print queue has been paused by an administrator.",
    "shutdown": "The printer is shutting down.",
    "stopped": "The printer has stopped.",
    "spool-area-full": "The print server's spool area is full.",
    "cups-missing-filter": "The print system has no filter to convert this file for the printer (driver problem).",
    "cups-insecure-filter": "A print filter has unsafe permissions and was blocked.",
    "cups-waiting-for-job-completed": "Waiting for the printer to confirm the job finished.",
    "moving-to-paused": "The printer is pausing.",
    "other": "The printer reported an unspecified condition.",
    "fuser-over-temp": "The fuser is overheating.",
    "fuser-under-temp": "The printer is warming up.",
    "interpreter-resource-unavailable": "The printer ran out of memory or resources for this job.",
    "developer-low": "Developer is running low.",
    "opc-near-eol": "The drum is near the end of its life.",
    "opc-life-over": "The drum needs replacing.",
    "deactivated": "The printer has been deactivated.",
    "identify-printer-requested": "Someone asked the printer to identify itself.",
    "hold-new-jobs": "The printer is holding new jobs.",
    # job-state-reasons
    "job-incoming": "The print server is receiving the file.",
    "job-queued": "Waiting in the print queue.",
    "job-queued-for-marker": "Waiting for the printer.",
    "job-printing": "Printing is in progress.",
    "job-transforming": "The print system is converting the file for the printer.",
    "job-hold-until-specified": "The job is on hold until a set time.",
    "job-held-for-review": "The job is held for review.",
    "job-canceled-by-user": "Cancelled.",
    "job-canceled-by-operator": "Cancelled by an administrator.",
    "job-canceled-at-device": "Cancelled at the printer.",
    "job-completed-successfully": "The print system reports the job finished successfully.",
    "job-completed-with-warnings": "The print system reports the job finished with warnings.",
    "job-completed-with-errors": "The print system reports the job finished with errors.",
    "aborted-by-system": "The print system stopped this job because of an error.",
    "document-format-error": "The printer could not process this document's format.",
    "unsupported-document-format": "The printer does not accept this document format.",
    "job-data-insufficient": "The job contained no printable data.",
    "printer-stopped": "The printer stopped while this job was waiting.",
    "printer-stopped-partly": "The printer is partly stopped.",
    "processing-to-stop-point": "The job is stopping.",
    "service-off-line": "The print service is offline.",
    "queued-in-device": "The job has been sent to the printer and is waiting there.",
    "resources-are-not-ready": "The printer is not ready (paper, toner or tray).",
    "job-fetchable": "The job is waiting to be fetched by the printer.",
}


def split_reason(reason: str) -> tuple[str, str]:
    """Split "media-empty-error" into ("media-empty", "error")."""
    for suffix in ("-error", "-warning", "-report"):
        if reason.endswith(suffix):
            return reason[: -len(suffix)], suffix[1:]
    return reason, "report"


def explain_reason(reason: str) -> dict:
    base, severity = split_reason(reason)
    text = REASONS.get(base) or REASONS.get(reason)
    return {
        "keyword": reason,
        "severity": severity,
        "explanation": text or "The printer reported a condition this hub does not recognize; see technical details.",
        "known": text is not None,
    }


def explain_reasons(reasons: list[str]) -> list[dict]:
    return [explain_reason(r) for r in reasons if r and r != "none"]
