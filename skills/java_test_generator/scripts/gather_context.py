#!/usr/bin/env python3
"""Gather rich context for Java test generation.

This script collects all relevant information needed to generate
meaningful, grounded unit tests including:
- Class AST structure
- Database schema (for JPA entities)
- Dependencies with constructors
- Existing test samples
- Test patterns from the repo
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_index(index_path: str) -> Dict[str, Any]:
    """Load the Java index file."""
    with open(index_path) as f:
        return json.load(f)


def find_class(index: Dict[str, Any], class_name: str) -> Optional[Dict[str, Any]]:
    """Find a class by name (simple or FQN) in the index."""
    classes = index.get('classes', {})

    # Try exact FQN match first
    if class_name in classes:
        return classes[class_name]

    # Try simple name match
    for fqn, cls_info in classes.items():
        if cls_info.get('name') == class_name:
            return cls_info

    return None


def get_database_schema(index: Dict[str, Any], class_fqn: str) -> Optional[Dict[str, Any]]:
    """Get database schema for a JPA entity."""
    schemas = index.get('database_schemas', {})

    for table_name, schema in schemas.items():
        if schema.get('entity_class_fqn') == class_fqn:
            return schema

    return None


def determine_class_kind(cls: Dict[str, Any], schema: Optional[Dict[str, Any]]) -> str:
    """Determine the kind of class (entity, service, controller, etc.)."""
    annotations = cls.get('annotations', [])
    name = cls.get('name', '')

    # Check annotations
    for ann in annotations:
        if '@Entity' in ann or '@Table' in ann:
            return 'entity'
        if '@Service' in ann:
            return 'service'
        if '@RestController' in ann or '@Controller' in ann:
            return 'controller'
        if '@Repository' in ann:
            return 'repository'
        if '@Component' in ann:
            return 'component'

    # Check by name convention
    if name.endswith('Service') or name.endswith('ServiceImpl'):
        return 'service'
    if name.endswith('Controller') or name.endswith('Resource'):
        return 'controller'
    if name.endswith('Repository'):
        return 'repository'

    # If has schema, it's an entity
    if schema:
        return 'entity'

    return 'class'


def extract_dependencies(cls: Dict[str, Any], index: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Extract dependencies from fields and constructor parameters."""
    deps = {}
    classes = index.get('classes', {})

    # From fields
    for field in cls.get('fields', []):
        field_type = field.get('type', '')
        # Skip primitives and common types
        if is_common_type(field_type):
            continue

        # Extract base type from generics
        base_type = extract_base_type(field_type)

        # Find in index
        for fqn, dep_cls in classes.items():
            if dep_cls.get('name') == base_type:
                deps[base_type] = {
                    'fqn': fqn,
                    'constructors': format_constructors(dep_cls.get('constructors', [])),
                    'kind': determine_class_kind(dep_cls, get_database_schema(index, fqn)),
                    'external': False
                }
                break
        else:
            # Not found in index - external dependency
            deps[base_type] = {
                'fqn': f'unknown.{base_type}',
                'constructors': [],
                'kind': 'external',
                'external': True
            }

    # From constructor parameters
    for ctor in cls.get('constructors', []):
        for param in ctor.get('parameters', []):
            param_type = param.get('type', '')
            if is_common_type(param_type):
                continue

            base_type = extract_base_type(param_type)
            if base_type not in deps:
                for fqn, dep_cls in classes.items():
                    if dep_cls.get('name') == base_type:
                        deps[base_type] = {
                            'fqn': fqn,
                            'constructors': format_constructors(dep_cls.get('constructors', [])),
                            'kind': determine_class_kind(dep_cls, get_database_schema(index, fqn)),
                            'external': False
                        }
                        break

    return deps


def is_common_type(type_name: str) -> bool:
    """Check if type is a common/primitive type that doesn't need dependency tracking."""
    common = {
        'String', 'Integer', 'Long', 'Double', 'Float', 'Boolean', 'Byte', 'Short', 'Character',
        'int', 'long', 'double', 'float', 'boolean', 'byte', 'short', 'char',
        'BigDecimal', 'BigInteger', 'LocalDate', 'LocalDateTime', 'Instant', 'ZonedDateTime',
        'List', 'Set', 'Map', 'Collection', 'Optional', 'UUID',
        'Object', 'Class', 'void', 'Void'
    }
    base = extract_base_type(type_name)
    return base in common


def extract_base_type(type_name: str) -> str:
    """Extract base type from generic type (e.g., List<User> -> User)."""
    # Handle generics like List<User>, Optional<String>
    if '<' in type_name:
        # Get the inner type for collections
        inner = re.search(r'<([^<>]+)>', type_name)
        if inner:
            inner_type = inner.group(1)
            # For Map<K,V>, just return the value type
            if ',' in inner_type:
                return inner_type.split(',')[-1].strip()
            return inner_type.strip()

    # Handle arrays
    if type_name.endswith('[]'):
        return type_name[:-2]

    return type_name


