# DailyFit: backend-managed food image URLs

1. Copy `food_assets.py` beside your existing `main.py`.
2. Add `from food_assets import configure_food_images, public_food` near your imports.
3. Below your EXISTING `app = FastAPI()` add `configure_food_images(app)`.
   Remove your previous `app.mount("/images", ...)` block first, to avoid duplicate mounts.
4. Images, if you have real licensed photos, belong at `assets/images/foods/0001-idli.png` etc.
   This package intentionally does NOT contain fake placeholders or actual food photographs.
5. Update your existing GET /api/v1/foods handler to accept `request: Request` and transform each document before returning:

```python
from fastapi import Request
from food_assets import configure_food_images, public_food

# after app = FastAPI():
configure_food_images(app)

@app.get("/api/v1/foods")
def get_foods(request: Request, category: Optional[str] = None, search: Optional[str] = None):
    query = db.collection("foods")
    if category:
        query = query.where("category", "==", category)
    foods = [doc.to_dict() for doc in query.stream()]
    if search:
        term = search.strip().lower()
        foods = [f for f in foods if term in (f.get("name") or "").lower() or any(term in str(t).lower() for t in (f.get("searchTerms") or []))]
    return {"total": len(foods), "foods": [public_food(food, request) for food in foods]}

@app.get("/api/v1/foods/{food_id}")
def get_food(food_id: int, request: Request):
    doc = db.collection("foods").document(str(food_id)).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Food not found")
    return public_food(doc.to_dict(), request)
```

**Important:** Replace, don't duplicate, your existing GET food handlers. Leave all POST handlers unchanged. `food_assets.py` maps images at request time; you do NOT need to import JSON again if Firestore already holds the 204 food documents. The included JSON has the correct relative file paths for optional future imports. No image appears unless you add a real file in `assets/images/foods/` or provide an actual hosted HTTPS image URL.

Test: `http://127.0.0.1:8000/api/v1/foods`, then `http://127.0.0.1:8000/images/0001-idli.png` (latter only works if the PNG exists).

Note: localhost URLs work only for clients that can reach your Mac. For production, deploy behind HTTPS.
