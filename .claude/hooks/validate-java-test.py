#!/usr/bin/env python3
"""PostToolUse hook to validate Java test code against AST.

This hook runs after Edit/Write tools and validates that any Java test
code uses only methods that actually exist in the class hierarchy.

Place in .claude/hooks/ and register in settings.json.
"""

import json
import re
import sys
from pathlib import Path


def load_index():
    """Load the Java index."""
    # Find project root
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        cache_path = parent / '.claude' / 'java_index.json'
        if cache_path.exists():
            with open(cache_path) as f:
                return json.load(f)
    return None


def get_all_methods_for_class(class_name: str, index: dict) -> set:
    """Get all methods for a class including inherited."""
    classes = index.get('classes', {})
    all_methods = set()

    cls = None
    for fqn, c in classes.items():
        if c.get('name') == class_name:
            cls = c
            break

    if not cls:
        return all_methods

    for m in cls.get('methods', []):
        if isinstance(m, dict):
            all_methods.add(m.get('name'))

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


def validate_java_test(content: str, index: dict) -> list:
    """Validate Java test code against the index."""
    errors = []

    # Infer variable types
    types = {}
    decl_pattern = r'(\w+)\s+(\w+)\s*='
    for match in re.finditer(decl_pattern, content):
        type_name = match.group(1)
        var_name = match.group(2)
        if type_name not in ['String', 'int', 'long', 'boolean', 'double', 'float', 'var', 'List', 'Set', 'Map']:
            types[var_name] = type_name

    # Check method calls
    call_pattern = r'(\w+)\.(\w+)\s*\('
    for match in re.finditer(call_pattern, content):
        var_name = match.group(1)
        method_name = match.group(2)

        if var_name not in types:
            continue

        type_name = types[var_name]
        available = get_all_methods_for_class(type_name, index)

        if available and method_name not in available:
            suggestion = None
            if method_name == 'setTypeId':
                suggestion = "setId()"
            elif method_name == 'setTypeName':
                suggestion = "setName()"
            elif method_name == 'getTypeId':
                suggestion = "getId()"
            elif method_name == 'getTypeName':
                suggestion = "getName()"

            errors.append({
                'method': f"{var_name}.{method_name}()",
                'type': type_name,
                'suggestion': suggestion,
                'available': list(available)[:8]
            })

    # Check for entity-as-enum usage
    enum_pattern = r'(PetType|Specialty)\.(DOG|CAT|[A-Z]+)'
    for match in re.finditer(enum_pattern, content):
        errors.append({
            'method': f"{match.group(1)}.{match.group(2)}",
            'type': 'entity_as_enum',
            'suggestion': f"new {match.group(1)}() with setName()"
        })

    return errors


def main():
    # Read hook input from stdin
    try:
        input_data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = input_data.get('tool_name', '')
    tool_input = input_data.get('tool_input', {})

    # Only check Edit and Write tools
    if tool_name not in ['Edit', 'Write']:
        sys.exit(0)

    file_path = tool_input.get('file_path', '')

    # Only check Java test files
    if not file_path.endswith('.java') or 'Test' not in file_path:
        sys.exit(0)

    # Get the content
    content = tool_input.get('new_string', '') or tool_input.get('content', '')
    if not content:
        sys.exit(0)

    # Load index
    index = load_index()
    if not index:
        sys.exit(0)

    # Validate
    errors = validate_java_test(content, index)

    if errors:
        output = []
        output.append("━" * 50)
        output.append("⚠️  JAVA TEST VALIDATION FAILED")
        output.append("━" * 50)
        output.append("")

        for err in errors:
            output.append(f"❌ {err['method']}")
            if err.get('suggestion'):
                output.append(f"   → Use: {err['suggestion']}")
            if err.get('available'):
                output.append(f"   → Available: {', '.join(err['available'][:5])}...")
            output.append("")

        output.append("Fix these issues before the test will compile.")
        output.append("━" * 50)

        print('\n'.join(output))

    sys.exit(0)


if __name__ == '__main__':
    main()
