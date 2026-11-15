"""Claude looks at a food photo and says what is on the plate and how much.

It only names foods and counts servings (2 rotis, 1 katori dal). It never
gives calories: those come from Hymn's food list in code. If the photo is a
packaged food's nutrition label, it transcribes the label instead.
The photo is not stored.
"""
from __future__ import annotations

import base64
import os
from typing import List, Literal

import anthropic
from pydantic import BaseModel, ValidationError

import claude_client
from claude_client import AssistantUnavailable
from food_catalog import FOODS

# Naming foods in a photo is the cheap model's job; HYMN_FOOD_MODEL overrides.
MODEL = os.environ.get("HYMN_FOOD_MODEL") or "claude-haiku-5-5"
MEDIA_TYPES = ("image/jpeg", "image/png", "image/webp")


def _system() -> str:
    listing = "\n".join(f"{f['id']}: {f['name']} (per {f['unit']})" for f in FOODS.values())
    return f"""You look at a photo of food someone is about to eat, or a packaged food's
nutrition label, and record what it shows. You never estimate calories.

If it is a plate, bowl, thali or drink:
- set kind to "plate" and list each distinct food in `items`;
- `food_id` is the closest food from the list below, or "" if nothing fits
  (then give a short plain `name`);
- `amount` is how many of that food's servings you see (the unit in
  brackets: piece, katori ~150 ml bowl, plate, cup, glass, tbsp…), in halves
  where needed: 2 rotis → 2; a full katori of dal → 1; half a plate → 0.5;
- `confidence` is low when the food or amount is hard to tell (hidden oil,
  mixed dishes, unclear bowl size);
- a thali: list each bowl separately.

If it is a nutrition label: set kind to "label" and copy the per-serving
figures exactly as printed (empty when not printed); `items` stays empty.

If there is no food in the photo: kind "not_food".

Foods:
{listing}"""


class PhotoItem(BaseModel):
    food_id: str
    name: str
    amount: float
    confidence: Literal["high", "medium", "low"]


class Label(BaseModel):
    product_name: str
    serving_size: str
    kcal: str
    protein_g: str
    carbs_g: str
    fat_g: str
    sugar_g: str


class PhotoReading(BaseModel):
    kind: Literal["plate", "label", "not_food"]
    items: List[PhotoItem]
    label: Label


async def read_photo(image: bytes, media_type: str) -> PhotoReading:
    """Raises AssistantUnavailable."""
    client = claude_client.get_client().with_options(timeout=60.0)
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                     "data": base64.standard_b64encode(image).decode("ascii")}},
        {"type": "text", "text": "What is in this photo?"},
    ]
    try:
        response = await client.beta.messages.parse(
            model=MODEL, max_tokens=4000,
            # The food list is the same for every photo: cache it.
            system=[{"type": "text", "text": _system(), "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}],
            output_format=PhotoReading, output_config={"effort": "low"},
            **claude_client.fallback_kwargs(MODEL),
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        raise claude_client.unavailable_from(exc) from exc
    except ValidationError as exc:
        raise AssistantUnavailable("malformed output") from exc
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        raise AssistantUnavailable(f"stop_reason={response.stop_reason}")
    return response.parsed_output
