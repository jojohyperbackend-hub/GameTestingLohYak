from __future__ import annotations

import html
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set

from src import settings


class SaveDataError(Exception):
    pass


class QuestionDatabaseError(Exception):
    pass


class AchievementDataError(Exception):
    pass


API_DIFFICULTY_TO_INTERNAL: Dict[str, int] = {
    "easy": 1,
    "medium": 2,
    "hard": 3,
}

INTERNAL_DIFFICULTY_TO_API: Dict[int, str] = {
    value: key for key, value in API_DIFFICULTY_TO_INTERNAL.items()
}

VALID_ACHIEVEMENT_RARITIES: Set[str] = {"bronze", "silver", "gold", "platinum"}

ACHIEVEMENT_RARITY_POTION_REWARD: Dict[str, int] = {
    "bronze": 1,
    "silver": 2,
    "gold": 3,
    "platinum": 0,
}


def _current_utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HeroSaveState:
    max_hp: int
    hp: int
    atk: int
    def_: int
    spd: int
    cleared_level_ids: Set[int] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_hp": self.max_hp,
            "hp": self.hp,
            "atk": self.atk,
            "def": self.def_,
            "spd": self.spd,
            "cleared_level_ids": sorted(self.cleared_level_ids),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "HeroSaveState":
        required_keys = ("max_hp", "hp", "atk", "def", "spd", "cleared_level_ids")
        for key in required_keys:
            if key not in data:
                raise SaveDataError(f"Field hero.{key} tidak ditemukan di save_data.json")
        return HeroSaveState(
            max_hp=int(data["max_hp"]),
            hp=int(data["hp"]),
            atk=int(data["atk"]),
            def_=int(data["def"]),
            spd=int(data["spd"]),
            cleared_level_ids=set(int(level_id) for level_id in data["cleared_level_ids"]),
        )

    @staticmethod
    def default() -> "HeroSaveState":
        return HeroSaveState(
            max_hp=settings.HERO_BASE_HP,
            hp=settings.HERO_BASE_HP,
            atk=settings.HERO_BASE_ATK,
            def_=settings.HERO_BASE_DEF,
            spd=settings.HERO_BASE_SPD,
            cleared_level_ids=set(),
        )


@dataclass
class PersistentCounters:
    total_correct_answers: int = 0
    total_fast_correct_answers: int = 0
    total_essay_correct_streak_best: int = 0
    total_element_swaps_lifetime: int = 0
    max_element_swaps_single_battle: int = 0
    max_melt_triggers_single_battle: int = 0
    total_battles_won: int = 0
    max_potions_held: int = settings.POTION_INVENTORY_START
    ended_battle_with_full_ap: bool = False
    perfect_clear_level_ids: Set[int] = field(default_factory=set)
    won_without_potion_level_ids: Set[int] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_correct_answers": self.total_correct_answers,
            "total_fast_correct_answers": self.total_fast_correct_answers,
            "total_essay_correct_streak_best": self.total_essay_correct_streak_best,
            "total_element_swaps_lifetime": self.total_element_swaps_lifetime,
            "max_element_swaps_single_battle": self.max_element_swaps_single_battle,
            "max_melt_triggers_single_battle": self.max_melt_triggers_single_battle,
            "total_battles_won": self.total_battles_won,
            "max_potions_held": self.max_potions_held,
            "ended_battle_with_full_ap": self.ended_battle_with_full_ap,
            "perfect_clear_level_ids": sorted(self.perfect_clear_level_ids),
            "won_without_potion_level_ids": sorted(self.won_without_potion_level_ids),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "PersistentCounters":
        required_keys = (
            "total_correct_answers",
            "total_fast_correct_answers",
            "total_essay_correct_streak_best",
            "total_element_swaps_lifetime",
            "max_element_swaps_single_battle",
            "max_melt_triggers_single_battle",
            "total_battles_won",
            "max_potions_held",
            "ended_battle_with_full_ap",
            "perfect_clear_level_ids",
            "won_without_potion_level_ids",
        )
        for key in required_keys:
            if key not in data:
                raise SaveDataError(f"Field counters.{key} tidak ditemukan di save_data.json")
        return PersistentCounters(
            total_correct_answers=int(data["total_correct_answers"]),
            total_fast_correct_answers=int(data["total_fast_correct_answers"]),
            total_essay_correct_streak_best=int(data["total_essay_correct_streak_best"]),
            total_element_swaps_lifetime=int(data["total_element_swaps_lifetime"]),
            max_element_swaps_single_battle=int(data["max_element_swaps_single_battle"]),
            max_melt_triggers_single_battle=int(data["max_melt_triggers_single_battle"]),
            total_battles_won=int(data["total_battles_won"]),
            max_potions_held=int(data["max_potions_held"]),
            ended_battle_with_full_ap=bool(data["ended_battle_with_full_ap"]),
            perfect_clear_level_ids=set(int(level_id) for level_id in data["perfect_clear_level_ids"]),
            won_without_potion_level_ids=set(
                int(level_id) for level_id in data["won_without_potion_level_ids"]
            ),
        )


