from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple

from src import settings


class Element(Enum):
    FIRE = "fire"
    ICE = "ice"

    def opposite(self) -> "Element":
        return Element.ICE if self is Element.FIRE else Element.FIRE


class ActionType(Enum):
    ATTACK = auto()
    SKILL = auto()
    ULTIMATE = auto()
    POTION_HEAL = auto()
    ELEMENT_SWAP = auto()


class QuizType(Enum):
    MULTIPLE_CHOICE = "mc"
    ESSAY = "essay"


class ActionOutcome(Enum):
    HIT = auto()
    MISS = auto()
    NO_QUIZ = auto()


class BattleResult(Enum):
    ONGOING = auto()
    VICTORY = auto()
    DEFEAT = auto()


class BattleState(Enum):
    WAIT_COMMAND = auto()
    QUIZ = auto()
    RESOLVE_ANIM = auto()
    NEXT_TURN = auto()
    ENEMY_TURN = auto()
    VICTORY = auto()
    DEFEAT = auto()


class Actor(Enum):
    HERO = auto()
    ENEMY = auto()


class EnemyActionKind(Enum):
    NORMAL_ATTACK = auto()
    STRONG_ATTACK = auto()
    DISRUPT = auto()
    BOSS_DOUBLE_NORMAL = auto()
    BOSS_STRONG_AND_NORMAL = auto()


def requires_quiz(action_type: ActionType) -> bool:
    return action_type in (ActionType.ATTACK, ActionType.SKILL, ActionType.ULTIMATE)


@dataclass
class ElementalMark:
    element: Element
    remaining_hero_turns: int
    applied_on_turn: int


@dataclass
class CombatStats:
    max_hp: int
    hp: int
    atk: int
    def_: int
    spd: int

    def is_alive(self) -> bool:
        return self.hp > 0

    def apply_damage(self, amount: int) -> int:
        actual = min(self.hp, max(0, amount))
        self.hp -= actual
        return actual

    def heal(self, amount: int) -> int:
        missing = self.max_hp - self.hp
        actual = min(missing, max(0, amount))
        self.hp += actual
        return actual

    def hp_percent(self) -> float:
        if self.max_hp <= 0:
            return 0.0
        return self.hp / self.max_hp


@dataclass
class GuakState:
    stats: CombatStats
    element: Element
    action_points: int = settings.ACTION_POINT_START
    momentum_stack: int = 0
    next_attack_bonus_active: bool = False
    cleared_level_ids: set = field(default_factory=set)

    def apply_first_clear_growth_if_needed(self, level_id: int) -> bool:
        if level_id in self.cleared_level_ids:
            return False
        self.cleared_level_ids.add(level_id)
        self.stats.max_hp += settings.HERO_LEVEL_CLEAR_HP_GROWTH
        self.stats.hp += settings.HERO_LEVEL_CLEAR_HP_GROWTH
        self.stats.atk += settings.HERO_LEVEL_CLEAR_ATK_GROWTH
        self.stats.def_ += settings.HERO_LEVEL_CLEAR_DEF_GROWTH
        return True

    def reset_for_new_battle(self) -> None:
        self.action_points = settings.ACTION_POINT_START
        self.momentum_stack = 0
        self.next_attack_bonus_active = False


@dataclass
class EnemyState:
    enemy_id: str
    stats: CombatStats
    mark: Optional[ElementalMark] = None
    turn_count: int = 0

    def is_melt_triggered_by(self, element: Element) -> bool:
        return self.mark is not None and self.mark.element is not element

    def set_or_refresh_mark(self, element: Element, current_hero_turn_index: int) -> None:
        if self.mark is not None and self.mark.element is element:
            self.mark.remaining_hero_turns = settings.MARK_DURATION_HERO_TURNS
            self.mark.applied_on_turn = current_hero_turn_index
        else:
            self.mark = ElementalMark(
                element=element,
                remaining_hero_turns=settings.MARK_DURATION_HERO_TURNS,
                applied_on_turn=current_hero_turn_index,
            )

    def clear_mark(self) -> None:
        self.mark = None

    def tick_mark(self, current_hero_turn_index: int) -> None:
        if self.mark is None:
            return
        if self.mark.applied_on_turn == current_hero_turn_index:
            return
        self.mark.remaining_hero_turns -= 1
        if self.mark.remaining_hero_turns <= 0:
            self.mark = None


