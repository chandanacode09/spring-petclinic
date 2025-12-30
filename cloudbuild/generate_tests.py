#!/usr/bin/env python3
"""Generate grounded Java tests for Cloud Build pipelines with BigQuery integration.

This script:
1. Loads or builds a Java AST index using tree-sitter
2. Streams index data to BigQuery for cross-repo analytics
3. Uses the java_test_generator skill for rich context (TestSamples, DB schemas, relationships)
4. Generates tests using LLM with grounded context
5. Injects missing TestSamples imports post-generation
6. Tracks generation results in BigQuery

Usage:
    python generate_tests.py --repo /workspace --changed-files changed.txt
"""

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def get_bq_client():
    """Get BigQuery client if available."""
    try:
        from bigquery.bq_client import ContextAgentBQ
        project_id = os.getenv('GOOGLE_CLOUD_PROJECT') or os.getenv('PROJECT_ID')
        if project_id:
            return ContextAgentBQ(project_id)
    except ImportError:
        pass
    except Exception as e:
        print(f"BigQuery client init failed: {e}", file=sys.stderr)
    return None


def get_skill_context_gatherer():
    """Import the skill's context gathering function if available."""
    try:
        from skills.java_test_generator.scripts.gather_context import (
            gather_context,
            format_context_for_prompt
        )
        return gather_context, format_context_for_prompt
    except ImportError as e:
        print(f"Skill import failed: {e}", file=sys.stderr)
        return None, None


def inject_test_samples_imports(test_code: str, rich_context: dict) -> str:
    """Inject missing TestSamples static imports into generated test code.

    The LLM often uses TestSamples methods but forgets to add static imports.
    This post-processor scans the generated code and adds missing imports.
    """
    if not rich_context:
        return test_code

    target = rich_context.get('target_class', {})
    package = target.get('package', '')
    imports_needed = set()

    # Check for target class TestSamples usage
    samples = rich_context.get('existing_test_samples')
    if samples:
        samples_class = samples.get('class_name', '')
        for method in samples.get('methods', []):
            method_name = method.get('name', '')
            if method_name and method_name + '(' in test_code:
                imports_needed.add(f"import static {package}.{samples_class}.*;")
                break

    # Check for dependency TestSamples usage
    dep_samples = rich_context.get('dependency_samples', {})
    deps = rich_context.get('dependencies', {})
    for dep_name, ds in dep_samples.items():
        if ds.get('has_samples'):
            for method_name in ds.get('sample_methods', []):
                if method_name + '(' in test_code:
                    dep_info = deps.get(dep_name, {})
                    dep_fqn = dep_info.get('fqn', '')
                    if dep_fqn and '.' in dep_fqn:
                        dep_package = dep_fqn.rsplit('.', 1)[0]
                        imports_needed.add(f"import static {dep_package}.{dep_name}TestSamples.*;")
                    break

    if not imports_needed:
        return test_code

    # Find the last import statement and insert after it
    lines = test_code.split('\n')
    last_import_idx = -1
    for i, line in enumerate(lines):
        if line.strip().startswith('import '):
            last_import_idx = i

    if last_import_idx >= 0:
        # Insert new imports after the last existing import
        for imp in sorted(imports_needed):
            if imp not in test_code:
                lines.insert(last_import_idx + 1, imp)
                last_import_idx += 1

    return '\n'.join(lines)


