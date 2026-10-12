"""Scalar retry snapshots and transaction-fenced persistence operations."""

from __future__ import annotations


def retry_candidates(connection, *, part_ids=None, job_ids=None, kinds=None, failed_only=True):
    where, values = [], []
    for column, selector in (("video_part_id", part_ids), ("job_id", job_ids), ("kind", kinds)):
        if selector is not None:
            selector = tuple(dict.fromkeys(getattr(item, "value", item) for item in selector))
            if not selector:
                return []
            where.append(f"j.{column} IN (" + ",".join("?" for _ in selector) + ")")
            values.extend(selector)
    if failed_only:
        where.append("j.status='failed'")
    query = (
        "SELECT j.job_id,j.kind,j.status,j.last_error_code,j.attempt_count,j.available_at,j.updated_at,"
        "a.attempt_id AS latest_attempt_id,a.finished_at AS latest_finished_at,a.error_code AS latest_attempt_error,a.outcome AS latest_attempt_outcome "
        "FROM workflow_jobs j LEFT JOIN workflow_attempts a ON a.rowid="
        "(SELECT x.rowid FROM workflow_attempts x WHERE x.job_id=j.job_id ORDER BY x.rowid DESC LIMIT 1)")
    if where:
        query += " WHERE " + " AND ".join(where)
    return [dict(row) for row in connection.execute(query + " ORDER BY j.job_id", values)]


def retry_replacements(connection, job_ids):
    """One scalar scan; never project frozen payloads into Python memory."""
    selected = set(job_ids)
    result = {job_id: [] for job_id in selected}
    for row in connection.execute(
        "SELECT job_id,kind,status,json_extract(payload_json,'$.repair_of_job_id') AS repair_of_job_id "
        "FROM workflow_jobs WHERE kind IN ('proofread','render_document') "
        "AND json_type(payload_json,'$.repair_of_job_id')='text'"):
        if row["repair_of_job_id"] in selected:
            result[row["repair_of_job_id"]].append({name: row[name] for name in ("job_id", "kind", "status")})
    return result


def requeue_decided_job(connection, snapshot, *, now):
    """Only callable inside the use case's writer fence after revalidation."""
    if not connection.in_transaction:
        raise RuntimeError("guarded requeue requires a write transaction")
    cursor = connection.execute(
        "UPDATE workflow_jobs SET status='queued',available_at=?,lease_owner=NULL,lease_expires_at=NULL,"
        "last_error_code=NULL,updated_at=? WHERE job_id=? AND status='failed' AND attempt_count=? AND last_error_code IS ?",
        (now, now, snapshot["job_id"], snapshot["attempt_count"], snapshot["last_error_code"]))
    return int(cursor.rowcount)