@dataclass
class PotionInventory:
    count: int

    def can_use(self) -> bool:
        return self.count > 0

    def consume_one(self) -> None:
        if self.count <= 0:
            raise RuntimeError("inventory potion kosong")
        self.count -= 1

    def add(self, amount: int) -> int:
        before = self.count
        self.count = min(settings.POTION_INVENTORY_MAX, self.count + amount)
        return self.count - before


class DamageCalculator:
    @staticmethod
    def compute_single_hit(attack_power: float, defense: int, multiplier: float, melt_active: bool) -> int:
        denominator = attack_power + defense
        mitigation = attack_power / denominator if denominator > 0 else 0.0
        raw_damage = (attack_power * multiplier) * mitigation
        if melt_active:
            raw_damage *= settings.MELT_DAMAGE_MULTIPLIER
        return max(1, math.floor(raw_damage))

    @staticmethod
    def compute_hero_effective_attack(base_atk: int, momentum_stack: int, swap_bonus_active: bool) -> float:
        momentum_multiplier = 1.0 + settings.MOMENTUM_ATK_BONUS_PER_STACK * momentum_stack
        swap_multiplier = 1.0 + settings.ELEMENT_SWAP_NEXT_ATTACK_BONUS if swap_bonus_active else 1.0
        return base_atk * momentum_multiplier * swap_multiplier

    @staticmethod
    def distribute_ultimate_damage(total_damage: int, hit_count: int) -> List[int]:
        if hit_count <= 0:
            return []
        base_amount = total_damage // hit_count
        remainder = total_damage % hit_count
        hits = [base_amount] * hit_count
        for index in range(remainder):
            hits[hit_count - 1 - index] += 1
        return hits


class EssayAnswerValidator:
    _PUNCTUATION_PATTERN = re.compile(r"[^\w\s]", re.UNICODE)
    _WHITESPACE_PATTERN = re.compile(r"\s+")

    @staticmethod
    def normalize(text: str) -> str:
        lowered = text.lower()
        without_punctuation = EssayAnswerValidator._PUNCTUATION_PATTERN.sub(" ", lowered)
        collapsed = EssayAnswerValidator._WHITESPACE_PATTERN.sub(" ", without_punctuation)
        return collapsed.strip()

    @staticmethod
    def validate(answer_text: str, keyword_groups: List[List[str]], min_group_ratio: float) -> bool:
        if not keyword_groups:
            return False
        normalized_answer = EssayAnswerValidator.normalize(answer_text)
        satisfied_groups = 0
        for group in keyword_groups:
            for synonym in group:
                normalized_synonym = EssayAnswerValidator.normalize(synonym)
                if normalized_synonym and normalized_synonym in normalized_answer:
                    satisfied_groups += 1
                    break
        required_groups = math.ceil(min_group_ratio * len(keyword_groups))
        return satisfied_groups >= required_groups


class ScoreCalculator:
    @staticmethod
    def compute(correct_answers: int, fast_answers: int, hp_percent_remaining: float) -> int:
        return (
            correct_answers * settings.SCORE_POINTS_PER_CORRECT_ANSWER
            + fast_answers * settings.SCORE_POINTS_PER_FAST_ANSWER
            + math.floor(hp_percent_remaining * settings.SCORE_POINTS_PER_HP_PERCENT_REMAINING)
        )


