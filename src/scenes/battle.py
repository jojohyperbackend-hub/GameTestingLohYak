from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, List, Optional, Set, Tuple

import pygame

from src import settings
from src.animation import (
    Tween,
    ease_in_out_quad,
    ease_in_quad,
    ease_out_back,
    ease_out_cubic,
    ParticlePool,
    Particle,
    TimeScaleController,
    SpriteAnimator,
    create_sprite_config_repository,
    create_static_sprite_loader,
    create_sprite_animator,
    compute_idle_bob_offset,
)
from src.audio.settingan_music import SfxManager, create_sfx_manager
from src.data_manager import (
    AchievementEvaluator,
    EssayQuestion,
    MultipleChoiceQuestion,
    QuestionManager,
    SaveData,
    SaveDataRepository,
    create_achievement_evaluator,
    create_question_manager,
    create_save_data_repository,
)
from src.hp_settingan import WindowDisplayManager, create_window_display_manager
from src.logic import (
    ActionOutcome,
    ActionResolution,
    ActionType,
    Actor,
    BattleEngine,
    BattleResult,
    BattleState,
    CombatStats,
    Element,
    GuakState,
    LevelConfig,
    PotionInventory,
    QuizType,
)
from src.main_layout_game_screen.settingan_layer import (
    ArenaZoomController,
    LayoutRegions,
    create_arena_zoom_controller,
    create_default_layout_regions,
)
from src.pov.camera import Camera2_5D, create_camera
from src.scene_manager import Scene, SceneManager, SceneType
from src.scenes.quiz_popup import QuizOutcome, open_essay_quiz, open_multiple_choice_quiz


class BattleSceneError(Exception):
    pass


_shared_display_manager: Optional[WindowDisplayManager] = None
_shared_sfx_manager: Optional[SfxManager] = None


def get_shared_display_manager() -> WindowDisplayManager:
    global _shared_display_manager
    if _shared_display_manager is None:
        _shared_display_manager = create_window_display_manager()
    return _shared_display_manager


def get_shared_sfx_manager() -> SfxManager:
    global _shared_sfx_manager
    if _shared_sfx_manager is None:
        _shared_sfx_manager = create_sfx_manager()
    return _shared_sfx_manager


