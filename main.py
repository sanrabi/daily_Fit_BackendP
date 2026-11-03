
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Literal

from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field, ConfigDict

import firebase_admin
from firebase_admin import auth, firestore
from google.api_core.exceptions import AlreadyExists
from firebase_admin import credentials
from typing import List, Optional
from datetime import date, datetime
from typing import Optional

from openai import OpenAI
import base64
import os
from dotenv import load_dotenv
from pathlib import Path
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError
from fastapi import (
    FastAPI,
    UploadFile,
    File,
    Form,
    HTTPException,
    Depends
)





# STEP 1: Initialize FastAPI and Firebase

app = FastAPI(title="DailyFit API")

cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

security = HTTPBearer()



load_dotenv(Path(__file__).resolve().parent / ".env")

api_key = os.getenv("GEMINI_API_KEY")

print("Gemini API Key Loaded:", bool(api_key))

if not api_key:
    raise RuntimeError("GEMINI_API_KEY is missing")

client = genai.Client(api_key=api_key)

try:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="Say Hello DailyFit"
    )

    print("Gemini Response:", response.text)

except Exception as e:
    print("GEMINI TEST ERROR:", repr(e))



def get_today():
    return datetime.now(
        ZoneInfo("Asia/Kolkata")
    ).strftime("%Y-%m-%d")


# STEP 2: Request Model

class ProfileRequest(BaseModel):

    displayName: str = Field(min_length=1, max_length=100)

    age: int = Field(ge=1, le=120)

    sex: Literal["male", "female", "other"]

    heightCm: float = Field(gt=0, le=300)

    weightKg: float = Field(gt=0, le=500)

    goal: Literal[
        "Stay Healthy",
        "Lose Weight",
        "Gain Weight",
        "Be More Active"
    ]


# STEP 3: Verify Firebase Authentication

def verify_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    try:
        decoded = auth.verify_id_token(
            credentials.credentials,
            check_revoked=True
        )

        return decoded["uid"]

    except auth.CertificateFetchError:
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable"
        )

    except (
        ValueError,
        auth.InvalidIdTokenError,
        auth.ExpiredIdTokenError,
        auth.RevokedIdTokenError,
        auth.UserDisabledError
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token"
        )


# STEP 4: Create Profile API

@app.post("/api/v1/profile")
def create_profile(
    profile: ProfileRequest,
    uid: str = Depends(verify_user)
):

    # Calculate BMI
    height_m = profile.heightCm / 100

    bmi = round(
        profile.weightKg / (height_m * height_m),
        2
    )

    # Get today's date
    today = datetime.now(
        ZoneInfo("Asia/Kolkata")
    ).date().isoformat()

    # Prepare profile data
    profile_data = profile.model_dump()

    profile_data["bmi"] = bmi

    # Prepare daily dashboard response
    dashboard = {

        "date": today,

        "profile": {
            "displayName": profile.displayName,
            "heightCm": profile.heightCm,
            "weightKg": profile.weightKg,
            "bmi": bmi,
            "goal": profile.goal
        },

        "dailyTargets": {
            "calories": 1800,
            "proteinGrams": 90,
            "carbsGrams": 225,
            "fatGrams": 60,
            "waterMl": 2500,
            "exerciseMinutes": 15,
            "steps": 8000
        },

        "nutrition": {
            "calories": 0,
            "proteinGrams": 0,
            "carbsGrams": 0,
            "fatGrams": 0
        },

        "water": {
            "consumedMl": 0,
            "goalMl": 2500
        },

        "steps": {
            "count": 0
        },

        "workouts": {
            "totalMinutes": 0
        },

        "overallPercentage": 0
    }

    # STEP 5: Save profile to Firebase
    user_ref = db.collection("users").document(uid)

    user_ref.set(profile_data, merge=True)

    # STEP 6: Save daily dashboard
    dashboard_ref = (
        user_ref.collection("dailyLogs")
        .document(today)
    )

    try:
        dashboard_ref.create(dashboard)

    except AlreadyExists:
        existing = dashboard_ref.get()
        dashboard = existing.to_dict()

    # STEP 7: Return JSON response
    return dashboard



# REPLACE your existing GET dashboard API