def generate_test_with_llm_rich(cls_name: str, rich_context: dict, format_context_fn) -> tuple:
    """Generate test using LLM with rich context from the java_test_generator skill.

    This uses the skill's context gathering which includes:
    - TestSamples discovery
    - Database schema extraction
    - Relationship mappings
    - Existing test patterns

    Returns:
        Tuple of (test_code, error_message, generation_time_ms)
    """
    start_time = time.time()

    try:
        from openai import OpenAI
    except ImportError:
        return None, "openai package not installed", 0

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None, "OPENROUTER_API_KEY not set", 0

    model = os.getenv("OPENROUTER_MODEL", "google/gemma-3-4b-it:free")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    # Use the skill's context formatter for rich prompts
    context_text = format_context_fn(rich_context)

    # Build the prompt with rich context
    target = rich_context.get('target_class', {})
    samples = rich_context.get('existing_test_samples')
    dep_samples = rich_context.get('dependency_samples', {})

    # Build sample usage instructions - ONLY if they actually exist
    sample_instructions = ""
    has_any_samples = False

    if samples and samples.get('methods'):
        has_any_samples = True
        sample_methods = [m.get('name') for m in samples.get('methods', [])]
        if sample_methods:
            sample_instructions += f"\n\nUSE THESE EXISTING SAMPLE METHODS (add static import for {samples.get('class_name')}):\n"
            for m in sample_methods[:5]:
                sample_instructions += f"  - {m}()\n"

    for dep_name, ds in dep_samples.items():
        if ds.get('has_samples') and ds.get('sample_methods'):
            has_any_samples = True
            sample_instructions += f"\nFor {dep_name}, use: {', '.join(ds.get('sample_methods', [])[:3])}\n"

    # Different prompt based on whether TestSamples exist
    if has_any_samples:
        sample_rule = "3. USE the TestSamples methods listed below with proper static imports"
    else:
        sample_rule = "3. Create test objects directly using constructors and setters - NO TestSamples exist in this repo"

    prompt = f"""You are an expert Java developer. Generate a complete JUnit 5 unit test class.

CRITICAL RULES:
1. ONLY use constructors and methods from the context below - DO NOT invent APIs
2. Use AssertJ assertions (assertThat) - this repo uses AssertJ
{sample_rule}
4. For entities, test relationships properly (add/remove sync)
5. Include ALL necessary imports
6. Follow the AAA pattern (Arrange, Act, Assert)
7. DO NOT import or use any classes that are not shown in the context below

{context_text}
{sample_instructions}

Generate a complete, compilable JUnit 5 test class with:
1. Package declaration matching the source class
2. ALL imports (only import classes shown in the context)
3. At least 3-4 meaningful test methods
4. Tests for relationships if this is an entity

Output ONLY the Java code, no explanations or markdown."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4000,
        )

        test_code = response.choices[0].message.content

        # Clean markdown if present
        if "```java" in test_code:
            start = test_code.find("```java") + 7
            end = test_code.find("```", start)
            if end > start:
                test_code = test_code[start:end]
        elif test_code.startswith("```"):
            test_code = test_code[3:]
        if test_code.endswith("```"):
            test_code = test_code[:-3]

        test_code = test_code.strip()

        # Post-process: inject missing TestSamples imports
        test_code = inject_test_samples_imports(test_code, rich_context)

        elapsed_ms = int((time.time() - start_time) * 1000)
        return test_code, None, elapsed_ms

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return None, str(e), elapsed_ms


def generate_test_with_llm(cls: dict, deps: dict) -> tuple:
    """Generate test using LLM via OpenRouter API (basic context, fallback).

    Returns:
        Tuple of (test_code, error_message, generation_time_ms)
    """
    start_time = time.time()

    try:
        from openai import OpenAI
    except ImportError:
        return None, "openai package not installed", 0

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return None, "OPENROUTER_API_KEY not set", 0

    model = os.getenv("OPENROUTER_MODEL", "google/gemma-3-4b-it:free")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    class_name = cls.get('name', 'Unknown')
    fqn = cls.get('fqn', '')
    package = cls.get('package', '')
    constructors = cls.get('constructors', [])
    methods = cls.get('methods', [])
    fields = cls.get('fields', [])

    # Build grounded context
    context = f"""CLASS TO TEST:
- Name: {class_name}
- Package: {package}
- FQN: {fqn}
- Constructors: {json.dumps(constructors)}
- Methods: {json.dumps(methods[:15])}
- Fields: {json.dumps(fields[:10])}

DEPENDENCIES (mock these):"""

    for dep_name, dep_info in list(deps.items())[:10]:
        if dep_info.get('external'):
            context += f"\n- {dep_name}: EXTERNAL (use @Mock)"
        else:
            dep_fqn = dep_info.get('fqn', '')
            context += f"\n- {dep_name}: {dep_fqn}"

    prompt = f"""You are an expert Java developer. Generate a complete JUnit 5 unit test class.

