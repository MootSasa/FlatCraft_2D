"""Игровое окно: ввод, связь мира/камеры/рендера."""

from __future__ import annotations

import logging
from typing import Any, Optional

import arcade

from src.engine.camera import GameCamera
from src.engine.input_manager import Action, InputManager
from src.engine.loading_screen import LoadingPhase, LoadingScreen
from src.engine.player import Player
from src.engine.renderer import Renderer
from src.ui.hud import HUD
from src.ui.main_menu import MainMenu
from src.utils.profiling import GameProfiler
from src.world.generator import GenerationConfig
from src.world.models import World

logger = logging.getLogger(__name__)

# Размер окна по умолчанию
_DEFAULT_WIDTH: int = 1280
_DEFAULT_HEIGHT: int = 720
_DEFAULT_TITLE: str = "FlatCraft"
# Размер тайла в пикселях
_DEFAULT_TILE_SIZE: int = 32
# Путь к музыке главного меню
_MENU_MUSIC_PATH: str = "assets/music/nyan_cat.mp3"


class FlatCraftWindow(arcade.Window):
    """Главное окно FlatCraft.

    Три режима работы:
    - Главное меню (MainMenu): выбор параметров генерации
    - Экран загрузки (LoadingScreen): генерация + анимация
    - Игровой режим: мир, камера, рендер, HUD

    Attributes:
        world: Сгенерированный мир.
        camera: Игровая камера.
        renderer: Рендер мира.
        tile_size: Размер тайла в пикселях.
        hud: Элементы интерфейса (миникарта, монитор производительности).
        player: Игровой персонаж Nyan Cat.
    """

    def __init__(
        self,
        config: GenerationConfig | None = None,
        width: int = _DEFAULT_WIDTH,
        height: int = _DEFAULT_HEIGHT,
        title: str = _DEFAULT_TITLE,
    ) -> None:
        """Инициализация окна.

        Args:
            config: Настройки генерации (по умолчанию).
            width: Ширина окна.
            height: Высота окна.
            title: Заголовок окна.
        """
        super().__init__(
            width=width,
            height=height,
            title=title,
            resizable=True,
        )
        self.tile_size = _DEFAULT_TILE_SIZE
        self._config = config or GenerationConfig()

        # Фон - цвет глубокого океана
        self.background_color = (10, 25, 80)

        # Частота обновления логики (120 раз/сек)
        self.set_update_rate(1.0 / 120)

        # FPS: среднее (EMA)
        self._fps_ema: float = 0.0
        self._fps_alpha: float = 0.1  # вес нового значения

        # Менеджер ввода (клавиатура + геймпад)
        self._input: InputManager = InputManager()

        # Главное меню (передаём InputManager для страницы управления)
        self._main_menu = MainMenu(
            config=self._config,
            on_play=self._on_play_from_menu,
            input_mgr=self._input,
        )

        # Экран загрузки (создаётся при старте генерации)
        self._loading_screen: LoadingScreen | None = None
        self._preload_notified: bool = False

        # Подсистемы - инициализируются лениво
        self.world: Optional[World] = None
        self.camera: Optional[GameCamera] = None
        self.renderer: Optional[Renderer] = None
        self.player: Optional[Player] = None
        self.hud: Optional[HUD] = None

        # Подтверждение Escape
        self._escape_pending: bool = False
        self._escape_timer: float = 0.0
        self._escape_timeout: float = 2.0  # секунды
        self._escape_msg = arcade.Text(
            "",
            0, 0,
            (255, 255, 255),
            font_size=18,
            anchor_x="center",
            anchor_y="center",
            font_name="JetBrains Mono",
        )

        # Профилировщик (pyinstrument)
        self._profiler: GameProfiler = GameProfiler()

        # Музыка главного меню (циклическая)
        self._menu_music: Optional[arcade.Sound] = None
        self._menu_music_player: Any = None
        self._menu_music_playing: bool = False
        self._menu_music_fade: float = 0.0  # оставшееся время затухания
        self._MENU_MUSIC_FADE_DURATION: float = 0.8  # секунды
        self._start_menu_music()

    # ================================================================
    # Переходы между экранами
    # ================================================================

    def _on_play_from_menu(self, config: GenerationConfig) -> None:
        """Callback из MainMenu - запуск генерации мира."""
        self._config = config

        # Отключаем UIManager главного меню, чтобы он
        # не перехватывал события мыши в игровом режиме
        self._main_menu.disable()

        # Начинаем затухание музыки при нажатии "Играть".
        self._fade_menu_music()

        self._start_loading(config)

    def _start_loading(self, config: GenerationConfig) -> None:
        """Запускает экран загрузки с генерацией мира."""
        self._loading_screen = LoadingScreen(
            window=self,
            config=config,
            tile_size=self.tile_size,
        )

    def _back_to_menu(self) -> None:
        """Возвращает в главное меню из игрового режима."""
        # Явная очистка ресурсов для уменьшения RSS.
        if self.renderer is not None:
            self.renderer.cleanup()
        if self.hud is not None:
            self.hud.cleanup()

        # Сбрасываем подсистемы
        if self.player is not None:
            self.player.stop_step_sound()
            self.player.stop_ambient_sound()
        self.world = None
        self.camera = None
        self.renderer = None
        self.player = None
        self.hud = None
        self._preload_notified = False

        # Принудительный сбор мусора для освобождения
        # циклических ссылок (SpriteList -> Sprite -> Texture)
        import gc
        gc.collect()

        # Показываем главное меню и запускаем музыку
        self._main_menu.visible = True
        self._start_menu_music()

    # ================================================================
    # Музыка главного меню
    # ================================================================

    def _start_menu_music(self) -> None:
        """Запускает циклическое воспроизведение музыки меню."""
        if self._menu_music_playing:
            return
        try:
            if self._menu_music is None:
                self._menu_music = arcade.Sound(_MENU_MUSIC_PATH)
            self._menu_music_player = self._menu_music.play(
                volume=0.5, loop=True
            )
            self._menu_music_playing = True
            self._menu_music_fade = 0.0
        except (FileNotFoundError, OSError, Exception) as exc:
            logger.warning("Не удалось воспроизвести музыку меню: %s", exc)

    def _fade_menu_music(self) -> None:
        """Начинает плавное затухание музыки меню."""
        if self._menu_music_playing:
            self._menu_music_fade = self._MENU_MUSIC_FADE_DURATION

    def _update_menu_music_fade(self, delta_time: float) -> None:
        """Обновляет громкость затухающей музыки каждый кадр."""
        if self._menu_music_fade <= 0 or not self._menu_music_playing:
            return
        self._menu_music_fade -= delta_time
        if self._menu_music_fade <= 0:
            self._menu_music_fade = 0.0
            self._stop_menu_music()
            return
        # Линейное затухание: от 0.5 до 0
        ratio = self._menu_music_fade / self._MENU_MUSIC_FADE_DURATION
        volume = 0.5 * ratio
        if self._menu_music_player is not None:
            try:
                self._menu_music_player.volume = volume
            except Exception:
                pass

    def _stop_menu_music(self) -> None:
        """Останавливает музыку главного меню."""
        if self._menu_music is not None and self._menu_music_playing:
            try:
                if self._menu_music_player is not None:
                    self._menu_music.stop(self._menu_music_player)
                else:
                    self._menu_music.stop()  # type: ignore[call-arg]
            except Exception:
                pass
            self._menu_music_playing = False
            self._menu_music_player = None
            self._menu_music_fade = 0.0

    # ================================================================
    # Ленивая инициализация подсистем
    # ================================================================

    def _init_game_subsystems(self, world: World) -> None:
        """Инициализирует игровые подсистемы (Renderer, Camera, Player, HUD).

        Вызывается после завершения генерации мира.

        Args:
            world: Сгенерированный мир.
        """
        self.world = world
        self.camera = GameCamera(
            window=self,
            world_width=world.width,
            world_height=world.height,
            tile_size=self.tile_size,
        )
        self.renderer = Renderer(world=world, tile_size=self.tile_size)
        self.player = Player(
            world_w=world.width,
            world_h=world.height,
            tile_size=self.tile_size,
            world=world,
        )
        self.hud = HUD(world=world)

    # ================================================================
    # Игровой цикл
    # ================================================================

    def on_draw(self) -> None:
        """Отрисовка кадра."""
        self.clear()

        # Главное меню
        if self._main_menu.visible:
            self.default_camera.use()
            self._main_menu.draw(self)
            # Подтверждение Escape (поверх меню)
            self._draw_escape_confirm()
            return

        # Экран загрузки
        if self._loading_screen is not None:
            phase = self._loading_screen.phase

            if phase == LoadingPhase.WORLD_REVEAL and self.camera is not None:
                # WORLD_REVEAL: рисуем мир игровой камерой
                assert self.renderer is not None
                self.camera.use()
                self.renderer.draw(self.camera, self.player)
                # Переключаемся на экранные координаты для маски
                self.default_camera.use()
            else:
                # GENERATING / CAT_FALL: экранные координаты
                self.default_camera.use()

            # Отрисовка экрана загрузки
            self._loading_screen.draw()
            return

        # Нормальный игровой режим - подсистемы гарантированно
        # инициализированы после завершения загрузки
        assert self.camera is not None
        assert self.renderer is not None
        assert self.player is not None
        assert self.hud is not None
        assert self.world is not None

        self.camera.use()
        self.renderer.draw(self.camera, self.player)

        # HUD (в экранных координатах)
        self.default_camera.use()

        cam_pos = self.camera.position
        visible = self.camera.visible_chunks(self.world.chunk_size)
        cs = self.world.chunk_size
        tile_count = len(visible) * cs * cs
        chunk_count = len(visible)

        self.hud.draw(
            screen_w=self.width,
            screen_h=self.height,
            fps=self._fps_ema,
            cam_x=float(cam_pos[0]),
            cam_y=float(cam_pos[1]),
            zoom=self.camera.zoom,
            tile_size=self.tile_size,
            tile_count=tile_count,
            chunk_count=chunk_count,
        )

        # Подтверждение Escape (поверх всего)
        self._draw_escape_confirm()

    def _draw_escape_confirm(self) -> None:
        """Отрисовывает сообщение подтверждения Escape."""
        if not self._escape_pending:
            return

        # Полупрозрачный фон
        arcade.draw_lrbt_rectangle_filled(
            0, self.width, 0, self.height,
            (0, 0, 0, 120),
        )

        self._escape_msg.x = self.width / 2
        self._escape_msg.y = self.height / 2
        self._escape_msg.draw()

    def on_update(self, delta_time: float) -> None:
        """Обновление логики каждый кадр.

        Args:
            delta_time: Время с прошлого кадра (сек).
        """
        # Таймер подтверждения Escape
        if self._escape_pending:
            self._escape_timer -= delta_time
            if self._escape_timer <= 0:
                self._escape_pending = False

        # Главное меню - обновляем InputManager
        # (геймпад, переназначение)
        if self._main_menu.visible:
            self._input.update()
            self._input.poll_gamepad_rebind()
            return

        # Экран загрузки
        if self._loading_screen is not None:
            self._loading_screen.update(delta_time)

            # Инициализация подсистем сразу после генерации (до CAT_FALL).
            # Предзагрузка чанков распределяется по кадрам,
            # чтобы не блокировать основной поток.
            if (
                self._loading_screen.is_world_ready()
                and self.world is None
            ):
                world = self._loading_screen.get_world()
                self._init_game_subsystems(world)

                # Камера на игроке
                assert self.camera is not None
                assert self.renderer is not None
                assert self.player is not None

                self.camera.follow(
                    self.player.world_x, self.player.world_y
                )
                self.camera.update(0, self._input)

            # Прогрессивная предзагрузка чанков
            if (
                self._loading_screen.is_world_ready()
                and self.world is not None
                and not self._loading_screen.is_done()
                and not self._preload_notified
            ):
                assert self.camera is not None
                assert self.renderer is not None
                built = self.renderer.build_pending_chunks(
                    self.camera, max_per_frame=2
                )
                # Все видимые чанки загружены - сигнал готовности
                if built == 0:
                    self._loading_screen.notify_subsystems_ready()
                    self._preload_notified = True

            # Полное завершение загрузки
            if self._loading_screen.is_done():
                self._loading_screen = None

            # Обновляем затухание музыки
            self._update_menu_music_fade(delta_time)

            return

        # Обновляем InputManager (очистка одноразовых событий,
        # проверка подключения геймпада, переназначение)
        self._input.update()
        self._input.poll_gamepad_rebind()

        # Обновляем затухание музыки (если ещё догорает)
        self._update_menu_music_fade(delta_time)

        # Обновляем игрока - подсистемы гарантированно не None
        assert self.player is not None
        assert self.camera is not None
        assert self.renderer is not None

        self.player.update(delta_time, self._input)

        # Камера следует за игроком
        self.camera.follow(self.player.world_x, self.player.world_y)
        self.camera.update(delta_time, self._input)

        # Меню через геймпад
        if self._input.just_pressed(Action.MENU):
            self._handle_menu_action()
            # _handle_menu_action мог вызвать _back_to_menu(),
            # обнулив подсистемы - прерываем обновление кадра
            if self._main_menu.visible:
                return

        # F3 - монитор производительности
        if self._input.just_pressed(Action.TOGGLE_PERF):
            assert self.hud is not None
            self.hud.toggle_perf()

        # F4 - профилировщик (вкл/выкл + автозахват)
        if self._input.just_pressed(Action.TOGGLE_PROFILER):
            self._profiler.toggle()
            if self._profiler.enabled and not self._profiler.is_capturing:
                self._profiler.start_capture(frames=300)

        # Отмечаем кадр для автозахвата профилировщика
        self._profiler.tick()

        # Прогрессивная загрузка чанков
        self.renderer.build_pending_chunks(
            self.camera, max_per_frame=2
        )

        # Обновляем FPS
        if delta_time > 0:
            instant_fps = 1.0 / delta_time
            if self._fps_ema <= 0:
                self._fps_ema = instant_fps
            else:
                self._fps_ema = (
                    self._fps_alpha * instant_fps
                    + (1.0 - self._fps_alpha) * self._fps_ema
                )

    # ================================================================
    # Ввод: клавиатура
    # ================================================================

    def on_key_press(self, key: int, modifiers: int) -> None:
        """Нажатие клавиши."""
        # Блокировка ввода во время загрузки
        if self._loading_screen is not None:
            return

        # Escape обрабатывается напрямую (подтверждение выхода),
        # минуя InputManager.
        if key == arcade.key.ESCAPE:
            if self._escape_pending:
                # Второе нажатие - подтверждено
                self._escape_pending = False
                if self._main_menu.visible:
                    self.close()
                else:
                    self._back_to_menu()
            else:
                # Первое нажатие - показываем подтверждение
                self._escape_pending = True
                self._escape_timer = self._escape_timeout
                if self._main_menu.visible:
                    self._escape_msg.text = (
                        "Нажмите Escape ещё раз для выхода"
                    )
                else:
                    self._escape_msg.text = (
                        "Нажмите Escape ещё раз "
                        "для возврата в меню"
                    )
            return

        # Передаём не ESC клавиши в InputManager
        self._input.handle_key_press(key)

        # Любая другая клавиша сбрасывает подтверждение
        if self._escape_pending:
            self._escape_pending = False

    def on_key_release(self, key: int, modifiers: int) -> None:
        """Отпускание клавиши."""
        # Блокировка ввода во время загрузки
        if self._loading_screen is not None:
            return

        # ESC не передаётся в InputManager (обрабатывается напрямую)
        if key != arcade.key.ESCAPE:
            self._input.handle_key_release(key)

    def _handle_menu_action(self) -> None:
        """Обрабатывает действие MENU (геймпад Start)."""
        if self._escape_pending:
            self._escape_pending = False
            if self._main_menu.visible:
                self.close()
            else:
                self._back_to_menu()
        else:
            self._escape_pending = True
            self._escape_timer = self._escape_timeout
            if self._main_menu.visible:
                self._escape_msg.text = (
                    "Нажмите Start ещё раз для выхода"
                )
            else:
                self._escape_msg.text = (
                    "Нажмите Start ещё раз "
                    "для возврата в меню"
                )

    # ================================================================
    # Ввод: мышь
    # ================================================================

    def on_mouse_scroll(
        self, x: int, y: int, scroll_x: float, scroll_y: float
    ) -> None:
        """Прокрутка колеса мыши (масштабирование)."""
        # Блокировка ввода во время загрузки / меню
        if self._loading_screen is not None:
            return
        if self._main_menu.visible:
            return

        assert self.camera is not None

        self.camera.handle_mouse_scroll(int(scroll_y))

    def on_mouse_press(
        self, x: float, y: float, button: int, modifiers: int
    ) -> None:
        """Клик мыши - проверяем миникарту."""
        # Блокировка ввода во время загрузки / меню
        if self._loading_screen is not None:
            return
        if self._main_menu.visible:
            return

        assert self.hud is not None
        assert self.player is not None

        if button == arcade.MOUSE_BUTTON_LEFT:
            if self.hud.on_mouse_press(x, y):
                # Клик попал в миникарту - перемещаем игрока
                world_x, world_y = self.hud.minimap_click_to_world(
                    x, y, self.tile_size
                )
                self.player.x = world_x
                self.player.y = world_y

    # ================================================================
    # События окна
    # ================================================================

    def on_resize(self, width: int, height: int) -> None:
        """Изменение размера окна."""
        super().on_resize(width, height)

        # Во время загрузки подсистемы ещё не созданы
        if self.camera is not None:
            self.camera.resize(width, height)
        if self.hud is not None:
            self.hud.on_resize(width, height)
