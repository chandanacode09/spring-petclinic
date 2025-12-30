"""Java repository indexer - walks repo and builds index."""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set

from tqdm import tqdm

from .models import JavaClass, JavaFile, JavaIndex
from .parser import JavaParser
from .schema_extractor import extract_jpa_schema, is_jpa_entity
from .api_extractor import extract_spring_endpoints, is_spring_controller

logger = logging.getLogger(__name__)


class JavaIndexer:
    """Index a Java repository by parsing all source files."""

    def __init__(self, repo_path: str):
        """
        Initialize indexer for a repository.

        Args:
            repo_path: Path to the repository root.
        """
        self.repo_path = Path(repo_path).resolve()
        self.parser = JavaParser()
        self.index: Optional[JavaIndex] = None

    def index_repo(self, show_progress: bool = True) -> JavaIndex:
        """
        Index the entire repository.

        Args:
            show_progress: Show progress bar.

        Returns:
            JavaIndex with all parsed classes.
        """
        repo_name = self.repo_path.name

        # Find all Java files
        java_files = self._find_java_files()
        logger.info(f"Found {len(java_files)} Java files in {repo_name}")

        # Initialize index
        self.index = JavaIndex(
            repo_name=repo_name,
            repo_path=str(self.repo_path),
            indexed_at=datetime.now().isoformat(),
        )

        # Parse each file
        iterator = tqdm(java_files, desc="Parsing") if show_progress else java_files
        parse_errors = 0

        for file_path in iterator:
            try:
                rel_path = str(file_path.relative_to(self.repo_path))
                parsed = self.parser.parse_file(str(file_path))
                parsed.file_path = rel_path

                if parsed.parse_errors:
                    parse_errors += 1
                    logger.warning(f"Parse errors in {rel_path}: {parsed.parse_errors}")

                # Add to index
                self._add_file_to_index(parsed, rel_path)

            except Exception as e:
                parse_errors += 1
                logger.error(f"Failed to process {file_path}: {e}")

        # Extract schemas and API info
        self._extract_schemas()

        # Calculate stats
        self.index.stats = {
            "total_files": len(java_files),
            "total_classes": len(self.index.classes) + len(self.index.test_utilities),
            "main_classes": len(self.index.classes),
            "test_utilities": len(self.index.test_utilities),
            "total_methods": sum(
                len(c.methods) for c in self.index.classes.values()
            ) + sum(
                len(c.methods) for c in self.index.test_utilities.values()
            ),
            "total_packages": len(self.index.packages),
            "parse_errors": parse_errors,
            "entity_count": len(self.index.database_schemas),
            "controller_count": len(self.index.api_controllers),
            "endpoint_count": sum(
                len(c.get("endpoints", [])) for c in self.index.api_controllers.values()
            ),
        }

        logger.info(f"Indexed {self.index.stats['total_classes']} classes, "
                   f"{self.index.stats['total_methods']} methods, "
                   f"{self.index.stats['entity_count']} entities, "
                   f"{self.index.stats['endpoint_count']} endpoints")

        return self.index

    def _find_java_files(self) -> List[Path]:
        """Find all Java source files in the repository."""
        java_files = []

        # Common source directories
        source_dirs = [
            "src/main/java",
            "src/test/java",
            "src",
            "java",
        ]

        found_dirs = set()
        for src_dir in source_dirs:
            full_path = self.repo_path / src_dir
            if full_path.exists():
                found_dirs.add(full_path)

        if not found_dirs:
            # Fall back to searching entire repo
            found_dirs.add(self.repo_path)

        for src_dir in found_dirs:
            for java_file in src_dir.rglob("*.java"):
                # Skip build directories
                if self._should_skip(java_file):
                    continue
                java_files.append(java_file)

        return sorted(java_files)

    def _should_skip(self, path: Path) -> bool:
        """Check if path should be skipped."""
        skip_patterns = [
            "target/",
            "build/",
            ".gradle/",
            "node_modules/",
            ".git/",
            "generated/",
            "generated-sources/",
        ]
        path_str = str(path)
        return any(pattern in path_str for pattern in skip_patterns)

    def _extract_schemas(self) -> None:
        """Extract database schemas and API endpoints from indexed classes."""
        # Extract JPA entity schemas
        for fqn, cls in self.index.classes.items():
            if is_jpa_entity(cls):
                try:
                    schema = extract_jpa_schema(cls)
                    if schema:
                        self.index.database_schemas[schema.table_name] = schema.to_dict()
                except Exception as e:
                    logger.warning(f"Failed to extract schema from {fqn}: {e}")

        # Extract Spring controller endpoints
        for fqn, cls in self.index.classes.items():
            if is_spring_controller(cls):
                try:
                    controller = extract_spring_endpoints(cls)
                    if controller:
                        self.index.api_controllers[fqn] = controller.to_dict()
                except Exception as e:
                    logger.warning(f"Failed to extract endpoints from {fqn}: {e}")

    def _add_file_to_index(self, parsed: JavaFile, rel_path: str) -> None:
        """Add a parsed file to the index."""
        self.index.files[rel_path] = parsed

        is_test = self._is_test_file(rel_path)

        for cls in parsed.classes:
            cls.source_file = rel_path
            self._add_class_to_index(cls, parsed.package, is_test)

    def _add_class_to_index(self, cls: JavaClass, package: str, is_test: bool) -> None:
        """Add a class (and its inner classes) to the index."""
        # Determine if this is a test utility
        is_test_utility = is_test and self._is_test_utility(cls)

        if is_test_utility:
            self.index.test_utilities[cls.fqn] = cls
        else:
            self.index.classes[cls.fqn] = cls

        # Add to package map
        if package not in self.index.packages:
            self.index.packages[package] = []
        if cls.name not in self.index.packages[package]:
            self.index.packages[package].append(cls.name)

        # Process inner classes
        for inner in cls.inner_classes:
            inner.source_file = cls.source_file
            self._add_class_to_index(inner, package, is_test)

    def _is_test_file(self, rel_path: str) -> bool:
        """Check if file is in test directory."""
        test_patterns = [
            "src/test/",
            "/test/",
            "Test.java",
            "Tests.java",
            "IT.java",  # Integration tests
        ]
        return any(pattern in rel_path for pattern in test_patterns)

    def _is_test_utility(self, cls: JavaClass) -> bool:
        """Check if class is a test utility (mock, helper, etc.)."""
        utility_patterns = [
            "Mock",
            "Fake",
            "Stub",
            "Helper",
            "Builder",
            "Factory",
            "Fixture",
            "TestUtil",
            "TestHelper",
            "TestData",
        ]

        # Check class name
        for pattern in utility_patterns:
            if pattern in cls.name:
                return True

        # Check if it's an abstract test base
        if "abstract" in cls.modifiers and "Test" in cls.name:
            return True

        return False

    def save_index(self, output_path: str) -> None:
        """Save index to JSON file."""
        if not self.index:
            raise ValueError("No index to save. Run index_repo() first.")
        self.index.save(output_path)
        logger.info(f"Saved index to {output_path}")

    @classmethod
    def load_index(cls, index_path: str) -> JavaIndex:
        """Load index from JSON file."""
        return JavaIndex.load(index_path)