def format_constructors(constructors: List) -> List[str]:
    """Format constructors as readable signatures."""
    formatted = []
    for ctor in constructors:
        if isinstance(ctor, str):
            formatted.append(ctor)
        elif isinstance(ctor, dict):
            params = ctor.get('parameters', [])
            param_strs = []
            for p in params:
                if isinstance(p, dict):
                    param_strs.append(f"{p.get('type', '?')} {p.get('name', '?')}")
                else:
                    param_strs.append(str(p))
            # Get class name from the constructor
            class_name = ctor.get('name', 'Constructor')
            formatted.append(f"{class_name}({', '.join(param_strs)})")
    return formatted


def find_test_samples(repo_path: str, class_name: str) -> Optional[Dict[str, Any]]:
    """Find existing TestSamples class for the target class."""
    repo = Path(repo_path)
    test_samples_name = f"{class_name}TestSamples.java"

    # Search in test directories
    for test_dir in ['src/test/java', 'test']:
        test_path = repo / test_dir
        if test_path.exists():
            for samples_file in test_path.rglob(test_samples_name):
                return parse_test_samples(samples_file)

    return None


def parse_test_samples(file_path: Path) -> Dict[str, Any]:
    """Parse a TestSamples file to extract sample generator methods."""
    content = file_path.read_text()

    result = {
        'class_name': file_path.stem,
        'file_path': str(file_path),
        'methods': []
    }

    # Find public static methods that return the entity type
    method_pattern = r'public\s+static\s+(\w+)\s+(\w+)\s*\([^)]*\)\s*\{([^}]+)\}'
    for match in re.finditer(method_pattern, content, re.DOTALL):
        return_type = match.group(1)
        method_name = match.group(2)
        body = match.group(3).strip()

        # Extract the return statement
        return_match = re.search(r'return\s+(.+?);', body, re.DOTALL)
        if return_match:
            return_expr = return_match.group(1).strip()
            # Clean up whitespace
            return_expr = ' '.join(return_expr.split())
            result['methods'].append({
                'name': method_name,
                'return_type': return_type,
                'return_expression': return_expr
            })

    return result


def find_existing_tests(repo_path: str, class_name: str) -> Optional[Dict[str, Any]]:
    """Find existing test class for the target."""
    repo = Path(repo_path)
    test_name = f"{class_name}Test.java"

    for test_dir in ['src/test/java', 'test']:
        test_path = repo / test_dir
        if test_path.exists():
            for test_file in test_path.rglob(test_name):
                return analyze_test_file(test_file)

    return None


def analyze_test_file(file_path: Path) -> Dict[str, Any]:
    """Analyze an existing test file for patterns."""
    content = file_path.read_text()

    result = {
        'file_path': str(file_path),
        'uses_assertj': 'assertThat(' in content,
        'uses_junit_assertions': 'assertEquals(' in content or 'assertTrue(' in content,
        'uses_mockito': '@Mock' in content or 'Mockito.' in content,
        'uses_spring_test': '@SpringBootTest' in content,
        'has_before_each': '@BeforeEach' in content,
        'has_after_each': '@AfterEach' in content,
        'test_methods': [],
        'imports': []
    }

    # Extract test method names
    for match in re.finditer(r'@Test\s+void\s+(\w+)\s*\(', content):
        result['test_methods'].append(match.group(1))

    # Extract static imports (useful patterns)
    for match in re.finditer(r'import\s+static\s+([^;]+);', content):
        result['imports'].append(match.group(1))

    return result


def find_test_utilities(repo_path: str) -> List[Dict[str, str]]:
    """Find test utility classes in the repo."""
    repo = Path(repo_path)
    utilities = []

    for test_dir in ['src/test/java', 'test']:
        test_path = repo / test_dir
        if test_path.exists():
            for util_file in test_path.rglob('*Util*.java'):
                if 'Test' not in util_file.stem or util_file.stem == 'TestUtil':
                    utilities.append({
                        'name': util_file.stem,
                        'path': str(util_file),
                        'methods': extract_util_methods(util_file)
                    })

    return utilities


def extract_util_methods(file_path: Path) -> List[str]:
    """Extract public static method signatures from a utility class."""
    content = file_path.read_text()
    methods = []

    for match in re.finditer(r'public\s+static\s+(\S+)\s+(\w+)\s*\(([^)]*)\)', content):
        return_type = match.group(1)
        method_name = match.group(2)
        params = match.group(3).strip()
        methods.append(f"{method_name}({params}) -> {return_type}")

    return methods