class TimelineScheduler:
    def __init__(self, hero_spd: int, enemy_spd: int):
        self.hero_next_av = settings.ACTION_VALUE_BASE_UNIT / hero_spd
        self.enemy_next_av = settings.ACTION_VALUE_BASE_UNIT / enemy_spd

    def current_actor(self) -> Actor:
        return Actor.HERO if self.hero_next_av <= self.enemy_next_av else Actor.ENEMY

    def advance_hero(self, hero_spd: int, action_delay: float) -> None:
        self.hero_next_av += settings.ACTION_VALUE_BASE_UNIT / hero_spd + action_delay

    def advance_enemy(self, enemy_spd: int, action_delay: float) -> None:
        self.enemy_next_av += settings.ACTION_VALUE_BASE_UNIT / enemy_spd + action_delay

    def apply_enemy_delay_bonus(self, bonus: float) -> None:
        self.enemy_next_av += bonus

    def apply_hero_delay_bonus(self, bonus: float) -> None:
        self.hero_next_av += bonus


@dataclass
class LevelConfig:
    level_id: int
    name: str
    enemy_id: str
    enemy_stats: CombatStats
    enemy_ai_type: str
    enemy_ai_params: Dict[str, Any]
    enemy_has_aura: bool
    quiz_rules: Dict[ActionType, QuizType]
    time_limit_mc: Optional[float]
    time_limit_essay: Optional[float]
    essay_min_keyword_group_ratio: Optional[float]
    first_clear_potion_reward: int
    first_clear_title: Optional[str]

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "LevelConfig":
        quiz_rules_raw = data["quiz_rules"]
        quiz_rules = {
            ActionType.ATTACK: QuizType(quiz_rules_raw["attack"]["type"]),
            ActionType.SKILL: QuizType(quiz_rules_raw["skill"]["type"]),
            ActionType.ULTIMATE: QuizType(quiz_rules_raw["ultimate"]["type"]),
        }
        enemy_stats_raw = data["enemy_stats"]
        enemy_stats = CombatStats(
            max_hp=enemy_stats_raw["hp"],
            hp=enemy_stats_raw["hp"],
            atk=enemy_stats_raw["atk"],
            def_=enemy_stats_raw["def"],
            spd=enemy_stats_raw["spd"],
        )
        essay_validation = data.get("essay_validation")
        time_limits = data["time_limit_seconds"]
        reward = data["first_clear_reward"]
        return LevelConfig(
            level_id=data["level_id"],
            name=data["name"],
            enemy_id=data["enemy_id"],
            enemy_stats=enemy_stats,
            enemy_ai_type=data["enemy_ai_type"],
            enemy_ai_params=data["enemy_ai_params"],
            enemy_has_aura=data["enemy_has_aura"],
            quiz_rules=quiz_rules,
            time_limit_mc=time_limits["mc"],
            time_limit_essay=time_limits["essay"],
            essay_min_keyword_group_ratio=(
                essay_validation["min_keyword_group_ratio"] if essay_validation else None
            ),
            first_clear_potion_reward=reward["potion_heal"],
            first_clear_title=reward["title"],
        )


@dataclass
class EnemyActionDecision:
    kind: EnemyActionKind
    multipliers: Tuple[float, ...]
    action_delay: float
    disrupt_av_bonus: Optional[float]


class EnemyAIStrategy(ABC):
    @abstractmethod
    def decide(self, hero: GuakState, enemy: EnemyState) -> EnemyActionDecision:
        raise NotImplementedError


class StaticBasicAI(EnemyAIStrategy):
    def decide(self, hero: GuakState, enemy: EnemyState) -> EnemyActionDecision:
        return EnemyActionDecision(
            kind=EnemyActionKind.NORMAL_ATTACK,
            multipliers=(1.0,),
            action_delay=0.0,
            disrupt_av_bonus=None,
        )