@dataclass
class SaveData:
    current_level: int
    hero: HeroSaveState
    element: str
    inventory: int
    highscore: Dict[int, int]
    counters: PersistentCounters
    title: List[str]
    achievements: Dict[str, Optional[str]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_level": self.current_level,
            "hero": self.hero.to_dict(),
            "element": self.element,
            "inventory": self.inventory,
            "highscore": {str(level_id): score for level_id, score in self.highscore.items()},
            "counters": self.counters.to_dict(),
            "title": list(self.title),
            "achievements": dict(self.achievements),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "SaveData":
        required_keys = (
            "current_level",
            "hero",
            "element",
            "inventory",
            "highscore",
            "counters",
            "title",
            "achievements",
        )
        for key in required_keys:
            if key not in data:
                raise SaveDataError(f"Field {key} tidak ditemukan di save_data.json")
        if data["element"] not in ("fire", "ice"):
            raise SaveDataError("Field element pada save_data.json harus 'fire' atau 'ice'")
        return SaveData(
            current_level=int(data["current_level"]),
            hero=HeroSaveState.from_dict(data["hero"]),
            element=data["element"],
            inventory=int(data["inventory"]),
            highscore={int(level_id): int(score) for level_id, score in data["highscore"].items()},
            counters=PersistentCounters.from_dict(data["counters"]),
            title=list(data["title"]),
            achievements={
                achievement_id: (timestamp if timestamp is None else str(timestamp))
                for achievement_id, timestamp in data["achievements"].items()
            },
        )

    @staticmethod
    def default() -> "SaveData":
        return SaveData(
            current_level=0,
            hero=HeroSaveState.default(),
            element="fire",
            inventory=settings.POTION_INVENTORY_START,
            highscore={},
            counters=PersistentCounters(),
            title=[],
            achievements={},
        )


class SaveDataRepository:
    def __init__(self, save_path: Path, backup_path: Path):
        self._save_path = save_path
        self._backup_path = backup_path

    def load(self) -> SaveData:
        if not self._save_path.exists():
            default_data = SaveData.default()
            self.save(default_data)
            return default_data
        try:
            raw_text = self._save_path.read_text(encoding="utf-8")
            raw_data = json.loads(raw_text)
            return SaveData.from_dict(raw_data)
        except (json.JSONDecodeError, SaveDataError, TypeError, ValueError, KeyError):
            self._backup_corrupted_file()
            default_data = SaveData.default()
            self.save(default_data)
            return default_data

    def save(self, save_data: SaveData) -> None:
        self._save_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._save_path.with_suffix(".tmp")
        serialized = json.dumps(save_data.to_dict(), indent=2, ensure_ascii=False)
        temporary_path.write_text(serialized, encoding="utf-8")
        temporary_path.replace(self._save_path)

    def _backup_corrupted_file(self) -> None:
        if not self._save_path.exists():
            return
        try:
            corrupted_content = self._save_path.read_text(encoding="utf-8")
            self._backup_path.write_text(corrupted_content, encoding="utf-8")
        except OSError:
            pass


@dataclass
class AchievementDefinition:
    id: str
    name: str
    description: str
    rarity: str

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "AchievementDefinition":
        required_keys = ("id", "name", "description", "rarity")
        for key in required_keys:
            if key not in data:
                raise AchievementDataError(f"Field {key} tidak ditemukan di entri achievements.json")
        rarity = data["rarity"]
        if rarity not in VALID_ACHIEVEMENT_RARITIES:
            raise AchievementDataError(f"Rarity '{rarity}' pada achievement '{data['id']}' tidak valid")
        return AchievementDefinition(
            id=str(data["id"]),
            name=str(data["name"]),
            description=str(data["description"]),
            rarity=rarity,
        )


@dataclass
class AchievementReward:
    potion_amount: int
    title: Optional[str]


class AchievementRepository:
    def __init__(self, achievements_path: Path):
        self._achievements_path = achievements_path
        self._definitions: Dict[str, AchievementDefinition] = {}

    def load(self) -> List[AchievementDefinition]:
        if not self._achievements_path.exists():
            raise AchievementDataError("File achievements.json tidak ditemukan")
        try:
            raw_text = self._achievements_path.read_text(encoding="utf-8")
            raw_list = json.loads(raw_text)
        except json.JSONDecodeError as error:
            raise AchievementDataError(f"achievements.json rusak: {error}") from error
        if not isinstance(raw_list, list) or not raw_list:
            raise AchievementDataError("achievements.json kosong atau formatnya tidak valid")
        definitions = [AchievementDefinition.from_dict(entry) for entry in raw_list]
        self._definitions = {definition.id: definition for definition in definitions}
        return definitions

    def get_all(self) -> List[AchievementDefinition]:
        if not self._definitions:
            self.load()
        return list(self._definitions.values())

    def get_by_id(self, achievement_id: str) -> AchievementDefinition:
        if not self._definitions:
            self.load()
        if achievement_id not in self._definitions:
            raise AchievementDataError(f"Achievement '{achievement_id}' tidak ditemukan")
        return self._definitions[achievement_id]


class AchievementEvaluator:
    def __init__(self, repository: AchievementRepository):
        self._repository = repository
        self._condition_checks = {
            "first_blood": self._check_first_blood,
            "perfect_l1": self._check_perfect_l1,
            "perfect_l2": self._check_perfect_l2,
            "perfect_l3": self._check_perfect_l3,
            "melt_master": self._check_melt_master,
            "ap_optimizer": self._check_ap_optimizer,
            "no_item_run": self._check_no_item_run,
            "scholar": self._check_scholar,
            "genius": self._check_genius,
            "encyclopedia": self._check_encyclopedia,
            "speed_answer": self._check_speed_answer,
            "essay_master": self._check_essay_master,
            "element_swap": self._check_element_swap,
            "swap_master": self._check_swap_master,
            "potion_hoarder": self._check_potion_hoarder,
        }

    def evaluate(self, counters: PersistentCounters, already_unlocked_ids: Set[str]) -> List[AchievementDefinition]:
        newly_unlocked: List[AchievementDefinition] = []
        for definition in self._repository.get_all():
            if definition.id in already_unlocked_ids:
                continue
            condition_check = self._condition_checks.get(definition.id)
            if condition_check is None:
                continue
            if condition_check(counters):
                newly_unlocked.append(definition)
        return newly_unlocked

    def compute_reward(self, definition: AchievementDefinition) -> AchievementReward:
        potion_amount = ACHIEVEMENT_RARITY_POTION_REWARD[definition.rarity]
        title = definition.name if definition.rarity == "platinum" else None
        return AchievementReward(potion_amount=potion_amount, title=title)

    def apply_unlocks(self, save_data: SaveData, newly_unlocked: List[AchievementDefinition]) -> List[AchievementReward]:
        applied_rewards: List[AchievementReward] = []
        for definition in newly_unlocked:
            reward = self.compute_reward(definition)
            save_data.achievements[definition.id] = _current_utc_timestamp()
            if reward.potion_amount > 0:
                save_data.inventory = min(
                    settings.POTION_INVENTORY_MAX, save_data.inventory + reward.potion_amount
                )
            if reward.title is not None and reward.title not in save_data.title:
                save_data.title.append(reward.title)
            applied_rewards.append(reward)
        return applied_rewards

    def _check_first_blood(self, counters: PersistentCounters) -> bool:
        return counters.total_battles_won >= 1

    def _check_perfect_l1(self, counters: PersistentCounters) -> bool:
        return 1 in counters.perfect_clear_level_ids

    def _check_perfect_l2(self, counters: PersistentCounters) -> bool:
        return 2 in counters.perfect_clear_level_ids

    def _check_perfect_l3(self, counters: PersistentCounters) -> bool:
        return 3 in counters.perfect_clear_level_ids

    def _check_melt_master(self, counters: PersistentCounters) -> bool:
        return counters.max_melt_triggers_single_battle >= 5

    def _check_ap_optimizer(self, counters: PersistentCounters) -> bool:
        return counters.ended_battle_with_full_ap

    def _check_no_item_run(self, counters: PersistentCounters) -> bool:
        return bool(counters.won_without_potion_level_ids & {2, 3})

    def _check_scholar(self, counters: PersistentCounters) -> bool:
        return counters.total_correct_answers >= 50

    def _check_genius(self, counters: PersistentCounters) -> bool:
        return counters.total_correct_answers >= 100

    def _check_encyclopedia(self, counters: PersistentCounters) -> bool:
        return counters.total_correct_answers >= 200

    def _check_speed_answer(self, counters: PersistentCounters) -> bool:
        return counters.total_fast_correct_answers >= 10

    def _check_essay_master(self, counters: PersistentCounters) -> bool:
        return counters.total_essay_correct_streak_best >= 20

    def _check_element_swap(self, counters: PersistentCounters) -> bool:
        return counters.total_element_swaps_lifetime >= 1

    def _check_swap_master(self, counters: PersistentCounters) -> bool:
        return counters.max_element_swaps_single_battle >= 10

    def _check_potion_hoarder(self, counters: PersistentCounters) -> bool:
        return counters.max_potions_held >= 5


@dataclass
class MultipleChoiceQuestion:
    id: str
    subject: str
    difficulty: int
    question_text: str
    options: List[str]
    answer_index: int


@dataclass
class EssayQuestion:
    id: str
    subject: str
    difficulty: int
    question_text: str
    keyword_groups: List[List[str]]


class LocalQuestionRepository:
    def __init__(self, questions_path: Path):
        self._questions_path = questions_path
        self._mc_pool: List[MultipleChoiceQuestion] = []
        self._essay_pool: List[EssayQuestion] = []
        self._loaded = False

    def load(self) -> None:
        if not self._questions_path.exists():
            raise QuestionDatabaseError("File questions.json tidak ditemukan")
        try:
            raw_text = self._questions_path.read_text(encoding="utf-8")
            raw_list = json.loads(raw_text)
        except json.JSONDecodeError as error:
            raise QuestionDatabaseError(f"questions.json rusak: {error}") from error
        if not isinstance(raw_list, list) or not raw_list:
            raise QuestionDatabaseError("questions.json kosong atau formatnya tidak valid")
        mc_pool: List[MultipleChoiceQuestion] = []
        essay_pool: List[EssayQuestion] = []
        for entry in raw_list:
            question_type = entry.get("type")
            if question_type == "mc":
                mc_pool.append(self._parse_mc_entry(entry))
            elif question_type == "essay":
                essay_pool.append(self._parse_essay_entry(entry))
            else:
                raise QuestionDatabaseError(f"Tipe soal tidak dikenal pada entri id={entry.get('id')}")
        if not mc_pool:
            raise QuestionDatabaseError("questions.json tidak memiliki soal bertipe mc")
        if not essay_pool:
            raise QuestionDatabaseError("questions.json tidak memiliki soal bertipe essay")
        self._mc_pool = mc_pool
        self._essay_pool = essay_pool
        self._loaded = True

    def _parse_mc_entry(self, entry: Dict[str, Any]) -> MultipleChoiceQuestion:
        required_keys = ("id", "difficulty", "subject", "question", "options", "answer_index")
        for key in required_keys:
            if key not in entry:
                raise QuestionDatabaseError(f"Field {key} tidak ditemukan pada soal mc id={entry.get('id')}")
        options = entry["options"]
        if not isinstance(options, list) or len(options) != 4:
            raise QuestionDatabaseError(f"Soal mc id={entry['id']} harus memiliki tepat 4 opsi")
        answer_index = int(entry["answer_index"])
        if not 0 <= answer_index <= 3:
            raise QuestionDatabaseError(f"answer_index soal mc id={entry['id']} di luar rentang 0-3")
        return MultipleChoiceQuestion(
            id=str(entry["id"]),
            subject=str(entry["subject"]),
            difficulty=int(entry["difficulty"]),
            question_text=str(entry["question"]),
            options=[str(option) for option in options],
            answer_index=answer_index,
        )

    def _parse_essay_entry(self, entry: Dict[str, Any]) -> EssayQuestion:
        required_keys = ("id", "difficulty", "subject", "question", "keywords")
        for key in required_keys:
            if key not in entry:
                raise QuestionDatabaseError(f"Field {key} tidak ditemukan pada soal essay id={entry.get('id')}")
        keyword_groups = entry["keywords"]
        if not isinstance(keyword_groups, list) or not keyword_groups:
            raise QuestionDatabaseError(f"Soal essay id={entry['id']} harus memiliki minimal satu grup keyword")
        parsed_groups: List[List[str]] = []
        for group in keyword_groups:
            if not isinstance(group, list) or not group:
                raise QuestionDatabaseError(f"Grup keyword kosong pada soal essay id={entry['id']}")
            parsed_groups.append([str(synonym) for synonym in group])
        return EssayQuestion(
            id=str(entry["id"]),
            subject=str(entry["subject"]),
            difficulty=int(entry["difficulty"]),
            question_text=str(entry["question"]),
            keyword_groups=parsed_groups,
        )

    def get_random_mc_question(self) -> MultipleChoiceQuestion:
        if not self._loaded:
            self.load()
        return random.choice(self._mc_pool)

    def get_random_essay_question(
        self, min_difficulty: Optional[int] = None, max_difficulty: Optional[int] = None
    ) -> EssayQuestion:
        if not self._loaded:
            self.load()
        candidates = self._essay_pool
        if min_difficulty is not None:
            candidates = [question for question in candidates if question.difficulty >= min_difficulty]
        if max_difficulty is not None:
            candidates = [question for question in candidates if question.difficulty <= max_difficulty]
        if not candidates:
            candidates = self._essay_pool
        if not candidates:
            raise QuestionDatabaseError("Tidak ada soal essay yang tersedia di questions.json")
        return random.choice(candidates)


class QuestionCacheRepository:
    def __init__(self, cache_path: Path, cache_duration_seconds: int):
        self._cache_path = cache_path
        self._cache_duration_seconds = cache_duration_seconds

    def load_fresh_pool(self) -> List[MultipleChoiceQuestion]:
        if not self._cache_path.exists():
            return []
        try:
            raw_text = self._cache_path.read_text(encoding="utf-8")
            raw_data = json.loads(raw_text)
        except (json.JSONDecodeError, OSError):
            return []
        cached_at = raw_data.get("cached_at")
        questions_raw = raw_data.get("questions")
        if cached_at is None or not isinstance(questions_raw, list):
            return []
        if time.time() - float(cached_at) > self._cache_duration_seconds:
            return []
        parsed_pool: List[MultipleChoiceQuestion] = []
        for entry in questions_raw:
            try:
                parsed_pool.append(
                    MultipleChoiceQuestion(
                        id=str(entry["id"]),
                        subject=str(entry["subject"]),
                        difficulty=int(entry["difficulty"]),
                        question_text=str(entry["question"]),
                        options=[str(option) for option in entry["options"]],
                        answer_index=int(entry["answer_index"]),
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return parsed_pool

    def save_pool(self, pool: List[MultipleChoiceQuestion]) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            "cached_at": time.time(),
            "questions": [
                {
                    "id": question.id,
                    "subject": question.subject,
                    "difficulty": question.difficulty,
                    "question": question.question_text,
                    "options": question.options,
                    "answer_index": question.answer_index,
                }
                for question in pool
            ],
        }
        temporary_path = self._cache_path.with_suffix(".tmp")
        temporary_path.write_text(json.dumps(serializable, ensure_ascii=False), encoding="utf-8")
        temporary_path.replace(self._cache_path)

    def clear(self) -> None:
        if self._cache_path.exists():
            try:
                self._cache_path.unlink()
            except OSError:
                pass


class OpenTriviaDBClient:
    def __init__(self, api_config: Dict[str, Any]):
        self._base_url = api_config["base_url"]
        self._timeout_seconds = api_config["timeout"]
        self._max_retries = api_config["max_retries"]
        self._max_calls_per_minute = api_config["max_calls_per_minute"]
        self._call_timestamps: Deque[float] = deque()

    def _is_call_allowed(self) -> bool:
        now = time.time()
        while self._call_timestamps and now - self._call_timestamps[0] > 60.0:
            self._call_timestamps.popleft()
        if len(self._call_timestamps) >= self._max_calls_per_minute:
            return False
        self._call_timestamps.append(now)
        return True

    def fetch_multiple_choice_questions(
        self, amount: int, preferred_difficulty: Optional[int] = None
    ) -> Optional[List[MultipleChoiceQuestion]]:
        if not self._is_call_allowed():
            return None
        query_params: Dict[str, Any] = {"amount": amount, "type": "multiple"}
        if preferred_difficulty is not None and preferred_difficulty in INTERNAL_DIFFICULTY_TO_API:
            query_params["difficulty"] = INTERNAL_DIFFICULTY_TO_API[preferred_difficulty]
        request_url = f"{self._base_url}?{urllib.parse.urlencode(query_params)}"
        last_error: Optional[Exception] = None
        for _ in range(self._max_retries):
            try:
                request = urllib.request.Request(request_url, headers={"User-Agent": "Game_guak/1.0"})
                with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                    response_body = response.read().decode("utf-8")
                parsed_response = json.loads(response_body)
                if parsed_response.get("response_code") != 0:
                    return None
                results = parsed_response.get("results")
                if not results:
                    return None
                return [self._map_api_entry_to_question(index, entry) for index, entry in enumerate(results)]
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, KeyError) as error:
                last_error = error
                continue
        return None

    def _map_api_entry_to_question(self, index: int, entry: Dict[str, Any]) -> MultipleChoiceQuestion:
        category = html.unescape(str(entry["category"]))
        difficulty_text = str(entry["difficulty"])
        difficulty = API_DIFFICULTY_TO_INTERNAL.get(difficulty_text, 2)
        question_text = html.unescape(str(entry["question"]))
        correct_answer = html.unescape(str(entry["correct_answer"]))
        incorrect_answers = [html.unescape(str(answer)) for answer in entry["incorrect_answers"]]
        options = incorrect_answers + [correct_answer]
        random.shuffle(options)
        answer_index = options.index(correct_answer)
        return MultipleChoiceQuestion(
            id=f"api_{int(time.time() * 1000)}_{index}",
            subject=category,
            difficulty=difficulty,
            question_text=question_text,
            options=options,
            answer_index=answer_index,
        )


class QuestionManager:
    def __init__(
        self,
        local_repository: LocalQuestionRepository,
        cache_repository: QuestionCacheRepository,
        api_client: OpenTriviaDBClient,
        api_fetch_amount: int = 10,
    ):
        self._local_repository = local_repository
        self._cache_repository = cache_repository
        self._api_client = api_client
        self._api_fetch_amount = api_fetch_amount
        self._active_pool: List[MultipleChoiceQuestion] = []

    def get_multiple_choice_question(self, preferred_difficulty: Optional[int] = None) -> MultipleChoiceQuestion:
        if not self._active_pool:
            self._active_pool = self._cache_repository.load_fresh_pool()
        if not self._active_pool:
            fetched_pool = self._api_client.fetch_multiple_choice_questions(
                self._api_fetch_amount, preferred_difficulty
            )
            if fetched_pool:
                self._active_pool = fetched_pool
                self._cache_repository.save_pool(fetched_pool)
        if self._active_pool:
            return self._active_pool.pop(0)
        return self._local_repository.get_random_mc_question()

    def get_essay_question(
        self, min_difficulty: Optional[int] = None, max_difficulty: Optional[int] = None
    ) -> EssayQuestion:
        return self._local_repository.get_random_essay_question(min_difficulty, max_difficulty)

    def clear_cache_on_exit(self) -> None:
        self._cache_repository.clear()


def create_save_data_repository() -> SaveDataRepository:
    return SaveDataRepository(settings.SAVE_DATA_FILE, settings.SAVE_DATA_BACKUP_FILE)


def create_achievement_evaluator() -> AchievementEvaluator:
    repository = AchievementRepository(settings.ACHIEVEMENTS_FILE)
    return AchievementEvaluator(repository)


def create_question_manager() -> QuestionManager:
    local_repository = LocalQuestionRepository(settings.QUESTIONS_FILE)
    cache_repository = QuestionCacheRepository(
        settings.CACHE_QUESTIONS_FILE, settings.API_CONFIG["cache_duration"]
    )
    api_client = OpenTriviaDBClient(settings.API_CONFIG)
    return QuestionManager(local_repository, cache_repository, api_client)