@app.get("/api/v1/dashboard/{day}")
def get_dashboard(
    day: date,
    uid: str = Depends(verify_user)
):

    selected_date = day.isoformat()

    user_ref = db.collection("users").document(uid)

    dashboard_ref = (
        user_ref.collection("dailyLogs")
        .document(selected_date)
    )

    # Step 1: Check dashboard
    snapshot = dashboard_ref.get()

    if snapshot.exists:
        print("Existing dashboard found")
        return snapshot.to_dict()

    # Step 2: Get user profile
    user_snapshot = user_ref.get()

    if not user_snapshot.exists:
        raise HTTPException(
            status_code=404,
            detail="User profile not found. Create profile first."
        )

    user = user_snapshot.to_dict()

    # Step 3: Get latest previous day's settings
    previous_docs = (
        user_ref.collection("dailyLogs")
        .where("date", "<", selected_date)
        .order_by("date", direction=firestore.Query.DESCENDING)
        .limit(1)
        .stream()
    )

    previous = next(previous_docs, None)

    if previous:
        old_dashboard = previous.to_dict()
        targets = old_dashboard.get("dailyTargets", {})
    else:
        targets = {}

    # Default targets for users without history
    default_targets = {
        "calories": 1800,
        "proteinGrams": 90,
        "carbsGrams": 225,
        "fatGrams": 60,
        "waterMl": 2500,
        "exerciseMinutes": 15,
        "steps": 8000
    }

    targets = {**default_targets, **targets}

    # Step 4: Create a fresh daily dashboard
    dashboard = {
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

    # Step 5: Create only if missing
    try:
        dashboard_ref.create(dashboard)

    except AlreadyExists:
        # Prevent overwriting an existing record
        dashboard = dashboard_ref.get().to_dict()

    print("Dashboard loaded:", selected_date)

    return dashboard








# ======================================
# DAILYFIT - UPDATE API MODELS
# ======================================

class BMIUpdate(BaseModel):
    heightCm: Optional[float] = Field(
        default=None, gt=0, le=300
    )
    weightKg: Optional[float] = Field(
        default=None, gt=0, le=500
    )


class NutritionUpdate(BaseModel):
    date: date
    calories: float
    proteinGrams: float
    carbsGrams: float
    fatGrams: float


class WaterUpdate(BaseModel):
    date: date
    amountMl: int = Field(gt=0)


class StepsUpdate(BaseModel):
    date: date
    count: int = Field(gt=0)


class WorkoutUpdate(BaseModel):
    date: date
    durationMinutes: int = Field(gt=0)



# ======================================
# HELPER - GET DAILY DOCUMENT
# ======================================

def daily_ref(uid, selected_date):
    return (
        db.collection("users")
        .document(uid)
        .collection("dailyLogs")
        .document(selected_date)
    )


def calculate_progress(data):

    targets = data["dailyTargets"]
    nutrition = data["nutrition"]

    def percent(actual, target):
        if target <= 0:
            return 0
        return min(100, actual / target * 100)

    values = [
        percent(nutrition["calories"], targets["calories"]),
        percent(nutrition["proteinGrams"], targets["proteinGrams"]),
        percent(nutrition["carbsGrams"], targets["carbsGrams"]),
        percent(nutrition["fatGrams"], targets["fatGrams"]),
        percent(data["water"]["consumedMl"], targets["waterMl"]),
        percent(data["steps"]["count"], targets["steps"]),
        percent(
            data["workouts"]["totalMinutes"],
            targets["exerciseMinutes"]
        )
    ]

    return round(sum(values) / len(values), 2)


# ==========================================
# STEP 3 - SHARED ADDITION FUNCTION
# ==========================================

def add_daily_data(uid, day, category, values):

    doc_ref = (
        db.collection("users")
        .document(uid)
        .collection("dailyLogs")
        .document(day.isoformat())
    )

    transaction = db.transaction()

    @firestore.transactional
    def save_data(transaction):

        snapshot = doc_ref.get(transaction=transaction)

        if not snapshot.exists:
            raise HTTPException(
                status_code=404,
                detail="Daily dashboard not found"
            )

        data = snapshot.to_dict()

        # ADD or SUBTRACT new values
        for field, amount in values.items():

            old_value = data[category][field]

            new_value = old_value + amount

            if new_value < -0.000001:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot reduce {field} below zero"
                )

            data[category][field] = round(
                max(0, new_value), 2
            )

        # Recalculate overall percentage
        data["overallPercentage"] = calculate_progress(data)

        # Update Firebase
        transaction.update(doc_ref, {
            category: data[category],
            "overallPercentage": data["overallPercentage"]
        })

        return data

    return save_data(transaction)


