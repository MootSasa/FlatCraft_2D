"""Менеджер ввода: клавиатура + геймпад + переназначение клавиш.

Обеспечивает унифицированный доступ к вводу:
- Аналоговое управление через левый стик геймпада
- Бинарные действия (бег, зум, меню, монитор)
- Переназначение клавиш и кнопок геймпада
- Автообнаружение геймпада
- Сохранение/загрузка привязок в JSON
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

import arcade

logger = logging.getLogger(__name__)

# Мёртвая зона для аналоговых стиков
_DEAD_ZONE: float = 0.15

# На Linux ось Y геймпада инвертирована относительно
# стандарта SDL2: +lefty = вниз вместо вверх.
# Инвертируем, чтобы +ly всегда = вверх в игровых координатах.
_Y_INVERT: int = -1 if sys.platform == "linux" else 1

# Порог триггеров (0..1)
_TRIGGER_THRESHOLD: float = 0.5

# Путь к файлу сохранения привязок
_BINDINGS_PATH: str = "assets/input_bindings.json"


class Action(Enum):
    """Игровые действия."""

    MOVE_UP = auto()
    MOVE_DOWN = auto()
    MOVE_LEFT = auto()
    MOVE_RIGHT = auto()
    RUN = auto()
    ZOOM_IN = auto()
    ZOOM_OUT = auto()
    MENU = auto()
    TOGGLE_PERF = auto()
    TOGGLE_PROFILER = auto()


# Названия действий
ACTION_LABELS: dict[Action, str] = {
    Action.MOVE_UP: "Движение вверх",
    Action.MOVE_DOWN: "Движение вниз",
    Action.MOVE_LEFT: "Движение влево",
    Action.MOVE_RIGHT: "Движение вправо",
    Action.RUN: "Бег",
    Action.ZOOM_IN: "Приблизить",
    Action.ZOOM_OUT: "Отдалить",
    Action.MENU: "Меню",
    Action.TOGGLE_PERF: "Монитор производительности (F3)",
    Action.TOGGLE_PROFILER: "Профилировщик (F4)",
}

# Названия кнопок геймпада для отображения
GAMEPAD_BUTTON_LABELS: dict[str, str] = {
    "a": "A", "b": "B", "x": "X", "y": "Y",
    "start": "Start", "back": "Back", "guide": "Guide",
    "leftshoulder": "LB", "rightshoulder": "RB",
    "lefttrigger": "LT", "righttrigger": "RT",
    "dpup": "D-Up", "dpdown": "D-Down",
    "dpleft": "D-Left", "dpright": "D-Right",
    "leftx+": "L-Stick >", "leftx-": "L-Stick <",
    "lefty+": "L-Stick v", "lefty-": "L-Stick ^",
    "rightx+": "R-Stick >", "rightx-": "R-Stick <",
    "righty+": "R-Stick v", "righty-": "R-Stick ^",
}


@dataclass
class KeyBindings:
    """Привязки клавиш к действиям.

    Attributes:
        bindings: action -> список кодов клавиш (arcade.key.*).
    """

    bindings: dict[Action, list[int]] = field(default_factory=dict)

    @classmethod
    def defaults(cls) -> KeyBindings:
        """Стандартные привязки клавиш."""
        return cls(bindings={
            Action.MOVE_UP: [arcade.key.W, arcade.key.UP],
            Action.MOVE_DOWN: [arcade.key.S, arcade.key.DOWN],
            Action.MOVE_LEFT: [arcade.key.A, arcade.key.LEFT],
            Action.MOVE_RIGHT: [arcade.key.D, arcade.key.RIGHT],
            Action.RUN: [arcade.key.LSHIFT, arcade.key.RSHIFT],
            Action.ZOOM_IN: [arcade.key.EQUAL, arcade.key.NUM_ADD],
            Action.ZOOM_OUT: [arcade.key.MINUS, arcade.key.NUM_SUBTRACT],
            # Action.MENU используется только для геймпада (Start).
            Action.MENU: [],
            Action.TOGGLE_PERF: [arcade.key.F3],
            Action.TOGGLE_PROFILER: [arcade.key.F4],
        })


@dataclass
class GamepadBindings:
    """Привязки кнопок/осей геймпада к действиям.

    Формат значений:
    - Кнопка: "a", "b", "x", "y", "start", "back",
      "leftshoulder", "rightshoulder",
      "lefttrigger", "righttrigger",
      "dpup", "dpdown", "dpleft", "dpright"
    - Ось: "leftx+", "leftx-", "lefty+", "lefty-",
      "rightx+", "rightx-", "righty+", "righty-"

    Attributes:
        bindings: action -> имя кнопки/оси геймпада.
    """

    bindings: dict[Action, str] = field(default_factory=dict)

    @classmethod
    def defaults(cls) -> GamepadBindings:
        """Стандартные привязки геймпада."""
        return cls(bindings={
            Action.MOVE_UP: "lefty-",
            Action.MOVE_DOWN: "lefty+",
            Action.MOVE_LEFT: "leftx-",
            Action.MOVE_RIGHT: "leftx+",
            Action.RUN: "a",
            Action.ZOOM_IN: "righttrigger",
            Action.ZOOM_OUT: "lefttrigger",
            Action.MENU: "start",
            Action.TOGGLE_PERF: "back",
        })


def _key_name(key: int) -> str:
    """Возвращает человекочитаемое название клавиши."""
    # Извлекаем из arcade.key атрибут с данным значением
    for attr in dir(arcade.key):
        if attr.startswith("_"):
            continue
        if getattr(arcade.key, attr, None) == key:
            name = attr.removeprefix("KEY_")
            if name in ("LSHIFT", "RSHIFT"):
                return "L-Shift" if name == "LSHIFT" else "R-Shift"
            if name in ("LCTRL", "RCTRL"):
                return "L-Ctrl" if name == "LCTRL" else "R-Ctrl"
            if name in ("LALT", "RALT"):
                return "L-Alt" if name == "LALT" else "R-Alt"
            if name == "ESCAPE":
                return "Esc"
            if name == "EQUAL":
                return "+"
            if name == "MINUS":
                return "-"
            if name == "NUM_ADD":
                return "Num+"
            if name == "NUM_SUBTRACT":
                return "Num-"
            if name.startswith("NUM_"):
                return "Num" + name[4:]
            if name in ("UP", "DOWN", "LEFT", "RIGHT"):
                return "^" if name == "UP" else (
                    "v" if name == "DOWN" else (
                        "<" if name == "LEFT" else ">"
                    )
                )
            return name.capitalize()
    return f"Key({key})"


def _gamepad_binding_label(binding: str) -> str:
    """Возвращает человекочитаемое название привязки геймпада."""
    return GAMEPAD_BUTTON_LABELS.get(binding, binding)


class InputManager:
    """Центральный менеджер ввода: клавиатура + геймпад.

    Поддерживает:
    - Аналоговое управление через левый стик геймпада
    - Бинарные действия (бег, зум, меню)
    - Переназначение клавиш и кнопок
    - Автообнаружение геймпада
    - Сохранение/загрузка привязок в JSON

    Attributes:
        key_bindings: Текущие привязки клавиш.
        gamepad_bindings: Текущие привязки геймпада.
    """

    def __init__(self) -> None:
        # Состояние клавиатуры
        self._keys_pressed: set[int] = set()
        self._keys_just_pressed: set[int] = set()
        self._keys_just_pressed_snap: set[int] = set()

        # Состояние геймпада
        self._controller: Optional[arcade.Controller] = None
        self._controller_manager: Optional[arcade.ControllerManager] = None
        self._prev_gamepad_buttons: set[str] = set()

        # Привязки
        self.key_bindings: KeyBindings = KeyBindings.defaults()
        self.gamepad_bindings: GamepadBindings = GamepadBindings.defaults()

        # Режим переназначения
        self._rebind_action: Optional[Action] = None
        self._rebind_mode: str = ""  # "key" or "gamepad"

        # Попытка инициализации ControllerManager
        self._init_controller_manager()

        # Загрузка сохранённых привязок
        self.load_bindings(_BINDINGS_PATH)

    # ================================================================
    # Инициализация геймпада
    # ================================================================

    def _init_controller_manager(self) -> None:
        """Инициализирует менеджер контроллеров."""
        try:
            self._controller_manager = arcade.ControllerManager()
            controllers = self._controller_manager.get_controllers()
            if controllers:
                self._controller = controllers[0]
                self._controller.open()
                logger.info("Геймпад подключён: %s", self._controller.name)
        except (OSError, Exception) as exc:
            logger.debug("ControllerManager недоступен: %s", exc)
            self._controller_manager = None

    # ================================================================
    # Клавиатура
    # ================================================================

    def handle_key_press(self, key: int) -> None:
        """Обрабатывает нажатие клавиши.

        Если активен режим переназначения - переназначает действие.

        Args:
            key: Код клавиши (arcade.key.*).
        """
        # Режим переназначения клавиши
        if self._rebind_action is not None and self._rebind_mode == "key":
            self.key_bindings.bindings[self._rebind_action] = [key]
            self._rebind_action = None
            self._rebind_mode = ""
            self.save_bindings(_BINDINGS_PATH)
            return

        self._keys_pressed.add(key)
        self._keys_just_pressed.add(key)

    def handle_key_release(self, key: int) -> None:
        """Обрабатывает отпускание клавиши.

        Args:
            key: Код клавиши.
        """
        self._keys_pressed.discard(key)

    # ================================================================
    # Обновление состояния
    # ================================================================

    def update(self) -> None:
        """Обновляет состояние ввода. Вызывается каждый кадр.

        Очищает одноразовые события и проверяет
        подключение новых контроллеров.
        """
        self._keys_just_pressed_snap = (
            self._keys_just_pressed.copy()
        )
        self._keys_just_pressed.clear()
        self._prev_gamepad_buttons = self._read_gamepad_buttons()

        # Проверяем подключение новых контроллеров
        if self._controller is None and self._controller_manager is not None:
            try:
                controllers = self._controller_manager.get_controllers()
                if controllers:
                    self._controller = controllers[0]
                    self._controller.open()
                    logger.info(
                        "Геймпад подключён: %s", self._controller.name
                    )
            except Exception:
                pass

    # ================================================================
    # Запрос состояния - движение
    # ================================================================

    def get_movement(self) -> tuple[float, float]:
        """Возвращает вектор движения (dx, dy) в диапазоне -1..1.

        Клавиатура даёт бинарные значения (-1/0/1),
        геймпад - аналоговые (-1..1).
        Геймпад приоритетнее при ненулевых значениях стика.

        Returns:
            (dx, dy): горизонтальное и вертикальное смещение.
        """
        # Клавиатура
        dx_kb = 0.0
        dy_kb = 0.0
        if self._is_key_action_active(Action.MOVE_LEFT):
            dx_kb -= 1.0
        if self._is_key_action_active(Action.MOVE_RIGHT):
            dx_kb += 1.0
        if self._is_key_action_active(Action.MOVE_UP):
            dy_kb += 1.0
        if self._is_key_action_active(Action.MOVE_DOWN):
            dy_kb -= 1.0

        # Геймпад
        dx_gp, dy_gp = self._read_movement_axes()

        dx = dx_gp if abs(dx_gp) > _DEAD_ZONE else dx_kb
        dy = dy_gp if abs(dy_gp) > _DEAD_ZONE else dy_kb

        return dx, dy

    # ================================================================
    # Запрос состояния
    # ================================================================

    def is_pressed(self, action: Action) -> bool:
        """Возвращает True, если действие активно в текущем кадре.

        Проверяет и клавиатуру, и геймпад.

        Args:
            action: Игровое действие.

        Returns:
            Активно ли действие.
        """
        return (
            self._is_key_action_active(action)
            or self._is_gamepad_action_active(action)
        )

    def just_pressed(self, action: Action) -> bool:
        """Возвращает True, если действие только что нажато.

        True только на первом кадре нажатия.
        Используется для одноразовых действий.

        Args:
            action: Игровое действие.

        Returns:
            Только что нажато ли действие.
        """
        # Клавиатура: проверяем снимок just_pressed
        keys = self.key_bindings.bindings.get(action, [])
        if any(
            k in self._keys_just_pressed_snap for k in keys
        ):
            return True

        # Геймпад: сравниваем текущее и предыдущее состояние
        if self._is_gamepad_action_active(action):
            if not self._was_gamepad_action_active(action):
                return True

        return False

    # ================================================================
    # Переназначение
    # ================================================================

    def start_rebind_key(self, action: Action) -> None:
        """Режим переназначения клавиши.

        Следующее нажатие клавиши назначится на данное действие.

        Args:
            action: Действие для переназначения.
        """
        self._rebind_action = action
        self._rebind_mode = "key"

    def start_rebind_gamepad(self, action: Action) -> None:
        """Режим переназначения кнопки геймпада.

        Следующее нажатие кнопки геймпада назначится на действие.

        Args:
            action: Действие для переназначения.
        """
        self._rebind_action = action
        self._rebind_mode = "gamepad"

    def cancel_rebind(self) -> None:
        """Отменяет режим переназначения."""
        self._rebind_action = None
        self._rebind_mode = ""

    @property
    def rebind_action(self) -> Optional[Action]:
        """Действие, ожидающее переназначения (None если нет)."""
        return self._rebind_action

    @property
    def rebind_mode(self) -> str:
        """Текущий режим переназначения: '' / 'key' / 'gamepad'."""
        return self._rebind_mode

    def reset_bindings(self) -> None:
        """Сбрасывает все привязки к умолчаниям."""
        self.key_bindings = KeyBindings.defaults()
        self.gamepad_bindings = GamepadBindings.defaults()
        self.save_bindings(_BINDINGS_PATH)

    # ================================================================
    # Сохранение/загрузка
    # ================================================================

    def save_bindings(self, path: str | Path) -> None:
        """Сохраняет привязки в JSON-файл.

        Args:
            path: Путь к файлу.
        """
        data = {
            "keys": {
                action.name: keys
                for action, keys in self.key_bindings.bindings.items()
            },
            "gamepad": {
                action.name: button
                for action, button in self.gamepad_bindings.bindings.items()
            },
        }
        try:
            Path(path).write_text(
                json.dumps(data, indent=2, ensure_ascii=False)
            )
        except OSError as exc:
            logger.warning("Не удалось сохранить привязки: %s", exc)

    def load_bindings(self, path: str | Path) -> None:
        """Загружает привязки из JSON-файла.

        Если файл не существует - использует умолчания.

        Args:
            path: Путь к файлу.
        """
        p = Path(path)
        if not p.exists():
            return

        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Не удалось загрузить привязки: %s", exc)
            return

        # Клавиши
        _ESCAPE_KEY = 65307
        for action_name, keys in data.get("keys", {}).items():
            try:
                action = Action[action_name]
                if isinstance(keys, list):
                    self.key_bindings.bindings[action] = [
                        int(k) for k in keys
                        if int(k) != _ESCAPE_KEY
                    ]
            except (KeyError, ValueError):
                pass

        # Геймпад
        for action_name, button in data.get("gamepad", {}).items():
            try:
                action = Action[action_name]
                if isinstance(button, str):
                    self.gamepad_bindings.bindings[action] = button
            except KeyError:
                pass

    # ================================================================
    # Информация о геймпаде
    # ================================================================

    @property
    def controller_connected(self) -> bool:
        """Подключён ли геймпад."""
        return self._controller is not None

    @property
    def controller_available(self) -> bool:
        """Доступна ли поддержка геймпада на данной платформе."""
        return self._controller_manager is not None

    @property
    def controller_name(self) -> str:
        """Имя подключённого геймпада."""
        if self._controller is None:
            return ""
        return getattr(self._controller, "name", "Unknown")

    # ================================================================
    # Отображение привязок
    # ================================================================

    def get_key_binding_text(self, action: Action) -> str:
        """Возвращает текстовое представление привязок клавиш.

        Args:
            action: Игровое действие.

        Returns:
            Строка вида "W / ^" или "не назначено".
        """
        keys = self.key_bindings.bindings.get(action, [])
        if not keys:
            return "не назначено"
        return " / ".join(_key_name(k) for k in keys)

    def get_gamepad_binding_text(self, action: Action) -> str:
        """Возвращает текстовое представление привязок геймпада.

        Args:
            action: Игровое действие.

        Returns:
            Строка вида "L-Stick ^" или "не назначено".
        """
        binding = self.gamepad_bindings.bindings.get(action)
        if binding is None:
            return "не назначено"
        return _gamepad_binding_label(binding)

    # ================================================================
    # Внутренние методы - клавиатура
    # ================================================================

    def _is_key_action_active(self, action: Action) -> bool:
        """Проверяет, активна ли клавиша для данного действия."""
        keys = self.key_bindings.bindings.get(action, [])
        return any(k in self._keys_pressed for k in keys)

    # ================================================================
    # Внутренние методы - геймпад
    # ================================================================

    def _read_movement_axes(self) -> tuple[float, float]:
        """Читает оси левого стика геймпада.

        Returns:
            (lx, ly): горизонтальная и вертикальная оси.
            +Y = вверх в игровых координатах.
        """
        if self._controller is None:
            return 0.0, 0.0

        try:
            lx: float = self._controller.leftx  # -1 (лево) .. 1 (право)
            ly: float = self._controller.lefty * _Y_INVERT  # +1 (верх)
            return lx, ly
        except (AttributeError, Exception):
            return 0.0, 0.0

    def _read_gamepad_buttons(self) -> set[str]:
        """Читает текущие нажатые кнопки геймпада.

        Returns:
            Множество имён нажатых кнопок.
        """
        if self._controller is None:
            return set()

        buttons: set[str] = set()
        button_names = [
            "a", "b", "x", "y",
            "start", "back", "guide",
            "leftshoulder", "rightshoulder",
            "dpup", "dpdown", "dpleft", "dpright",
        ]

        for name in button_names:
            try:
                if getattr(self._controller, name, False):
                    buttons.add(name)
            except Exception:
                pass

        # Триггеры как кнопки (порог)
        try:
            lt: float = getattr(self._controller, "lefttrigger", 0)
            if lt > _TRIGGER_THRESHOLD:
                buttons.add("lefttrigger")
        except Exception:
            pass
        try:
            rt: float = getattr(self._controller, "righttrigger", 0)
            if rt > _TRIGGER_THRESHOLD:
                buttons.add("righttrigger")
        except Exception:
            pass

        return buttons

    def _is_gamepad_action_active(self, action: Action) -> bool:
        """Проверяет, активно ли действие на геймпаде."""
        binding = self.gamepad_bindings.bindings.get(action)
        if binding is None or self._controller is None:
            return False

        # Оси (например "leftx+", "lefty-")
        if binding.endswith("+") or binding.endswith("-"):
            return self._check_axis_binding(binding)

        # Кнопки
        current_buttons = self._read_gamepad_buttons()
        return binding in current_buttons

    def _was_gamepad_action_active(self, action: Action) -> bool:
        """Проверяет, было ли действие активно на геймпаде в прошлом кадре."""
        binding = self.gamepad_bindings.bindings.get(action)
        if binding is None:
            return False

        # Для осей не отслеживаем just_pressed, так как они аналоговые
        if binding.endswith("+") or binding.endswith("-"):
            return self._is_gamepad_action_active(action)

        return binding in self._prev_gamepad_buttons

    def _check_axis_binding(self, binding: str) -> bool:
        """Проверяет, активна ли привязка оси геймпада.

        Args:
            binding: Имя оси с направлением, например "leftx+".

        Returns:
            Активна ли ось в указанном направлении.
        """
        if self._controller is None:
            return False

        direction = binding[-1]  # "+" or "-"
        axis_name = binding[:-1]  # "leftx", "lefty", etc.

        try:
            value: float = getattr(self._controller, axis_name, 0)
        except Exception:
            return False

        # Инверсия Y-осей на Linux (evdev даёт инвертированный lefty)
        if axis_name.endswith("y"):
            value *= _Y_INVERT

        if direction == "+":
            return value > _DEAD_ZONE
        else:
            return value < -_DEAD_ZONE

    def poll_gamepad_rebind(self) -> bool:
        """Проверяет нажатие кнопки геймпада для переназначения.

        Вызывается каждый кадр, пока активен режим
        переназначения геймпада (rebind_mode == "gamepad").

        Returns:
            True если кнопка была нажата и привязка обновлена.
        """
        if self._rebind_action is None or self._rebind_mode != "gamepad":
            return False
        if self._controller is None:
            return False

        # Проверяем кнопки
        current = self._read_gamepad_buttons()
        newly_pressed = current - self._prev_gamepad_buttons

        if newly_pressed:
            button = next(iter(newly_pressed))
            self.gamepad_bindings.bindings[self._rebind_action] = button
            self._rebind_action = None
            self._rebind_mode = ""
            self.save_bindings(_BINDINGS_PATH)
            return True

        # Проверяем оси (если стик отклонён значительно)
        axis_names = ["leftx", "lefty", "rightx", "righty"]
        for axis in axis_names:
            try:
                value: float = getattr(self._controller, axis, 0)
            except Exception:
                continue
            if value > 0.5:
                binding = f"{axis}+"
                self.gamepad_bindings.bindings[self._rebind_action] = binding
                self._rebind_action = None
                self._rebind_mode = ""
                self.save_bindings(_BINDINGS_PATH)
                return True
            if value < -0.5:
                binding = f"{axis}-"
                self.gamepad_bindings.bindings[self._rebind_action] = binding
                self._rebind_action = None
                self._rebind_mode = ""
                self.save_bindings(_BINDINGS_PATH)
                return True

        return False
