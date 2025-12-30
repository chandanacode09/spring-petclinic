"""Data models for Java AST index."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from datetime import datetime
import json

if TYPE_CHECKING:
    from .schema_extractor import TableSchema
    from .api_extractor import ControllerInfo


@dataclass
class JavaParameter:
    """A method or constructor parameter."""
    name: str
    type: str
    annotations: List[str] = field(default_factory=list)
    is_varargs: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "annotations": self.annotations,
            "is_varargs": self.is_varargs,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JavaParameter":
        return cls(
            name=data["name"],
            type=data["type"],
            annotations=data.get("annotations", []),
            is_varargs=data.get("is_varargs", False),
        )

    def signature(self) -> str:
        """Return parameter as signature string."""
        type_str = self.type + "..." if self.is_varargs else self.type
        return f"{type_str} {self.name}"


@dataclass
class JavaField:
    """A class field."""
    name: str
    type: str
    modifiers: List[str] = field(default_factory=list)
    annotations: List[str] = field(default_factory=list)
    initial_value: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "modifiers": self.modifiers,
            "annotations": self.annotations,
            "initial_value": self.initial_value,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JavaField":
        return cls(
            name=data["name"],
            type=data["type"],
            modifiers=data.get("modifiers", []),
            annotations=data.get("annotations", []),
            initial_value=data.get("initial_value"),
        )


@dataclass
class JavaMethod:
    """A class method."""
    name: str
    return_type: str
    parameters: List[JavaParameter] = field(default_factory=list)
    modifiers: List[str] = field(default_factory=list)
    annotations: List[str] = field(default_factory=list)
    throws: List[str] = field(default_factory=list)
    type_parameters: List[str] = field(default_factory=list)  # Generic type params
    start_line: int = 0
    end_line: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "return_type": self.return_type,
            "parameters": [p.to_dict() for p in self.parameters],
            "modifiers": self.modifiers,
            "annotations": self.annotations,
            "throws": self.throws,
            "type_parameters": self.type_parameters,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JavaMethod":
        return cls(
            name=data["name"],
            return_type=data["return_type"],
            parameters=[JavaParameter.from_dict(p) for p in data.get("parameters", [])],
            modifiers=data.get("modifiers", []),
            annotations=data.get("annotations", []),
            throws=data.get("throws", []),
            type_parameters=data.get("type_parameters", []),
            start_line=data.get("start_line", 0),
            end_line=data.get("end_line", 0),
        )

    def signature(self) -> str:
        """Return method signature string."""
        mods = " ".join(self.modifiers)
        type_params = f"<{', '.join(self.type_parameters)}> " if self.type_parameters else ""
        params = ", ".join(p.signature() for p in self.parameters)
        throws = f" throws {', '.join(self.throws)}" if self.throws else ""
        return f"{mods} {type_params}{self.return_type} {self.name}({params}){throws}".strip()


@dataclass
class JavaConstructor:
    """A class constructor."""
    parameters: List[JavaParameter] = field(default_factory=list)
    modifiers: List[str] = field(default_factory=list)
    annotations: List[str] = field(default_factory=list)
    throws: List[str] = field(default_factory=list)
    type_parameters: List[str] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameters": [p.to_dict() for p in self.parameters],
            "modifiers": self.modifiers,
            "annotations": self.annotations,
            "throws": self.throws,
            "type_parameters": self.type_parameters,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JavaConstructor":
        return cls(
            parameters=[JavaParameter.from_dict(p) for p in data.get("parameters", [])],
            modifiers=data.get("modifiers", []),
            annotations=data.get("annotations", []),
            throws=data.get("throws", []),
            type_parameters=data.get("type_parameters", []),
            start_line=data.get("start_line", 0),
            end_line=data.get("end_line", 0),
        )

    def signature(self, class_name: str) -> str:
        """Return constructor signature string."""
        mods = " ".join(self.modifiers)
        params = ", ".join(p.signature() for p in self.parameters)
        throws = f" throws {', '.join(self.throws)}" if self.throws else ""
        return f"{mods} {class_name}({params}){throws}".strip()


@dataclass
class JavaClass:
    """A Java class, interface, enum, or record."""
    name: str
    fqn: str  # Fully qualified name
    kind: str = "class"  # class, interface, enum, record, annotation
    modifiers: List[str] = field(default_factory=list)
    annotations: List[str] = field(default_factory=list)
    extends: Optional[str] = None
    implements: List[str] = field(default_factory=list)
    type_parameters: List[str] = field(default_factory=list)
    constructors: List[JavaConstructor] = field(default_factory=list)
    methods: List[JavaMethod] = field(default_factory=list)
    fields: List[JavaField] = field(default_factory=list)
    inner_classes: List["JavaClass"] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0
    source_file: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "fqn": self.fqn,
            "kind": self.kind,
            "modifiers": self.modifiers,
            "annotations": self.annotations,
            "extends": self.extends,
            "implements": self.implements,
            "type_parameters": self.type_parameters,
            "constructors": [c.to_dict() for c in self.constructors],
            "methods": [m.to_dict() for m in self.methods],
            "fields": [f.to_dict() for f in self.fields],
            "inner_classes": [c.to_dict() for c in self.inner_classes],
            "start_line": self.start_line,
            "end_line": self.end_line,
            "source_file": self.source_file,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JavaClass":
        return cls(
            name=data["name"],
            fqn=data["fqn"],
            kind=data.get("kind", "class"),
            modifiers=data.get("modifiers", []),
            annotations=data.get("annotations", []),
            extends=data.get("extends"),
            implements=data.get("implements", []),
            type_parameters=data.get("type_parameters", []),
            constructors=[JavaConstructor.from_dict(c) for c in data.get("constructors", [])],
            methods=[JavaMethod.from_dict(m) for m in data.get("methods", [])],
            fields=[JavaField.from_dict(f) for f in data.get("fields", [])],
            inner_classes=[cls.from_dict(c) for c in data.get("inner_classes", [])],
            start_line=data.get("start_line", 0),
            end_line=data.get("end_line", 0),
            source_file=data.get("source_file", ""),
        )

    def get_method_at_line(self, line: int) -> Optional[JavaMethod]:
        """Find method containing the given line number."""
        for method in self.methods:
            if method.start_line <= line <= method.end_line:
                return method
        # Check inner classes
        for inner in self.inner_classes:
            method = inner.get_method_at_line(line)
            if method:
                return method
        return None

    def constructor_signatures(self) -> List[str]:
        """Get list of constructor signatures."""
        if not self.constructors:
            return [f"{self.name}()"]  # Default constructor
        return [c.signature(self.name) for c in self.constructors]


@dataclass
class JavaFile:
    """A parsed Java source file."""
    file_path: str
    package: str = ""
    imports: List[str] = field(default_factory=list)
    classes: List[JavaClass] = field(default_factory=list)
    parse_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file_path,
            "package": self.package,
            "imports": self.imports,
            "classes": [c.to_dict() for c in self.classes],
            "parse_errors": self.parse_errors,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JavaFile":
        return cls(
            file_path=data["file"],
            package=data.get("package", ""),
            imports=data.get("imports", []),
            classes=[JavaClass.from_dict(c) for c in data.get("classes", [])],
            parse_errors=data.get("parse_errors", []),
        )


@dataclass
class JavaIndex:
    """Complete index of a Java repository."""
    repo_name: str
    repo_path: str
    indexed_at: str = ""
    stats: Dict[str, int] = field(default_factory=dict)
    classes: Dict[str, JavaClass] = field(default_factory=dict)  # fqn -> class
    test_utilities: Dict[str, JavaClass] = field(default_factory=dict)  # fqn -> class
    packages: Dict[str, List[str]] = field(default_factory=dict)  # package -> class names
    files: Dict[str, JavaFile] = field(default_factory=dict)  # file_path -> parsed file
    # Schema context (populated by extractors)
    database_schemas: Dict[str, Any] = field(default_factory=dict)  # table_name -> TableSchema dict
    api_controllers: Dict[str, Any] = field(default_factory=dict)  # class_fqn -> ControllerInfo dict

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo": self.repo_name,
            "repo_path": self.repo_path,
            "indexed_at": self.indexed_at,
            "stats": self.stats,
            "classes": {fqn: c.to_dict() for fqn, c in self.classes.items()},
            "test_utilities": {fqn: c.to_dict() for fqn, c in self.test_utilities.items()},
            "packages": self.packages,
            "files": {path: f.to_dict() for path, f in self.files.items()},
            "database_schemas": self.database_schemas,
            "api_controllers": self.api_controllers,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JavaIndex":
        return cls(
            repo_name=data["repo"],
            repo_path=data.get("repo_path", ""),
            indexed_at=data.get("indexed_at", ""),
            stats=data.get("stats", {}),
            classes={fqn: JavaClass.from_dict(c) for fqn, c in data.get("classes", {}).items()},
            test_utilities={fqn: JavaClass.from_dict(c) for fqn, c in data.get("test_utilities", {}).items()},
            packages=data.get("packages", {}),
            files={path: JavaFile.from_dict(f) for path, f in data.get("files", {}).items()},
            database_schemas=data.get("database_schemas", {}),
            api_controllers=data.get("api_controllers", {}),
        )

    def save(self, path: str) -> None:
        """Save index to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "JavaIndex":
        """Load index from JSON file."""
        with open(path, "r") as f:
            return cls.from_dict(json.load(f))

    def lookup_class(self, name: str) -> Optional[JavaClass]:
        """Look up a class by name or FQN."""
        # Try direct FQN lookup
        if name in self.classes:
            return self.classes[name]
        if name in self.test_utilities:
            return self.test_utilities[name]

        # Try simple name lookup
        for fqn, cls in self.classes.items():
            if cls.name == name:
                return cls
        for fqn, cls in self.test_utilities.items():
            if cls.name == name:
                return cls

        return None

    def get_classes_in_package(self, package: str) -> List[JavaClass]:
        """Get all classes in a package."""
        class_names = self.packages.get(package, [])
        result = []
        for name in class_names:
            fqn = f"{package}.{name}"
            if fqn in self.classes:
                result.append(self.classes[fqn])
            elif fqn in self.test_utilities:
                result.append(self.test_utilities[fqn])
        return result

    def get_schema_for_entity(self, entity_name: str) -> Optional[Dict[str, Any]]:
        """Get database schema for an entity class."""
        # Try direct table name lookup
        entity_lower = entity_name.lower()
        for table_name, schema in self.database_schemas.items():
            if table_name.lower() == entity_lower:
                return schema
            if schema.get("entity_class_name", "").lower() == entity_lower:
                return schema
        return None

    def get_endpoints_for_entity(self, entity_name: str) -> List[Dict[str, Any]]:
        """Get API endpoints related to an entity."""
        entity_lower = entity_name.lower()
        matching = []

        for controller in self.api_controllers.values():
            # Check controller name
            if entity_lower in controller.get("class_name", "").lower():
                matching.extend(controller.get("endpoints", []))
            else:
                # Check endpoint paths/types
                for endpoint in controller.get("endpoints", []):
                    if entity_lower in endpoint.get("path", "").lower():
                        matching.append(endpoint)
                    elif entity_lower in endpoint.get("response_type", "").lower():
                        matching.append(endpoint)
                    elif entity_lower in (endpoint.get("request_body") or "").lower():
                        matching.append(endpoint)

        return matching

    def get_all_entities(self) -> List[str]:
        """Get all entity class names."""
        return [s.get("entity_class_name", "") for s in self.database_schemas.values()]

    def get_all_endpoints(self) -> List[Dict[str, Any]]:
        """Get all API endpoints."""
        endpoints = []
        for controller in self.api_controllers.values():
            endpoints.extend(controller.get("endpoints", []))
        return endpoints
