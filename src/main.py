#!/usr/bin/env python3
"""Точка входа FlatCraft.

Запускает игровое окно Arcade с экраном загрузки.
Мир генерируется в фоновом потоке во время загрузки.

Использование::
    linux: python3 -m src.main
        [--seed SEED] [--width W] [--height H]
    windows: python.exe -m src.main
        [--seed SEED] [--width W] [--height H]
"""

from __future__ import annotations

import argparse
import os
import sys

import arcade

from src.engine.game_window import FlatCraftWindow
from src.world.generator import GenerationConfig


def _parse_args() -> argparse.Namespace:
    """Парсит аргументы командной строки."""
    parser = argparse.ArgumentParser(
        description="FlatCraft - игра с процедурной генерацией мира")
    parser.add_argument(
        "--seed", type=int, default=42, help="Сид генерации (default: 42)"
    )
    parser.add_argument(
        "--width",
        type=int,
        default=500,
        help="Ширина мира в тайлах (default: 500)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=500,
        help="Высота мира в тайлах (default: 500)",
    )
    return parser.parse_args()


def _get_base_dir() -> str:
    """Определяет базовую директорию с ``assets/``."""
    candidates: list[str] = []
    if getattr(sys, "frozen", False):
        candidates.append(os.path.dirname(sys.executable))
        if __file__:
            candidates.append(os.path.dirname(os.path.abspath(__file__)))
    else:
        if __file__:
            candidates.append(os.path.dirname(os.path.abspath(__file__)))
    for d in candidates:
        if os.path.isdir(os.path.join(d, "assets")):
            return d
    return os.getcwd()


def main() -> None:
    """Запускает окно с экраном загрузки."""
    os.chdir(_get_base_dir())

    arcade.load_font("assets/fonts/JetBrainsMono-Regular.ttf")
    arcade.load_font("assets/fonts/JetBrainsMono-Bold.ttf")

    args = _parse_args()

    config = GenerationConfig(
        seed=args.seed,
        width=args.width,
        height=args.height,
    )

    FlatCraftWindow(config=config)
    arcade.run()


if __name__ == "__main__":
    main()