class ReactivePriorityAI(EnemyAIStrategy):
    def __init__(self, params: Dict[str, Any]):
        self.hp_threshold_strong_attack = params["hp_threshold_strong_attack"]
        self.strong_attack_multiplier = params["strong_attack_multiplier"]
        self.strong_attack_delay = params["strong_attack_delay"]
        self.ap_threshold_disrupt = params["ap_threshold_disrupt"]
        self.disrupt_next_av_bonus = params["disrupt_next_av_bonus"]
        self.normal_attack_multiplier = params["normal_attack_multiplier"]

    def decide(self, hero: GuakState, enemy: EnemyState) -> EnemyActionDecision:
        if hero.stats.hp_percent() < self.hp_threshold_strong_attack:
            return EnemyActionDecision(
                kind=EnemyActionKind.STRONG_ATTACK,
                multipliers=(self.strong_attack_multiplier,),
                action_delay=self.strong_attack_delay,
                disrupt_av_bonus=None,
            )
        if hero.action_points >= self.ap_threshold_disrupt:
            return EnemyActionDecision(
                kind=EnemyActionKind.DISRUPT,
                multipliers=(),
                action_delay=0.0,
                disrupt_av_bonus=self.disrupt_next_av_bonus,
            )
        return EnemyActionDecision(
            kind=EnemyActionKind.NORMAL_ATTACK,
            multipliers=(self.normal_attack_multiplier,),
            action_delay=0.0,
            disrupt_av_bonus=None,
        )


class BossPatternAI(EnemyAIStrategy):
    def __init__(self, params: Dict[str, Any]):
        self.normal_turn_attack_multiplier = params["normal_turn_attack_multiplier"]
        self.normal_turn_attack_count = params["normal_turn_attack_count"]
        self.strong_turn_interval = params["strong_turn_interval"]
        self.strong_turn_strong_attack_multiplier = params["strong_turn_strong_attack_multiplier"]
        self.strong_turn_normal_attack_multiplier = params["strong_turn_normal_attack_multiplier"]

    def decide(self, hero: GuakState, enemy: EnemyState) -> EnemyActionDecision:
        current_turn_number = enemy.turn_count + 1
        if current_turn_number % self.strong_turn_interval == 0:
            return EnemyActionDecision(
                kind=EnemyActionKind.BOSS_STRONG_AND_NORMAL,
                multipliers=(
                    self.strong_turn_strong_attack_multiplier,
                    self.strong_turn_normal_attack_multiplier,
                ),
                action_delay=0.0,
                disrupt_av_bonus=None,
            )
        multipliers = tuple(
            self.normal_turn_attack_multiplier for _ in range(self.normal_turn_attack_count)
        )
        return EnemyActionDecision(
            kind=EnemyActionKind.BOSS_DOUBLE_NORMAL,
            multipliers=multipliers,
            action_delay=0.0,
            disrupt_av_bonus=None,
        )


def create_ai_strategy(ai_type: str, ai_params: Dict[str, Any]) -> EnemyAIStrategy:
    if ai_type == "static_basic":
        return StaticBasicAI()
    if ai_type == "reactive_priority":
        return ReactivePriorityAI(ai_params)
    if ai_type == "boss_pattern":
        return BossPatternAI(ai_params)
    raise ValueError(f"enemy_ai_type tidak dikenal: {ai_type}")


@dataclass
class ActionResolution:
    actor: Actor
    action_type: Optional[ActionType]
    outcome: ActionOutcome
    damage_dealt: List[int]
    melt_triggered: bool
    healed_amount: int
    enemy_delay_bonus_applied: float
    hero_ap_after: int
    hero_momentum_after: int
    hero_hp_after: int
    enemy_hp_after: int
    battle_result: BattleResult


