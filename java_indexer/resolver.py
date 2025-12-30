"""Import resolver - resolve class names to full class info."""

import logging
from typing import Dict, List, Optional, Set

from .models import JavaClass, JavaIndex, JavaFile

logger = logging.getLogger(__name__)


# Common Java standard library packages
JAVA_STDLIB_PACKAGES = {
    "java.lang",
    "java.util",
    "java.io",
    "java.nio",
    "java.net",
    "java.time",
    "java.math",
    "java.text",
    "java.sql",
    "java.security",
    "java.util.concurrent",
    "java.util.stream",
    "java.util.function",
    "java.util.regex",
}

# Common framework packages
FRAMEWORK_PACKAGES = {
    "org.springframework",
    "org.hibernate",
    "javax.persistence",
    "jakarta.persistence",
    "org.junit",
    "org.mockito",
    "org.assertj",
    "org.slf4j",
    "org.apache.commons",
    "com.google.common",
    "com.fasterxml.jackson",
}


class ImportResolver:
    """Resolve imports and class names to their definitions."""

    def __init__(self, index: JavaIndex):
        """
        Initialize resolver with an index.

        Args:
            index: The Java index to resolve against.
        """
        self.index = index
        self._build_simple_name_map()

    def _build_simple_name_map(self) -> None:
        """Build map from simple class name to list of FQNs."""
        self.simple_name_map: Dict[str, List[str]] = {}

        for fqn, cls in self.index.classes.items():
            if cls.name not in self.simple_name_map:
                self.simple_name_map[cls.name] = []
            self.simple_name_map[cls.name].append(fqn)

        for fqn, cls in self.index.test_utilities.items():
            if cls.name not in self.simple_name_map:
                self.simple_name_map[cls.name] = []
            self.simple_name_map[cls.name].append(fqn)

    def resolve(self, name: str, context_file: Optional[JavaFile] = None) -> Optional[JavaClass]:
        """
        Resolve a class name to its full definition.

        Args:
            name: Class name (simple or fully qualified).
            context_file: Optional file context for import resolution.

        Returns:
            JavaClass if found, None otherwise.
        """
        # Try direct FQN lookup
        if "." in name:
            cls = self.index.lookup_class(name)
            if cls:
                return cls

        # Try with context file imports
        if context_file:
            cls = self._resolve_with_imports(name, context_file)
            if cls:
                return cls

        # Try simple name lookup (may be ambiguous)
        fqns = self.simple_name_map.get(name, [])
        if len(fqns) == 1:
            return self.index.lookup_class(fqns[0])
        elif len(fqns) > 1:
            logger.warning(f"Ambiguous class name '{name}': {fqns}")
            # Return first match
            return self.index.lookup_class(fqns[0])

        return None

    def _resolve_with_imports(self, name: str, file: JavaFile) -> Optional[JavaClass]:
        """Resolve using file's import statements."""
        # Check explicit imports
        for imp in file.imports:
            # Skip static imports
            if imp.startswith("static "):
                continue

            # Direct import match
            if imp.endswith(f".{name}"):
                return self.index.lookup_class(imp)

            # Wildcard import
            if imp.endswith(".*"):
                package = imp[:-2]
                fqn = f"{package}.{name}"
                cls = self.index.lookup_class(fqn)
                if cls:
                    return cls

        # Check same package
        if file.package:
            fqn = f"{file.package}.{name}"
            cls = self.index.lookup_class(fqn)
            if cls:
                return cls

        # Check java.lang (always implicitly imported)
        java_lang_fqn = f"java.lang.{name}"
        # We don't have java.lang in our index, but mark it as external
        if name in ("String", "Object", "Integer", "Long", "Boolean", "Double",
                    "Float", "Byte", "Short", "Character", "Void", "Class",
                    "System", "Math", "Exception", "RuntimeException", "Error",
                    "Throwable", "Thread", "Runnable", "Comparable", "Iterable"):
            return None  # It's a known Java standard type

        return None

    def resolve_all_in_file(self, file: JavaFile) -> Dict[str, Optional[JavaClass]]:
        """
        Resolve all imports in a file.

        Returns:
            Dict mapping import string to resolved class (or None if external).
        """
        resolved = {}

        for imp in file.imports:
            if imp.startswith("static "):
                # Static import - try to resolve the class part
                parts = imp[7:].rsplit(".", 1)
                if len(parts) == 2:
                    class_part = parts[0]
                    resolved[imp] = self.resolve(class_part, file)
            elif imp.endswith(".*"):
                # Wildcard - resolve package
                package = imp[:-2]
                classes = self.get_package_classes(package)
                if classes:
                    resolved[imp] = classes[0] if classes else None
                else:
                    resolved[imp] = None  # External package
            else:
                resolved[imp] = self.resolve(imp, file)

        return resolved

    def get_package_classes(self, package: str) -> List[JavaClass]:
        """Get all classes in a package."""
        return self.index.get_classes_in_package(package)

    def is_external(self, fqn: str) -> bool:
        """Check if a class is external (not in our index)."""
        if fqn in self.index.classes or fqn in self.index.test_utilities:
            return False

        # Check if it's a known external package
        for pkg in JAVA_STDLIB_PACKAGES:
            if fqn.startswith(pkg + "."):
                return True

        for pkg in FRAMEWORK_PACKAGES:
            if fqn.startswith(pkg + "."):
                return True

        return True

    def get_class_dependencies(self, cls: JavaClass,
                              context_file: Optional[JavaFile] = None) -> Dict[str, Dict]:
        """
        Get all type dependencies of a class.

        Returns:
            Dict mapping type name to info about the dependency.
        """
        dependencies = {}
        seen_types: Set[str] = set()

        def add_type(type_str: str) -> None:
            """Add a type to dependencies."""
            # Extract base type from generics
            base_type = self._extract_base_type(type_str)
            if not base_type or base_type in seen_types:
                return
            if self._is_primitive(base_type):
                return

            seen_types.add(base_type)

            resolved = self.resolve(base_type, context_file)
            if resolved:
                dependencies[base_type] = {
                    "fqn": resolved.fqn,
                    "constructors": resolved.constructor_signatures(),
                    "source_file": resolved.source_file,
                    "external": False,
                }
            else:
                dependencies[base_type] = {
                    "fqn": base_type,
                    "external": True,
                }

            # Also process generic type arguments
            type_args = self._extract_type_arguments(type_str)
            for arg in type_args:
                add_type(arg)

        # Process extends
        if cls.extends:
            add_type(cls.extends)

        # Process implements
        for iface in cls.implements:
            add_type(iface)

        # Process fields
        for field in cls.fields:
            add_type(field.type)

        # Process constructors
        for ctor in cls.constructors:
            for param in ctor.parameters:
                add_type(param.type)
            for exc in ctor.throws:
                add_type(exc)

        # Process methods
        for method in cls.methods:
            add_type(method.return_type)
            for param in method.parameters:
                add_type(param.type)
            for exc in method.throws:
                add_type(exc)

        return dependencies

    def _extract_base_type(self, type_str: str) -> str:
        """Extract base type from a type string (strip generics, arrays)."""
        # Remove array brackets
        type_str = type_str.replace("[]", "")

        # Remove generic parameters
        if "<" in type_str:
            type_str = type_str[:type_str.index("<")]

        return type_str.strip()

    def _extract_type_arguments(self, type_str: str) -> List[str]:
        """Extract type arguments from generics."""
        if "<" not in type_str:
            return []

        # Simple extraction - doesn't handle nested generics perfectly
        start = type_str.index("<") + 1
        end = type_str.rindex(">")
        inner = type_str[start:end]

        # Split by comma, but respect nested generics
        args = []
        depth = 0
        current = ""
        for char in inner:
            if char == "<":
                depth += 1
                current += char
            elif char == ">":
                depth -= 1
                current += char
            elif char == "," and depth == 0:
                args.append(current.strip())
                current = ""
            else:
                current += char

        if current.strip():
            args.append(current.strip())

        return args

    def _is_primitive(self, type_str: str) -> bool:
        """Check if type is a Java primitive."""
        primitives = {"int", "long", "short", "byte", "float", "double",
                     "boolean", "char", "void"}
        return type_str in primitives