def find_dependency_test_samples(repo_path: str, dependencies: Dict[str, Dict]) -> Dict[str, Dict]:
    """Find TestSamples for each dependency."""
    dep_samples = {}

    for dep_name, dep_info in dependencies.items():
        if not dep_info.get('external', False):
            samples = find_test_samples(repo_path, dep_name)
            if samples:
                dep_samples[dep_name] = {
                    'has_samples': True,
                    'sample_methods': [m['name'] for m in samples.get('methods', [])]
                }
            else:
                dep_samples[dep_name] = {
                    'has_samples': False,
                    'sample_methods': []
                }

    return dep_samples


def gather_context(
    index_path: str,
    class_name: str,
    repo_path: str,
    method_name: Optional[str] = None
) -> Dict[str, Any]:
    """Gather all context needed for test generation."""

    index = load_index(index_path)
    cls = find_class(index, class_name)

    if not cls:
        return {'error': f'Class {class_name} not found in index'}

    class_fqn = cls.get('fqn', '')
    schema = get_database_schema(index, class_fqn)
    kind = determine_class_kind(cls, schema)
    dependencies = extract_dependencies(cls, index)

    context = {
        'target_class': {
            'name': cls.get('name'),
            'fqn': class_fqn,
            'kind': kind,
            'package': '.'.join(class_fqn.split('.')[:-1]) if class_fqn else '',
            'constructors': format_constructors(cls.get('constructors', [])),
            'methods': cls.get('methods', []),
            'fields': cls.get('fields', []),
            'annotations': cls.get('annotations', []),
            'extends': cls.get('extends'),
            'implements': cls.get('implements', []),
            'source_file': cls.get('source_file')
        },
        'target_method': None,
        'database_schema': schema,
        'dependencies': dependencies,
        'dependency_samples': find_dependency_test_samples(repo_path, dependencies),
        'existing_test_samples': find_test_samples(repo_path, cls.get('name', '')),
        'existing_tests': find_existing_tests(repo_path, cls.get('name', '')),
        'test_utilities': find_test_utilities(repo_path),
        'repo_path': repo_path,
        'index_path': index_path
    }

    # If specific method requested, extract its info
    if method_name:
        for method in cls.get('methods', []):
            if method.get('name') == method_name:
                context['target_method'] = method
                break

    return context


