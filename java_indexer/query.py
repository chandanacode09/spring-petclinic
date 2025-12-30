"""Query interface for context retrieval."""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from .models import JavaClass, JavaMethod, JavaIndex, JavaFile
from .resolver import ImportResolver

logger = logging.getLogger(__name__)


@dataclass
class ContextResult:
    """Result of a context query."""
    target: Optional[Dict[str, Any]] = None
    dependencies: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    available_test_utilities: List[Dict[str, str]] = field(default_factory=list)
    similar_tests: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "dependencies": self.dependencies,
            "available_test_utilities": self.available_test_utilities,
            "similar_tests": self.similar_tests,
        }


class ContextQuery:
    """Query interface for retrieving grounded context."""

    def __init__(self, index: JavaIndex):
        """
        Initialize query interface.

        Args:
            index: The Java index to query.
        """
        self.index = index
        self.resolver = ImportResolver(index)

    def query_context(self, file_path: str, line_number: int) -> ContextResult:
        """
        Get context for a specific file and line.

        Args:
            file_path: Path to the Java file (relative to repo root).
            line_number: Line number to get context for.

        Returns:
            ContextResult with target info, dependencies, and related context.
        """
        result = ContextResult()

        # Normalize file path
        file_path = self._normalize_path(file_path)

        # Get parsed file
        parsed_file = self.index.files.get(file_path)
        if not parsed_file:
            logger.warning(f"File not in index: {file_path}")
            return result

        # Find class and method at line
        target_class = None
        target_method = None

        for cls in parsed_file.classes:
            if cls.start_line <= line_number <= cls.end_line:
                target_class = cls
                target_method = cls.get_method_at_line(line_number)
                break

        if not target_class:
            logger.warning(f"No class found at line {line_number} in {file_path}")
            return result

        # Build target info
        result.target = {
            "class": target_class.name,
            "fqn": target_class.fqn,
            "kind": target_class.kind,
            "file": file_path,
        }

        if target_method:
            result.target["method"] = target_method.name
            result.target["signature"] = target_method.signature()
            result.target["line_range"] = {
                "start": target_method.start_line,
                "end": target_method.end_line,
            }

        # Get dependencies
        result.dependencies = self.resolver.get_class_dependencies(
            target_class, parsed_file
        )

        # Find available test utilities
        result.available_test_utilities = self._find_related_test_utilities(
            target_class, parsed_file
        )

        # Find similar tests
        result.similar_tests = self._find_similar_tests(target_class)

        return result

    def lookup_class(self, class_name: str) -> Optional[Dict[str, Any]]:
        """
        Look up a class by name or FQN.

        Args:
            class_name: Simple name or fully qualified name.

        Returns:
            Class info dict or None if not found.
        """
        cls = self.resolver.resolve(class_name)
        if not cls:
            return None

        return {
            "name": cls.name,
            "fqn": cls.fqn,
            "kind": cls.kind,
            "modifiers": cls.modifiers,
            "extends": cls.extends,
            "implements": cls.implements,
            "constructors": cls.constructor_signatures(),
            "methods": [m.signature() for m in cls.methods],
            "fields": [
                {"name": f.name, "type": f.type, "modifiers": f.modifiers}
                for f in cls.fields
            ],
            "source_file": cls.source_file,
        }

    def get_class_with_dependencies(self, class_name: str) -> Dict[str, Any]:
        """
        Get a class and all its dependencies.

        Args:
            class_name: Class name to look up.

        Returns:
            Dict with class info and dependencies.
        """
        cls = self.resolver.resolve(class_name)
        if not cls:
            return {"error": f"Class not found: {class_name}"}

        # Get the file for import context
        file = self.index.files.get(cls.source_file)

        return {
            "class": self.lookup_class(class_name),
            "dependencies": self.resolver.get_class_dependencies(cls, file),
        }

    def get_method_context(self, class_name: str, method_name: str) -> Dict[str, Any]:
        """
        Get context for a specific method.

        Args:
            class_name: Class containing the method.
            method_name: Method name.

        Returns:
            Method info and parameter type details.
        """
        cls = self.resolver.resolve(class_name)
        if not cls:
            return {"error": f"Class not found: {class_name}"}

        # Find the method
        method = None
        for m in cls.methods:
            if m.name == method_name:
                method = m
                break

        if not method:
            return {"error": f"Method not found: {method_name} in {class_name}"}

        # Get the file for import context
        file = self.index.files.get(cls.source_file)

        # Resolve parameter types
        param_types = {}
        for param in method.parameters:
            base_type = self.resolver._extract_base_type(param.type)
            if not self.resolver._is_primitive(base_type):
                resolved = self.resolver.resolve(base_type, file)
                if resolved:
                    param_types[param.name] = {
                        "type": param.type,
                        "fqn": resolved.fqn,
                        "constructors": resolved.constructor_signatures(),
                        "source_file": resolved.source_file,
                    }
                else:
                    param_types[param.name] = {
                        "type": param.type,
                        "external": True,
                    }

        return {
            "class": cls.name,
            "class_fqn": cls.fqn,
            "method": method.name,
            "signature": method.signature(),
            "return_type": method.return_type,
            "parameters": param_types,
            "annotations": method.annotations,
            "source_file": cls.source_file,
        }

    def find_implementations(self, interface_name: str) -> List[Dict[str, Any]]:
        """
        Find all classes implementing an interface.

        Args:
            interface_name: Interface name or FQN.

        Returns:
            List of implementing classes.
        """
        results = []

        # Resolve the interface to get its FQN
        interface_cls = self.resolver.resolve(interface_name)
        interface_fqn = interface_cls.fqn if interface_cls else interface_name

        for fqn, cls in self.index.classes.items():
            if interface_fqn in cls.implements or interface_name in cls.implements:
                results.append({
                    "name": cls.name,
                    "fqn": cls.fqn,
                    "source_file": cls.source_file,
                    "constructors": cls.constructor_signatures(),
                })

        return results

    def find_subclasses(self, class_name: str) -> List[Dict[str, Any]]:
        """
        Find all classes extending a class.

        Args:
            class_name: Class name or FQN.

        Returns:
            List of subclasses.
        """
        results = []

        # Resolve to get FQN
        parent_cls = self.resolver.resolve(class_name)
        parent_fqn = parent_cls.fqn if parent_cls else class_name

        for fqn, cls in self.index.classes.items():
            if cls.extends == parent_fqn or cls.extends == class_name:
                results.append({
                    "name": cls.name,
                    "fqn": cls.fqn,
                    "source_file": cls.source_file,
                    "constructors": cls.constructor_signatures(),
                })

        return results

    def _find_related_test_utilities(self, target_class: JavaClass,
                                     file: JavaFile) -> List[Dict[str, str]]:
        """Find test utilities related to the target class."""
        utilities = []

        # Look for utilities matching the class name
        target_name = target_class.name
        patterns = [
            f"Mock{target_name}",
            f"{target_name}Mock",
            f"Fake{target_name}",
            f"{target_name}Fake",
            f"{target_name}Builder",
            f"{target_name}Fixture",
            f"Test{target_name}",
            f"{target_name}TestHelper",
        ]

        for fqn, util_cls in self.index.test_utilities.items():
            for pattern in patterns:
                if util_cls.name == pattern or pattern in util_cls.name:
                    utilities.append({
                        "name": util_cls.name,
                        "fqn": util_cls.fqn,
                        "file": util_cls.source_file,
                        "constructors": util_cls.constructor_signatures(),
                    })
                    break

        # Also check imports for test utilities
        for imp in file.imports:
            if imp in self.index.test_utilities:
                util_cls = self.index.test_utilities[imp]
                if not any(u["fqn"] == util_cls.fqn for u in utilities):
                    utilities.append({
                        "name": util_cls.name,
                        "fqn": util_cls.fqn,
                        "file": util_cls.source_file,
                        "constructors": util_cls.constructor_signatures(),
                    })

        return utilities

    def _find_similar_tests(self, target_class: JavaClass) -> List[str]:
        """Find test files for the target class."""
        tests = []
        target_name = target_class.name

        # Common test naming patterns
        test_patterns = [
            f"{target_name}Test",
            f"{target_name}Tests",
            f"{target_name}IT",  # Integration test
            f"{target_name}IntegrationTest",
            f"Test{target_name}",
        ]

        for fqn, cls in self.index.classes.items():
            if any(cls.name == pattern for pattern in test_patterns):
                if cls.source_file and cls.source_file not in tests:
                    tests.append(cls.source_file)

        # Also check test utilities that might be actual tests
        for fqn, cls in self.index.test_utilities.items():
            if any(cls.name == pattern for pattern in test_patterns):
                if cls.source_file and cls.source_file not in tests:
                    tests.append(cls.source_file)

        return tests

    def _normalize_path(self, file_path: str) -> str:
        """Normalize file path to match index keys."""
        # Remove leading slashes
        file_path = file_path.lstrip("/")

        # If path starts with repo path, remove it
        if self.index.repo_path:
            repo_path = self.index.repo_path.rstrip("/") + "/"
            if file_path.startswith(repo_path):
                file_path = file_path[len(repo_path):]

        return file_path

    def get_package_summary(self, package: str) -> Dict[str, Any]:
        """
        Get summary of all classes in a package.

        Args:
            package: Package name.

        Returns:
            Summary with class names and brief info.
        """
        classes = self.index.get_classes_in_package(package)

        return {
            "package": package,
            "class_count": len(classes),
            "classes": [
                {
                    "name": cls.name,
                    "fqn": cls.fqn,
                    "kind": cls.kind,
                    "method_count": len(cls.methods),
                }
                for cls in classes
            ],
        }

    def search_classes(self, pattern: str) -> List[Dict[str, str]]:
        """
        Search for classes matching a pattern.

        Args:
            pattern: Search pattern (substring match).

        Returns:
            List of matching classes.
        """
        results = []
        pattern_lower = pattern.lower()

        for fqn, cls in self.index.classes.items():
            if pattern_lower in cls.name.lower() or pattern_lower in fqn.lower():
                results.append({
                    "name": cls.name,
                    "fqn": fqn,
                    "kind": cls.kind,
                    "source_file": cls.source_file,
                })

        for fqn, cls in self.index.test_utilities.items():
            if pattern_lower in cls.name.lower() or pattern_lower in fqn.lower():
                results.append({
                    "name": cls.name,
                    "fqn": fqn,
                    "kind": cls.kind,
                    "source_file": cls.source_file,
                    "is_test_utility": True,
                })

        return results
