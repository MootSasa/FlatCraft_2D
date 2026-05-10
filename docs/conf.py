import os
import sys

sys.path.insert(0, os.path.abspath(".."))

project = "FlatCraft"
copyright = "2026, Artiukhova Uliana, Shamko Alexander"
author = "Artiukhova Uliana, Shamko Alexander"

release = "0.2.0"
version = "0.2.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns = ["_build"]

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}

napoleon_google_docstring = True
napoleon_use_param = True
napoleon_use_rtype = True
