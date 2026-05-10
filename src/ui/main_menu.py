"""Главный экран: выбор параметров генерации мира и управление."""

from __future__ import annotations

import random
from typing import Callable, Optional

import arcade
import arcade.gui as gui

from src.engine.input_manager import Action, ACTION_LABELS, InputManager
from src.world.generator import GenerationConfig
from src.utils.noise import NoiseParams

_FONT: str = "JetBrains Mono"


class MainMenu:
    """Главный экран FlatCraft.

    Позволяет задать параметры генерации мира,
    сгенерировать случайный сид и настроить управление.

    Attributes:
        visible: Видимость меню.
    """

    def __init__(
        self,
        config: GenerationConfig,
        on_play: Callable[[GenerationConfig], None],
        input_mgr: Optional[InputManager] = None,
    ) -> None:
        """Инициализация главного меню.

        Args:
            config: Настройки генерации по умолчанию.
            on_play: Callback при нажатии "Играть".
                Принимает GenerationConfig с выбранными параметрами.
            input_mgr: Менеджер ввода для страницы управления.
        """
        self.visible: bool = True
        self._config = config
        self._on_play = on_play
        self._input_mgr: InputManager = input_mgr or InputManager()

        # Фон главного меню
        self._bg_texture: Optional[arcade.Texture] = None
        try:
            self._bg_texture = arcade.load_texture(
                "assets/pics/Flatcraft.png"
            )
        except (FileNotFoundError, OSError):
            pass

        # Текущая страница меню: "main" или "controls"
        self._page: str = "main"

        # UIManager для главной страницы
        self._manager: Optional[gui.UIManager] = None
        self._seed_input: Optional[gui.UIInputText] = None
        self._width_input: Optional[gui.UIInputText] = None
        self._height_input: Optional[gui.UIInputText] = None
        self._sea_slider: Optional[gui.UISlider] = None
        self._freq_slider: Optional[gui.UISlider] = None
        self._sea_label: Optional[gui.UILabel] = None
        self._freq_label: Optional[gui.UILabel] = None

        # UIManager для страницы управления
        self._ctrl_manager: Optional[gui.UIManager] = None
        self._rebind_action: Optional[Action] = None
        self._rebind_mode: str = ""  # "key" or "gamepad"
        self._rebind_buttons: dict[Action, gui.UIFlatButton] = {}
        self._gp_rebind_buttons: dict[Action, gui.UIFlatButton] = {}
        self._rebind_hint: Optional[gui.UILabel] = None

    # ================================================================
    # Инициализация UI
    # ================================================================

    def _ensure_ui(self, window: arcade.Window) -> None:
        """Создаёт виджеты при первом показе."""
        if self._manager is not None:
            return

        self._manager = gui.UIManager()
        self._manager.enable()

        # Anchor layout - центрирование контента на экране
        anchor = gui.UIAnchorLayout()

        # Вертикальный контейнер для контента
        box = gui.UIBoxLayout(
            vertical=True,
            space_between=8,
            align="center",
        )

        # Заголовок
        title = gui.UILabel(
            text="FlatCraft",
            font_size=46,
            text_color=(80, 180, 255),
            font_name=_FONT,
        )
        box.add(title)

        subtitle = gui.UILabel(
            text="Параметры генерации мира",
            font_size=14,
            text_color=(150, 170, 200),
            font_name=_FONT,
        )
        box.add(subtitle)

        # Seed
        seed_row = gui.UIBoxLayout(
            vertical=False, space_between=8, align="center"
        )
        seed_label = gui.UILabel(
            text="Seed:", font_size=14, text_color=(200, 200, 200),
            font_name=_FONT,
        )
        seed_row.add(seed_label)

        self._seed_input = gui.UIInputText(
            text=str(self._config.seed),
            width=120,
            height=30,
            font_size=14,
            text_color=(255, 255, 255),
            font_name=_FONT,
        )
        seed_row.add(self._seed_input)

        random_btn = gui.UIFlatButton(
            text="Случайный",
            width=130,
            height=30,
            font_name=_FONT,
        )

        @random_btn.event("on_click")
        def on_random(event: gui.UIOnClickEvent) -> None:
            if self._seed_input is not None:
                self._seed_input.text = str(random.randint(1, 999999))

        seed_row.add(random_btn)
        box.add(seed_row)

        # Размер мира
        size_label = gui.UILabel(
            text="Размер мира (тайлы):",
            font_size=14,
            text_color=(200, 200, 200),
            font_name=_FONT,
        )
        box.add(size_label)

        size_row = gui.UIBoxLayout(
            vertical=False, space_between=10, align="center"
        )

        w_label = gui.UILabel(
            text="Ширина:", font_size=12, text_color=(170, 170, 170),
            font_name=_FONT,
        )
        size_row.add(w_label)
        self._width_input = gui.UIInputText(
            text=str(self._config.width),
            width=70,
            height=28,
            font_size=13,
            text_color=(255, 255, 255),
            font_name=_FONT,
        )
        size_row.add(self._width_input)

        h_label = gui.UILabel(
            text="Высота:", font_size=12, text_color=(170, 170, 170),
            font_name=_FONT,
        )
        size_row.add(h_label)
        self._height_input = gui.UIInputText(
            text=str(self._config.height),
            width=70,
            height=28,
            font_size=13,
            text_color=(255, 255, 255),
            font_name=_FONT,
        )
        size_row.add(self._height_input)
        box.add(size_row)

        # Уровень моря
        self._sea_label = gui.UILabel(
            text=f"Уровень моря: {self._config.sea_level:.2f}",
            font_size=15,
            text_color=(220, 220, 255),
            font_name=_FONT,
        )
        box.add(self._sea_label)

        sea_row = gui.UIBoxLayout(
            vertical=False, space_between=5, align="center"
        )
        sea_min = gui.UILabel(
            text="0.1", font_size=11, text_color=(220, 220, 255),
            font_name=_FONT,
        )
        sea_row.add(sea_min)

        self._sea_slider = gui.UISlider(
            value=self._config.sea_level,
            min_value=0.1,
            max_value=0.8,
            width=280,
            height=20,
        )

        @self._sea_slider.event
        def on_sea_change(event: gui.UIOnChangeEvent) -> None:
            if self._sea_label is not None and self._sea_slider is not None:
                self._sea_label.text = (
                    f"Уровень моря: {self._sea_slider.value:.2f}"
                )

        sea_row.add(self._sea_slider)
        sea_max = gui.UILabel(
            text="0.8", font_size=11, text_color=(220, 220, 255),
            font_name=_FONT,
        )
        sea_row.add(sea_max)
        box.add(sea_row)

        # Частота шума
        freq = self._config.continental_params.frequency
        self._freq_label = gui.UILabel(
            text=f"Частота шума: {freq:.4f}",
            font_size=15,
            text_color=(220, 220, 255),
            font_name=_FONT,
        )
        box.add(self._freq_label)

        freq_row = gui.UIBoxLayout(
            vertical=False, space_between=5, align="center"
        )
        freq_min = gui.UILabel(
            text="0.0005", font_size=11, text_color=(220, 220, 255),
            font_name=_FONT,
        )
        freq_row.add(freq_min)

        self._freq_slider = gui.UISlider(
            value=freq * 1000.0,
            min_value=0.5,
            max_value=5.0,
            width=240,
            height=20,
        )

        @self._freq_slider.event
        def on_freq_change(event: gui.UIOnChangeEvent) -> None:
            if self._freq_label is not None and self._freq_slider is not None:
                real_freq = self._freq_slider.value / 1000.0
                self._freq_label.text = (
                    f"Частота шума: {real_freq:.4f}"
                )

        freq_row.add(self._freq_slider)
        freq_max = gui.UILabel(
            text="0.005", font_size=11, text_color=(220, 220, 255),
            font_name=_FONT,
        )
        freq_row.add(freq_max)
        box.add(freq_row)

        # Кнопки "Играть" и "Управление"
        btn_row = gui.UIBoxLayout(
            vertical=False, space_between=15, align="center"
        )

        play_btn = gui.UIFlatButton(
            text="Играть",
            width=180,
            height=45,
            font_name=_FONT,
        )

        @play_btn.event("on_click")
        def on_play(event: gui.UIOnClickEvent) -> None:
            self._apply_and_play()

        btn_row.add(play_btn)

        ctrl_btn = gui.UIFlatButton(
            text="Управление",
            width=180,
            height=45,
            font_name=_FONT,
        )

        @ctrl_btn.event("on_click")
        def on_controls(event: gui.UIOnClickEvent) -> None:
            self._page = "controls"

        btn_row.add(ctrl_btn)
        box.add(btn_row)

        # Центрируем box на экране
        anchor.add(
            child=box,
            anchor_x="center",
            anchor_y="center",
        )

        self._manager.add(anchor)

    # ================================================================
    # Применение настроек
    # ================================================================

    def _apply_and_play(self) -> None:
        """Собирает настройки из виджетов и вызывает callback."""
        seed = self._config.seed
        width = self._config.width
        height = self._config.height
        sea_level = self._config.sea_level
        freq = self._config.continental_params.frequency

        # Seed
        if self._seed_input is not None:
            try:
                seed = int(self._seed_input.text)
            except ValueError:
                pass

        # Размер мира
        if self._width_input is not None:
            try:
                width = max(50, int(self._width_input.text))
            except ValueError:
                pass
        if self._height_input is not None:
            try:
                height = max(50, int(self._height_input.text))
            except ValueError:
                pass

        # Уровень моря
        if self._sea_slider is not None:
            sea_level = float(self._sea_slider.value)

        # Частота шума
        if self._freq_slider is not None:
            freq = float(self._freq_slider.value) / 1000.0

        # Создаём новый конфиг
        old = self._config
        new_params = NoiseParams(
            octaves=old.continental_params.octaves,
            frequency=freq,
            persistence=old.continental_params.persistence,
            lacunarity=old.continental_params.lacunarity,
        )
        new_config = GenerationConfig(
            seed=seed,
            width=width,
            height=height,
            chunk_size=old.chunk_size,
            sea_level=sea_level,
            deep_ocean_distance=old.deep_ocean_distance,
            gaussian_sigma=old.gaussian_sigma,
            min_biome_size=old.min_biome_size,
            ocean_moisture_weight=old.ocean_moisture_weight,
            warp_strength=old.warp_strength,
            continental_params=new_params,
            regional_params=old.regional_params,
            local_params=old.local_params,
            temperature_params=old.temperature_params,
            moisture_params=old.moisture_params,
            warp_params=old.warp_params,
            continental_weight=old.continental_weight,
            regional_weight=old.regional_weight,
            local_weight=old.local_weight,
        )

        self.visible = False
        self._on_play(new_config)

    # ================================================================
    # Страница управления
    # ================================================================

    def _ensure_controls_ui(self, window: arcade.Window) -> None:
        """Создаёт виджеты страницы управления."""
        if self._ctrl_manager is not None:
            return

        self._ctrl_manager = gui.UIManager()
        self._ctrl_manager.enable()

        anchor = gui.UIAnchorLayout()
        box = gui.UIBoxLayout(
            vertical=True, space_between=6, align="center"
        )

        # Заголовок
        title = gui.UILabel(
            text="Управление",
            font_size=28,
            text_color=(80, 180, 255),
            font_name=_FONT,
        )
        box.add(title)

        # Статус геймпада
        if self._input_mgr.controller_connected:
            gp_status = (
                f"Геймпад: {self._input_mgr.controller_name}"
            )
        elif self._input_mgr.controller_available:
            gp_status = "Геймпад: не подключён"
        else:
            gp_status = "Геймпад: недоступен"
        gp_label = gui.UILabel(
            text=gp_status,
            font_size=12,
            text_color=(130, 150, 170),
            font_name=_FONT,
        )
        box.add(gp_label)

        # Заголовки столбцов
        header_row = gui.UIBoxLayout(
            vertical=False, space_between=10, align="center"
        )
        header_row.add(gui.UILabel(
            text="Действие", width=200, font_size=13,
            text_color=(180, 200, 220), font_name=_FONT,
        ))
        header_row.add(gui.UILabel(
            text="Клавиша", width=140, font_size=13,
            text_color=(180, 200, 220), font_name=_FONT,
        ))
        header_row.add(gui.UILabel(
            text="Геймпад", width=140, font_size=13,
            text_color=(180, 200, 220), font_name=_FONT,
        ))
        box.add(header_row)

        # Строка для каждого действия
        self._rebind_buttons = {}
        self._gp_rebind_buttons = {}
        for action in Action:
            row = gui.UIBoxLayout(
                vertical=False, space_between=10, align="center"
            )

            # Название действия
            row.add(gui.UILabel(
                text=ACTION_LABELS.get(action, action.name),
                width=200, font_size=12,
                text_color=(200, 200, 200), font_name=_FONT,
            ))

            # Кнопка переназначения клавиши
            key_btn = gui.UIFlatButton(
                text=self._input_mgr.get_key_binding_text(action),
                width=140, height=28, font_name=_FONT,
            )

            @key_btn.event("on_click")
            def on_key_rebind(
                event: gui.UIOnClickEvent, a: Action = action
            ) -> None:
                self._input_mgr.start_rebind_key(a)
                self._rebind_action = a
                self._rebind_mode = "key"
                self._refresh_controls_buttons()

            row.add(key_btn)
            self._rebind_buttons[action] = key_btn

            # Кнопка переназначения геймпада
            gp_btn = gui.UIFlatButton(
                text=self._input_mgr.get_gamepad_binding_text(action),
                width=140, height=28, font_name=_FONT,
            )

            @gp_btn.event("on_click")
            def on_gp_rebind(
                event: gui.UIOnClickEvent, a: Action = action
            ) -> None:
                self._input_mgr.start_rebind_gamepad(a)
                self._rebind_action = a
                self._rebind_mode = "gamepad"
                self._refresh_controls_buttons()

            row.add(gp_btn)
            self._gp_rebind_buttons[action] = gp_btn
            box.add(row)

        # Подсказка переназначения
        self._rebind_hint = gui.UILabel(
            text="",
            font_size=12,
            text_color=(255, 200, 80),
            font_name=_FONT,
        )
        box.add(self._rebind_hint)

        # Кнопки "Сброс" и "Назад"
        bottom_row = gui.UIBoxLayout(
            vertical=False, space_between=15, align="center"
        )

        reset_btn = gui.UIFlatButton(
            text="Сбросить", width=140, height=35, font_name=_FONT,
        )

        @reset_btn.event("on_click")
        def on_reset(event: gui.UIOnClickEvent) -> None:
            self._input_mgr.reset_bindings()
            self._refresh_controls_buttons()

        bottom_row.add(reset_btn)

        back_btn = gui.UIFlatButton(
            text="Назад", width=140, height=35, font_name=_FONT,
        )

        @back_btn.event("on_click")
        def on_back(event: gui.UIOnClickEvent) -> None:
            self._page = "main"

        bottom_row.add(back_btn)
        box.add(bottom_row)

        anchor.add(child=box, anchor_x="center", anchor_y="center")
        self._ctrl_manager.add(anchor)

    def _refresh_controls_buttons(self) -> None:
        """Обновляет текст кнопок привязок на странице управления."""
        for action, btn in self._rebind_buttons.items():
            btn.text = self._input_mgr.get_key_binding_text(action)
        for action, btn in self._gp_rebind_buttons.items():
            btn.text = self._input_mgr.get_gamepad_binding_text(action)
        # Обновляем подсказку
        if self._rebind_hint is not None:
            if self._rebind_action is not None:
                if self._rebind_mode == "key":
                    self._rebind_hint.text = (
                        f"Нажмите клавишу для: "
                        f"{ACTION_LABELS.get(self._rebind_action, '')}"
                    )
                elif self._rebind_mode == "gamepad":
                    self._rebind_hint.text = (
                        f"Нажмите кнопку/стик для: "
                        f"{ACTION_LABELS.get(self._rebind_action, '')}"
                    )
            else:
                self._rebind_hint.text = ""

    # ================================================================
    # Отрисовка
    # ================================================================

    def draw(self, window: arcade.Window) -> None:
        """Отрисовывает главное меню.

        Переключает между главной страницей и страницей управления.

        Args:
            window: Игровое окно.
        """
        if not self.visible:
            if self._manager is not None:
                self._manager.disable()
            if self._ctrl_manager is not None:
                self._ctrl_manager.disable()
            return

        # Фон - картинка (cover: без сжатия, с обрезкой) или цвет
        if self._bg_texture is not None:
            tw = self._bg_texture.width
            th = self._bg_texture.height
            sw = window.width
            sh = window.height
            scale = max(sw / tw, sh / th)
            dw = tw * scale
            dh = th * scale
            cx = sw / 2
            cy = sh / 2
            rect = arcade.rect.LRBT(
                cx - dw / 2, cx + dw / 2,
                cy - dh / 2, cy + dh / 2,
            )
            arcade.draw_texture_rect(self._bg_texture, rect)
        else:
            arcade.draw_lrbt_rectangle_filled(
                0,
                window.width,
                0,
                window.height,
                (10, 25, 80),
            )

        if self._page == "controls":
            # Отключаем главный UIManager
            if self._manager is not None:
                self._manager.disable()
            # Страница управления
            self._ensure_controls_ui(window)
            # Проверяем завершение переназначения
            if self._rebind_action is not None:
                if self._input_mgr.rebind_action is None:
                    # Переназначение завершено
                    self._rebind_action = None
                    self._rebind_mode = ""
                    self._refresh_controls_buttons()
            if self._ctrl_manager is not None:
                self._ctrl_manager.enable()
                self._ctrl_manager.draw()
        else:
            # Отключаем UIManager управления
            if self._ctrl_manager is not None:
                self._ctrl_manager.disable()
            # Главная страница
            self._ensure_ui(window)
            if self._manager is not None:
                self._manager.enable()
                self._manager.draw()

    def handle_ui_event(self, event: object) -> bool:
        """Обрабатывает событие через активный UIManager."""
        if not self.visible:
            return False
        if self._page == "controls" and self._ctrl_manager is not None:
            result = self._ctrl_manager.on_event(event)
            return bool(result)
        if self._manager is not None:
            result = self._manager.on_event(event)
            return bool(result)
        return False

    def disable(self) -> None:
        """Отключает UIManager главного меню.

        Вызывается при уходе с главного меню,
        чтобы не перехватывать события мыши/клавиатуры.
        """
        if self._manager is not None:
            self._manager.disable()
        if self._ctrl_manager is not None:
            self._ctrl_manager.disable()
