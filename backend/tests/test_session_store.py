from __future__ import annotations

from app.services.session_store import (
    HAND_PROMPTS,
    TRICKY_HAND_GESTURE_IDS,
    VerificationStore,
    sample_hand_prompts,
)


def test_hand_prompt_ids_are_unique() -> None:
    ids = [prompt_id for prompt_id, _, _ in HAND_PROMPTS]
    assert len(ids) == len(set(ids))


def test_tricky_ids_exist_in_prompts() -> None:
    ids = {prompt_id for prompt_id, _, _ in HAND_PROMPTS}
    assert TRICKY_HAND_GESTURE_IDS <= ids


def test_sampled_hand_prompts_keep_at_most_one_tricky_gesture() -> None:
    for _ in range(200):
        picks = sample_hand_prompts(3)
        assert len(picks) == 3
        assert len({prompt_id for prompt_id, _, _ in picks}) == 3
        tricky = [prompt_id for prompt_id, _, _ in picks if prompt_id in TRICKY_HAND_GESTURE_IDS]
        assert len(tricky) <= 1


def test_create_session_uses_easy_weighted_hand_challenges() -> None:
    store = VerificationStore()
    for _ in range(50):
        result = store.create("user-test")
        assert len(result.hand_challenges) == 3
        tricky = [c for c in result.hand_challenges if c.id in TRICKY_HAND_GESTURE_IDS]
        assert len(tricky) <= 1
