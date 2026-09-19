"""Third-party extension point. `Plugin` has the identical hook shape as a
built-in `DerivativeWorker` — `PluginLoader` and `DerivativePool` treat both
uniformly (see plugins/loader.py, derivatives/pool.py). What a `Plugin`
adds on top: an `id` the config-store namespaces its settings under, and an
optional `config_schema` the loader validates those settings against before
construction.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from caelum.derivatives.base import DerivativeWorker


class Plugin(DerivativeWorker):
    id: ClassVar[str]
    config_schema: ClassVar[type[BaseModel] | None] = None

    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings
