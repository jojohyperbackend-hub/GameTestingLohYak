from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Set

from src import settings


class RNGConfigurationError(Exception):
    pass


class RNGPoolExhaustedError(Exception):
    pass


MIN_ACTIVE_POOL_SIZE: int = 18
HISTORY_MAX_CAPACITY: int = 50
HISTORY_TRIM_CHUNK_SIZE: int = 25
BASE_QUESTION_WEIGHT: float = 1.0
SAME_SUBJECT_STREAK_MULTIPLIER: float = 0.20
DIFFERENT_SUBJECT_MULTIPLIER: float = 1.0
MOMENTUM_ADAPTIVE_BONUS_PER_STACK: float = 0.10
VALID_WEIGHTING_MODES: Set[str] = {"dynamic", "fixed"}


class QuestionRNGManager:
    def __init__(self, config: Dict[str, Any], weighting_mode: str = "dynamic"):
        if weighting_mode not in VALID_WEIGHTING_MODES:
            raise RNGConfigurationError("weighting_mode harus 'dynamic' atau 'fixed'")
        raw_pool = config.get("pool")
        raw_history = config.get("history")
        if not isinstance(raw_pool, list) or not raw_pool:
            raise RNGConfigurationError("config['pool'] wajib berupa list berisi minimal satu soal")
        if raw_history is None:
            raw_history = []
        if not isinstance(raw_history, list):
            raise RNGConfigurationError("config['history'] wajib berupa list")

        self._weighting_mode = weighting_mode
        validated_pool = self._validate_and_normalize_pool(raw_pool)
        working_history: List[str] = [str(item_id) for item_id in raw_history][-HISTORY_MAX_CAPACITY:]

        candidates = self._filter_candidates_by_history(validated_pool, working_history)
        while len(candidates) < MIN_ACTIVE_POOL_SIZE and working_history:
            working_history = working_history[HISTORY_TRIM_CHUNK_SIZE:]
            candidates = self._filter_candidates_by_history(validated_pool, working_history)

        self._deck: List[Dict[str, Any]] = self._fisher_yates_shuffle(candidates)
        self._history: List[str] = working_history
        self._last_subject: Optional[str] = None
        self._last_served_question_id: Optional[str] = None
        self._total_correct_recorded: int = 0
        self._total_incorrect_recorded: int = 0

    def get_next_question(self, game_state: Dict[str, Any]) -> Dict[str, Any]:
        if not self._deck:
            raise RNGPoolExhaustedError("Tidak ada soal tersisa di deck RNG untuk sesi ini")
        if self._weighting_mode == "dynamic":
            momentum_stack = self._extract_momentum_stack(game_state)
            weights = [self._compute_weight(item, momentum_stack) for item in self._deck]
        else:
            weights = [BASE_QUESTION_WEIGHT for _ in self._deck]
        chosen_index = self._weighted_random_index(weights)
        chosen_item = self._deck.pop(chosen_index)
        self._last_subject = chosen_item["subject"]
        self._last_served_question_id = chosen_item["id"]
        return dict(chosen_item)

    def record_answer(self, is_correct: bool) -> None:
        if self._last_served_question_id is None:
            raise RuntimeError("record_answer dipanggil tanpa soal aktif yang sedang dijawab")
        self._history.append(self._last_served_question_id)
        if len(self._history) > HISTORY_MAX_CAPACITY:
            overflow_count = len(self._history) - HISTORY_MAX_CAPACITY
            self._history = self._history[overflow_count:]
        if is_correct:
            self._total_correct_recorded += 1
        else:
            self._total_incorrect_recorded += 1
        self._last_served_question_id = None

    def get_updated_history(self) -> List[str]:
        return list(self._history)

    def _validate_and_normalize_pool(self, pool: List[Any]) -> List[Dict[str, Any]]:
        normalized_pool: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        for raw_item in pool:
            if not isinstance(raw_item, dict):
                raise RNGConfigurationError("Setiap entri pool RNG harus berupa dict")
            for required_key in ("id", "subject", "difficulty"):
                if required_key not in raw_item:
                    raise RNGConfigurationError(f"Entri pool RNG kehilangan field '{required_key}'")
            item_id = str(raw_item["id"])
            if item_id in seen_ids:
                raise RNGConfigurationError(f"ID soal duplikat terdeteksi di pool RNG: {item_id}")
            seen_ids.add(item_id)
            normalized_item = dict(raw_item)
            normalized_item["id"] = item_id
            normalized_item["subject"] = str(raw_item["subject"])
            normalized_item["difficulty"] = int(raw_item["difficulty"])
            normalized_pool.append(normalized_item)
        return normalized_pool

    def _filter_candidates_by_history(
        self, pool: List[Dict[str, Any]], history: List[str]
    ) -> List[Dict[str, Any]]:
        history_set = set(history)
        return [item for item in pool if item["id"] not in history_set]

    def _extract_momentum_stack(self, game_state: Dict[str, Any]) -> int:
        if not isinstance(game_state, dict):
            return 0
        raw_value = game_state.get("momentum_stack", 0)
        try:
            momentum_stack = int(raw_value)
        except (TypeError, ValueError):
            momentum_stack = 0
        return max(0, min(settings.MOMENTUM_MAX_STACK, momentum_stack))

    def _resolve_target_difficulty_for_momentum(self, momentum_stack: int) -> int:
        if momentum_stack <= 1:
            return 1
        if momentum_stack <= 3:
            return 2
        return 3

    def _compute_weight(self, item: Dict[str, Any], momentum_stack: int) -> float:
        subject_multiplier = (
            SAME_SUBJECT_STREAK_MULTIPLIER
            if self._last_subject is not None and item["subject"] == self._last_subject
            else DIFFERENT_SUBJECT_MULTIPLIER
        )
        target_difficulty = self._resolve_target_difficulty_for_momentum(momentum_stack)
        adaptive_multiplier = (
            1.0 + MOMENTUM_ADAPTIVE_BONUS_PER_STACK * momentum_stack
            if item["difficulty"] == target_difficulty
            else 1.0
        )
        return BASE_QUESTION_WEIGHT * subject_multiplier * adaptive_multiplier

    def _weighted_random_index(self, weights: List[float]) -> int:
        total_weight = sum(weights)
        if total_weight <= 0.0:
            return random.randrange(len(weights))
        threshold = random.random() * total_weight
        cumulative = 0.0
        for index, weight in enumerate(weights):
            cumulative += weight
            if threshold <= cumulative:
                return index
        return len(weights) - 1

    @staticmethod
    def _fisher_yates_shuffle(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        shuffled = list(items)
        for i in range(len(shuffled) - 1, 0, -1):
            j = random.randint(0, i)
            shuffled[i], shuffled[j] = shuffled[j], shuffled[i]
        return shuffled