CRITICAL RULES:
1. ONLY use constructors and methods listed below - DO NOT invent or assume any APIs
2. Use @ExtendWith(MockitoExtension.class) for mocking
3. Use @Mock for dependencies, @InjectMocks for the class under test
4. Use AssertJ assertions (assertThat)
5. Follow AAA pattern (Arrange, Act, Assert)
6. Add when().thenReturn() for any mocked method calls
7. Include proper imports

{context}

Generate a complete, compilable JUnit 5 test class. Include:
1. Package declaration matching the source class
2. All necessary imports
3. At least 2-3 test methods
4. Proper setup with @BeforeEach if needed

Output ONLY the Java code, no explanations or markdown."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4000,
        )

        test_code = response.choices[0].message.content

        # Clean markdown if present
        if "```java" in test_code:
            start = test_code.find("```java") + 7
            end = test_code.find("```", start)
            if end > start:
                test_code = test_code[start:end]
        elif test_code.startswith("```"):
            test_code = test_code[3:]
        if test_code.endswith("```"):
            test_code = test_code[:-3]

        elapsed_ms = int((time.time() - start_time) * 1000)
        return test_code.strip(), None, elapsed_ms

    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return None, str(e), elapsed_ms


def generate_template_test(cls: dict, deps: dict) -> str:
    """Generate a template-based test as fallback."""
    class_name = cls.get('name', 'Unknown')
    fqn = cls.get('fqn', class_name)
    package = cls.get('package', 'com.example')
    constructors = cls.get('constructors', [])
    methods = cls.get('methods', [])

    # Parse first constructor for parameters
    ctor_params = []
    if constructors:
        ctor = constructors[0]
        if isinstance(ctor, str) and '(' in ctor and ')' in ctor:
            params_str = ctor[ctor.index('(')+1:ctor.index(')')]
            if params_str.strip():
                for param in params_str.split(','):
                    param = param.strip()
                    if param:
                        parts = param.rsplit(' ', 1)
                        if len(parts) == 2:
                            ctor_params.append({'type': parts[0].strip(), 'name': parts[1].strip()})

    # Build imports
    imports = [
        "import static org.assertj.core.api.Assertions.assertThat;",
        "import static org.mockito.Mockito.*;",
        "",
        f"import {fqn};",
        "import org.junit.jupiter.api.BeforeEach;",
        "import org.junit.jupiter.api.Test;",
        "import org.junit.jupiter.api.extension.ExtendWith;",
        "import org.mockito.InjectMocks;",
        "import org.mockito.Mock;",
        "import org.mockito.junit.jupiter.MockitoExtension;",
    ]

    # Add dependency imports
    for dep_name, dep_info in deps.items():
        if not dep_info.get('external') and dep_info.get('fqn'):
            imports.append(f"import {dep_info['fqn']};")

    # Mock fields
    mock_fields = []
    for p in ctor_params:
        mock_fields.append(f"    @Mock\n    private {p['type']} {p['name']};")

    instance_name = class_name[0].lower() + class_name[1:]

    # Generate test methods for first few public methods
    test_methods = []
    for method in methods[:3]:
        if isinstance(method, str):
            method_name = method.split("(")[0].split()[-1] if "(" in method else method
            test_name = f"test{method_name[0].upper()}{method_name[1:]}"
            test_methods.append(f"""
    @Test
    void {test_name}() {{
        // Arrange
        // TODO: Set up test data and mock behaviors

        // Act
        // TODO: Call {instance_name}.{method_name}(...)

        // Assert
        // TODO: Verify results
        assertThat({instance_name}).isNotNull();
    }}""")

    if not test_methods:
        test_methods.append(f"""
    @Test
    void testCreation() {{
        assertThat({instance_name}).isNotNull();
    }}""")

    return f'''package {package};

{chr(10).join(imports)}

/**
 * Unit tests for {class_name}.
 * Generated by: Context Agent (Cloud Build)
 */
@ExtendWith(MockitoExtension.class)
class {class_name}Test {{

{chr(10).join(mock_fields) if mock_fields else "    // No dependencies to mock"}

    @InjectMocks
    private {class_name} {instance_name};

    @BeforeEach
    void setUp() {{
        // Additional setup if needed
    }}
{"".join(test_methods)}
}}
'''


