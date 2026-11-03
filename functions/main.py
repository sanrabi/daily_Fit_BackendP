from firebase_functions import scheduler_fn
from firebase_admin import initialize_app, firestore
from datetime import datetime
from zoneinfo import ZoneInfo

initialize_app()
db = firestore.client()

@scheduler_fn.on_schedule(
    schedule="0 0 * * *",
    timezone="Asia/Kolkata"
)
def create_all_users_daily(event):
    today = datetime.now(
        ZoneInfo("Asia/Kolkata")
    ).strftime("%Y-%m-%d")

    users = db.collection("users").stream()

    for user in users:
        profile = user.to_dict() or {}

        if not profile.get("profile"):
            continue

        daily_ref = (
            db.collection("users")
            .document(user.id)
            .collection("dailyLogs")
            .document(today)
        )

        if daily_ref.get().exists:
            continue

        daily_ref.create({
            "date": today,
            "nutrition": {
                "calories": 0,
                "proteinGrams": 0,
                "carbsGrams": 0,
                "fatGrams": 0
            },
            "water": {
                "consumedMl": 0
            },
            "steps": {
                "count": 0
            },
            "workouts": {
                "totalMinutes": 0
            }
        })