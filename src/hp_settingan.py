from __future__ import annotations

from typing import Tuple

import pygame

from src import settings


class WindowDisplayManager:
    def __init__(self, window_title: str = "Game_guak"):
        pygame.display.set_caption(window_title)
        self._is_fullscreen: bool = False
        self._windowed_size: Tuple[int, int] = (settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT)
        self._window_surface: pygame.Surface = pygame.display.set_mode(
            self._windowed_size, pygame.RESIZABLE
        )
        self._base_surface: pygame.Surface = pygame.Surface(
            (settings.SCREEN_WIDTH, settings.SCREEN_HEIGHT)
        )
        self._scale_factor: float = 1.0
        self._offset_x: int = 0
        self._offset_y: int = 0
        self._recompute_scale_and_offset()

    def get_render_surface(self) -> pygame.Surface:
        return self._base_surface

    def present(self) -> None:
        self._window_surface.fill((0, 0, 0))
        scaled_width = max(1, round(settings.SCREEN_WIDTH * self._scale_factor))
        scaled_height = max(1, round(settings.SCREEN_HEIGHT * self._scale_factor))
        scaled_surface = pygame.transform.scale(self._base_surface, (scaled_width, scaled_height))
        self._window_surface.blit(scaled_surface, (self._offset_x, self._offset_y))
        pygame.display.flip()

    def handle_resize_event(self, new_width: int, new_height: int) -> None:
        if not self._is_fullscreen:
            self._windowed_size = (new_width, new_height)
        self._window_surface = pygame.display.set_mode(
            (new_width, new_height), pygame.FULLSCREEN if self._is_fullscreen else pygame.RESIZABLE
        )
        self._recompute_scale_and_offset()

    def toggle_fullscreen(self) -> None:
        self._is_fullscreen = not self._is_fullscreen
        if self._is_fullscreen:
            self._window_surface = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        else:
            self._window_surface = pygame.display.set_mode(self._windowed_size, pygame.RESIZABLE)
        self._recompute_scale_and_offset()

    def convert_window_position_to_base(self, window_position: Tuple[int, int]) -> Tuple[float, float]:
        window_x, window_y = window_position
        if self._scale_factor <= 0:
            return 0.0, 0.0
        base_x = (window_x - self._offset_x) / self._scale_factor
        base_y = (window_y - self._offset_y) / self._scale_factor
        return base_x, base_y

    def is_position_inside_render_area(self, base_position: Tuple[float, float]) -> bool:
        base_x, base_y = base_position
        return 0 <= base_x <= settings.SCREEN_WIDTH and 0 <= base_y <= settings.SCREEN_HEIGHT

    @property
    def is_fullscreen(self) -> bool:
        return self._is_fullscreen

    @property
    def scale_factor(self) -> float:
        return self._scale_factor

    def _recompute_scale_and_offset(self) -> None:
        window_width, window_height = self._window_surface.get_size()
        horizontal_scale = window_width / settings.SCREEN_WIDTH
        vertical_scale = window_height / settings.SCREEN_HEIGHT
        self._scale_factor = min(horizontal_scale, vertical_scale)
        scaled_width = round(settings.SCREEN_WIDTH * self._scale_factor)
        scaled_height = round(settings.SCREEN_HEIGHT * self._scale_factor)
        self._offset_x = (window_width - scaled_width) // 2
        self._offset_y = (window_height - scaled_height) // 2


def create_window_display_manager() -> WindowDisplayManager:
    return WindowDisplayManager()