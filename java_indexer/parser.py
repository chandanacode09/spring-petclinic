"""Java AST parser using tree-sitter."""

import logging
from pathlib import Path
from typing import List, Optional, Tuple

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser, Node

from .models import (
    JavaParameter,
    JavaField,
    JavaMethod,
    JavaConstructor,
    JavaClass,
    JavaFile,
)

logger = logging.getLogger(__name__)

# Initialize tree-sitter
JAVA_LANGUAGE = Language(tsjava.language())


class JavaParser:
    """Parse Java source files using tree-sitter AST."""

    def __init__(self):
        self.parser = Parser(JAVA_LANGUAGE)

    def parse_file(self, file_path: str) -> JavaFile:
        """Parse a Java source file and extract structure."""
        path = Path(file_path)
        if not path.exists():
            return JavaFile(
                file_path=file_path,
                parse_errors=[f"File not found: {file_path}"]
            )

        try:
            source = path.read_bytes()
            tree = self.parser.parse(source)
            return self._extract_file(tree.root_node, source, file_path)
        except Exception as e:
            logger.error(f"Failed to parse {file_path}: {e}")
            return JavaFile(
                file_path=file_path,
                parse_errors=[str(e)]
            )

    def parse_source(self, source: str, file_path: str = "<string>") -> JavaFile:
        """Parse Java source code string."""
        try:
            source_bytes = source.encode("utf-8")
            tree = self.parser.parse(source_bytes)
            return self._extract_file(tree.root_node, source_bytes, file_path)
        except Exception as e:
            logger.error(f"Failed to parse source: {e}")
            return JavaFile(
                file_path=file_path,
                parse_errors=[str(e)]
            )

    def _get_text(self, node: Node, source: bytes) -> str:
        """Get text content of a node."""
        return source[node.start_byte:node.end_byte].decode("utf-8")

    def _extract_file(self, root: Node, source: bytes, file_path: str) -> JavaFile:
        """Extract file-level information."""
        package = ""
        imports = []
        classes = []
        errors = []

        for child in root.children:
            if child.type == "package_declaration":
                package = self._extract_package(child, source)
            elif child.type == "import_declaration":
                imp = self._extract_import(child, source)
                if imp:
                    imports.append(imp)
            elif child.type in ("class_declaration", "interface_declaration",
                               "enum_declaration", "record_declaration",
                               "annotation_type_declaration"):
                try:
                    cls = self._extract_class(child, source, package, file_path)
                    if cls:
                        classes.append(cls)
                except Exception as e:
                    errors.append(f"Error parsing class: {e}")
            elif child.type == "ERROR":
                errors.append(f"Parse error at line {child.start_point[0] + 1}")

        return JavaFile(
            file_path=file_path,
            package=package,
            imports=imports,
            classes=classes,
            parse_errors=errors,
        )

    def _extract_package(self, node: Node, source: bytes) -> str:
        """Extract package name."""
        for child in node.children:
            if child.type == "scoped_identifier" or child.type == "identifier":
                return self._get_text(child, source)
        return ""

    def _extract_import(self, node: Node, source: bytes) -> Optional[str]:
        """Extract import statement."""
        # Handle static imports
        is_static = any(c.type == "static" for c in node.children)

        for child in node.children:
            if child.type in ("scoped_identifier", "identifier"):
                imp = self._get_text(child, source)
                if is_static:
                    imp = f"static {imp}"
                return imp
            elif child.type == "asterisk":
                # Handle wildcard imports
                for c in node.children:
                    if c.type == "scoped_identifier":
                        return self._get_text(c, source) + ".*"
        return None

    def _extract_class(self, node: Node, source: bytes, package: str,
                       file_path: str, outer_class: str = "") -> Optional[JavaClass]:
        """Extract class/interface/enum/record information."""
        kind_map = {
            "class_declaration": "class",
            "interface_declaration": "interface",
            "enum_declaration": "enum",
            "record_declaration": "record",
            "annotation_type_declaration": "annotation",
        }
        kind = kind_map.get(node.type, "class")

        name = ""
        modifiers = []
        annotations = []
        extends = None
        implements = []
        type_parameters = []
        constructors = []
        methods = []
        fields = []
        inner_classes = []

        for child in node.children:
            if child.type == "modifiers":
                mods, annots = self._extract_modifiers(child, source)
                modifiers = mods
                annotations = annots
            elif child.type == "identifier":
                name = self._get_text(child, source)
            elif child.type == "type_parameters":
                type_parameters = self._extract_type_parameters(child, source)
            elif child.type == "superclass":
                extends = self._extract_superclass(child, source)
            elif child.type == "super_interfaces" or child.type == "extends_interfaces":
                implements = self._extract_interfaces(child, source)
            elif child.type == "class_body" or child.type == "interface_body" or \
                 child.type == "enum_body" or child.type == "record_declaration_body" or \
                 child.type == "annotation_type_body":
                body_result = self._extract_class_body(child, source, package, file_path, name)
                constructors = body_result["constructors"]
                methods = body_result["methods"]
                fields = body_result["fields"]
                inner_classes = body_result["inner_classes"]
            elif child.type == "formal_parameters":
                # Record parameters (treated as fields and constructor)
                record_params = self._extract_record_parameters(child, source)
                fields.extend(record_params)
                if record_params:
                    # Add implicit constructor
                    constructors.append(JavaConstructor(
                        parameters=[JavaParameter(name=f.name, type=f.type) for f in record_params],
                        modifiers=["public"],
                        start_line=node.start_point[0] + 1,
                        end_line=node.start_point[0] + 1,
                    ))

        if not name:
            return None

        # Build FQN
        if outer_class:
            fqn = f"{outer_class}.{name}"
        elif package:
            fqn = f"{package}.{name}"
        else:
            fqn = name

        return JavaClass(
            name=name,
            fqn=fqn,
            kind=kind,
            modifiers=modifiers,
            annotations=annotations,
            extends=extends,
            implements=implements,
            type_parameters=type_parameters,
            constructors=constructors,
            methods=methods,
            fields=fields,
            inner_classes=inner_classes,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            source_file=file_path,
        )

    def _extract_modifiers(self, node: Node, source: bytes) -> Tuple[List[str], List[str]]:
        """Extract modifiers and annotations from a modifiers node."""
        modifiers = []
        annotations = []

        for child in node.children:
            if child.type == "marker_annotation" or child.type == "annotation":
                annot = self._get_text(child, source)
                annotations.append(annot)
            elif child.type in ("public", "private", "protected", "static",
                               "final", "abstract", "synchronized", "native",
                               "transient", "volatile", "strictfp", "default"):
                modifiers.append(child.type)

        return modifiers, annotations

    def _extract_type_parameters(self, node: Node, source: bytes) -> List[str]:
        """Extract generic type parameters like <T, E extends Number>."""
        params = []
        for child in node.children:
            if child.type == "type_parameter":
                params.append(self._get_text(child, source))
        return params

    def _extract_superclass(self, node: Node, source: bytes) -> Optional[str]:
        """Extract superclass from extends clause."""
        for child in node.children:
            if child.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                return self._extract_type(child, source)
        return None

    def _extract_interfaces(self, node: Node, source: bytes) -> List[str]:
        """Extract implemented interfaces."""
        interfaces = []
        for child in node.children:
            if child.type == "type_list":
                for type_child in child.children:
                    if type_child.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                        interfaces.append(self._extract_type(type_child, source))
            elif child.type in ("type_identifier", "scoped_type_identifier", "generic_type"):
                interfaces.append(self._extract_type(child, source))
        return interfaces

    def _extract_type(self, node: Node, source: bytes) -> str:
        """Extract a type, handling generics like List<String>."""
        if node.type == "generic_type":
            base_type = ""
            type_args = []
            for child in node.children:
                if child.type in ("type_identifier", "scoped_type_identifier"):
                    base_type = self._get_text(child, source)
                elif child.type == "type_arguments":
                    type_args = self._extract_type_arguments(child, source)
            if type_args:
                return f"{base_type}<{', '.join(type_args)}>"
            return base_type
        elif node.type == "array_type":
            element_type = ""
            dims = ""
            for child in node.children:
                if child.type == "dimensions":
                    dims = self._get_text(child, source)
                else:
                    element_type = self._extract_type(child, source)
            return f"{element_type}{dims}"
        elif node.type == "scoped_type_identifier":
            return self._get_text(node, source)
        elif node.type == "type_identifier":
            return self._get_text(node, source)
        elif node.type in ("integral_type", "floating_point_type", "boolean_type", "void_type"):
            return self._get_text(node, source)
        else:
            return self._get_text(node, source)

    def _extract_type_arguments(self, node: Node, source: bytes) -> List[str]:
        """Extract type arguments from <T, E>."""
        args = []
        for child in node.children:
            if child.type == "wildcard":
                args.append(self._get_text(child, source))
            elif child.type in ("type_identifier", "scoped_type_identifier",
                               "generic_type", "array_type"):
                args.append(self._extract_type(child, source))
        return args

    def _extract_class_body(self, node: Node, source: bytes, package: str,
                           file_path: str, class_name: str) -> dict:
        """Extract class body: constructors, methods, fields, inner classes."""
        constructors = []
        methods = []
        fields = []
        inner_classes = []

        outer_fqn = f"{package}.{class_name}" if package else class_name

        for child in node.children:
            if child.type == "constructor_declaration":
                ctor = self._extract_constructor(child, source)
                if ctor:
                    constructors.append(ctor)
            elif child.type == "method_declaration":
                method = self._extract_method(child, source)
                if method:
                    methods.append(method)
            elif child.type == "field_declaration":
                fields.extend(self._extract_fields(child, source))
            elif child.type in ("class_declaration", "interface_declaration",
                               "enum_declaration", "record_declaration"):
                inner = self._extract_class(child, source, package, file_path, outer_fqn)
                if inner:
                    inner_classes.append(inner)
            elif child.type == "enum_constant":
                # Enum constants - treat as static final fields
                const_name = None
                for c in child.children:
                    if c.type == "identifier":
                        const_name = self._get_text(c, source)
                        break
                if const_name:
                    fields.append(JavaField(
                        name=const_name,
                        type=class_name,
                        modifiers=["public", "static", "final"],
                    ))

        return {
            "constructors": constructors,
            "methods": methods,
            "fields": fields,
            "inner_classes": inner_classes,
        }

    def _extract_constructor(self, node: Node, source: bytes) -> Optional[JavaConstructor]:
        """Extract constructor declaration."""
        modifiers = []
        annotations = []
        parameters = []
        throws = []
        type_parameters = []

        for child in node.children:
            if child.type == "modifiers":
                modifiers, annotations = self._extract_modifiers(child, source)
            elif child.type == "type_parameters":
                type_parameters = self._extract_type_parameters(child, source)
            elif child.type == "formal_parameters":
                parameters = self._extract_parameters(child, source)
            elif child.type == "throws":
                throws = self._extract_throws(child, source)

        return JavaConstructor(
            parameters=parameters,
            modifiers=modifiers,
            annotations=annotations,
            throws=throws,
            type_parameters=type_parameters,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

    def _extract_method(self, node: Node, source: bytes) -> Optional[JavaMethod]:
        """Extract method declaration."""
        name = ""
        return_type = "void"
        modifiers = []
        annotations = []
        parameters = []
        throws = []
        type_parameters = []

        for child in node.children:
            if child.type == "modifiers":
                modifiers, annotations = self._extract_modifiers(child, source)
            elif child.type == "type_parameters":
                type_parameters = self._extract_type_parameters(child, source)
            elif child.type in ("type_identifier", "scoped_type_identifier",
                               "generic_type", "array_type", "void_type",
                               "integral_type", "floating_point_type", "boolean_type"):
                return_type = self._extract_type(child, source)
            elif child.type == "identifier":
                name = self._get_text(child, source)
            elif child.type == "formal_parameters":
                parameters = self._extract_parameters(child, source)
            elif child.type == "throws":
                throws = self._extract_throws(child, source)

        if not name:
            return None

        return JavaMethod(
            name=name,
            return_type=return_type,
            parameters=parameters,
            modifiers=modifiers,
            annotations=annotations,
            throws=throws,
            type_parameters=type_parameters,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
        )

    def _extract_parameters(self, node: Node, source: bytes) -> List[JavaParameter]:
        """Extract method/constructor parameters."""
        parameters = []

        for child in node.children:
            if child.type == "formal_parameter":
                param = self._extract_single_parameter(child, source)
                if param:
                    parameters.append(param)
            elif child.type == "spread_parameter":
                # Varargs: String... args
                param = self._extract_single_parameter(child, source, is_varargs=True)
                if param:
                    parameters.append(param)

        return parameters

    def _extract_single_parameter(self, node: Node, source: bytes,
                                  is_varargs: bool = False) -> Optional[JavaParameter]:
        """Extract a single parameter."""
        param_type = ""
        param_name = ""
        annotations = []

        for child in node.children:
            if child.type == "modifiers":
                _, annotations = self._extract_modifiers(child, source)
            elif child.type in ("type_identifier", "scoped_type_identifier",
                               "generic_type", "array_type",
                               "integral_type", "floating_point_type", "boolean_type"):
                param_type = self._extract_type(child, source)
            elif child.type == "identifier":
                param_name = self._get_text(child, source)
            elif child.type == "variable_declarator":
                for c in child.children:
                    if c.type == "identifier":
                        param_name = self._get_text(c, source)

        if not param_name or not param_type:
            return None

        return JavaParameter(
            name=param_name,
            type=param_type,
            annotations=annotations,
            is_varargs=is_varargs,
        )

    def _extract_throws(self, node: Node, source: bytes) -> List[str]:
        """Extract throws clause exceptions."""
        exceptions = []
        for child in node.children:
            if child.type in ("type_identifier", "scoped_type_identifier"):
                exceptions.append(self._get_text(child, source))
        return exceptions

    def _extract_fields(self, node: Node, source: bytes) -> List[JavaField]:
        """Extract field declarations (may have multiple declarators)."""
        fields = []
        field_type = ""
        modifiers = []
        annotations = []

        for child in node.children:
            if child.type == "modifiers":
                modifiers, annotations = self._extract_modifiers(child, source)
            elif child.type in ("type_identifier", "scoped_type_identifier",
                               "generic_type", "array_type",
                               "integral_type", "floating_point_type", "boolean_type"):
                field_type = self._extract_type(child, source)
            elif child.type == "variable_declarator":
                field_name = ""
                initial_value = None
                for c in child.children:
                    if c.type == "identifier":
                        field_name = self._get_text(c, source)
                    elif c.type == "dimensions":
                        # Array dimensions after name: int foo[]
                        field_type += self._get_text(c, source)

                if field_name:
                    fields.append(JavaField(
                        name=field_name,
                        type=field_type,
                        modifiers=modifiers.copy(),
                        annotations=annotations.copy(),
                        initial_value=initial_value,
                    ))

        return fields

    def _extract_record_parameters(self, node: Node, source: bytes) -> List[JavaField]:
        """Extract record component parameters as fields."""
        fields = []
        for child in node.children:
            if child.type == "formal_parameter":
                param = self._extract_single_parameter(child, source)
                if param:
                    fields.append(JavaField(
                        name=param.name,
                        type=param.type,
                        modifiers=["private", "final"],
                        annotations=param.annotations,
                    ))
        return fields
