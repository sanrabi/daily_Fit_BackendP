"""DailyFit food image serving and URL resolution.

Add `configure_food_images(app)` immediately after `app = FastAPI()`.
Call `public_food(food, request)` inside existing GET routes.
Actual images must be saved as assets/images/foods/<filename>.
"""
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
FOOD_IMAGE_DIR = BASE_DIR / "assets" / "images" / "foods"

def configure_food_images(app: FastAPI) -> None:
    FOOD_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    # Keep current Firestore image names valid at the /images/ endpoint.
    app.mount("/images", StaticFiles(directory=str(FOOD_IMAGE_DIR)), name="food_images")

def public_food(food: dict, request: Request) -> dict:
    item = dict(food)
    raw = (item.get("image") or "").strip()
    if raw.startswith("https://"):
        # Already hosted elsewhere; do not repackage.
        item["imageType"] = "url"
        return item
    # Only use file basename, never allow request-controlled directory traversal.
    filename = Path(raw.replace("\\", "/")).name
    file_path = FOOD_IMAGE_DIR / filename
    if filename and file_path.is_file() and file_path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        base = str(request.base_url).rstrip("/")
        item["image"] = f"{base}/images/{quote(filename)}"
        item["imageType"] = "url"
    else:
        # Don't return broken links. SwiftUI should show a placeholder.
        item["image"] = None
        item["imageType"] = None
    return item
