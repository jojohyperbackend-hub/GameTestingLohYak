from __future__ import annotations

import random
from typing import Optional, Tuple

from src import settings
from src.animation import Tween, ease_out_cubic
from src.main_layout_game_screen.settingan_layer import ArenaZoomController


class ShakeState:
    def __init__(self):
        self._remaining_seconds: float = 0.0
        self._total_duration_seconds: float = 0.0
        self._magnitude_px: float = 0.0
        self._current_offset: Tuple[float, float] = (0.0, 0.0)

    def trigger(self, magnitude_px: float, duration_seconds: float) -> None:
        if self._remaining_seconds > 0.0 and magnitude_px < self._magnitude_px:
            return
        self._magnitude_px = magnitude_px
        self._total_duration_seconds = max(0.0001, duration_seconds)
        self._remaining_seconds = self._total_duration_seconds

    def update(self, delta_time_seconds: float) -> None:
        if self._remaining_seconds <= 0.0:
            self._current_offset = (0.0, 0.0)
            return
        self._remaining_seconds = max(0.0, self._remaining_seconds - delta_time_seconds)
        intensity_ratio = self._remaining_seconds / self._total_duration_seconds
        current_magnitude = self._magnitude_px * intensity_ratio
        self._current_offset = (
            random.uniform(-current_magnitude, current_magnitude),
            random.uniform(-current_magnitude, current_magnitude),
        )

    def get_offset(self) -> Tuple[float, float]:
        return self._current_offset

    @property
    def is_active(self) -> bool:
        return self._remaining_seconds > 0.0


class Camera2_5D:
    def __init__(self, zoom_controller: ArenaZoomController):
        self._zoom_controller = zoom_controller
        self._default_pivot: Tuple[float, float] = (
            settings.SCREEN_WIDTH / 2.0,
            (settings.ARENA_Y_START + settings.ARENA_Y_END) / 2.0,
        )
        self._pivot: Tuple[float, float] = self._default_pivot
        self._ultimate_zoom_tween: Optional[Tween] = None
        self._ultimate_zoom_multiplier: float = 1.0
        self._shake = ShakeState()

    def begin_ultimate_zoom(
        self,
        pivot: Optional[Tuple[float, float]] = None,
        duration_seconds: Optional[float] = None,
    ) -> None:
        resolved_duration = (
            duration_seconds
            if duration_seconds is not None
            else settings.ULTIMATE_SCREEN_DIM_DURATION_SECONDS
        )
        self._pivot = pivot if pivot is not None else settings.HERO_HOME
        self._ultimate_zoom_tween = Tween(
            (self._ultimate_zoom_multiplier,),
            (settings.ULTIMATE_CAMERA_ZOOM_TARGET,),
            resolved_duration,
            ease_out_cubic,
        )

    def end_ultimate_zoom(self, duration_seconds: Optional[float] = None) -> None:
        resolved_duration = (
            duration_seconds
            if duration_seconds is not None
            else settings.ULTIMATE_SCREEN_DIM_DURATION_SECONDS
        )
        self._ultimate_zoom_tween = Tween(
            (self._ultimate_zoom_multiplier,), (1.0,), resolved_duration, ease_out_cubic
        )

    def update(self, delta_time_seconds: float) -> None:
        if self._ultimate_zoom_tween is not None:
            self._ultimate_zoom_tween.update(delta_time_seconds)
            self._ultimate_zoom_multiplier = self._ultimate_zoom_tween.current_values[0]
            if self._ultimate_zoom_tween.is_finished:
                if self._ultimate_zoom_multiplier <= 1.0:
                    self._pivot = self._default_pivot
                self._ultimate_zoom_tween = None
        self._shake.update(delta_time_seconds)

    def trigger_shake(self, magnitude_px: float, duration_seconds: float) -> None:
        self._shake.trigger(magnitude_px, duration_seconds)

    def get_effective_zoom(self) -> float:
        return self._zoom_controller.get_effective_zoom(self._ultimate_zoom_multiplier)

    def world_to_screen(
        self, world_x: float, world_y: float, depth_factor: float = 1.0
    ) -> Tuple[float, float]:
        zoom = self.get_effective_zoom()
        effective_scale = 1.0 + (zoom - 1.0) * depth_factor
        pivot_x, pivot_y = self._pivot
        shake_x, shake_y = self._shake.get_offset()
        screen_x = pivot_x + (world_x - pivot_x) * effective_scale + shake_x
        screen_y = pivot_y + (world_y - pivot_y) * effective_scale + shake_y
        return screen_x, screen_y

    def get_current_pivot(self) -> Tuple[float, float]:
        return self._pivot

    def reset(self) -> None:
        self._pivot = self._default_pivot
        self._ultimate_zoom_tween = None
        self._ultimate_zoom_multiplier = 1.0
        self._shake = ShakeState()

    @property
    def is_shaking(self) -> bool:
        return self._shake.is_active

    @property
    def is_ultimate_zoom_active(self) -> bool:
        return self._ultimate_zoom_tween is not None


def create_camera(zoom_controller: ArenaZoomController) -> Camera2_5D:
    return Camera2_5D(zoom_controller)