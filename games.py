import random
import secrets
from typing import List, Tuple

import config


# ---------- Рулетка ----------

def spin_roulette() -> Tuple[int, str]:
    number = random.randint(0, 36)
    if number == 0:
        color = "green"
    elif number in config.ROULETTE_RED:
        color = "red"
    else:
        color = "black"
    return number, color


# ---------- Слоты ----------

def spin_slots() -> List[str]:
    return [random.choice(config.SLOT_SYMBOLS) for _ in range(3)]


def slots_payout(reels: List[str], bet: int) -> int:
    a, b, c = reels
    if a == b == c:
        return bet * config.SLOT_PAYOUTS.get(a, 3)
    if a == b or b == c or a == c:
        return bet * 2
    return 0


# ---------- Блэкджек ----------

SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]


def new_deck() -> List[Tuple[str, str]]:
    deck = [(rank, suit) for suit in SUITS for rank in RANKS]
    secrets.SystemRandom().shuffle(deck)
    return deck


def card_value(rank: str) -> int:
    if rank in ("J", "Q", "K"):
        return 10
    if rank == "A":
        return 11
    return int(rank)


def hand_value(hand: List[Tuple[str, str]]) -> int:
    total = sum(card_value(rank) for rank, _ in hand)
    aces = sum(1 for rank, _ in hand if rank == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def hand_str(hand: List[Tuple[str, str]]) -> str:
    return " ".join(f"{rank}{suit}" for rank, suit in hand)


# ---------- Кости ----------

def roll_dice(count: int = 2) -> List[int]:
    return [random.randint(config.DICE_MIN, config.DICE_MAX) for _ in range(count)]


# ---------- Монетка ----------

def flip_coin() -> str:
    return random.choice(["heads", "tails"])