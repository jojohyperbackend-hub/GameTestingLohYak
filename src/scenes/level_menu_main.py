from __future__ import annotations

import json
import tkinter as tk
from typing import List, Optional

from src import settings
from src.data_manager import SaveData, create_save_data_repository
from src.logic import LevelConfig
from src.scene_manager import Scene, SceneManager, SceneType
from src.scenes.battle import create_battle_scene_factory


class LevelSelectSceneError(Exception):
    pass


def load_all_level_configs() -> List[LevelConfig]:
    if not settings.LEVELS_FILE.exists():
        raise LevelSelectSceneError("File levels.json tidak ditemukan")
    try:
        raw_data = json.loads(settings.LEVELS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise LevelSelectSceneError(f"levels.json rusak: {error}") from error
    entries = raw_data.get("levels", [])
    if not entries:
        raise LevelSelectSceneError("levels.json tidak memiliki data level")
    return [LevelConfig.from_dict(entry) for entry in sorted(entries, key=lambda e: e["level_id"])]


def is_level_unlocked(level_id: int, current_level: int) -> bool:
    return level_id <= max(current_level, 1)


class LevelSelectScene(Scene):
    def __init__(self, scene_manager: SceneManager):
        super().__init__(scene_manager)
        self._save_repository = create_save_data_repository()
        self._save_data: Optional[SaveData] = None
        self._level_configs: List[LevelConfig] = []
        self._frame: Optional[tk.Frame] = None

    def on_enter(self) -> None:
        root = self.scene_manager.get_tk_root()
        root.title("Pilih Level")

        self._save_data = self._save_repository.load()
        self._level_configs = load_all_level_configs()

        self._frame = tk.Frame(root, padx=32, pady=32, bg="#1a1a2e")
        self._frame.pack(fill="both", expand=True)

        title_label = tk.Label(
            self._frame, text="Pilih Level", font=("Consolas", 22, "bold"), fg="#f5f5f5", bg="#1a1a2e"
        )
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 24))

        for row_index, level_config in enumerate(self._level_configs, start=1):
            self._build_level_row(row_index, level_config)

        back_button = tk.Button(
            self._frame, text="Kembali", font=("Consolas", 12), width=16, command=self._handle_back
        )
        back_button.grid(row=len(self._level_configs) + 1, column=0, columnspan=3, pady=(24, 0))

    def _build_level_row(self, row_index: int, level_config: LevelConfig) -> None:
        unlocked = is_level_unlocked(level_config.level_id, self._save_data.current_level)
        highscore = self._save_data.highscore.get(level_config.level_id)

        name_label = tk.Label(
            self._frame,
            text=f"Level {level_config.level_id}: {level_config.name}",
            font=("Consolas", 14),
            fg="#f5f5f5" if unlocked else "#777777",
            bg="#1a1a2e",
            anchor="w",
        )
        name_label.grid(row=row_index, column=0, sticky="w", padx=(0, 16), pady=6)

        if unlocked:
            status_text = f"Skor Tertinggi: {highscore}" if highscore is not None else "Belum Dimainkan"
        else:
            status_text = "Terkunci"
        status_label = tk.Label(
            self._frame,
            text=status_text,
            font=("Consolas", 11),
            fg="#aaaaaa" if unlocked else "#555555",
            bg="#1a1a2e",
            anchor="w",
        )
        status_label.grid(row=row_index, column=1, sticky="w", padx=(0, 16), pady=6)

        play_button = tk.Button(
            self._frame,
            text="Main",
            font=("Consolas", 12),
            width=10,
            state="normal" if unlocked else "disabled",
            command=lambda level_id=level_config.level_id: self._handle_play(level_id),
        )
        play_button.grid(row=row_index, column=2, pady=6)

    def on_exit(self) -> None:
        if self._frame is not None:
            self._frame.destroy()
            self._frame = None

    def update(self, delta_time_seconds: float) -> None:
        pass

    def _handle_play(self, level_id: int) -> None:
        self.scene_manager.register_scene_factory(SceneType.BATTLE, create_battle_scene_factory(level_id))
        self.scene_manager.transition_to(SceneType.BATTLE)

    def _handle_back(self) -> None:
        self.scene_manager.transition_to(SceneType.MAIN_MENU)


def create_level_select_scene(scene_manager: SceneManager) -> LevelSelectScene:
    return LevelSelectScene(scene_manager)