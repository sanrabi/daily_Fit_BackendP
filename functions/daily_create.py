
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import firebase_admin
from firebase_admin import credentials, firestore
from google.api_core.exceptions import AlreadyExists

PROJECT_ID = "dailyfit-97fe1"

DEFAULT_TARGETS = {
    "calories": 1800,
    "proteinGrams": 90,
    "carbsGrams": 225,
    "fatGrams": 60,
    "waterMl": 2500,
    "exerciseMinutes": 15,
    "steps": 8000,
}


def connect_firebase():
    secret = os.getenv("FIREBASE_CREDENTIALS")

    if secret:
        cred = credentials.Certificate(json.loads(secret))
    else:
        cred = credentials.Certificate(
            "serviceAccountKey.json"
        )

    firebase_admin.initialize_app(
        cred,
        {"projectId": PROJECT_ID}
    )

    return firestore.client()


def build_dashboard(user, selected_date):
    targets = {
        **DEFAULT_TARGETS,
        **(user.get("dailyTargets") or {})
    }

    return {
        "date": selected_date,
        "profile": {
            "displayName": user["displayName"],
            "heightCm": user["heightCm"],
            "weightKg": user["weightKg"],
            "bmi": user["bmi"],
            "goal": user["goal"]
        },
        "dailyTargets": targets,
        "nutrition": {
            "calories": 0,
            "proteinGrams": 0,
            "carbsGrams": 0,
            "fatGrams": 0
        },
        "water": {
            "consumedMl": 0,
            "goalMl": targets["waterMl"]
        },
        "steps": {
            "count": 0
        },
        "workouts": {
            "totalMinutes": 0
        },
        "overallPercentage": 0
    }


def main():
    db = connect_firebase()

    today = datetime.now(
        ZoneInfo("Asia/Kolkata")
    ).date()

    dry_run = os.getenv(
        "DRY_RUN", "true"
    ).lower() == "true"

    max_users = int(os.getenv("MAX_USERS", "2"))

    if not 1 <= max_users <= 10000:
        raise ValueError("MAX_USERS must be 1-10000")

    # Today + previous 3 days = 4 dates
    dates = [
        (today - timedelta(days=i)).isoformat()
        for i in range(3, -1, -1)
    ]

    print("DailyFit automatic records")
    print("Dates:", dates)
    print("Dry run:", dry_run)

    created = 0
    existing = 0
    skipped = 0
    errors = 0

    users = (
        db.collection("users")
        .limit(max_users)
        .stream()
    )

    for user_doc in users:
        user = user_doc.to_dict() or {}

        required = [
            "displayName",
            "heightCm",
            "weightKg",
            "bmi",
            "goal"
        ]

        if any(user.get(k) is None for k in required):
            skipped += 1
            continue

        for selected_date in dates:
            ref = (
                db.collection("users")
                .document(user_doc.id)
                .collection("dailyLogs")
                .document(selected_date)
            )

            if dry_run:
                print(
                    "Would check:",
                    user_doc.id,
                    selected_date
                )
                continue

            dashboard = build_dashboard(
                user, selected_date
            )

            try:
                ref.create(dashboard)
                created += 1

            except AlreadyExists:
                existing += 1

            except Exception as exc:
                errors += 1
                print(
                    "ERROR:",
                    user_doc.id,
                    selected_date,
                    str(exc)
                )

    print("Created:", created)
    print("Already exists:", existing)
    print("Skipped profiles:", skipped)
    print("Errors:", errors)

    if errors:
        raise RuntimeError(
            f"{errors} records failed"
        )



if __name__ == "__main__":
    main()
