from __future__ import annotations

import tkinter as tk
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Callable, Dict, FrozenSet, List, Optional

import pygame

from src import settings


class SceneManagerError(Exception):
    pass


class SceneType(Enum):
    MAIN_MENU = auto()
    LOADOUT = auto()
    STORY = auto()
    LEVEL_SELECT = auto()
    ACHIEVEMENT_GALLERY = auto()
    BATTLE = auto()


PYGAME_SCENE_TYPES: FrozenSet[SceneType] = frozenset({SceneType.BATTLE})
TKINTER_SCENE_TYPES: FrozenSet[SceneType] = frozenset(
    scene_type for scene_type in SceneType if scene_type not in PYGAME_SCENE_TYPES
)


class Scene(ABC):
    def __init__(self, scene_manager: "SceneManager"):
        self.scene_manager = scene_manager

    @abstractmethod
    def on_enter(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def on_exit(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def update(self, delta_time_seconds: float) -> None:
        raise NotImplementedError


SceneFactory = Callable[["SceneManager"], Scene]


class SceneManager:
    def __init__(self, tk_root: Optional[tk.Tk] = None):
        self._tk_root: tk.Tk = tk_root if tk_root is not None else tk.Tk()
        self._tk_root.protocol("WM_DELETE_WINDOW", self.request_exit)
        self._clock: pygame.time.Clock = pygame.time.Clock()
        self._scene_factories: Dict[SceneType, SceneFactory] = {}
        self._current_scene: Optional[Scene] = None
        self._current_scene_type: Optional[SceneType] = None
        self._should_exit: bool = False
        self._exit_callbacks: List[Callable[[], None]] = []

    def register_scene_factory(self, scene_type: SceneType, factory: SceneFactory) -> None:
        self._scene_factories[scene_type] = factory

    def register_exit_callback(self, callback: Callable[[], None]) -> None:
        self._exit_callbacks.append(callback)

    def get_tk_root(self) -> tk.Tk:
        return self._tk_root

    def get_clock(self) -> pygame.time.Clock:
        return self._clock

    def get_current_scene_type(self) -> Optional[SceneType]:
        return self._current_scene_type

    def transition_to(self, scene_type: SceneType) -> None:
        if scene_type not in self._scene_factories:
            raise SceneManagerError(f"Scene '{scene_type.name}' belum didaftarkan ke SceneManager")
        if self._current_scene is not None:
            self._current_scene.on_exit()
        if scene_type in PYGAME_SCENE_TYPES:
            self._tk_root.withdraw()
        else:
            self._tk_root.deiconify()
        factory = self._scene_factories[scene_type]
        new_scene = factory(self)
        self._current_scene = new_scene
        self._current_scene_type = scene_type
        new_scene.on_enter()

    def request_exit(self) -> None:
        self._should_exit = True

    def run(self, initial_scene_type: SceneType) -> None:
        self.transition_to(initial_scene_type)
        while not self._should_exit:
            elapsed_milliseconds = self._clock.tick(settings.TARGET_FPS)
            delta_time_seconds = elapsed_milliseconds / 1000.0
            if self._current_scene_type in PYGAME_SCENE_TYPES:
                pygame.event.pump()
            if self._current_scene is not None:
                self._current_scene.update(delta_time_seconds)
            try:
                if not self._tk_root.winfo_exists():
                    self._should_exit = True
                    break
                self._tk_root.update()
            except tk.TclError:
                self._should_exit = True
                break
        self._shutdown()

    def _shutdown(self) -> None:
        if self._current_scene is not None:
            self._current_scene.on_exit()
            self._current_scene = None
        for callback in self._exit_callbacks:
            callback()
        pygame.quit()
        try:
            if self._tk_root.winfo_exists():
                self._tk_root.destroy()
        except tk.TclError:
            pass


def create_scene_manager(tk_root: Optional[tk.Tk] = None) -> SceneManager:
    return SceneManager(tk_root)