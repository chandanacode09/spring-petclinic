#!/usr/bin/env python3
"""Get class context from Java AST index for test generation.

This script loads actual class signatures, methods, and fields from the
tree-sitter AST index - ensuring tests only use methods that actually exist.

Usage:
    python3 get_class_context.py --class Pet
    python3 get_class_context.py --class Pet --include-deps
"""

import argparse
import json
import sys
from pathlib import Path


def find_project_root():
    """Find the project root (where java_indexer is)."""
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        if (parent / 'java_indexer').exists():
            return parent
        if (parent / 'pom.xml').exists():
            return parent
    return current


def load_or_build_index(project_root: Path):
    """Load cached index or build fresh one."""
    cache_path = project_root / '.claude' / 'java_index.json'

    if cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)

    # Try to build index
    sys.path.insert(0, str(project_root))
    try:
        from java_indexer import JavaIndexer
        indexer = JavaIndexer(str(project_root))
        index = indexer.index_repo(show_progress=False)

        # Cache it
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        index.save(str(cache_path))

        with open(cache_path) as f:
            return json.load(f)
    except ImportError:
        print("ERROR: java_indexer not found. Run from project root.", file=sys.stderr)
        sys.exit(1)


def resolve_inheritance(cls_name: str, index: dict) -> dict:
    """Resolve inherited methods and fields for a class."""
    classes = index.get('classes', {})

    # Find the class
    cls = None
    for fqn, c in classes.items():
        if c.get('name') == cls_name:
            cls = c
            break

    if not cls:
        return None

    # Collect own members
    own_methods = []
    for m in cls.get('methods', []):
        if isinstance(m, dict):
            own_methods.append({
                'name': m.get('name'),
                'return_type': m.get('return_type'),
                'parameters': m.get('parameters', [])
            })

    own_fields = []
    for f in cls.get('fields', []):
        if isinstance(f, dict):
            own_fields.append({
                'name': f.get('name'),
                'type': f.get('type')
            })

    # Walk inheritance chain
    inherited_methods = []
    inherited_fields = []
    parent_chain = []

    parent_name = cls.get('extends')
    visited = set()

    while parent_name and parent_name not in visited:
        visited.add(parent_name)
        parent_chain.append(parent_name)

        # Find parent
        parent_cls = None
        for fqn, c in classes.items():
            if c.get('name') == parent_name:
                parent_cls = c
                break

        if not parent_cls:
            break

        # Add parent methods
        for m in parent_cls.get('methods', []):
            if isinstance(m, dict):
                method_name = m.get('name')
                if method_name not in [om['name'] for om in own_methods + inherited_methods]:
                    inherited_methods.append({
                        'name': method_name,
                        'return_type': m.get('return_type'),
                        'parameters': m.get('parameters', []),
                        'from': parent_name
                    })

        # Add parent fields
        for f in parent_cls.get('fields', []):
            if isinstance(f, dict):
                field_name = f.get('name')
                if field_name not in [of['name'] for of in own_fields + inherited_fields]:
                    inherited_fields.append({
                        'name': field_name,
                        'type': f.get('type'),
                        'from': parent_name
                    })

        parent_name = parent_cls.get('extends')

    return {
        'name': cls.get('name'),
        'fqn': cls.get('fqn'),
        'package': cls.get('package'),
        'extends': cls.get('extends'),
        'parent_chain': parent_chain,
        'constructors': cls.get('constructors', []),
        'own_methods': own_methods,
        'inherited_methods': inherited_methods,
        'own_fields': own_fields,
        'inherited_fields': inherited_fields,
        'all_methods': own_methods + inherited_methods,
        'all_fields': own_fields + inherited_fields
    }


def get_dependency_context(cls_info: dict, index: dict) -> dict:
    """Get context for class dependencies."""
    deps = {}
    classes = index.get('classes', {})

    # Find dependencies from fields
    for field in cls_info.get('all_fields', []):
        field_type = field.get('type', '')
        # Skip primitives and common types
        if field_type in ['String', 'Integer', 'Long', 'int', 'long', 'boolean', 'LocalDate']:
            continue

        # Extract base type from generics
        base_type = field_type
        if '<' in field_type:
            import re
            match = re.search(r'<([^<>]+)>', field_type)
            if match:
                base_type = match.group(1).split(',')[-1].strip()

        # Find in index
        for fqn, c in classes.items():
            if c.get('name') == base_type:
                dep_info = resolve_inheritance(base_type, index)
                if dep_info:
                    deps[base_type] = dep_info
                break

    return deps


def format_for_prompt(cls_info: dict, deps: dict = None) -> str:
    """Format class info for LLM prompt."""
    lines = []

    lines.append("=" * 60)
    lines.append(f"CLASS: {cls_info['name']}")
    lines.append("=" * 60)
    lines.append(f"Package: {cls_info.get('package', '')}")
    lines.append(f"FQN: {cls_info.get('fqn', '')}")

    if cls_info.get('parent_chain'):
        lines.append(f"Inherits: {' -> '.join(cls_info['parent_chain'])}")

    lines.append("")
    lines.append("CONSTRUCTORS:")
    ctors = cls_info.get('constructors', [])
    if ctors:
        for c in ctors:
            lines.append(f"  - {c}")
    else:
        lines.append(f"  - {cls_info['name']}() (default no-arg)")

    lines.append("")
    lines.append("OWN METHODS:")
    for m in cls_info.get('own_methods', []):
        params = ', '.join([
            f"{p.get('type')} {p.get('name')}"
            for p in m.get('parameters', [])
        ])
        lines.append(f"  - {m.get('return_type', 'void')} {m['name']}({params})")

    if cls_info.get('inherited_methods'):
        lines.append("")
        lines.append("INHERITED METHODS:")
        for m in cls_info.get('inherited_methods', []):
            params = ', '.join([
                f"{p.get('type')} {p.get('name')}"
                for p in m.get('parameters', [])
            ])
            lines.append(f"  - {m.get('return_type', 'void')} {m['name']}({params}) [from {m.get('from')}]")

    lines.append("")
    lines.append("ALL AVAILABLE METHODS (use ONLY these):")
    all_method_names = [m['name'] for m in cls_info.get('all_methods', [])]
    lines.append(f"  {', '.join(all_method_names)}")

    if deps:
        lines.append("")
        lines.append("=" * 60)
        lines.append("DEPENDENCIES")
        lines.append("=" * 60)
        for dep_name, dep_info in deps.items():
            lines.append(f"\n{dep_name}:")
            all_dep_methods = [m['name'] for m in dep_info.get('all_methods', [])]
            lines.append(f"  Available methods: {', '.join(all_dep_methods)}")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Get class context for test generation')
    parser.add_argument('--class', dest='class_name', required=True, help='Class name')
    parser.add_argument('--include-deps', action='store_true', help='Include dependency context')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    project_root = find_project_root()
    index = load_or_build_index(project_root)

    cls_info = resolve_inheritance(args.class_name, index)
    if not cls_info:
        print(f"ERROR: Class '{args.class_name}' not found in index", file=sys.stderr)
        sys.exit(1)

    deps = {}
    if args.include_deps:
        deps = get_dependency_context(cls_info, index)

    if args.json:
        output = {
            'class': cls_info,
            'dependencies': deps
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        print(format_for_prompt(cls_info, deps))


if __name__ == '__main__':
    main()
