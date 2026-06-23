# Thread-safe singleton, adapted from https://refactoring.guru/design-patterns/singleton/python/example#example-1
from threading import Lock
from typing import Any, ClassVar


class SingletonMeta(type):
    """A thread-safe implementation of Singleton."""

    _instances: ClassVar[dict[type, Any]] = {}
    _lock: ClassVar[Lock] = Lock()

    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        # Lock guards the first-access race: the first thread to acquire the
        # lock creates the instance; subsequent threads see it already set.
        with cls._lock:
            if cls not in cls._instances:
                instance = super().__call__(*args, **kwargs)
                cls._instances[cls] = instance
        return cls._instances[cls]
