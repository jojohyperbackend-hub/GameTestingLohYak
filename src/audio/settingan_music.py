from __future__ import annotations

from typing import Optional

import pygame

from src import settings


class SfxManager:
    def __init__(self):
        self._mixer_available: bool = False
        self._attack_sound: Optional[pygame.mixer.Sound] = None
        self._initialize_mixer()
        self._load_attack_sfx()

    def _initialize_mixer(self) -> None:
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._mixer_available = True
        except pygame.error:
            self._mixer_available = False

    def _load_attack_sfx(self) -> None:
        if not self._mixer_available:
            return
        if not settings.SFX_ATTACK_PATH.exists():
            return
        try:
            self._attack_sound = pygame.mixer.Sound(str(settings.SFX_ATTACK_PATH))
        except pygame.error:
            self._attack_sound = None

    def play_attack_impact(self) -> None:
        if self._mixer_available and self._attack_sound is not None:
            self._attack_sound.play()

    @property
    def is_attack_sfx_loaded(self) -> bool:
        return self._attack_sound is not None

    @property
    def is_mixer_available(self) -> bool:
        return self._mixer_available


def create_sfx_manager() -> SfxManager:
    return SfxManager()