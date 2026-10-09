from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable, List, Optional, Union

from src.data_manager import EssayQuestion, MultipleChoiceQuestion
from src.logic import EssayAnswerValidator

QuizQuestion = Union[MultipleChoiceQuestion, EssayQuestion]


@dataclass
class QuizOutcome:
    is_correct: bool
    elapsed_seconds: float
    was_timeout: bool
    was_cancelled: bool


TIMER_BAR_UPDATE_INTERVAL_MILLISECONDS: int = 33
TIMER_BAR_WIDTH_PX: int = 360
TIMER_BAR_HEIGHT_PX: int = 14


class QuizPopup:
    def __init__(
        self,
        tk_root: tk.Tk,
        question: QuizQuestion,
        time_limit_seconds: Optional[float],
        on_complete: Callable[[QuizOutcome], None],
        essay_min_group_ratio: float = 1.0,
    ):
        if not isinstance(question, (MultipleChoiceQuestion, EssayQuestion)):
            raise TypeError("question harus berupa MultipleChoiceQuestion atau EssayQuestion")

        self._tk_root = tk_root
        self._question = question
        self._time_limit_seconds = time_limit_seconds
        self._on_complete = on_complete
        self._essay_min_group_ratio = essay_min_group_ratio
        self._has_completed: bool = False
        self._start_time_seconds: float = time.monotonic()
        self._timeout_after_id: Optional[str] = None
        self._timer_bar_after_id: Optional[str] = None
        self._timer_deadline_seconds: Optional[float] = None
        self._timer_canvas: Optional[tk.Canvas] = None
        self._timer_bar_rect_id: Optional[int] = None
        self._essay_text_widget: Optional[tk.Text] = None

        self._toplevel = tk.Toplevel(tk_root)
        self._toplevel.title("Kuis")
        self._toplevel.resizable(False, False)
        self._toplevel.attributes("-topmost", True)
        self._toplevel.protocol("WM_DELETE_WINDOW", self._handle_cancel)

        self._build_widgets()

        if self._time_limit_seconds is not None:
            self._start_timer()

    def _build_widgets(self) -> None:
        container = tk.Frame(self._toplevel, padx=16, pady=16)
        container.pack(fill="both", expand=True)

        if self._time_limit_seconds is not None:
            self._timer_canvas = tk.Canvas(
                container,
                width=TIMER_BAR_WIDTH_PX,
                height=TIMER_BAR_HEIGHT_PX,
                highlightthickness=0,
                bg="#2b2b2b",
            )
            self._timer_canvas.pack(pady=(0, 12))
            self._timer_bar_rect_id = self._timer_canvas.create_rectangle(
                0, 0, TIMER_BAR_WIDTH_PX, TIMER_BAR_HEIGHT_PX, fill="#4caf50", width=0
            )

        question_label = tk.Label(
            container,
            text=self._question.question_text,
            wraplength=TIMER_BAR_WIDTH_PX,
            justify="left",
            font=("Consolas", 12, "bold"),
        )
        question_label.pack(pady=(0, 12))

        if isinstance(self._question, MultipleChoiceQuestion):
            self._build_multiple_choice_widgets(container, self._question.options)
        else:
            self._build_essay_widgets(container)

    def _build_multiple_choice_widgets(self, container: tk.Frame, options: List[str]) -> None:
        options_frame = tk.Frame(container)
        options_frame.pack(fill="x")
        for option_index, option_text in enumerate(options):
            option_button = tk.Button(
                options_frame,
                text=option_text,
                font=("Consolas", 11),
                anchor="w",
                justify="left",
                wraplength=TIMER_BAR_WIDTH_PX - 20,
                command=lambda index=option_index: self._handle_multiple_choice_selected(index),
            )
            option_button.pack(fill="x", pady=4)

    def _build_essay_widgets(self, container: tk.Frame) -> None:
        self._essay_text_widget = tk.Text(container, width=42, height=5, font=("Consolas", 11), wrap="word")
        self._essay_text_widget.pack(pady=(0, 12))
        self._essay_text_widget.focus_set()
        submit_button = tk.Button(
            container, text="Jawab", font=("Consolas", 11, "bold"), command=self._handle_essay_submit
        )
        submit_button.pack()

    def _start_timer(self) -> None:
        self._timer_deadline_seconds = self._start_time_seconds + self._time_limit_seconds
        timeout_milliseconds = max(0, int(self._time_limit_seconds * 1000))
        self._timeout_after_id = self._tk_root.after(timeout_milliseconds, self._handle_timeout)
        self._update_timer_bar()

    def _update_timer_bar(self) -> None:
        if self._has_completed or self._timer_deadline_seconds is None:
            return
        remaining_seconds = self._timer_deadline_seconds - time.monotonic()
        remaining_ratio = max(0.0, min(1.0, remaining_seconds / self._time_limit_seconds))
        bar_width = int(TIMER_BAR_WIDTH_PX * remaining_ratio)
        if self._timer_canvas is not None and self._timer_bar_rect_id is not None:
            bar_color = "#4caf50" if remaining_ratio > 0.3 else "#e53935"
            self._timer_canvas.coords(self._timer_bar_rect_id, 0, 0, bar_width, TIMER_BAR_HEIGHT_PX)
            self._timer_canvas.itemconfig(self._timer_bar_rect_id, fill=bar_color)
        if remaining_ratio > 0.0:
            self._timer_bar_after_id = self._tk_root.after(
                TIMER_BAR_UPDATE_INTERVAL_MILLISECONDS, self._update_timer_bar
            )

    def _handle_multiple_choice_selected(self, selected_index: int) -> None:
        if self._has_completed:
            return
        question = self._question
        assert isinstance(question, MultipleChoiceQuestion)
        is_correct = selected_index == question.answer_index
        self._finish(is_correct, was_timeout=False, was_cancelled=False)

    def _handle_essay_submit(self) -> None:
        if self._has_completed:
            return
        question = self._question
        assert isinstance(question, EssayQuestion)
        answer_text = self._essay_text_widget.get("1.0", "end") if self._essay_text_widget else ""
        is_correct = EssayAnswerValidator.validate(
            answer_text, question.keyword_groups, self._essay_min_group_ratio
        )
        self._finish(is_correct, was_timeout=False, was_cancelled=False)

    def _handle_timeout(self) -> None:
        if self._has_completed:
            return
        self._finish(False, was_timeout=True, was_cancelled=False)

    def _handle_cancel(self) -> None:
        if self._has_completed:
            return
        self._finish(False, was_timeout=False, was_cancelled=True)

    def _finish(self, is_correct: bool, was_timeout: bool, was_cancelled: bool) -> None:
        self._has_completed = True
        elapsed_seconds = time.monotonic() - self._start_time_seconds
        if self._timeout_after_id is not None:
            try:
                self._tk_root.after_cancel(self._timeout_after_id)
            except tk.TclError:
                pass
            self._timeout_after_id = None
        if self._timer_bar_after_id is not None:
            try:
                self._tk_root.after_cancel(self._timer_bar_after_id)
            except tk.TclError:
                pass
            self._timer_bar_after_id = None
        if self._toplevel.winfo_exists():
            self._toplevel.destroy()
        outcome = QuizOutcome(
            is_correct=is_correct,
            elapsed_seconds=elapsed_seconds,
            was_timeout=was_timeout,
            was_cancelled=was_cancelled,
        )
        self._on_complete(outcome)


def open_multiple_choice_quiz(
    tk_root: tk.Tk,
    question: MultipleChoiceQuestion,
    time_limit_seconds: Optional[float],
    on_complete: Callable[[QuizOutcome], None],
) -> QuizPopup:
    return QuizPopup(tk_root, question, time_limit_seconds, on_complete)


def open_essay_quiz(
    tk_root: tk.Tk,
    question: EssayQuestion,
    time_limit_seconds: Optional[float],
    min_group_ratio: float,
    on_complete: Callable[[QuizOutcome], None],
) -> QuizPopup:
    return QuizPopup(tk_root, question, time_limit_seconds, on_complete, essay_min_group_ratio=min_group_ratio)