#!/usr/bin/env python3
"""
Exceptions for the registrable mixin.
"""


class RegistryError(Exception):
    """Base exception for registry-related errors."""


class InvalidRegistrationNameError(RegistryError):
    """Raised when a registration name is invalid."""


class RegistryImportError(RegistryError):
    """Raised when there is an error importing subtypes from a module."""


class UnregisteredTypeError(RegistryError, ValueError):
    """Raised when a requested registration name is not found in the registry."""
