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
import importlib
import inspect
import logging
import pathlib

from pydantic_core import core_schema

from .exceptions import (
    RegistryError,
    InvalidRegistrationNameError,
    RegistryImportError,
    UnregisteredTypeError,
)

LOGGER = logging.getLogger(__name__)


def _find_modules(search_path, base_package):
    """
    Find Python modules recursively and generate valid module names.

    Args:
        search_path: Path to search for modules
        base_package: Base package name for imports

    Returns:
        List of fully qualified module names

    Raises:
        ImportError: If the search path doesn't exist or isn't a valid Python package
    """
    search_path = pathlib.Path(search_path).resolve()
    if not search_path.exists():
        raise ImportError(f"Module path not found: {search_path}")

    if not (search_path / "__init__.py").exists():
        raise ImportError(
            f"Not a valid Python package (missing __init__.py): {search_path}"
        )

    # Find the package root by looking for the first parent with __init__.py
    package_root = search_path
    while (
        package_root.parent.exists() and (package_root.parent / "__init__.py").exists()
    ):
        package_root = package_root.parent

    modules = []
    for file in search_path.rglob("*.py"):
        if file.name == "__init__.py":
            continue

        try:
            relative_path = file.relative_to(package_root)
            module_parts = list(relative_path.with_suffix("").parts)

            if base_package:
                module_parts.insert(0, base_package)

            modules.append(".".join(module_parts))

        except ValueError as e:
            LOGGER.warning("Failed to compute module name for %s: %s", file, e)

    return modules


def _import_types(suffix, base_class, submod="type"):
    """
    Import types from submodules dynamically.

    Args:
        suffix: Class name suffix to match (e.g., "Generator")
        base_class: Base class whose location will be used to find types
        submod: Subdirectory name to search in (default: "type")

    Yields:
        Classes that match the specified suffix and inherit from base_class

    Raises:
        ImportError: If the submodule path is not found
    """
    base_path = pathlib.Path(inspect.getfile(base_class)).parent
    base_module = base_class.__module__.split(".")[0]

    submod_path = (base_path / submod).resolve()
    if not submod_path.exists():
        raise ImportError(f"Submodule path not found: {submod_path}")

    LOGGER.debug("Importing types from %s (resolved to %s)", submod, submod_path)

    for module_name in _find_modules(submod_path, base_module):
        try:
            LOGGER.debug("Importing %s", module_name)
            mod = importlib.import_module(module_name)

            for name, cls in inspect.getmembers(mod):
                if (
                    name.endswith(suffix)
                    and cls != base_class
                    and inspect.isclass(cls)
                    and issubclass(cls, base_class)
                ):
                    LOGGER.debug("Found %s", name)
                    yield cls

        except ImportError as e:
            LOGGER.warning("Failed to import %s: %s", module_name, e)


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
    _TYPE_SUBMODULE = "../type"

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
    def get_registered(cls, name, retry_with_reload=True, submod=None):
        """
        Get a registered class by name.

        Performs case-insensitive lookup and suggests close matches if the exact name
        is not found. If the name is not found and retry_with_reload is True,
        attempts to reload the registry and try again.

        Args:
            name: String name of the registered class to retrieve
            retry_with_reload: If True and name not found, reload registry and retry once
            submod: Subdirectory name for reload if needed (default: None).
            If None, uses cls._TYPE_SUBMODULE

        Returns:
            Type[Registrable]: The registered class

        Raises:
            UnregisteredTypeError: If no class is registered with given name (even after reload),
                    includes suggestions for close matches
        """

        def raise_error(name, err):
            close_matches = get_close_matches(name, cls.list_registered())
            if close_matches:
                error_msg = (
                    f"No {cls.__name__} registered as '{name}'. "
                    f"Did you mean '{close_matches[0]}'?"
                )
            else:
                error_msg = f"No {cls.__name__} registered as '{name}'."
            raise UnregisteredTypeError(error_msg) from err

        name = cls.validate_registration_name(name)
        register = cls._get_register()
        if submod is None:
            submod = cls._TYPE_SUBMODULE

        try:
            return register[name]
        except KeyError as err:
            if retry_with_reload:
                try:
                    return cls._try_reload_and_get(name, submod)
                except (KeyError, RegistryImportError):
                    pass

            ## - retry_with_reload is False or reloading fails
            raise_error(name, err)

    @classmethod
    def _try_reload_and_get(cls, name, submod):
        """Try to reload registry and get registered class.

        Args:
            name: Name to look for after reload
            submod: Submodule to reload from

        Returns:
            The registered class if found

        Raises:
            RegistryImportError: If submodule import fails
            KeyError: If name not found after reload
        """
        LOGGER.debug("Trying to reload registry and search again.")
        cls.register_subtypes(submod=submod)
        return cls._get_register()[name]

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

    @classmethod
    def register_subtypes(cls, submod=None):
        """
        Import and register subtypes from the specified subdirectory.

        The registration is automatic through __init_subclass__, so this method
        just needs to trigger the imports.

        Args:
            submod: Subdirectory name where subtypes are located (default: None).
                If None, uses cls._TYPE_SUBMODULE

        Returns:
            tuple[type]: All registered subtype classes
        """
        if submod is None:
            submod = cls._TYPE_SUBMODULE

        if submod is None:  # if still None, nothing to do
            return ()
        return tuple(cls._import_subtypes(submod))

    @classmethod
    def reload(cls, submod=None, clear=True):
        """
        Reload the registration system by clearing and re-registering all subtypes.

        The method will:
        1. Clear all current registrations
        2. Re-scan and re-register all subtypes from the specified directory

        Args:
            clear: If True, clears all current registrations
            submod: Subdirectory name where subtypes are located (default: None).
                If None, uses cls._TYPE_SUBMODULE
        """
        if clear:
            cls.clear_registered()
        cls.register_subtypes(submod)

    @classmethod
    def _import_subtypes(cls, submod):
        """
        Import and yield all subtypes defined in the specified subdirectory.

        Args:
            submod: Subdirectory name where subtypes are located.

        Yields:
            Subtype classes found in the subdirectory.
        """
        try:
            yield from _import_types(cls.__name__, cls, submod=submod)
        except ImportError as err:
            LOGGER.debug("Failed to import subtypes: %s", err)
            raise RegistryImportError("Failed to import subtypes. " + str(err)) from err

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