def stream_index_to_bigquery(bq_client, repo: str, index, git_sha: str = None):
    """Stream Java index data to BigQuery."""
    if not bq_client:
        return

    print(f"Streaming index to BigQuery...", file=sys.stderr)

    # Stream classes
    classes = []
    for cls in index.classes.values():
        classes.append({
            "name": cls.name,
            "fqn": cls.fqn,
            "package": cls.package,
            "source_file": cls.source_file,
            "constructors": [str(c) for c in cls.constructors] if cls.constructors else [],
            "methods": [str(m) for m in cls.methods] if cls.methods else [],
            "is_test": "Test" in cls.name,
            "has_tests": False,  # Will be updated after checking
        })

    if classes:
        count = bq_client.stream_java_classes(repo, classes, git_sha)
        print(f"  Streamed {count}/{len(classes)} classes", file=sys.stderr)

    # Stream dependencies
    dep_count = 0
    for cls in index.classes.values():
        if hasattr(cls, 'dependencies') and cls.dependencies:
            deps = {d.name: {"fqn": d.fqn, "external": d.external} for d in cls.dependencies}
            dep_count += bq_client.stream_java_dependencies(repo, cls.fqn, deps)

    if dep_count:
        print(f"  Streamed {dep_count} dependencies", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Generate Java tests for Cloud Build')
    parser.add_argument('--repo', required=True, help='Path to Java repository')
    parser.add_argument('--repo-name', help='Repository name for BigQuery (defaults to dir name)')
    parser.add_argument('--changed-files', required=True, help='File with list of changed Java files')
    parser.add_argument('--cached-index', help='Path to cached index file')
    parser.add_argument('--output-dir', default='generated-tests', help='Output directory')
    parser.add_argument('--output-index', help='Path to save updated index')
    parser.add_argument('--max-classes', type=int, default=20, help='Max classes to process')
    parser.add_argument('--json-output', action='store_true', help='Output JSON results')
    parser.add_argument('--no-llm', action='store_true', help='Skip LLM, use templates only')
    parser.add_argument('--no-bigquery', action='store_true', help='Skip BigQuery streaming')
    parser.add_argument('--build-id', help='Cloud Build ID for tracking')
    parser.add_argument('--git-sha', help='Git commit SHA')

    args = parser.parse_args()

    # Import java_indexer
    try:
        from java_indexer import JavaIndexer, ContextQuery, JavaIndex
    except ImportError as e:
        print(f"ERROR: Failed to import java_indexer: {e}", file=sys.stderr)
        sys.exit(1)

    repo_path = Path(args.repo)
    if not repo_path.exists():
        print(f"ERROR: Repository not found: {args.repo}", file=sys.stderr)
        sys.exit(1)

    repo_name = args.repo_name or repo_path.name

    # Initialize BigQuery client
    bq_client = None
    if not args.no_bigquery:
        bq_client = get_bq_client()
        if bq_client:
            print(f"BigQuery streaming enabled", file=sys.stderr)

    # Load changed files
    changed_files = []
    changed_path = Path(args.changed_files)
    if changed_path.exists():
        with open(changed_path) as f:
            changed_files = [l.strip() for l in f if l.strip().endswith('.java')]

    if not changed_files:
        print("No changed Java files to process.", file=sys.stderr)
        results = {'generated': [], 'skipped': [], 'failed': []}
        if args.json_output:
            print(json.dumps(results))
        sys.exit(0)

    print(f"Processing {len(changed_files)} changed files...", file=sys.stderr)

    # Load or build index
    index = None
    if args.cached_index and Path(args.cached_index).exists():
        print(f"Loading cached index: {args.cached_index}", file=sys.stderr)
        try:
            index = JavaIndex.load(args.cached_index)
            print(f"Loaded index with {len(index.classes)} classes", file=sys.stderr)
        except Exception as e:
            print(f"Failed to load cached index: {e}", file=sys.stderr)

    if index is None:
        print(f"Building fresh index for: {repo_path}", file=sys.stderr)
        indexer = JavaIndexer(str(repo_path))
        index = indexer.index_repo(show_progress=False)
        print(f"Indexed {len(index.classes)} classes", file=sys.stderr)

    # Stream index to BigQuery
    if bq_client and index:
        stream_index_to_bigquery(bq_client, repo_name, index, args.git_sha)

    query = ContextQuery(index)

    # Try to load the skill's context gathering functions
    gather_context, format_context_for_prompt = get_skill_context_gatherer()
    use_rich_context = gather_context is not None and format_context_for_prompt is not None
    if use_rich_context:
        print("Using java_test_generator skill for rich context", file=sys.stderr)
    else:
        print("Skill not available, using basic context", file=sys.stderr)

    # Save index temporarily for skill to use
    temp_index_path = None
    if use_rich_context:
        temp_index_path = Path('/tmp/cloudbuild_index.json')
        index.save(str(temp_index_path))

    # Find classes to generate tests for
    classes_to_test = []
    for f in changed_files:
        for cls in index.classes.values():
            if cls.source_file and f.endswith(cls.source_file):
                classes_to_test.append(cls.name)
    classes_to_test = list(set(classes_to_test))[:args.max_classes]

    print(f"Generating tests for {len(classes_to_test)} classes...", file=sys.stderr)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = {'generated': [], 'skipped': [], 'failed': []}
    model = os.getenv("OPENROUTER_MODEL", "google/gemma-3-4b-it:free")

    for cls_name in classes_to_test:
        print(f"  Processing: {cls_name}", file=sys.stderr)

        context = query.get_class_with_dependencies(cls_name)
        if not context or not context.get('class'):
            results['skipped'].append({'class': cls_name, 'reason': 'Not found in index'})
            continue

        cls = context['class']
        deps = context.get('dependencies', {})
        fqn = cls.get('fqn', cls_name)

        # Generate test
        test_code = None
        llm_used = False
        error = None
        generation_time_ms = 0
        rich_context = None

        if not args.no_llm:
            # Try rich context first (from skill)
            if use_rich_context:
                try:
                    rich_context = gather_context(
                        str(temp_index_path),
                        cls_name,
                        str(repo_path)
                    )
                    if rich_context and 'error' not in rich_context:
                        print(f"    Using rich context (TestSamples, schemas)", file=sys.stderr)
                        test_code, error, generation_time_ms = generate_test_with_llm_rich(
                            cls_name, rich_context, format_context_for_prompt
                        )
                        if test_code:
                            llm_used = True
                except Exception as e:
                    print(f"    Rich context failed: {e}", file=sys.stderr)

            # Fallback to basic context
            if not test_code:
                test_code, error, generation_time_ms = generate_test_with_llm(cls, deps)
                if test_code:
                    llm_used = True
                elif error:
                    print(f"    LLM failed: {error}", file=sys.stderr)

        if not test_code:
            test_code = generate_template_test(cls, deps)

        # Write test file
        package_path = fqn.rsplit('.', 1)[0].replace('.', '/') if '.' in fqn else ''
        test_dir = output_dir / package_path
        test_dir.mkdir(parents=True, exist_ok=True)

        output_path = test_dir / f"{cls_name}Test.java"
        output_path.write_text(test_code)

        result = {
            'class': cls_name,
            'fqn': fqn,
            'test_file': str(output_path),
            'llm_used': llm_used,
            'rich_context_used': rich_context is not None,
            'generation_time_ms': generation_time_ms,
        }
        results['generated'].append(result)
        context_type = "rich" if rich_context else ("basic" if llm_used else "template")
        print(f"    Generated: {output_path} [{context_type}]", file=sys.stderr)

        # Track in BigQuery
        if bq_client:
            bq_client.stream_generated_test(
                repo=repo_name,
                class_fqn=fqn,
                success=True,
                test_code=test_code if len(test_code) < 50000 else test_code[:50000],  # Limit size
                model_used=model if llm_used else "template",
                trigger_type="cloudbuild",
                trigger_ref=args.build_id,
                generation_time_ms=generation_time_ms,
            )

    # Save updated index
    if args.output_index:
        print(f"Saving index to: {args.output_index}", file=sys.stderr)
        indexer = JavaIndexer(str(repo_path))
        indexer.index = index
        indexer.save_index(args.output_index)

    # Output results
    if args.json_output:
        print(json.dumps(results, indent=2))
    else:
        print(f"\nGenerated: {len(results['generated'])} tests", file=sys.stderr)
        print(f"Skipped: {len(results['skipped'])}", file=sys.stderr)
        print(f"Failed: {len(results['failed'])}", file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
