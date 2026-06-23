from typing import ClassVar, TypeVar

T = TypeVar("T")


class DependencyContainer:
    _registry: ClassVar[dict[type, object]] = {}

    @classmethod
    def register(cls, key: type[T], instance: T) -> None:
        cls._registry[key] = instance

    @classmethod
    def resolve(cls, key: type[T]) -> T:
        instance = cls._registry.get(key)
        if instance is None:
            raise RuntimeError(f"{key.__name__} was not registered in the container.")
        return instance  # type: ignore[return-value]