def format_context_for_prompt(context: Dict[str, Any]) -> str:
    """Format the context as a readable string for LLM prompts."""
    lines = []

    # Add guardrails section at the top
    lines.append("!" * 60)
    lines.append("IMPORTANT: ONLY use classes, methods, and imports shown below!")
    lines.append("DO NOT invent or assume any APIs that are not explicitly listed.")
    lines.append("!" * 60)
    lines.append("")

    target = context.get('target_class', {})
    lines.append("=" * 60)
    lines.append("TARGET CLASS")
    lines.append("=" * 60)
    lines.append(f"Name: {target.get('name')}")
    lines.append(f"FQN: {target.get('fqn')}")
    lines.append(f"Kind: {target.get('kind')}")
    lines.append(f"Package: {target.get('package')}")

    if target.get('extends'):
        lines.append(f"Extends: {target.get('extends')}")
    if target.get('implements'):
        lines.append(f"Implements: {', '.join(target.get('implements', []))}")

    # Constructors
    lines.append("\nCONSTRUCTORS:")
    for ctor in target.get('constructors', []) or ['(default no-arg)']:
        lines.append(f"  - {ctor}")

    # Fields
    lines.append("\nFIELDS:")
    for field in target.get('fields', []):
        field_str = f"  - {field.get('type')} {field.get('name')}"
        if field.get('annotations'):
            field_str += f" [{', '.join(field.get('annotations', []))}]"
        lines.append(field_str)

    # Methods
    lines.append("\nMETHODS:")
    for method in target.get('methods', [])[:20]:  # Limit to avoid huge prompts
        params = ', '.join([
            f"{p.get('type')} {p.get('name')}"
            for p in method.get('parameters', [])
        ])
        lines.append(f"  - {method.get('return_type')} {method.get('name')}({params})")

    # Database schema
    schema = context.get('database_schema')
    if schema:
        lines.append("\n" + "=" * 60)
        lines.append("DATABASE SCHEMA")
        lines.append("=" * 60)
        lines.append(f"Table: {schema.get('table_name')}")

        lines.append("\nColumns:")
        for col in schema.get('columns', []):
            col_str = f"  - {col.get('name')}: {col.get('java_type')}"
            attrs = []
            if col.get('is_pk'):
                attrs.append('PK')
            if col.get('is_generated'):
                attrs.append('AUTO')
            if not col.get('nullable', True):
                attrs.append('NOT NULL')
            if col.get('length'):
                attrs.append(f"length={col.get('length')}")
            if col.get('precision'):
                attrs.append(f"precision={col.get('precision')},{col.get('scale', 0)}")
            if attrs:
                col_str += f" ({', '.join(attrs)})"
            lines.append(col_str)

        lines.append("\nRelationships:")
        for rel in schema.get('relationships', []):
            rel_str = f"  - {rel.get('java_field')}: {rel.get('type')} -> {rel.get('target_entity')}"
            if rel.get('fetch_type'):
                rel_str += f" (fetch={rel.get('fetch_type')})"
            if rel.get('mapped_by'):
                rel_str += f" (mappedBy={rel.get('mapped_by')})"
            lines.append(rel_str)

    # Dependencies
    deps = context.get('dependencies', {})
    if deps:
        lines.append("\n" + "=" * 60)
        lines.append("DEPENDENCIES")
        lines.append("=" * 60)
        for dep_name, dep_info in deps.items():
            if dep_info.get('external'):
                lines.append(f"  - {dep_name}: EXTERNAL (mock it)")
            else:
                lines.append(f"  - {dep_name}:")
                lines.append(f"      FQN: {dep_info.get('fqn')}")
                lines.append(f"      Kind: {dep_info.get('kind')}")
                for ctor in dep_info.get('constructors', []):
                    lines.append(f"      Constructor: {ctor}")

    # Existing test samples - with explicit warning if none exist
    samples = context.get('existing_test_samples')
    lines.append("\n" + "=" * 60)
    lines.append("TEST SAMPLES STATUS")
    lines.append("=" * 60)
    if samples and samples.get('methods'):
        lines.append(f"Class: {samples.get('class_name')}")
        lines.append("Available sample methods (USE THESE):")
        for method in samples.get('methods', []):
            lines.append(f"  - {method.get('name')}():")
            lines.append(f"      return {method.get('return_expression')}")
    else:
        lines.append("*** NO TestSamples class exists for this class ***")
        lines.append("*** Create test objects using constructors and setters ***")
        lines.append("*** DO NOT import or use any *TestSamples classes ***")
        lines.append("")
        lines.append("HOW TO CREATE TEST OBJECTS:")
        target_ctors = target.get('constructors', [])
        if target_ctors:
            lines.append(f"  Use constructor: {target.get('name')}()")
            for ctor in target_ctors[:3]:
                lines.append(f"    - {ctor}")
        else:
            lines.append(f"  {target.get('name')} obj = new {target.get('name')}();")
        lines.append("  Then use setter methods to populate fields.")

    # Dependency samples
    dep_samples = context.get('dependency_samples', {})
    if any(ds.get('has_samples') for ds in dep_samples.values()):
        lines.append("\nDEPENDENCY TEST SAMPLES:")
        for dep_name, ds in dep_samples.items():
            if ds.get('has_samples'):
                lines.append(f"  - {dep_name}TestSamples: {', '.join(ds.get('sample_methods', []))}")

    # Existing test patterns
    existing = context.get('existing_tests')
    if existing:
        lines.append("\n" + "=" * 60)
        lines.append("EXISTING TEST PATTERNS")
        lines.append("=" * 60)
        lines.append(f"Uses AssertJ: {existing.get('uses_assertj')}")
        lines.append(f"Uses Mockito: {existing.get('uses_mockito')}")
        lines.append(f"Uses JUnit assertions: {existing.get('uses_junit_assertions')}")
        lines.append(f"Has @BeforeEach: {existing.get('has_before_each')}")
        if existing.get('test_methods'):
            lines.append(f"Existing test methods: {', '.join(existing.get('test_methods', []))}")

    # Test utilities
    utils = context.get('test_utilities', [])
    if utils:
        lines.append("\nTEST UTILITIES AVAILABLE:")
        for util in utils:
            lines.append(f"  - {util.get('name')}:")
            for method in util.get('methods', [])[:5]:
                lines.append(f"      {method}")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Gather context for Java test generation')
    parser.add_argument('--index', required=True, help='Path to Java index JSON file')
    parser.add_argument('--class-name', required=True, help='Class name to generate tests for')
    parser.add_argument('--repo-path', required=True, help='Path to the Java repository')
    parser.add_argument('--method-name', help='Specific method to test (optional)')
    parser.add_argument('--output', help='Output file path (default: stdout)')
    parser.add_argument('--format', choices=['json', 'prompt'], default='json',
                       help='Output format (json or prompt-ready text)')

    args = parser.parse_args()

    context = gather_context(
        args.index,
        args.class_name,
        args.repo_path,
        args.method_name
    )

    if 'error' in context:
        print(f"Error: {context['error']}", file=sys.stderr)
        sys.exit(1)

    if args.format == 'prompt':
        output = format_context_for_prompt(context)
    else:
        output = json.dumps(context, indent=2, default=str)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Context written to {args.output}")
    else:
        print(output)


if __name__ == '__main__':
    main()
