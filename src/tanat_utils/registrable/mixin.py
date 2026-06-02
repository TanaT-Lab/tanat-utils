#!/usr/bin/env python3
"""
Base class for registrable classes with automatic registration capabilities.

The implementation is largely inspired by the Registrable class in jrai_common_mixins (Mike Rye).

This version provides a registry system for classes that:
- Uses __init_subclass__ hook for automatic registration
- Supports case-insensitive registration and lookup
- Provides suggestions for misspelled names using difflib
"""

from difflib import get_close_matches
import logging

from pydantic_core import core_schema

from .exceptions import (
    RegistryError,
    InvalidRegistrationNameError,
    UnregisteredTypeError,
)

LOGGER = logging.getLogger(__name__)


class Registrable:
    """
    Base class for creating registrable class hierarchies.

    Subclasses are automatically registered via ``__init_subclass__``.
    Lookup is case-insensitive with close-match suggestions on error.
    Integrates with Pydantic for string-based validation and serialization.

    Example::

        class BaseMetric(Registrable):
            _REGISTER = {}

        class Euclidean(BaseMetric, register_name="euclidean"):
            pass

        BaseMetric.get_registered("euclidean")  # -> Euclidean
    """

    _REGISTER_NAME = "_REGISTER"

    def __init_subclass__(cls, *, register_name=None):
        """
        Register subclass in its base class registry.

        Args:
            register_name: Optional string to use as registration name.
                 If None, inferred from class name.

        Raises:
            AttributeError: If a direct Registrable class doesn't define _REGISTER_NAME
            InvalidRegistrationNameError: If the registration name is invalid
        """
        if register_name is not None:
            base_cls = cls.get_base_registry()
            register = getattr(base_cls, base_cls._REGISTER_NAME)
            register_name = cls.validate_registration_name(register_name)

            if register_name in register:
                LOGGER.warning(
                    "Registering %s with name %s [replaces %s]",
                    cls.__qualname__,
                    register_name,
                    register[register_name].__qualname__,
                )

            register[register_name] = cls

    @classmethod
    def validate_registration_name(cls, name):
        """Validate and normalize a registration name.

        Args:
            name: The registration name to validate

        Returns:
            str: The normalized (lowercase) registration name

        Raises:
            InvalidRegistrationNameError: If the name is invalid
        """
        if not name:
            raise InvalidRegistrationNameError("Registration name cannot be empty")
        return name.lower()

    @classmethod
    def get_base_registry(cls):
        """
        Get the base class containing the registry.

        Returns:
            Type[Registrable]: The base class containing the registry.
        """
        for base in cls.__mro__:
            if base is Registrable:
                break
            if hasattr(base, cls._REGISTER_NAME):
                return base
        raise RegistryError(
            f"Class {cls.__qualname__} must inherit from a class defining `{cls._REGISTER_NAME}`."
        )

    @classmethod
    def _get_register(cls):
        """
        Get the register dictionary from the base registry class.

        Returns:
            dict: The registry dictionary mapping names to classes
        """
        base_cls = cls.get_base_registry()
        return getattr(base_cls, cls._REGISTER_NAME)

    @classmethod
    def get_registration_name(cls_or_self):  # pylint: disable=bad-classmethod-argument
        """
        Get the registration name for this class.
        Works as both class method and instance method.

        Returns:
            str: The actual registration name used, or None if not found
        """
        target_cls = (
            cls_or_self if isinstance(cls_or_self, type) else cls_or_self.__class__
        )
        # pylint: disable=protected-access
        register = target_cls._get_register()
        for name, registered_cls in register.items():
            if registered_cls is target_cls:
                return name
        return None

    @classmethod
    def register(cls, register_name=None):
        """
        Explicitly register this class in its base registry.

        Args:
            register_name: Optional string to use as registration name.
                 If None, inferred from class name.

        Raises:
            InvalidRegistrationNameError: If the registration name is invalid
        """
        if register_name is None:
            register_name = cls.get_registration_name()
        name = cls.validate_registration_name(register_name)
        register = cls._get_register()
        if name in register:
            old_cls = register[name]
            LOGGER.warning(
                "Registering %s with name %s [replaces %s]",
                cls.__qualname__,
                name,
                old_cls.__qualname__,
            )
        register[name] = cls

    @classmethod
    def get_registered(cls, name: str):
        """Get a registered class by name (case-insensitive).

        Args:
            name: String name of the registered class to retrieve

        Returns:
            Type[Registrable]: The registered class

        Raises:
            UnregisteredTypeError: If no class is registered with the given name,
                    includes suggestions for close matches
        """
        name = cls.validate_registration_name(name)
        register = cls._get_register()
        try:
            return register[name]
        except KeyError:
            close_matches = get_close_matches(name, cls.list_registered())
            msg = f"No {cls.__name__} registered as '{name}'."
            if close_matches:
                msg += f" Did you mean '{close_matches[0]}'?"
            raise UnregisteredTypeError(msg) from None

    @classmethod
    def list_registered(cls):
        """
        List all registered names.

        Returns:
            list[str]: Sorted list of registered names
        """
        return sorted(cls._get_register().keys())

    @classmethod
    def clear_registered(cls):
        """Clear all registrations from the registry."""
        cls._get_register().clear()

    # -------------------------------------------------------------------------
    # Pydantic Support
    # -------------------------------------------------------------------------

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type, handler
    ):  # pylint: disable=unused-argument
        """
        Allow Pydantic to validate Registrable subclasses.

        Accepts:
        - An existing instance of the class (pass-through)
        - A string (looks up registered class and instantiates with defaults)

        Example:
            class MyModel(BaseModel):
                metric: BaseMetric  # BaseMetric is Registrable

            MyModel(metric="euclidean")  # Creates EuclideanMetric()
            MyModel(metric=EuclideanMetric())  # Pass-through
        """

        def validate(value):
            if isinstance(value, cls):
                return value
            if isinstance(value, str):
                return cls.get_registered(value)()
            if isinstance(value, dict):
                # Delegate to from_config if CachableSettings
                if hasattr(cls, "from_config"):
                    return cls.from_config(value)
                # Fallback: type only
                type_name = value.get("type")
                if type_name is None:
                    raise ValueError(
                        f"Dict config for {cls.__name__} must have 'type' key. "
                        f"Example: {{'type': '<name>'}}"
                    )
                return cls.get_registered(type_name)()

            # Build helpful error message
            registered = cls.list_registered()
            examples = f"'{registered[0]}'" if registered else "'<name>'"
            raise ValueError(
                f"Cannot create {cls.__name__} from {type(value).__name__}. "
                f"Expected: {cls.__name__} instance, str ({examples}), "
                f"or dict ({{'type': {examples}}}). "
                f"Registered types: {registered or '(none)'}"
            )

        def serialize(instance):
            # Use to_config if CachableSettings, else just the name
            if hasattr(instance, "to_config"):
                return instance.to_config()
            return instance.get_registration_name()

        return core_schema.no_info_plain_validator_function(
            validate,
            serialization=core_schema.plain_serializer_function_ser_schema(
                serialize,
                info_arg=False,
            ),
        )
