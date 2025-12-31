#!/usr/bin/env python3
"""Validate generated test code against Java AST index.

This script checks if methods used in test code actually exist in the
target classes, catching hallucinations BEFORE they become build errors.

Usage:
    python3 validate_test.py --file PetTest.java
    python3 validate_test.py --code "pet.setTypeId(1);"
"""

import argparse
import json
import re
import sys
from pathlib import Path


def find_project_root():
    """Find the project root."""
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / 'java_indexer').exists():
            return parent
        if (parent / 'pom.xml').exists():
            return parent
    return current


def load_index(project_root: Path):
    """Load the Java index."""
    cache_path = project_root / '.claude' / 'java_index.json'
    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)
    return None


def get_all_methods_for_class(class_name: str, index: dict) -> set:
    """Get all available methods for a class including inherited."""
    classes = index.get('classes', {})
    all_methods = set()

    # Find the class
    cls = None
    for fqn, c in classes.items():
        if c.get('name') == class_name:
            cls = c
            break

    if not cls:
        return all_methods

    # Add own methods
    for m in cls.get('methods', []):
        if isinstance(m, dict):
            all_methods.add(m.get('name'))

    # Walk inheritance chain
    parent_name = cls.get('extends')
    visited = set()

    while parent_name and parent_name not in visited:
        visited.add(parent_name)

        for fqn, c in classes.items():
            if c.get('name') == parent_name:
                for m in c.get('methods', []):
                    if isinstance(m, dict):
                        all_methods.add(m.get('name'))
                parent_name = c.get('extends')
                break
        else:
            break

    return all_methods


def extract_method_calls(code: str) -> list:
    """Extract method calls from Java code."""
    # Pattern: variable.methodName(
    pattern = r'(\w+)\.(\w+)\s*\('
    calls = []
    for match in re.finditer(pattern, code):
        var_name = match.group(1)
        method_name = match.group(2)
        calls.append({
            'variable': var_name,
            'method': method_name,
            'position': match.start()
        })
    return calls


def infer_variable_types(code: str) -> dict:
    """Infer variable types from declarations."""
    types = {}

    # Pattern: Type varName = new Type() or Type varName = ...
    decl_pattern = r'(\w+)\s+(\w+)\s*='
    for match in re.finditer(decl_pattern, code):
        type_name = match.group(1)
        var_name = match.group(2)
        # Skip primitives and common types
        if type_name not in ['String', 'int', 'long', 'boolean', 'double', 'float', 'var']:
            types[var_name] = type_name

    # Pattern: for-each: for (Type var : collection)
    foreach_pattern = r'for\s*\(\s*(\w+)\s+(\w+)\s*:'
    for match in re.finditer(foreach_pattern, code):
        type_name = match.group(1)
        var_name = match.group(2)
        if type_name not in ['String', 'int', 'long', 'boolean', 'double', 'float', 'var']:
            types[var_name] = type_name

    return types


def validate_code(code: str, index: dict) -> list:
    """Validate code against the index. Returns list of errors."""
    errors = []

    var_types = infer_variable_types(code)
    method_calls = extract_method_calls(code)

    for call in method_calls:
        var_name = call['variable']
        method_name = call['method']

        # Skip if we don't know the type
        if var_name not in var_types:
            continue

        type_name = var_types[var_name]
        available_methods = get_all_methods_for_class(type_name, index)

        if available_methods and method_name not in available_methods:
            # Check for common hallucinations and suggest fixes
            suggestion = None
            if method_name == 'setTypeId':
                suggestion = "Use setId() instead (inherited from BaseEntity)"
            elif method_name == 'setTypeName':
                suggestion = "Use setName() instead (inherited from NamedEntity)"
            elif method_name == 'getTypeId':
                suggestion = "Use getId() instead (inherited from BaseEntity)"
            elif method_name == 'getTypeName':
                suggestion = "Use getName() instead (inherited from NamedEntity)"

            error = {
                'variable': var_name,
                'type': type_name,
                'method': method_name,
                'available': sorted(available_methods)[:10],
                'suggestion': suggestion
            }
            errors.append(error)

    # Check for enum-style usage of entities
    entity_enum_pattern = r'(PetType|Specialty|Owner|Pet|Visit|Vet)\.(DOG|CAT|BIRD|[A-Z]+)'
    for match in re.finditer(entity_enum_pattern, code):
        entity = match.group(1)
        constant = match.group(2)
        errors.append({
            'type': 'entity_as_enum',
            'entity': entity,
            'constant': constant,
            'suggestion': f"{entity} is a JPA entity, not an enum. Use: new {entity}() with setName()"
        })

    return errors


def format_errors(errors: list) -> str:
    """Format errors for display."""
    if not errors:
        return "✅ No validation errors found!"

    lines = []
    lines.append("❌ VALIDATION ERRORS FOUND:")
    lines.append("=" * 50)

    for i, err in enumerate(errors, 1):
        if err.get('type') == 'entity_as_enum':
            lines.append(f"\n{i}. {err['entity']}.{err['constant']}")
            lines.append(f"   Problem: {err['suggestion']}")
        else:
            lines.append(f"\n{i}. {err['variable']}.{err['method']}()")
            lines.append(f"   Type: {err['type']}")
            lines.append(f"   Problem: Method '{err['method']}' does not exist")
            if err.get('suggestion'):
                lines.append(f"   Fix: {err['suggestion']}")
            lines.append(f"   Available: {', '.join(err['available'])}")

    lines.append("\n" + "=" * 50)
    lines.append("Fix these errors before saving the test file.")
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Validate test code against AST')
    parser.add_argument('--file', help='Test file to validate')
    parser.add_argument('--code', help='Code snippet to validate')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    if not args.file and not args.code:
        parser.error("Either --file or --code is required")

    project_root = find_project_root()
    index = load_index(project_root)

    if not index:
        print("ERROR: Java index not found. Run get_class_context.py first.", file=sys.stderr)
        sys.exit(1)

    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            print(f"ERROR: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        code = file_path.read_text()
    else:
        code = args.code

    errors = validate_code(code, index)

    if args.json:
        print(json.dumps({'errors': errors, 'valid': len(errors) == 0}, indent=2))
    else:
        print(format_errors(errors))

    # Exit with error code if validation failed
    sys.exit(1 if errors else 0)


if __name__ == '__main__':
    main()
