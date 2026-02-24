import base64
import json
import os
from typing import Any, Dict, List
from dotenv import load_dotenv

from openai import OpenAI

load_dotenv()

VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")

try:
    client = OpenAI()
except Exception as e:
    import warnings
    warnings.warn(f"OpenAI client initialization failed: {e}. Set OPENAI_API_KEY in .env file.")
    client = None


def _img_to_data_url(path: str) -> str:
    ext = (os.path.splitext(path)[1] or "").lower()
    mime = "image/jpeg"
    if ext == ".png":
        mime = "image/png"
    elif ext == ".webp":
        mime = "image/webp"
    elif ext in (".heic", ".heif"):
        mime = "image/heic"

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def extract_removal_inventory(image_paths: List[str]) -> Dict[str, Any]:
    """Extract removal inventory from images using OpenAI Vision API."""
    if client is None:
        raise Exception("OpenAI client not initialized. Please set OPENAI_API_KEY in .env file.")

    if not image_paths:
        return {"items": [], "summary": ""}

    valid_paths = []
    for p in image_paths[:6]:
        if not os.path.exists(p):
            raise ValueError(f"Image file not found: {p}")
        valid_paths.append(p)

    if not valid_paths:
        return {"items": [], "summary": ""}

    content = [
        {
            "type": "text",
            "text": (
                "You are an expert removals surveyor analyzing photos to create a detailed moving inventory.\n\n"
                "Return ONLY valid JSON with this schema:\n"
                "{\n"
                '  "items": [\n'
                '    {\n'
                '      "name": "string",\n'
                '      "qty": 1,\n'
                '      "length_cm": 100,\n'
                '      "width_cm": 50,\n'
                '      "height_cm": 80,\n'
                '      "weight_kg": 25,\n'
                '      "cbm": 0.4,\n'
                '      "bulky": false,\n'
                '      "fragile": false,\n'
                '      "item_category": "furniture",\n'
                '      "packing_requirement": "none",\n'
                '      "notes": "string"\n'
                '    }\n'
                "  ],\n"
                '  "summary": "short sentence describing the room contents"\n'
                "}\n\n"
                "CRITICAL RULES:\n"
                "1. DIMENSIONS: Estimate realistic dimensions (length x width x height in cm) for EVERY item\n"
                "2. WEIGHT: Estimate weight in kg for each item\n"
                "3. CBM: Calculate cubic meters (length*width*height/1000000) for each item\n"
                "4. BULKY: Mark as true if item weighs over 50kg\n"
                "5. FRAGILE: Mark as true if item is glass, electronics, or breakable\n"
                "6. QTY: Count ALL visible items of same type\n"
                "7. NAMES: Be specific (e.g., '3-seater fabric sofa', 'double wardrobe')\n"
                "8. ACCURACY: This is used for professional moving quotes - be thorough and realistic\n"
                "9. ITEM_CATEGORY: Classify each item:\n"
                "   - 'furniture': Large furniture that moves as-is\n"
                "   - 'loose_items': Small items that need boxing\n"
                "   - 'wardrobe': Wardrobes with hanging clothes\n"
                "   - 'mattress': Mattresses\n"
                "   - 'already_boxed': Items already in boxes\n"
                "10. PACKING_REQUIREMENT: Specify what packing is needed:\n"
                "   - 'none': Furniture, moves as-is\n"
                "   - 'small_box': Books, small electronics, heavy items\n"
                "   - 'medium_box': Kitchen items, clothes, linens\n"
                "   - 'large_box': Large items, bedding, cushions\n"
                "   - 'wardrobe_box': Hanging clothes\n"
                "   - 'mattress_cover': Mattresses\n\n"
                "KITCHEN CUPBOARD CONTENTS:\n"
                "When you see kitchen cupboards, estimate the CONTENTS:\n"
                "- Plates/bowls/cups -> 'Kitchen crockery', qty: boxes needed (typically 2-4)\n"
                "- Pots/pans -> 'Pots and pans', qty: boxes (typically 1-2)\n"
                "- Food cupboard -> 'Dry food items', qty: boxes (typically 1-3)\n"
                "- Under sink -> 'Cleaning supplies', qty: 1\n"
                "- Cutlery drawer -> 'Cutlery and utensils', qty: 1\n\n"
                "HANGING CLOTHES - WARDROBE BOXES:\n"
                "- Standard single wardrobe = 1-2 wardrobe boxes\n"
                "- Double wardrobe = 2-4 wardrobe boxes\n"
                "- Always add wardrobe boxes separately from the wardrobe furniture\n\n"
                "Common item dimensions:\n"
                "- Sofa (3-seater): 200x90x85cm, ~30kg\n"
                "- Wardrobe (double): 120x60x190cm, ~80kg\n"
                "- Dining table (4-seater): 140x90x75cm, ~35kg\n"
                "- Washing machine: 60x60x85cm, ~70kg\n"
                "- TV (50 inch): 115x70x10cm, ~15kg\n"
                "- Bed (double): 140x200x50cm, ~40kg\n\n"
                "ACROSS MULTIPLE PHOTOS:\n"
                "- If an item appears in multiple photos, count it ONCE only\n"
                "- Deduplicate across photos\n\n"
                "Output JSON only. No markdown, no explanation."
            ),
        }
    ]

    try:
        for p in valid_paths:
            content.append({"type": "image_url", "image_url": {"url": _img_to_data_url(p)}})
    except Exception as e:
        raise ValueError(f"Error encoding images: {e}")

    try:
        resp = client.chat.completions.create(
            model=VISION_MODEL,
            messages=[{"role": "user", "content": content}],
            max_tokens=2000,
        )
    except Exception as e:
        raise Exception(f"OpenAI API error: {e}")

    text = (resp.choices[0].message.content or "").strip()
    if not text:
        return {"items": [], "summary": ""}

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        return {"items": [], "summary": ""}