def load_level_config(level_id: int) -> LevelConfig:
    if not settings.LEVELS_FILE.exists():
        raise BattleSceneError("File levels.json tidak ditemukan")
    try:
        raw_data = json.loads(settings.LEVELS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise BattleSceneError(f"levels.json rusak: {error}") from error
    for entry in raw_data.get("levels", []):
        if entry.get("level_id") == level_id:
            return LevelConfig.from_dict(entry)
    raise BattleSceneError(f"Level {level_id} tidak ditemukan di levels.json")


SPRITE_DISPLAY_TARGET_HEIGHT_PX: int = settings.SPRITE_FRAME_HEIGHT * settings.SPRITE_SCALE
HP_BAR_WIDTH_PX: int = 160
HP_BAR_HEIGHT_PX: int = 14
COMMAND_BUTTON_WIDTH_PX: int = 56
COMMAND_BUTTON_HEIGHT_PX: int = 70
COMMAND_BUTTON_GAP_PX: int = 6
SLASH_FLASH_DURATION_SECONDS: float = settings.HIT_FLASH_DURATION_SECONDS


def load_pixel_font(size_px: int) -> pygame.font.Font:
    if settings.FONT_PIXEL_PATH.exists():
        try:
            return pygame.font.Font(str(settings.FONT_PIXEL_PATH), size_px)
        except pygame.error:
            pass
    return pygame.font.Font(None, size_px)


@dataclass
class DamageNumberPopup:
    text: str
    color: Tuple[int, int, int]
    world_x: float
    world_y: float
    tween: Tween
    alpha: float = 255.0

    def update(self, delta_time_seconds: float) -> None:
        self.tween.update(delta_time_seconds)
        progress = self.tween.current_values[0]
        if progress > 0.7:
            fade_ratio = (progress - 0.7) / 0.3
            self.alpha = max(0.0, 255.0 * (1.0 - fade_ratio))

    @property
    def is_finished(self) -> bool:
        return self.tween.is_finished

    def get_render_offset(self) -> Tuple[float, float]:
        progress = self.tween.current_values[0]
        rise = -settings.DAMAGE_NUMBER_RISE_DISTANCE * min(1.0, progress / 0.9)
        scale = 1.4 - 0.4 * min(1.0, progress / 0.2) if progress < 0.2 else 1.0
        return rise, scale


@dataclass
class ToastNotification:
    text: str
    tween: Tween

    def update(self, delta_time_seconds: float) -> None:
        self.tween.update(delta_time_seconds)

    @property
    def is_finished(self) -> bool:
        return self.tween.is_finished


class ChoreographyPhase(Enum):
    ANTICIPATION = auto()
    DASH_IN = auto()
    STRIKE = auto()
    DASH_OUT = auto()
    DONE = auto()


@dataclass
class ActionChoreography:
    attacker_is_hero: bool
    attacker_animation_name: str
    defender_reaction_animation_name: str
    is_miss: bool
    on_impact: Callable[[], None]
    on_finished: Callable[[], None]
    phase: ChoreographyPhase = ChoreographyPhase.ANTICIPATION
    phase_elapsed_seconds: float = 0.0
    attacker_offset_x: float = 0.0
    defender_offset_x: float = 0.0
    impact_fired: bool = False
    started_attack_animation: bool = False

    def update(self, delta_time_seconds: float) -> None:
        self.phase_elapsed_seconds += delta_time_seconds
        if self.phase == ChoreographyPhase.ANTICIPATION:
            ratio = min(1.0, self.phase_elapsed_seconds / settings.ANTICIPATION_DURATION_SECONDS)
            self.attacker_offset_x = -settings.ANTICIPATION_RECOIL_DISTANCE * ease_out_cubic(ratio)
            if ratio >= 1.0:
                self._advance_phase(ChoreographyPhase.DASH_IN)
        elif self.phase == ChoreographyPhase.DASH_IN:
            ratio = min(1.0, self.phase_elapsed_seconds / settings.DASH_IN_DURATION_SECONDS)
            eased = ease_in_quad(ratio)
            start_offset = -settings.ANTICIPATION_RECOIL_DISTANCE
            end_offset = settings.ATTACK_APPROACH_DISTANCE if self.attacker_is_hero else -settings.ATTACK_APPROACH_DISTANCE
            self.attacker_offset_x = start_offset + (end_offset - start_offset) * eased
            if ratio >= 1.0:
                self._advance_phase(ChoreographyPhase.STRIKE)
        elif self.phase == ChoreographyPhase.STRIKE:
            if not self.impact_fired and self.phase_elapsed_seconds >= 0.33:
                self.impact_fired = True
                self.on_impact()
            if self.phase_elapsed_seconds >= 0.75:
                self._advance_phase(ChoreographyPhase.DASH_OUT)
        elif self.phase == ChoreographyPhase.DASH_OUT:
            ratio = min(1.0, self.phase_elapsed_seconds / settings.DASH_OUT_DURATION_SECONDS)
            eased = ease_in_out_quad(ratio)
            start_offset = settings.ATTACK_APPROACH_DISTANCE if self.attacker_is_hero else -settings.ATTACK_APPROACH_DISTANCE
            self.attacker_offset_x = start_offset * (1.0 - eased)
            self.defender_offset_x *= 1.0 - eased
            if ratio >= 1.0:
                self.phase = ChoreographyPhase.DONE
                self.on_finished()

    def _advance_phase(self, next_phase: ChoreographyPhase) -> None:
        self.phase = next_phase
        self.phase_elapsed_seconds = 0.0

    @property
    def is_finished(self) -> bool:
        return self.phase == ChoreographyPhase.DONE


@dataclass
class CommandButtonDefinition:
    action_type: ActionType
    label: str
    rect: pygame.Rect


class BattleScene(Scene):
    def __init__(self, scene_manager: SceneManager, level_id: int):
        super().__init__(scene_manager)
        self._level_id = level_id
        self._level_config = load_level_config(level_id)
        self._save_repository: SaveDataRepository = create_save_data_repository()
        self._save_data: SaveData = self._save_repository.load()
        self._question_manager: QuestionManager = create_question_manager()
        self._achievement_evaluator: AchievementEvaluator = create_achievement_evaluator()

        hero_stats = CombatStats(
            max_hp=self._save_data.hero.max_hp,
            hp=self._save_data.hero.max_hp,
            atk=self._save_data.hero.atk,
            def_=self._save_data.hero.def_,
            spd=self._save_data.hero.spd,
        )
        hero_element = Element.FIRE if self._save_data.element == "fire" else Element.ICE
        hero_state = GuakState(
            stats=hero_stats,
            element=hero_element,
            cleared_level_ids=set(self._save_data.hero.cleared_level_ids),
        )
        self._pre_battle_inventory_count = self._save_data.inventory
        self._inventory = PotionInventory(count=self._save_data.inventory)
        self._engine = BattleEngine(hero_state, self._level_config, self._inventory)

        self._display_manager = get_shared_display_manager()
        self._sfx_manager = get_shared_sfx_manager()
        self._zoom_controller: ArenaZoomController = create_arena_zoom_controller()
        self._camera: Camera2_5D = create_camera(self._zoom_controller)
        self._layout_regions: LayoutRegions = create_default_layout_regions()

        sprite_repository = create_sprite_config_repository()
        sprite_loader = create_static_sprite_loader()
        self._hero_animator: SpriteAnimator = create_sprite_animator("hero", sprite_repository, sprite_loader)
        self._enemy_animator: SpriteAnimator = create_sprite_animator("enemy", sprite_repository, sprite_loader)
        self._hero_animator.play("idle")
        self._enemy_animator.play("idle")

        self._time_scale = TimeScaleController()
        self._particle_pool = ParticlePool()
        self._damage_numbers: List[DamageNumberPopup] = []
        self._toasts: List[ToastNotification] = []
        self._choreography: Optional[ActionChoreography] = None

        self._quiz_popup_active: bool = False
        self._enemy_turn_started: bool = False
        self._battle_end_handled: bool = False
        self._elapsed_seconds_total: float = 0.0
        self._screen_flash_alpha: float = 0.0

        self._correct_count = 0
        self._wrong_count = 0
        self._potion_used_this_battle = False
        self._element_swap_count_this_battle = 0
        self._melt_trigger_count_this_battle = 0
        self._max_inventory_seen = self._save_data.inventory

        self._font_small = load_pixel_font(12)
        self._font_medium = load_pixel_font(16)
        self._font_large = load_pixel_font(24)

        self._command_buttons: List[CommandButtonDefinition] = self._build_command_buttons()

    def _build_command_buttons(self) -> List[CommandButtonDefinition]:
        labels = [
            (ActionType.ATTACK, "Serang"),
            (ActionType.SKILL, "Skill"),
            (ActionType.ULTIMATE, "Ultimate"),
            (ActionType.POTION_HEAL, "Item"),
            (ActionType.ELEMENT_SWAP, "Ganti"),
        ]
        buttons: List[CommandButtonDefinition] = []
        total_width = len(labels) * COMMAND_BUTTON_WIDTH_PX + (len(labels) - 1) * COMMAND_BUTTON_GAP_PX
        start_x = settings.SCREEN_WIDTH - total_width - 10
        start_y = settings.BOTTOM_PANEL_Y_START + (
            (settings.BOTTOM_PANEL_Y_END - settings.BOTTOM_PANEL_Y_START - COMMAND_BUTTON_HEIGHT_PX) // 2
        )
        for index, (action_type, label) in enumerate(labels):
            rect = pygame.Rect(
                start_x + index * (COMMAND_BUTTON_WIDTH_PX + COMMAND_BUTTON_GAP_PX),
                start_y,
                COMMAND_BUTTON_WIDTH_PX,
                COMMAND_BUTTON_HEIGHT_PX,
            )
            buttons.append(CommandButtonDefinition(action_type, label, rect))
        return buttons

    def on_enter(self) -> None:
        self._zoom_controller.reset_to_default()

    def on_exit(self) -> None:
        self._persist_save_data()

    def update(self, delta_time_seconds: float) -> None:
        scaled_delta = self._time_scale.apply(delta_time_seconds)
        self._elapsed_seconds_total += delta_time_seconds

        self._process_pygame_events()
        self._zoom_controller.update(delta_time_seconds)
        self._camera.update(delta_time_seconds)
        self._hero_animator.update(scaled_delta)
        self._enemy_animator.update(scaled_delta)
        self._particle_pool.update(scaled_delta)
        self._screen_flash_alpha = max(0.0, self._screen_flash_alpha - delta_time_seconds / SLASH_FLASH_DURATION_SECONDS)

        for popup in self._damage_numbers:
            popup.update(delta_time_seconds)
        self._damage_numbers = [popup for popup in self._damage_numbers if not popup.is_finished]

        for toast in self._toasts:
            toast.update(delta_time_seconds)
        self._toasts = [toast for toast in self._toasts if not toast.is_finished]

        if self._choreography is not None:
            self._choreography.update(scaled_delta)

        self._advance_state_machine()
        self._render()
        self._display_manager.present()

    def _process_pygame_events(self) -> None:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.scene_manager.request_exit()
            elif event.type == pygame.VIDEORESIZE:
                self._display_manager.handle_resize_event(event.w, event.h)
            elif event.type == pygame.MOUSEWHEEL:
                self._zoom_controller.handle_mouse_wheel(event.y)
            elif event.type == pygame.KEYDOWN:
                self._handle_key_down(event.key)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._handle_mouse_click(event.pos)

    def _handle_key_down(self, key: int) -> None:
        if key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
            self._zoom_controller.handle_zoom_in_key()
        elif key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self._zoom_controller.handle_zoom_out_key()
        elif key == pygame.K_0:
            self._zoom_controller.handle_zoom_reset_key()

    def _handle_mouse_click(self, window_position: Tuple[int, int]) -> None:
        if self._engine.state != BattleState.WAIT_COMMAND:
            return
        base_x, base_y = self._display_manager.convert_window_position_to_base(window_position)
        for button in self._command_buttons:
            if button.rect.collidepoint(base_x, base_y):
                self._handle_command_button(button.action_type)
                return

    def _handle_command_button(self, action_type: ActionType) -> None:
        if action_type == ActionType.ATTACK and self._engine.can_perform_attack():
            self._engine.begin_action(ActionType.ATTACK)
        elif action_type == ActionType.SKILL and self._engine.can_perform_skill():
            self._engine.begin_action(ActionType.SKILL)
        elif action_type == ActionType.ULTIMATE and self._engine.can_perform_ultimate():
            self._engine.begin_action(ActionType.ULTIMATE)
        elif action_type == ActionType.POTION_HEAL and self._engine.can_perform_potion_heal():
            resolution = self._engine.perform_potion_heal()
            self._potion_used_this_battle = True
            self._max_inventory_seen = max(self._max_inventory_seen, self._inventory.count)
            self._start_heal_choreography(resolution)
        elif action_type == ActionType.ELEMENT_SWAP and self._engine.can_perform_element_swap():
            self._engine.perform_element_swap()
            self._element_swap_count_this_battle += 1

    def _advance_state_machine(self) -> None:
        if self._engine.state == BattleState.QUIZ and not self._quiz_popup_active:
            self._open_quiz_for_pending_action()
        elif self._engine.state == BattleState.RESOLVE_ANIM:
            if self._choreography is None or self._choreography.is_finished:
                result = self._engine.complete_resolve_animation()
                if result == BattleState.VICTORY:
                    self._handle_victory()
                elif result == BattleState.DEFEAT:
                    self._handle_defeat()
        elif self._engine.state == BattleState.NEXT_TURN:
            self._enemy_turn_started = False
            self._engine.resolve_next_turn()
        elif self._engine.state == BattleState.ENEMY_TURN:
            if not self._enemy_turn_started:
                self._enemy_turn_started = True
                resolution = self._engine.run_enemy_turn()
                self._start_enemy_attack_choreography(resolution)

    def _open_quiz_for_pending_action(self) -> None:
        action_type = self._engine.pending_action
        if action_type is None:
            return
        self._quiz_popup_active = True
        quiz_type = self._engine.get_quiz_type(action_type)
        time_limit = self._engine.get_time_limit_seconds(action_type)
        tk_root = self.scene_manager.get_tk_root()

        if quiz_type == QuizType.MULTIPLE_CHOICE:
            question = self._question_manager.get_multiple_choice_question(preferred_difficulty=self._level_id)
            open_multiple_choice_quiz(tk_root, question, time_limit, self._on_quiz_complete)
        else:
            min_ratio = self._level_config.essay_min_keyword_group_ratio or 1.0
            question = self._question_manager.get_essay_question(
                min_difficulty=max(1, self._level_id - 1), max_difficulty=self._level_id + 1
            )
            open_essay_quiz(tk_root, question, time_limit, min_ratio, self._on_quiz_complete)

    def _on_quiz_complete(self, outcome: QuizOutcome) -> None:
        self._quiz_popup_active = False
        action_type = self._engine.pending_action
        if action_type is None:
            return
        if outcome.is_correct:
            self._correct_count += 1
        else:
            self._wrong_count += 1
        resolution = self._engine.submit_quiz_result(action_type, outcome.is_correct, outcome.elapsed_seconds)
        if resolution.melt_triggered:
            self._melt_trigger_count_this_battle += 1
        self._start_hero_attack_choreography(resolution, action_type)

    def _start_hero_attack_choreography(self, resolution: ActionResolution, action_type: ActionType) -> None:
        animation_name = {
            ActionType.ATTACK: "attack01",
            ActionType.SKILL: "attack02",
            ActionType.ULTIMATE: "attack03",
        }.get(action_type, "attack01")
        is_miss = resolution.outcome == ActionOutcome.MISS
        self._hero_animator.play(animation_name)

        def on_impact() -> None:
            if is_miss:
                self._spawn_damage_text("MISS", (160, 160, 160), settings.ENEMY_HOME)
                self._enemy_animator.play("idle")
            else:
                total_damage = sum(resolution.damage_dealt) if resolution.damage_dealt else 0
                color = (255, 140, 0) if resolution.melt_triggered else (255, 255, 255)
                self._spawn_damage_text(str(total_damage), color, settings.ENEMY_HOME)
                self._enemy_animator.play("hit")
                self._sfx_manager.play_attack_impact()
                self._camera.trigger_shake(4.0, 0.15)
                self._screen_flash_alpha = 180.0
                self._spawn_hit_particles(settings.ENEMY_HOME)

        def on_finished() -> None:
            self._enemy_animator.play("idle")
            self._choreography = None

        self._choreography = ActionChoreography(
            attacker_is_hero=True,
            attacker_animation_name=animation_name,
            defender_reaction_animation_name="hit",
            is_miss=is_miss,
            on_impact=on_impact,
            on_finished=on_finished,
        )

    def _start_enemy_attack_choreography(self, resolution: ActionResolution) -> None:
        self._enemy_animator.play("attack01")

        def on_impact() -> None:
            total_damage = sum(resolution.damage_dealt) if resolution.damage_dealt else 0
            if total_damage > 0:
                self._spawn_damage_text(str(total_damage), (255, 80, 80), settings.HERO_HOME)
                self._hero_animator.play("hit")
                self._camera.trigger_shake(4.0, 0.15)
                self._screen_flash_alpha = 120.0
                self._spawn_hit_particles(settings.HERO_HOME)

        def on_finished() -> None:
            self._hero_animator.play("idle")
            self._choreography = None

        self._choreography = ActionChoreography(
            attacker_is_hero=False,
            attacker_animation_name="attack01",
            defender_reaction_animation_name="hit",
            is_miss=False,
            on_impact=on_impact,
            on_finished=on_finished,
        )

    def _start_heal_choreography(self, resolution: ActionResolution) -> None:
        self._spawn_damage_text(f"+{resolution.healed_amount}", (120, 220, 120), settings.HERO_HOME)

        def on_impact() -> None:
            pass

        def on_finished() -> None:
            self._choreography = None

        self._choreography = ActionChoreography(
            attacker_is_hero=True,
            attacker_animation_name="idle",
            defender_reaction_animation_name="idle",
            is_miss=False,
            on_impact=on_impact,
            on_finished=on_finished,
        )

    def _spawn_damage_text(self, text: str, color: Tuple[int, int, int], world_position: Tuple[int, int]) -> None:
        tween = Tween((0.0,), (1.0,), settings.DAMAGE_NUMBER_RISE_DURATION_SECONDS, ease_out_cubic)
        self._damage_numbers.append(
            DamageNumberPopup(text=text, color=color, world_x=world_position[0], world_y=world_position[1], tween=tween)
        )

    def _spawn_hit_particles(self, world_position: Tuple[int, int]) -> None:
        for _ in range(8):
            self._particle_pool.spawn(
                Particle(
                    position_x=float(world_position[0]),
                    position_y=float(world_position[1]),
                    velocity_x=float(pygame.math.Vector2(1, 0).rotate(pygame.time.get_ticks() % 360).x * 60),
                    velocity_y=-80.0,
                    color=(255, 200, 100),
                    radius=3.0,
                    alpha=255.0,
                    time_to_live_seconds=0.4,
                )
            )

    def _handle_victory(self) -> None:
        if self._battle_end_handled:
            return
        self._battle_end_handled = True
        rewards = self._engine.finalize_victory_rewards()
        self._update_save_data_after_battle(won=True, rewards=rewards)
        self._check_and_apply_achievements()
        self._persist_save_data()
        self.scene_manager.transition_to(SceneType.STORY)

    def _handle_defeat(self) -> None:
        if self._battle_end_handled:
            return
        self._battle_end_handled = True
        self._engine.restore_inventory_on_defeat()
        self._update_save_data_after_battle(won=False, rewards=None)
        self._persist_save_data()
        self.scene_manager.transition_to(SceneType.LEVEL_SELECT)

    def _update_save_data_after_battle(self, won: bool, rewards: Optional[dict]) -> None:
        hero = self._engine.hero
        self._save_data.hero.max_hp = hero.stats.max_hp
        self._save_data.hero.hp = hero.stats.hp
        self._save_data.hero.atk = hero.stats.atk
        self._save_data.hero.def_ = hero.stats.def_
        self._save_data.hero.spd = hero.stats.spd
        self._save_data.hero.cleared_level_ids = set(hero.cleared_level_ids)
        self._save_data.element = hero.element.value
        self._save_data.inventory = self._inventory.count

        counters = self._save_data.counters
        counters.total_correct_answers += self._correct_count
        counters.total_fast_correct_answers += self._engine.fast_answer_count
        counters.total_element_swaps_lifetime += self._element_swap_count_this_battle
        counters.max_element_swaps_single_battle = max(
            counters.max_element_swaps_single_battle, self._element_swap_count_this_battle
        )
        counters.max_melt_triggers_single_battle = max(
            counters.max_melt_triggers_single_battle, self._melt_trigger_count_this_battle
        )
        counters.max_potions_held = max(counters.max_potions_held, self._max_inventory_seen, self._inventory.count)
        if hero.action_points >= settings.ACTION_POINT_MAX:
            counters.ended_battle_with_full_ap = True

        if won:
            counters.total_battles_won += 1
            if self._wrong_count == 0:
                counters.perfect_clear_level_ids.add(self._level_id)
            if self._level_id in (2, 3) and not self._potion_used_this_battle:
                counters.won_without_potion_level_ids.add(self._level_id)
            score = self._engine.compute_current_score()
            previous_highscore = self._save_data.highscore.get(self._level_id, 0)
            self._save_data.highscore[self._level_id] = max(previous_highscore, score)
            if self._save_data.current_level <= self._level_id:
                self._save_data.current_level = self._level_id + 1

    def _check_and_apply_achievements(self) -> None:
        already_unlocked = set(self._save_data.achievements.keys())
        newly_unlocked = self._achievement_evaluator.evaluate(self._save_data.counters, already_unlocked)
        if not newly_unlocked:
            return
        self._achievement_evaluator.apply_unlocks(self._save_data, newly_unlocked)
        for definition in newly_unlocked:
            tween = Tween((0.0,), (1.0,), settings.TOAST_ACHIEVEMENT_HOLD_DURATION_SECONDS, ease_out_back)
            self._toasts.append(ToastNotification(text=f"Achievement: {definition.name}", tween=tween))

    def _persist_save_data(self) -> None:
        self._save_repository.save(self._save_data)

    def _render(self) -> None:
        surface = self._display_manager.get_render_surface()
        surface.fill((18, 18, 26))
        self._draw_arena(surface)
        self._draw_enemy_status(surface)
        self._draw_timeline(surface)
        self._draw_bottom_panel(surface)
        self._draw_toasts(surface)
        if self._screen_flash_alpha > 0.0:
            flash_surface = pygame.Surface((settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT), pygame.SRCALPHA)
            flash_surface.fill((255, 255, 255, int(self._screen_flash_alpha)))
            surface.blit(flash_surface, (0, 0))

    def _draw_arena(self, surface: pygame.Surface) -> None:
        arena_rect = self._layout_regions.arena_region
        pygame.draw.rect(surface, (34, 40, 54), arena_rect)

        hero_bob = compute_idle_bob_offset(self._elapsed_seconds_total)
        enemy_bob = compute_idle_bob_offset(self._elapsed_seconds_total + 0.4)
        hero_offset_x = self._choreography.attacker_offset_x if (
            self._choreography is not None and self._choreography.attacker_is_hero
        ) else 0.0
        enemy_offset_x = self._choreography.attacker_offset_x if (
            self._choreography is not None and not self._choreography.attacker_is_hero
        ) else 0.0

        hero_world = (settings.HERO_HOME[0] + hero_offset_x, settings.HERO_HOME[1] + hero_bob)
        enemy_world = (settings.ENEMY_HOME[0] + enemy_offset_x, settings.ENEMY_HOME[1] + enemy_bob)

        self._draw_sprite(surface, self._hero_animator, hero_world, flip_horizontal=False)
        self._draw_sprite(surface, self._enemy_animator, enemy_world, flip_horizontal=True)

        for particle in self._particle_pool.get_active_particles():
            screen_x, screen_y = self._camera.world_to_screen(particle.position_x, particle.position_y)
            pygame.draw.circle(surface, particle.color, (int(screen_x), int(screen_y)), max(1, int(particle.radius)))

        for popup in self._damage_numbers:
            rise, scale = popup.get_render_offset()
            screen_x, screen_y = self._camera.world_to_screen(popup.world_x, popup.world_y + rise)
            text_surface = self._font_medium.render(popup.text, True, popup.color)
            if scale != 1.0:
                new_size = (max(1, int(text_surface.get_width() * scale)), max(1, int(text_surface.get_height() * scale)))
                text_surface = pygame.transform.scale(text_surface, new_size)
            text_surface.set_alpha(int(popup.alpha))
            rect = text_surface.get_rect(center=(int(screen_x), int(screen_y)))
            surface.blit(text_surface, rect)

    def _draw_sprite(
        self, surface: pygame.Surface, animator: SpriteAnimator, world_position: Tuple[float, float], flip_horizontal: bool
    ) -> None:
        sprite_surface = animator.get_surface(flip_horizontal=flip_horizontal)
        scale_ratio = SPRITE_DISPLAY_TARGET_HEIGHT_PX / sprite_surface.get_height()
        display_width = max(1, int(sprite_surface.get_width() * scale_ratio))
        display_height = max(1, int(sprite_surface.get_height() * scale_ratio))
        scaled_sprite = pygame.transform.scale(sprite_surface, (display_width, display_height))
        screen_x, screen_y = self._camera.world_to_screen(world_position[0], world_position[1])
        rect = scaled_sprite.get_rect(midbottom=(int(screen_x), int(screen_y)))
        surface.blit(scaled_sprite, rect)

    def _draw_enemy_status(self, surface: pygame.Surface) -> None:
        enemy = self._engine.enemy
        bar_x = settings.ENEMY_HOME[0] - HP_BAR_WIDTH_PX // 2
        bar_y = settings.ARENA_Y_START + 10
        self._draw_hp_bar(surface, bar_x, bar_y, enemy.stats.hp, enemy.stats.max_hp)
        if enemy.mark is not None:
            mark_color = (255, 120, 40) if enemy.mark.element == Element.FIRE else (120, 200, 255)
            pygame.draw.circle(surface, mark_color, (settings.ENEMY_HOME[0], bar_y - 12), 6)

    def _draw_hp_bar(self, surface: pygame.Surface, x: int, y: int, hp: int, max_hp: int) -> None:
        ratio = max(0.0, min(1.0, hp / max_hp)) if max_hp > 0 else 0.0
        pygame.draw.rect(surface, (60, 20, 20), (x, y, HP_BAR_WIDTH_PX, HP_BAR_HEIGHT_PX))
        pygame.draw.rect(surface, (60, 200, 90), (x, y, int(HP_BAR_WIDTH_PX * ratio), HP_BAR_HEIGHT_PX))
        pygame.draw.rect(surface, (10, 10, 10), (x, y, HP_BAR_WIDTH_PX, HP_BAR_HEIGHT_PX), 1)

    def _draw_timeline(self, surface: pygame.Surface) -> None:
        timeline_rect = self._layout_regions.timeline_region
        pygame.draw.rect(surface, (24, 24, 32), timeline_rect)
        hero_icon_x = settings.SCREEN_WIDTH / 2 - 20
        enemy_icon_x = settings.SCREEN_WIDTH / 2 + 20
        icon_y = timeline_rect.centery
        hero_color = (255, 215, 0) if self._engine.timeline.current_actor() == Actor.HERO else (120, 120, 140)
        enemy_color = (255, 215, 0) if self._engine.timeline.current_actor() == Actor.ENEMY else (120, 120, 140)
        pygame.draw.circle(surface, hero_color, (int(hero_icon_x), icon_y), 10)
        pygame.draw.circle(surface, enemy_color, (int(enemy_icon_x), icon_y), 10)

    def _draw_bottom_panel(self, surface: pygame.Surface) -> None:
        panel_rect = self._layout_regions.bottom_panel_region
        pygame.draw.rect(surface, (22, 22, 30), panel_rect)

        hero = self._engine.hero
        self._draw_hp_bar(surface, 10, panel_rect.y + 10, hero.stats.hp, hero.stats.max_hp)

        element_color = (255, 120, 40) if hero.element == Element.FIRE else (120, 200, 255)
        pygame.draw.circle(surface, element_color, (10 + HP_BAR_WIDTH_PX + 16, panel_rect.y + 17), 8)

        for pip_index in range(settings.ACTION_POINT_MAX):
            pip_color = (255, 215, 0) if pip_index < hero.action_points else (60, 60, 70)
            pygame.draw.circle(surface, pip_color, (14 + pip_index * 16, panel_rect.y + 36), 5)

        for stack_index in range(settings.MOMENTUM_MAX_STACK):
            stack_color = (255, 100, 100) if stack_index < hero.momentum_stack else (60, 60, 70)
            pygame.draw.rect(surface, stack_color, (14 + stack_index * 14, panel_rect.y + 50, 10, 10))

        for button in self._command_buttons:
            enabled = self._is_command_button_enabled(button.action_type)
            base_color = (70, 90, 130) if enabled else (40, 40, 48)
            pygame.draw.rect(surface, base_color, button.rect, border_radius=4)
            pygame.draw.rect(surface, (200, 200, 210), button.rect, 1, border_radius=4)
            label_surface = self._font_small.render(button.label, True, (230, 230, 235) if enabled else (110, 110, 115))
            label_rect = label_surface.get_rect(center=button.rect.center)
            surface.blit(label_surface, label_rect)

    def _is_command_button_enabled(self, action_type: ActionType) -> bool:
        if action_type == ActionType.ATTACK:
            return self._engine.can_perform_attack()
        if action_type == ActionType.SKILL:
            return self._engine.can_perform_skill()
        if action_type == ActionType.ULTIMATE:
            return self._engine.can_perform_ultimate()
        if action_type == ActionType.POTION_HEAL:
            return self._engine.can_perform_potion_heal()
        if action_type == ActionType.ELEMENT_SWAP:
            return self._engine.can_perform_element_swap()
        return False

    def _draw_toasts(self, surface: pygame.Surface) -> None:
        for index, toast in enumerate(self._toasts):
            progress = toast.tween.current_values[0]
            slide_in_ratio = min(1.0, progress / 0.2)
            toast_y = -30 + 50 * slide_in_ratio
            toast_surface = self._font_small.render(toast.text, True, (255, 255, 255))
            background_rect = pygame.Rect(0, 0, toast_surface.get_width() + 20, toast_surface.get_height() + 10)
            background_rect.midtop = (settings.SCREEN_WIDTH // 2, int(toast_y) + index * 30)
            pygame.draw.rect(surface, (40, 40, 60), background_rect, border_radius=6)
            surface.blit(toast_surface, toast_surface.get_rect(center=background_rect.center))


def create_battle_scene_factory(level_id: int) -> Callable[[SceneManager], BattleScene]:
    return lambda scene_manager: BattleScene(scene_manager, level_id)