from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
from typing import Optional

from src import settings
from src.data_manager import SaveData, create_save_data_repository
from src.scene_manager import Scene, SceneManager, SceneType


class MainMenuScene(Scene):
    def __init__(self, scene_manager: SceneManager):
        super().__init__(scene_manager)
        self._save_repository = create_save_data_repository()
        self._frame: Optional[tk.Frame] = None
        self._continue_button: Optional[tk.Button] = None

    def on_enter(self) -> None:
        root = self.scene_manager.get_tk_root()
        root.title("Game_guak")

        self._frame = tk.Frame(root, padx=48, pady=48, bg="#1a1a2e")
        self._frame.pack(fill="both", expand=True)

        title_label = tk.Label(
            self._frame,
            text="GAME_GUAK",
            font=("Consolas", 28, "bold"),
            fg="#f5f5f5",
            bg="#1a1a2e",
        )
        title_label.pack(pady=(0, 30))

        has_existing_save = settings.SAVE_DATA_FILE.exists()

        start_button = tk.Button(
            self._frame, text="Start", font=("Consolas", 14), width=20, command=self._handle_start
        )
        start_button.pack(pady=6)

        self._continue_button = tk.Button(
            self._frame,
            text="Continue",
            font=("Consolas", 14),
            width=20,
            command=self._handle_continue,
            state="normal" if has_existing_save else "disabled",
        )
        self._continue_button.pack(pady=6)

        loadout_button = tk.Button(
            self._frame, text="Loadout", font=("Consolas", 14), width=20, command=self._handle_loadout
        )
        loadout_button.pack(pady=6)

        achievement_button = tk.Button(
            self._frame,
            text="Achievement",
            font=("Consolas", 14),
            width=20,
            command=self._handle_achievement,
        )
        achievement_button.pack(pady=6)

        quit_button = tk.Button(
            self._frame, text="Quit", font=("Consolas", 14), width=20, command=self._handle_quit
        )
        quit_button.pack(pady=6)

    def on_exit(self) -> None:
        if self._frame is not None:
            self._frame.destroy()
            self._frame = None
            self._continue_button = None

    def update(self, delta_time_seconds: float) -> None:
        pass

    def _handle_start(self) -> None:
        if settings.SAVE_DATA_FILE.exists():
            confirmed = messagebox.askyesno(
                "Mulai Baru", "Data permainan yang ada akan ditimpa dan tidak bisa dikembalikan. Lanjutkan?"
            )
            if not confirmed:
                return
        fresh_save_data = SaveData.default()
        self._save_repository.save(fresh_save_data)
        self.scene_manager.transition_to(SceneType.LOADOUT)

    def _handle_continue(self) -> None:
        if not settings.SAVE_DATA_FILE.exists():
            return
        self.scene_manager.transition_to(SceneType.LEVEL_SELECT)

    def _handle_loadout(self) -> None:
        self.scene_manager.transition_to(SceneType.LOADOUT)

    def _handle_achievement(self) -> None:
        self.scene_manager.transition_to(SceneType.ACHIEVEMENT_GALLERY)

    def _handle_quit(self) -> None:
        self.scene_manager.request_exit()


def create_main_menu_scene(scene_manager: SceneManager) -> MainMenuScene:
    return MainMenuScene(scene_manager)