@app.patch("/api/v1/profile/bmi")
def update_bmi(
    request: BMIUpdate,
    uid: str = Depends(verify_user)
):

    if request.heightCm is None and request.weightKg is None:
        raise HTTPException(
            status_code=422,
            detail="Provide height or weight"
        )

    user_ref = db.collection("users").document(uid)

    today = datetime.now(
        ZoneInfo("Asia/Kolkata")
    ).date().isoformat()

    dashboard_ref = (
        user_ref.collection("dailyLogs")
        .document(today)
    )

    transaction = db.transaction()

    @firestore.transactional
    def save_bmi(transaction):

        user_snapshot = user_ref.get(
            transaction=transaction
        )

        dashboard_snapshot = dashboard_ref.get(
            transaction=transaction
        )

        if not user_snapshot.exists:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        if not dashboard_snapshot.exists:
            raise HTTPException(
                status_code=404,
                detail="Today's dashboard not found"
            )

        user = user_snapshot.to_dict()

        height = (
            request.heightCm
            if request.heightCm is not None
            else user["heightCm"]
        )

        weight = (
            request.weightKg
            if request.weightKg is not None
            else user["weightKg"]
        )

        height_m = height / 100
        bmi = round(weight / (height_m ** 2), 2)

        transaction.update(user_ref, {
            "heightCm": height,
            "weightKg": weight,
            "bmi": bmi
        })

        transaction.update(dashboard_ref, {
            "profile.heightCm": height,
            "profile.weightKg": weight,
            "profile.bmi": bmi
        })

        return {
            "message": "BMI updated successfully",
            "heightCm": height,
            "weightKg": weight,
            "bmi": bmi
        }

    return save_bmi(transaction)


# ==========================================
# API 2 - ADD NUTRITION
# PATCH /api/v1/nutrition
# ==========================================

@app.patch("/api/v1/nutrition")
def add_nutrition(
    request: NutritionUpdate,
    uid: str = Depends(verify_user)
):

    return add_daily_data(
        uid,
        request.date,
        "nutrition",
        {
            "calories": request.calories,
            "proteinGrams": request.proteinGrams,
            "carbsGrams": request.carbsGrams,
            "fatGrams": request.fatGrams
        }
    )


# ==========================================
# API 3 - ADD WATER
# PATCH /api/v1/water
# ==========================================

@app.patch("/api/v1/water")
def add_water(
    request: WaterUpdate,
    uid: str = Depends(verify_user)
):

    return add_daily_data(
        uid,
        request.date,
        "water",
        {
            "consumedMl": request.amountMl
        }
    )


# ==========================================
# API 4 - ADD STEPS
# PATCH /api/v1/steps
# ==========================================

@app.patch("/api/v1/steps")
def add_steps(
    request: StepsUpdate,
    uid: str = Depends(verify_user)
):

    return add_daily_data(
        uid,
        request.date,
        "steps",
        {
            "count": request.count
        }
    )


# ==========================================
# API 5 - ADD WORKOUTS
# PATCH /api/v1/workouts
# ==========================================

@app.patch("/api/v1/workouts")
def add_workouts(
    request: WorkoutUpdate,
    uid: str = Depends(verify_user)
):

    return add_daily_data(
        uid,
        request.date,
        "workouts",
        {
            "totalMinutes": request.durationMinutes
        }
    )






#food, fruit, and vegetable endpoint: /api/v1/nutrition
# MARK: Nutrition Item Without Category

class NutritionData(BaseModel):
    title: str
    subtitle: str
    icon: str
    benefits: str
    protein: float
    carbohydrates: float
    fat: float
    calories: float


class NutritionCatalog(BaseModel):
    foodItems: List[NutritionData] = Field(default_factory=list)
    fruitItems: List[NutritionData] = Field(default_factory=list)
    vegetableItems: List[NutritionData] = Field(default_factory=list)


# MARK: Import All Nutrition Items

@app.post("/api/v1/nutrition/import")
def import_nutrition_items(catalog: NutritionCatalog):

    collection = db.collection("nutrition_items")
    batch = db.batch()
    count = 0

    categories = {
        "food": catalog.foodItems,
        "fruit": catalog.fruitItems,
        "vegetable": catalog.vegetableItems
    }

    for category, items in categories.items():

        for item in items:

            data = item.model_dump()
            data["category"] = category

            doc_ref = collection.document()

            batch.set(doc_ref, data)
            count += 1

            if count % 400 == 0:
                batch.commit()
                batch = db.batch()

    if count % 400 != 0:
        batch.commit()

    return {
        "message": "Nutrition catalog imported successfully",
        "totalStored": count
    }


    # MARK: - GET Nutrition Items

@app.get("/api/v1/nutrition")
def get_nutrition_items(
    category: Optional[str] = None,
    search: Optional[str] = None
):

    docs = db.collection("nutrition_items").stream()

    items = []

    for doc in docs:

        data = doc.to_dict()
        data["id"] = doc.id

        # Filter by category
        if category:
            if data.get("category", "").lower() != category.lower():
                continue

        # Search by food name
        if search:
            if search.lower() not in data.get("title", "").lower():
                continue

        items.append(data)

    return {
        "count": len(items),
        "items": items
    }



    #history


