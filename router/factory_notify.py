"""Deliver durable Need Human events to operator-configured notification services.

Run explicitly with --deliver. Destinations and credentials stay in environment
configuration, never in project manifests, browser responses, or event records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from urllib.parse import urlsplit

import httpx

from router.factory_api import database, get_card


def destinations() -> list[dict]:
    targets = json.loads(os.environ.get("MULLM_FACTORY_NOTIFICATIONS", "[]"))
    if not isinstance(targets, list) or len(targets) > 20:
        raise ValueError("MULLM_FACTORY_NOTIFICATIONS must be a JSON array of at most 20 destinations")
    for target in targets:
        if not isinstance(target, dict) or set(target) - {"name", "kind", "url", "token_env"}:
            raise ValueError("Invalid notification destination")
        if not isinstance(target.get("url"), str) or not target["url"]:
            raise ValueError("Destination URL required")
        if target.get("kind", "apprise") not in ("apprise", "webhook"):
            raise ValueError("Destination kind must be apprise or webhook")
        if target.get("kind") == "webhook" and urlsplit(target["url"]).scheme != "https":
            raise ValueError("Notification webhooks require HTTPS")
    return targets


def send(target: dict, event: dict) -> bool:
    if target.get("kind") == "webhook":
        token = os.environ.get(target.get("token_env", ""), "")
        headers = {"Idempotency-Key": event["id"]}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            response = client.post(target["url"], json=event, headers=headers)
            response.raise_for_status()
        return True
    import apprise

    notifier = apprise.Apprise()
    if not notifier.add(target["url"]):
        return False
    return bool(notifier.notify(title="muLLM — Need Human", body=event["message"] + "\n" + event["url"]))


def deliver_one(targets: list[dict], sender=send) -> bool:
    if not targets:
        return False
    now = time.time()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("""SELECT n.*, d.payload, d.resolved
            FROM notifications n JOIN cards d ON n.decision_id=d.id
            WHERE n.status='pending' AND n.available<=? AND n.lease_until<=?
            ORDER BY n.available LIMIT 1""", (now, now)).fetchone()
        if row is None:
            return False
        event_id = row["id"]
        if row["resolved"] is not None:
            db.execute("UPDATE notifications SET status='cancelled' WHERE id=?", (event_id,))
            return True
        # Lease survives a worker crash; another worker can retry later.
        db.execute("UPDATE notifications SET lease_until=?, attempts=attempts+1 WHERE id=?", (now + 600, event_id))
    payload = json.loads(row["payload"])
    run_id = payload.get("run_id", "")
    base = os.environ.get("MULLM_FACTORY_PUBLIC_URL", "https://127.0.0.1:6856").rstrip("/")
    event = {"id": event_id, "type": "factory.need_human", "version": 1,
             "decision_id": row["decision_id"], "run_id": run_id,
             "message": "A factory task needs your decision.",
             "url": base + "/unblock#" + row["decision_id"]}
    # Prompts and project content are intentionally absent from external alerts.
    delivered = set(json.loads(row["delivered"]))
    failed = False
    for target in targets:
        key = hashlib.sha256(target["url"].encode()).hexdigest()
        if key in delivered:
            continue
        if get_card(row["decision_id"])["resolved"]:
            with database() as db:
                db.execute("UPDATE notifications SET status='cancelled' WHERE id=?", (event_id,))
            return True
        try:
            success = sender(target, event)
        except Exception:
            success = False  # Provider errors can contain webhook credentials.
        if success:
            delivered.add(key)
            with database() as db:
                db.execute("UPDATE notifications SET delivered=? WHERE id=?", (json.dumps(sorted(delivered)), event_id))
        else:
            failed = True
    attempts = row["attempts"] + 1
    status = "dead" if failed and attempts >= 8 else ("pending" if failed else "sent")
    with database() as db:
        db.execute("""UPDATE notifications SET status=?, available=?, lease_until=0, error=?
                      WHERE id=? AND status='pending'""",
                   (status, time.time() + min(300, 2 ** attempts),
                    "Delivery failed; check destination configuration" if failed else None, event_id))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deliver", action="store_true", help="Enable external notification delivery")
    parser.add_argument("--once", action="store_true", help="Process at most one queued event")
    args = parser.parse_args()
    targets = destinations()
    if not args.deliver:
        print(f"{len(targets)} destinations configured. Delivery requires --deliver.")
        return
    if not targets:
        parser.error("Configure MULLM_FACTORY_NOTIFICATIONS before enabling delivery")
    while True:
        worked = deliver_one(targets)
        if args.once:
            return
        if not worked:
            time.sleep(2)


if __name__ == "__main__":
    main()
