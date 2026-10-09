from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import FrozenSet

import pygame

from src import settings


ZOOM_TRANSITION_DURATION_SECONDS: float = 0.2


class LayerName(IntEnum):
    ARENA_BACKGROUND = 1
    ARENA_GROUND_EFFECTS = 2
    ARENA_SPRITES = 3
    ARENA_ACTION_EFFECTS = 4
    ARENA_DAMAGE_NUMBERS = 5
    HUD_ENEMY_STATUS = 6
    HUD_TIMELINE = 7
    HUD_BOTTOM_PANEL = 8
    HUD_TOAST_AND_TRANSITION = 9


RENDER_LAYER_ORDER: tuple[LayerName, ...] = tuple(sorted(LayerName, key=lambda layer: layer.value))

ZOOMABLE_LAYERS: FrozenSet[LayerName] = frozenset(
    {
        LayerName.ARENA_BACKGROUND,
        LayerName.ARENA_GROUND_EFFECTS,
        LayerName.ARENA_SPRITES,
        LayerName.ARENA_ACTION_EFFECTS,
        LayerName.ARENA_DAMAGE_NUMBERS,
    }
)


def is_layer_zoomable(layer: LayerName) -> bool:
    return layer in ZOOMABLE_LAYERS


@dataclass(frozen=True)
class LayoutRegions:
    timeline_region: pygame.Rect
    arena_region: pygame.Rect
    bottom_panel_region: pygame.Rect


def create_default_layout_regions() -> LayoutRegions:
    timeline_region = pygame.Rect(
        0,
        settings.HUD_TIMELINE_Y_START,
        settings.SCREEN_WIDTH,
        settings.HUD_TIMELINE_Y_END - settings.HUD_TIMELINE_Y_START,
    )
    arena_region = pygame.Rect(
        0,
        settings.ARENA_Y_START,
        settings.SCREEN_WIDTH,
        settings.ARENA_Y_END - settings.ARENA_Y_START,
    )
    bottom_panel_region = pygame.Rect(
        0,
        settings.BOTTOM_PANEL_Y_START,
        settings.SCREEN_WIDTH,
        settings.BOTTOM_PANEL_Y_END - settings.BOTTOM_PANEL_Y_START,
    )
    return LayoutRegions(
        timeline_region=timeline_region,
        arena_region=arena_region,
        bottom_panel_region=bottom_panel_region,
    )


def _ease_out_cubic(progress_ratio: float) -> float:
    clamped_ratio = max(0.0, min(1.0, progress_ratio))
    return 1.0 - (1.0 - clamped_ratio) ** 3


class ArenaZoomController:
    def __init__(self):
        self._current_zoom: float = settings.ZOOM_DEFAULT
        self._transition_start_zoom: float = settings.ZOOM_DEFAULT
        self._target_zoom: float = settings.ZOOM_DEFAULT
        self._transition_elapsed_seconds: float = ZOOM_TRANSITION_DURATION_SECONDS

    def handle_mouse_wheel(self, wheel_direction: int) -> None:
        if wheel_direction > 0:
            self._set_target(self._target_zoom + settings.ZOOM_STEP)
        elif wheel_direction < 0:
            self._set_target(self._target_zoom - settings.ZOOM_STEP)

    def handle_zoom_in_key(self) -> None:
        self._set_target(self._target_zoom + settings.ZOOM_STEP)

    def handle_zoom_out_key(self) -> None:
        self._set_target(self._target_zoom - settings.ZOOM_STEP)

    def handle_zoom_reset_key(self) -> None:
        self._set_target(settings.ZOOM_DEFAULT)

    def update(self, delta_time_seconds: float) -> None:
        if self._transition_elapsed_seconds >= ZOOM_TRANSITION_DURATION_SECONDS:
            self._current_zoom = self._target_zoom
            return
        self._transition_elapsed_seconds = min(
            ZOOM_TRANSITION_DURATION_SECONDS, self._transition_elapsed_seconds + delta_time_seconds
        )
        progress_ratio = self._transition_elapsed_seconds / ZOOM_TRANSITION_DURATION_SECONDS
        eased_ratio = _ease_out_cubic(progress_ratio)
        self._current_zoom = (
            self._transition_start_zoom + (self._target_zoom - self._transition_start_zoom) * eased_ratio
        )

    def get_player_zoom(self) -> float:
        return self._current_zoom

    def get_effective_zoom(self, ultimate_zoom_multiplier: float = 1.0) -> float:
        return self._current_zoom * ultimate_zoom_multiplier

    def reset_to_default(self) -> None:
        self._current_zoom = settings.ZOOM_DEFAULT
        self._transition_start_zoom = settings.ZOOM_DEFAULT
        self._target_zoom = settings.ZOOM_DEFAULT
        self._transition_elapsed_seconds = ZOOM_TRANSITION_DURATION_SECONDS

    def _set_target(self, new_target_zoom: float) -> None:
        clamped_target = max(settings.ZOOM_MIN, min(settings.ZOOM_MAX, new_target_zoom))
        if clamped_target == self._target_zoom:
            return
        self._transition_start_zoom = self._current_zoom
        self._target_zoom = clamped_target
        self._transition_elapsed_seconds = 0.0


def create_arena_zoom_controller() -> ArenaZoomController:
    return ArenaZoomController()