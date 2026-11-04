
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import firebase_admin
from firebase_admin import credentials, firestore
from google.api_core.exceptions import AlreadyExists

PROJECT_ID = "dailyfit-97fe1"
IST = ZoneInfo("Asia/Kolkata")

DEFAULT_TARGETS = {
    "calories": 1800,
    "proteinGrams": 90,
    "carbsGrams": 225,
    "fatGrams": 60,
    "waterMl": 2500,
    "exerciseMinutes": 15,
    "steps": 8000,
}


# 1. Connect Firebase
def connect_firebase():
    secret = os.getenv("FIREBASE_CREDENTIALS")

    if secret:
        cred = credentials.Certificate(json.loads(secret))
    else:
        cred = credentials.Certificate(
            "serviceAccountKey.json"
        )

    if not firebase_admin._apps:
        firebase_admin.initialize_app(
            cred,
            {"projectId": PROJECT_ID}
        )

    return firestore.client()


# 2. Build default dashboard
def build_dashboard(user, selected_date):

    profile = user.get("profile") or user

    targets = {
        **DEFAULT_TARGETS,
        **(user.get("dailyTargets") or {})
    }

    return {
        "date": selected_date,
        "profile": {
            "displayName": profile["displayName"],
            "heightCm": profile["heightCm"],
            "weightKg": profile["weightKg"],
            "bmi": profile["bmi"],
            "goal": profile["goal"]
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


# 3. Get registration date
def get_registration_date(user_doc):

    created_at = user_doc.create_time

    if created_at is None:
        return None

    return created_at.astimezone(IST).date()


# 4. Check and create missing date
def create_if_missing(
    db, user_doc, user, selected_date, dry_run
):

    ref = (
        db.collection("users")
        .document(user_doc.id)
        .collection("dailyLogs")
        .document(selected_date)
    )

    # Check whether record already exists
    snapshot = ref.get()

    if snapshot.exists:

        print("Already exists:", selected_date)
        return "existing"

    else:

        if dry_run:
            print("Would create:", selected_date)
            return "dry_run"

        dashboard = build_dashboard(
            user, selected_date
        )

        try:
            # Atomic create: never overwrite existing data
            ref.create(dashboard)

            print("Created:", selected_date)
            return "created"

        except AlreadyExists:
            print("Already created:", selected_date)
            return "existing"


# 5. Main function
def main():

    db = connect_firebase()

    today = datetime.now(IST).date()

    dry_run = os.getenv(
        "DRY_RUN", "true"
    ).lower() == "true"

    max_users = int(os.getenv("MAX_USERS", "2"))

    if not 1 <= max_users <= 10000:
        raise ValueError("MAX_USERS must be 1-10000")

    created = 0
    existing = 0
    skipped = 0
    errors = 0

    print("DailyFit automatic records")
    print("Today:", today)
    print("Dry run:", dry_run)

    users = (
        db.collection("users")
        .limit(max_users)
        .stream()
    )

    for user_doc in users:

        user = user_doc.to_dict() or {}
        profile = user.get("profile") or user

        required = [
            "displayName",
            "heightCm",
            "weightKg",
            "bmi",
            "goal"
        ]

        if any(profile.get(k) is None for k in required):
            skipped += 1
            continue

        registration_date = get_registration_date(
            user_doc
        )

        if registration_date is None:
            skipped += 1
            continue

        if registration_date > today:
            skipped += 1
            continue

        print("\nUSER:", user_doc.id)
        print("Registered:", registration_date)

        # FLAG 1: Check all previous dates
        current_date = registration_date

        while current_date < today:

            selected_date = current_date.isoformat()

            try:
                result = create_if_missing(
                    db,
                    user_doc,
                    user,
                    selected_date,
                    dry_run
                )

                if result == "created":
                    created += 1
                elif result == "existing":
                    existing += 1

            except Exception as exc:
                errors += 1
                print("ERROR:", selected_date, exc)

            current_date += timedelta(days=1)

        # FLAG 2: Check today's date
        today_string = today.isoformat()

        try:
            result = create_if_missing(
                db,
                user_doc,
                user,
                today_string,
                dry_run
            )

            if result == "created":
                created += 1
            elif result == "existing":
                existing += 1

        except Exception as exc:
            errors += 1
            print("TODAY ERROR:", exc)

    print("\n===== FINAL RESULT =====")
    print("Created:", created)
    print("Already exists:", existing)
    print("Skipped users:", skipped)
    print("Errors:", errors)

    if errors:
        raise RuntimeError(
            f"{errors} records failed"
        )


if __name__ == "__main__":
    main()