@app.get("/api/v1/history/weekly")
def get_weekly_history(
    uid: str = Depends(verify_user)
):

    today = datetime.now(
        ZoneInfo("Asia/Kolkata")
    ).date()

    # Monday of current week
    week_start = today - timedelta(
        days=today.weekday()
    )

    week_end = week_start + timedelta(days=6)

    daily_history = []
    total_percentage = 0
    recorded_days = 0

    for i in range(7):

        day = week_start + timedelta(days=i)

        doc_ref = (
            db.collection("users")
            .document(uid)
            .collection("dailyLogs")
            .document(day.isoformat())
        )

        # Don't query future dates
        snapshot = doc_ref.get() if day <= today else None

        if snapshot is not None and snapshot.exists:
            data = snapshot.to_dict() or {}

            percentage = round(
                float(data.get("overallPercentage", 0)),
                2
            )

            recorded_days += 1
            total_percentage += percentage

        else:
            percentage = 0

        daily_history.append({
            "date": day.isoformat(),
            "day": day.strftime("%A"),
            "overallPercentage": percentage
        })

    weekly_percentage = round(
        total_percentage / recorded_days, 2
    ) if recorded_days else 0

    return {
        "weekStart": week_start.isoformat(),
        "weekEnd": week_end.isoformat(),
        "recordedDays": recorded_days,
        "weeklyPercentage": weekly_percentage,
        "dailyHistory": daily_history
    }













# =====================================
# DAILYFIT - GEMINI AI FOOD ANALYSIS
# =====================================
# STEP 3 - Nutrition response model
class FoodResponse(BaseModel):
    calories: float = Field(ge=0)
    proteinGrams: float = Field(ge=0)
    carbsGrams: float = Field(ge=0)
    fatGrams: float = Field(ge=0)


# STEP 4 - Create AI Food Scanner API
@app.post("/api/v1/food/analyze")
async def analyze_food(
    file: UploadFile = File(...),
    quantityGrams: float = Form(..., gt=0, le=20000),
    uid: str = Depends(verify_user)
):

    print("Gemini Food Analysis Started")

    # STEP 5 - Validate image type
    if file.content_type not in [
        "image/jpeg",
        "image/png",
        "image/webp"
    ]:
        raise HTTPException(
            status_code=400,
            detail="Only JPG, PNG and WebP images are allowed"
        )

    # STEP 6 - Read image
    image = await file.read(5 * 1024 * 1024 + 1)

    if not image or len(image) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Image must be between 1 byte and 5 MB"
        )

    print("Quantity in grams:", quantityGrams)

    try:
        # STEP 7 - Send image and weight to Gemini
        result = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=[
                types.Part.from_bytes(
                    data=image,
                    mime_type=file.content_type
                ),
                (
                    "You are a food nutrition estimation assistant. "
                    "Identify the food in this photograph. "
                    f"The user consumed {quantityGrams} grams "
                    "of edible food. "
                    "Estimate the nutrition for this stated weight. "
                    "First estimate calories, protein, "
                    "carbohydrates and fat per 100 grams "
                    "using typical nutrition values. "
                    "Then multiply those values by "
                    f"{quantityGrams} / 100. "
                    "Take into account visible ingredients "
                    "and cooking methods. "
                    "If there are multiple food items, "
                    "assume the stated weight represents "
                    "the entire combined edible portion. "
                    "Do not use the apparent weight "
                    "of the whole photographed plate. "
                    "Return nonnegative approximate values. "
                    "If there is no food, return zero values."
                )
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=FoodResponse
            )
        )

        # STEP 8 - Check Gemini response
        if not result.text:
            raise ValueError(
                "Gemini returned an empty response"
            )

        # STEP 9 - Convert JSON into Python object
        food = FoodResponse.model_validate_json(
            result.text
        )

        # STEP 10 - Get today's date
        today = get_today()

        # STEP 11 - Return JSON to SwiftUI/Postman
        response = {
            "date": today,
            "quantityGrams": quantityGrams,
            "calories": round(food.calories, 2),
            "proteinGrams": round(food.proteinGrams, 2),
            "carbsGrams": round(food.carbsGrams, 2),
            "fatGrams": round(food.fatGrams, 2)
        }

        print("Gemini Food Analysis Successful")

        return response

    except ServerError as e:
        print("GEMINI SERVER ERROR:", repr(e))

        raise HTTPException(
            status_code=503,
            detail="Gemini is temporarily unavailable. Retry later."
        )

    except ClientError as e:
        print("GEMINI CLIENT ERROR:", repr(e))

        raise HTTPException(
            status_code=502,
            detail="Gemini rejected the request. Check terminal logs."
        )

    except Exception as e:
        print("GEMINI AI ERROR:", repr(e))

        raise HTTPException(
            status_code=502,
            detail="Food analysis failed. Check terminal logs."
        )