class BattleEngine:
    def __init__(self, hero: GuakState, level_config: LevelConfig, inventory: PotionInventory):
        self.hero = hero
        self.level_config = level_config
        self.enemy = EnemyState(enemy_id=level_config.enemy_id, stats=level_config.enemy_stats)
        self.inventory = inventory
        self._initial_potion_count = inventory.count
        self.timeline = TimelineScheduler(hero.stats.spd, self.enemy.stats.spd)
        self.ai = create_ai_strategy(level_config.enemy_ai_type, level_config.enemy_ai_params)
        self.aura_hero_next_av_bonus = (
            float(level_config.enemy_ai_params.get("aura_hero_next_av_bonus_per_turn", 0.0))
            if level_config.enemy_has_aura
            else 0.0
        )
        self.hero_turn_index = 0
        self.correct_answer_count = 0
        self.fast_answer_count = 0
        self.pending_action: Optional[ActionType] = None
        self.swap_used_this_turn = False
        self.accumulated_turn_delay = 0.0
        self.hero.reset_for_new_battle()
        initial_actor = self.timeline.current_actor()
        if initial_actor is Actor.HERO:
            self.begin_hero_turn()
        else:
            self.state = BattleState.ENEMY_TURN

    def begin_hero_turn(self) -> None:
        self.hero_turn_index += 1
        self.enemy.tick_mark(self.hero_turn_index)
        self.swap_used_this_turn = False
        self.accumulated_turn_delay = 0.0
        self.state = BattleState.WAIT_COMMAND

    def get_quiz_type(self, action_type: ActionType) -> QuizType:
        return self.level_config.quiz_rules[action_type]

    def get_time_limit_seconds(self, action_type: ActionType) -> Optional[float]:
        quiz_type = self.get_quiz_type(action_type)
        if quiz_type is QuizType.MULTIPLE_CHOICE:
            return self.level_config.time_limit_mc
        return self.level_config.time_limit_essay

    def can_perform_attack(self) -> bool:
        return self.state is BattleState.WAIT_COMMAND

    def can_perform_skill(self) -> bool:
        return self.state is BattleState.WAIT_COMMAND and self.hero.action_points >= settings.SKILL_AP_COST

    def can_perform_ultimate(self) -> bool:
        return self.state is BattleState.WAIT_COMMAND and self.hero.action_points >= settings.ULTIMATE_AP_COST

    def can_perform_element_swap(self) -> bool:
        return (
            self.state is BattleState.WAIT_COMMAND
            and not self.swap_used_this_turn
            and self.hero.action_points >= settings.ELEMENT_SWAP_AP_COST
        )

    def can_perform_potion_heal(self) -> bool:
        return self.state is BattleState.WAIT_COMMAND and self.inventory.can_use()

    def begin_action(self, action_type: ActionType) -> None:
        if self.state is not BattleState.WAIT_COMMAND:
            raise RuntimeError("begin_action hanya valid saat WAIT_COMMAND")
        if action_type is ActionType.ATTACK:
            if not self.can_perform_attack():
                raise RuntimeError("Serang tidak dapat dilakukan saat ini")
        elif action_type is ActionType.SKILL:
            if not self.can_perform_skill():
                raise RuntimeError("Skill tidak dapat dilakukan saat ini")
            self.hero.action_points -= settings.SKILL_AP_COST
        elif action_type is ActionType.ULTIMATE:
            if not self.can_perform_ultimate():
                raise RuntimeError("Ultimate tidak dapat dilakukan saat ini")
            self.hero.action_points -= settings.ULTIMATE_AP_COST
        else:
            raise ValueError("action_type tidak valid untuk begin_action")
        self.pending_action = action_type
        self.state = BattleState.QUIZ

    def submit_quiz_result(
        self,
        action_type: ActionType,
        is_correct: bool,
        elapsed_seconds: Optional[float] = None,
    ) -> ActionResolution:
        if self.state is not BattleState.QUIZ:
            raise RuntimeError("submit_quiz_result dipanggil di luar state QUIZ")
        if not requires_quiz(action_type):
            raise ValueError("action_type tidak memerlukan quiz")

        swap_bonus_consumed = self.hero.next_attack_bonus_active
        self.hero.next_attack_bonus_active = False

        if is_correct:
            self.hero.momentum_stack = min(settings.MOMENTUM_MAX_STACK, self.hero.momentum_stack + 1)
            self.correct_answer_count += 1
            if elapsed_seconds is not None and elapsed_seconds < settings.SCORE_FAST_ANSWER_THRESHOLD_SECONDS:
                self.fast_answer_count += 1
        else:
            self.hero.momentum_stack = 0

        if action_type is ActionType.ATTACK and is_correct:
            self.hero.action_points = min(
                settings.ACTION_POINT_MAX,
                self.hero.action_points + settings.ACTION_POINT_GAIN_ON_CORRECT_ATTACK,
            )

        base_delay = self._base_action_delay(action_type)
        total_delay = base_delay + self.accumulated_turn_delay

        if not is_correct:
            resolution = ActionResolution(
                actor=Actor.HERO,
                action_type=action_type,
                outcome=ActionOutcome.MISS,
                damage_dealt=[],
                melt_triggered=False,
                healed_amount=0,
                enemy_delay_bonus_applied=0.0,
                hero_ap_after=self.hero.action_points,
                hero_momentum_after=self.hero.momentum_stack,
                hero_hp_after=self.hero.stats.hp,
                enemy_hp_after=self.enemy.stats.hp,
                battle_result=self._evaluate_battle_result(),
            )
            self._finalize_hero_action(total_delay)
            return resolution

        skill_multiplier = self._skill_multiplier(action_type, self.hero.element)
        effective_atk = DamageCalculator.compute_hero_effective_attack(
            self.hero.stats.atk, self.hero.momentum_stack, swap_bonus_consumed
        )
        melt_triggered = self.enemy.is_melt_triggered_by(self.hero.element)

        if action_type is ActionType.ULTIMATE:
            total_damage = DamageCalculator.compute_single_hit(
                effective_atk, self.enemy.stats.def_, skill_multiplier, melt_triggered
            )
            hit_count = settings.ULTIMATE_LOOPS * len(settings.SPRITE_IMPACT_FRAME_INDICES_DEFAULT)
            damage_list = DamageCalculator.distribute_ultimate_damage(total_damage, hit_count)
        else:
            damage_list = [
                DamageCalculator.compute_single_hit(
                    effective_atk, self.enemy.stats.def_, skill_multiplier, melt_triggered
                )
            ]

        for amount in damage_list:
            self.enemy.stats.apply_damage(amount)

        if melt_triggered:
            self.enemy.clear_mark()
        else:
            self.enemy.set_or_refresh_mark(self.hero.element, self.hero_turn_index)

        enemy_delay_bonus = 0.0
        if self.hero.element is Element.ICE and action_type in (ActionType.SKILL, ActionType.ULTIMATE):
            enemy_delay_bonus = self._ice_enemy_delay_bonus(action_type)
            self.timeline.apply_enemy_delay_bonus(enemy_delay_bonus)

        resolution = ActionResolution(
            actor=Actor.HERO,
            action_type=action_type,
            outcome=ActionOutcome.HIT,
            damage_dealt=damage_list,
            melt_triggered=melt_triggered,
            healed_amount=0,
            enemy_delay_bonus_applied=enemy_delay_bonus,
            hero_ap_after=self.hero.action_points,
            hero_momentum_after=self.hero.momentum_stack,
            hero_hp_after=self.hero.stats.hp,
            enemy_hp_after=self.enemy.stats.hp,
            battle_result=self._evaluate_battle_result(),
        )
        self._finalize_hero_action(total_delay)
        return resolution

    def perform_element_swap(self) -> ActionResolution:
        if not self.can_perform_element_swap():
            raise RuntimeError("Ganti Elemen tidak dapat dilakukan saat ini")
        self.hero.action_points -= settings.ELEMENT_SWAP_AP_COST
        self.hero.element = self.hero.element.opposite()
        self.hero.next_attack_bonus_active = True
        self.swap_used_this_turn = True
        self.accumulated_turn_delay += settings.ELEMENT_SWAP_ACTION_DELAY
        return ActionResolution(
            actor=Actor.HERO,
            action_type=ActionType.ELEMENT_SWAP,
            outcome=ActionOutcome.NO_QUIZ,
            damage_dealt=[],
            melt_triggered=False,
            healed_amount=0,
            enemy_delay_bonus_applied=0.0,
            hero_ap_after=self.hero.action_points,
            hero_momentum_after=self.hero.momentum_stack,
            hero_hp_after=self.hero.stats.hp,
            enemy_hp_after=self.enemy.stats.hp,
            battle_result=BattleResult.ONGOING,
        )

    def perform_potion_heal(self) -> ActionResolution:
        if not self.can_perform_potion_heal():
            raise RuntimeError("Potion Heal tidak dapat dilakukan saat ini")
        self.inventory.consume_one()
        heal_amount = math.floor(self.hero.stats.max_hp * settings.POTION_HEAL_PERCENT_OF_MAX_HP)
        actual_healed = self.hero.stats.heal(heal_amount)
        total_delay = settings.POTION_HEAL_ACTION_DELAY + self.accumulated_turn_delay
        resolution = ActionResolution(
            actor=Actor.HERO,
            action_type=ActionType.POTION_HEAL,
            outcome=ActionOutcome.NO_QUIZ,
            damage_dealt=[],
            melt_triggered=False,
            healed_amount=actual_healed,
            enemy_delay_bonus_applied=0.0,
            hero_ap_after=self.hero.action_points,
            hero_momentum_after=self.hero.momentum_stack,
            hero_hp_after=self.hero.stats.hp,
            enemy_hp_after=self.enemy.stats.hp,
            battle_result=self._evaluate_battle_result(),
        )
        self._finalize_hero_action(total_delay)
        return resolution

    def run_enemy_turn(self) -> ActionResolution:
        if self.state is not BattleState.ENEMY_TURN:
            raise RuntimeError("run_enemy_turn dipanggil di luar state ENEMY_TURN")
        decision = self.ai.decide(self.hero, self.enemy)
        damage_list: List[int] = []
        disrupt_bonus_applied = 0.0

        if decision.kind is EnemyActionKind.DISRUPT:
            disrupt_bonus_applied = decision.disrupt_av_bonus or 0.0
            self.timeline.apply_hero_delay_bonus(disrupt_bonus_applied)
        else:
            for multiplier in decision.multipliers:
                amount = DamageCalculator.compute_single_hit(
                    float(self.enemy.stats.atk), self.hero.stats.def_, multiplier, False
                )
                damage_list.append(amount)
                self.hero.stats.apply_damage(amount)

        self.enemy.turn_count += 1
        self.timeline.advance_enemy(self.enemy.stats.spd, decision.action_delay)
        self.state = BattleState.RESOLVE_ANIM

        return ActionResolution(
            actor=Actor.ENEMY,
            action_type=None,
            outcome=ActionOutcome.NO_QUIZ,
            damage_dealt=damage_list,
            melt_triggered=False,
            healed_amount=0,
            enemy_delay_bonus_applied=disrupt_bonus_applied,
            hero_ap_after=self.hero.action_points,
            hero_momentum_after=self.hero.momentum_stack,
            hero_hp_after=self.hero.stats.hp,
            enemy_hp_after=self.enemy.stats.hp,
            battle_result=self._evaluate_battle_result(),
        )

    def complete_resolve_animation(self) -> BattleState:
        if self.state is not BattleState.RESOLVE_ANIM:
            raise RuntimeError("complete_resolve_animation hanya valid saat RESOLVE_ANIM")
        battle_result = self._evaluate_battle_result()
        if battle_result is BattleResult.VICTORY:
            self.state = BattleState.VICTORY
        elif battle_result is BattleResult.DEFEAT:
            self.state = BattleState.DEFEAT
        else:
            self.state = BattleState.NEXT_TURN
        return self.state

    def resolve_next_turn(self) -> BattleState:
        if self.state is not BattleState.NEXT_TURN:
            raise RuntimeError("resolve_next_turn hanya valid saat NEXT_TURN")
        next_actor = self.timeline.current_actor()
        if next_actor is Actor.HERO:
            self.begin_hero_turn()
        else:
            self.state = BattleState.ENEMY_TURN
        return self.state

    def compute_current_score(self) -> int:
        return ScoreCalculator.compute(
            self.correct_answer_count,
            self.fast_answer_count,
            self.hero.stats.hp_percent() * 100.0,
        )

    def restore_inventory_on_defeat(self) -> None:
        self.inventory.count = self._initial_potion_count

    def finalize_victory_rewards(self) -> Dict[str, Any]:
        if self.state is not BattleState.VICTORY:
            raise RuntimeError("finalize_victory_rewards hanya valid saat VICTORY")
        is_first_clear = self.hero.apply_first_clear_growth_if_needed(self.level_config.level_id)
        potion_awarded = 0
        title_awarded: Optional[str] = None
        if is_first_clear:
            potion_awarded = self.inventory.add(self.level_config.first_clear_potion_reward)
            title_awarded = self.level_config.first_clear_title
        return {
            "is_first_clear": is_first_clear,
            "potion_awarded": potion_awarded,
            "title_awarded": title_awarded,
            "score": self.compute_current_score(),
        }

    def _base_action_delay(self, action_type: ActionType) -> float:
        if action_type is ActionType.ATTACK:
            return settings.ATTACK_ACTION_DELAY
        if action_type is ActionType.SKILL:
            return settings.SKILL_ACTION_DELAY
        if action_type is ActionType.ULTIMATE:
            return settings.ULTIMATE_ACTION_DELAY
        raise ValueError("action_type tidak memiliki action_delay dasar")

    def _skill_multiplier(self, action_type: ActionType, element: Element) -> float:
        if action_type is ActionType.ATTACK:
            return settings.ATTACK_MULTIPLIER_FIRE if element is Element.FIRE else settings.ATTACK_MULTIPLIER_ICE
        if action_type is ActionType.SKILL:
            return settings.SKILL_MULTIPLIER_FIRE if element is Element.FIRE else settings.SKILL_MULTIPLIER_ICE
        if action_type is ActionType.ULTIMATE:
            return (
                settings.ULTIMATE_MULTIPLIER_FIRE if element is Element.FIRE else settings.ULTIMATE_MULTIPLIER_ICE
            )
        raise ValueError("action_type tidak memiliki skill_multiplier")

    def _ice_enemy_delay_bonus(self, action_type: ActionType) -> float:
        if action_type is ActionType.SKILL:
            return settings.SKILL_ICE_ENEMY_DELAY_BONUS
        if action_type is ActionType.ULTIMATE:
            return settings.ULTIMATE_ICE_ENEMY_DELAY_BONUS
        return 0.0

    def _finalize_hero_action(self, total_delay: float) -> None:
        self.timeline.advance_hero(self.hero.stats.spd, total_delay)
        if self.aura_hero_next_av_bonus:
            self.timeline.apply_hero_delay_bonus(self.aura_hero_next_av_bonus)
        self.pending_action = None
        self.state = BattleState.RESOLVE_ANIM

    def _evaluate_battle_result(self) -> BattleResult:
        if not self.hero.stats.is_alive():
            return BattleResult.DEFEAT
        if not self.enemy.stats.is_alive():
            return BattleResult.VICTORY
        return BattleResult.ONGOING