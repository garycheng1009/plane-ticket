from __future__ import annotations


def rating(current: int, average: int | None, lowest: int | None, max_price: int | None) -> tuple[str, str]:
    score = 3
    if max_price and current <= max_price:
        score += 1
    if average and current <= average * 0.95:
        score += 1
    if lowest and current <= lowest * 1.08:
        score += 1
    score = min(score, 5)
    stars = "★" * score + "☆" * (5 - score)
    advice = "建議買" if score >= 4 else "可再等等"
    return stars, advice
