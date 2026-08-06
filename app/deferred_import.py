"""Small explicit proxy for application modules loaded only on first use."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType


class DeferredModule:
    """Expose a module-shaped object without importing its target eagerly.

    Failed imports are not cached, so a transient environment or dependency
    problem can be corrected and retried. Introspection and representation stay
    inert: only an actual attribute request resolves the target module.
    """

    __slots__ = ("_module", "_module_name")

    def __init__(self, module_name: str):
        if not isinstance(module_name, str) or not module_name:
            raise ValueError("module_name must be a non-empty string")
        self._module_name = module_name
        self._module: ModuleType | None = None

    @property
    def module_name(self) -> str:
        return self._module_name

    @property
    def loaded(self) -> bool:
        return self._module is not None

    def _resolve(self) -> ModuleType:
        module = self._module
        if module is None:
            module = import_module(self._module_name)
            self._module = module
        return module

    def __getattr__(self, name: str):
        return getattr(self._resolve(), name)

    def __dir__(self) -> list[str]:
        return ["loaded", "module_name"]

    def __repr__(self) -> str:
        state = "loaded" if self.loaded else "deferred"
        return f"DeferredModule({self.module_name!r}, {state})"


def deferred_module(module_name: str) -> DeferredModule:
    """Return a deferred proxy for ``module_name``."""

    return DeferredModule(module_name)
