from __future__ import annotations

import tkinter as tk
from typing import Optional

from src.data_manager import SaveData, create_save_data_repository
from src.scene_manager import Scene, SceneManager, SceneType

ELEMENT_FIRE: str = "fire"
ELEMENT_ICE: str = "ice"
SELECTED_BUTTON_BG: str = "#e67e22"
UNSELECTED_BUTTON_BG: str = "#34495e"


class LoadoutScene(Scene):
    def __init__(self, scene_manager: SceneManager):
        super().__init__(scene_manager)
        self._save_repository = create_save_data_repository()
        self._save_data: Optional[SaveData] = None
        self._is_fresh_start: bool = False
        self._frame: Optional[tk.Frame] = None
        self._fire_button: Optional[tk.Button] = None
        self._ice_button: Optional[tk.Button] = None

    def on_enter(self) -> None:
        root = self.scene_manager.get_tk_root()
        root.title("Loadout")

        self._save_data = self._save_repository.load()
        self._is_fresh_start = (
            not self._save_data.hero.cleared_level_ids and self._save_data.current_level == 0
        )

        self._frame = tk.Frame(root, padx=40, pady=40, bg="#1a1a2e")
        self._frame.pack(fill="both", expand=True)

        title_label = tk.Label(
            self._frame, text="Loadout", font=("Consolas", 22, "bold"), fg="#f5f5f5", bg="#1a1a2e"
        )
        title_label.pack(pady=(0, 20))

        stats_frame = tk.Frame(self._frame, bg="#1a1a2e")
        stats_frame.pack(pady=(0, 24))
        hero = self._save_data.hero
        stat_lines = [
            f"HP   : {hero.max_hp}",
            f"ATK  : {hero.atk}",
            f"DEF  : {hero.def_}",
            f"SPD  : {hero.spd}",
        ]
        for stat_line in stat_lines:
            stat_label = tk.Label(
                stats_frame, text=stat_line, font=("Consolas", 13), fg="#dddddd", bg="#1a1a2e", anchor="w"
            )
            stat_label.pack(anchor="w")

        element_label = tk.Label(
            self._frame, text="Pilih Elemen Awal", font=("Consolas", 14), fg="#f5f5f5", bg="#1a1a2e"
        )
        element_label.pack(pady=(0, 10))

        element_buttons_frame = tk.Frame(self._frame, bg="#1a1a2e")
        element_buttons_frame.pack(pady=(0, 24))

        self._fire_button = tk.Button(
            element_buttons_frame,
            text="Pedang Api",
            font=("Consolas", 12, "bold"),
            width=14,
            command=self._handle_select_fire,
        )
        self._fire_button.grid(row=0, column=0, padx=8)

        self._ice_button = tk.Button(
            element_buttons_frame,
            text="Pedang Es",
            font=("Consolas", 12, "bold"),
            width=14,
            command=self._handle_select_ice,
        )
        self._ice_button.grid(row=0, column=1, padx=8)

        self._refresh_element_buttons()

        navigation_frame = tk.Frame(self._frame, bg="#1a1a2e")
        navigation_frame.pack(pady=(10, 0))

        back_button = tk.Button(
            navigation_frame, text="Kembali", font=("Consolas", 12), width=14, command=self._handle_back
        )
        back_button.grid(row=0, column=0, padx=8)

        continue_label = "Mulai Cerita" if self._is_fresh_start else "Lanjut"
        continue_button = tk.Button(
            navigation_frame, text=continue_label, font=("Consolas", 12), width=14, command=self._handle_continue
        )
        continue_button.grid(row=0, column=1, padx=8)

    def on_exit(self) -> None:
        if self._frame is not None:
            self._frame.destroy()
            self._frame = None
            self._fire_button = None
            self._ice_button = None

    def update(self, delta_time_seconds: float) -> None:
        pass

    def _handle_select_fire(self) -> None:
        self._save_data.element = ELEMENT_FIRE
        self._save_repository.save(self._save_data)
        self._refresh_element_buttons()

    def _handle_select_ice(self) -> None:
        self._save_data.element = ELEMENT_ICE
        self._save_repository.save(self._save_data)
        self._refresh_element_buttons()

    def _refresh_element_buttons(self) -> None:
        if self._fire_button is None or self._ice_button is None:
            return
        is_fire_selected = self._save_data.element == ELEMENT_FIRE
        self._fire_button.config(bg=SELECTED_BUTTON_BG if is_fire_selected else UNSELECTED_BUTTON_BG)
        self._ice_button.config(bg=UNSELECTED_BUTTON_BG if is_fire_selected else SELECTED_BUTTON_BG)

    def _handle_continue(self) -> None:
        next_scene_type = SceneType.STORY if self._is_fresh_start else SceneType.LEVEL_SELECT
        self.scene_manager.transition_to(next_scene_type)

    def _handle_back(self) -> None:
        self.scene_manager.transition_to(SceneType.MAIN_MENU)


def create_loadout_scene(scene_manager: SceneManager) -> LoadoutScene:
    return LoadoutScene(scene_manager)