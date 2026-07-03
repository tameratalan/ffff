from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class PersonaProfile:
    name: str
    emoji: str
    min_session_sec: float
    max_session_sec: float
    read_reviews: bool
    browse_store: bool
    photo_gallery: bool
    cart_priority: float  # 0-1 sepete ekleme olasılığı
    favorite_priority: float
    scroll_intensity: int  # 1-5


PERSONAS = [
    PersonaProfile(
        name="Detaycı Müşteri",
        emoji="🔍",
        min_session_sec=90,
        max_session_sec=180,
        read_reviews=True,
        browse_store=True,
        photo_gallery=True,
        cart_priority=0.45,
        favorite_priority=0.55,
        scroll_intensity=5,
    ),
    PersonaProfile(
        name="Gezgin Müşteri",
        emoji="🧭",
        min_session_sec=45,
        max_session_sec=100,
        read_reviews=False,
        browse_store=False,
        photo_gallery=True,
        cart_priority=0.35,
        favorite_priority=0.75,
        scroll_intensity=4,
    ),
    PersonaProfile(
        name="Aceleci Müşteri",
        emoji="⚡",
        min_session_sec=20,
        max_session_sec=55,
        read_reviews=False,
        browse_store=False,
        photo_gallery=False,
        cart_priority=0.85,
        favorite_priority=0.25,
        scroll_intensity=2,
    ),
]


def pick_persona() -> PersonaProfile:
    return random.choice(PERSONAS)
