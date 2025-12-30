#!/usr/bin/env python3
"""Generate Java unit tests using LLM with rich context.

This script takes the context gathered by gather_context.py and
generates comprehensive, grounded unit tests using an LLM.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Load .env file
try:
    from dotenv import load_dotenv
    current = Path(__file__).parent
    for _ in range(5):
        env_file = current / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=True)
            break
        current = current.parent
except ImportError:
    pass


def build_system_prompt() -> str:
    """Build the system prompt for test generation."""
    return """You are an expert Java developer specializing in writing comprehensive JUnit 5 unit tests.

CRITICAL RULES:
1. ONLY use constructors, methods, and fields that are explicitly listed in the context
2. NEVER invent or hallucinate APIs - if it's not in the context, don't use it
3. Use the EXACT method signatures provided
4. Follow the existing test patterns found in the repository
5. Generate realistic test data that respects schema constraints (NOT NULL, length limits, precision)
6. Test bidirectional relationships properly (add/remove should sync both sides)
7. Use existing TestSamples classes when available (import and call their methods)
8. Prefer AssertJ assertions (assertThat) if the repo uses them

OUTPUT RULES:
1. Output ONLY valid, compilable Java code
2. No markdown code blocks, no explanations
3. Include all necessary imports at the top
4. Use the correct package declaration matching the target class
5. Follow Java naming conventions"""


def build_user_prompt(context: Dict[str, Any], method_name: Optional[str] = None) -> str:
    """Build the user prompt from context."""
    from gather_context import format_context_for_prompt

    target = context.get('target_class', {})
    schema = context.get('database_schema')
    samples = context.get('existing_test_samples')
    existing = context.get('existing_tests')
    dep_samples = context.get('dependency_samples', {})

    prompt_parts = []

    # Context section
    prompt_parts.append("CONTEXT FOR TEST GENERATION:")
    prompt_parts.append(format_context_for_prompt(context))

    # Specific instructions based on class kind
    kind = target.get('kind', 'class')
    prompt_parts.append("\n" + "=" * 60)
    prompt_parts.append("GENERATION INSTRUCTIONS")
    prompt_parts.append("=" * 60)

    if kind == 'entity':
        prompt_parts.append("""
Generate a JPA entity test that includes:
1. Basic CRUD operations using builder/setter pattern
2. Equals and hashCode verification (use TestUtil.equalsVerifier if available)
3. Bidirectional relationship tests (add/remove should sync both sides)
4. Field validation tests based on schema constraints
5. Use TestSamples methods for creating test objects when available""")

    elif kind == 'service':
        prompt_parts.append("""
Generate a service test that includes:
1. @ExtendWith(MockitoExtension.class) annotation
2. @Mock annotations for all dependencies (repositories, other services)
3. @InjectMocks for the service under test
4. Happy path tests for main methods
5. Error/exception handling tests
6. Proper when().thenReturn() setup for mocks
7. verify() calls to ensure correct interactions""")

    elif kind == 'controller':
        prompt_parts.append("""
Generate a controller test that includes:
1. MockMvc setup with standaloneSetup or webAppContextSetup
2. Tests for each endpoint (GET, POST, PUT, DELETE)
3. Request/response body validation
4. HTTP status code assertions
5. Content type verification
6. Error response handling""")

    else:
        prompt_parts.append("""
Generate a comprehensive test that includes:
1. Constructor tests
2. Method behavior tests
3. Edge cases (null inputs, empty collections, boundary values)
4. Exception scenarios""")

    # Sample data guidance
    if samples:
        prompt_parts.append(f"""
IMPORTANT: Use the existing {samples.get('class_name')} for test data:
- Import: import static {target.get('package')}.{samples.get('class_name')}.*;""")
        for method in samples.get('methods', []):
            prompt_parts.append(f"- Use {method.get('name')}() which returns: {method.get('return_expression')}")

    # Dependency samples
    if any(ds.get('has_samples') for ds in dep_samples.values()):
        prompt_parts.append("\nDEPENDENCY SAMPLES TO USE:")
        for dep_name, ds in dep_samples.items():
            if ds.get('has_samples'):
                prompt_parts.append(f"- Import {dep_name}TestSamples and use: {', '.join(ds.get('sample_methods', []))}")

    # Schema constraints for test data
    if schema:
        prompt_parts.append("\nTEST DATA CONSTRAINTS FROM SCHEMA:")
        for col in schema.get('columns', []):
            constraints = []
            if not col.get('nullable', True):
                constraints.append("required")
            if col.get('length'):
                constraints.append(f"max length {col.get('length')}")
            if col.get('precision'):
                constraints.append(f"precision {col.get('precision')}, scale {col.get('scale', 0)}")
            if constraints:
                prompt_parts.append(f"- {col.get('name')}: {', '.join(constraints)}")

    # Test pattern guidance
    if existing:
        prompt_parts.append("\nFOLLOW THESE PATTERNS FROM EXISTING TESTS:")
        if existing.get('uses_assertj'):
            prompt_parts.append("- Use AssertJ: assertThat(actual).isEqualTo(expected)")
        if existing.get('uses_mockito'):
            prompt_parts.append("- Use Mockito: @Mock, when().thenReturn(), verify()")
        if existing.get('has_before_each'):
            prompt_parts.append("- Use @BeforeEach for setup")

    # Specific method if requested
    if method_name:
        prompt_parts.append(f"\nFOCUS ON TESTING METHOD: {method_name}")
        target_method = context.get('target_method')
        if target_method:
            params = ', '.join([
                f"{p.get('type')} {p.get('name')}"
                for p in target_method.get('parameters', [])
            ])
            prompt_parts.append(f"Signature: {target_method.get('return_type')} {method_name}({params})")

    prompt_parts.append("\nNow generate the complete test class:")

    return '\n'.join(prompt_parts)


def generate_test_with_llm(
    context: Dict[str, Any],
    method_name: Optional[str] = None,
    model: Optional[str] = None
) -> tuple[str, bool]:
    """Generate test code using LLM.

    Returns:
        tuple: (test_code, llm_used) - the generated code and whether LLM was used
    """
    try:
        from openai import OpenAI
    except ImportError:
        print("Warning: openai package not installed, using template fallback", file=sys.stderr)
        return generate_template_test(context, method_name), False

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("Warning: OPENROUTER_API_KEY not set, using template fallback", file=sys.stderr)
        return generate_template_test(context, method_name), False

    model = model or os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt(context, method_name)

    try:
        # For models that don't support system messages well, combine them
        full_prompt = system_prompt + "\n\n" + user_prompt

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": full_prompt}
            ],
            temperature=0.2,  # Lower temperature for more consistent code
            max_tokens=4000,
        )

        test_code = response.choices[0].message.content.strip()

        # Clean up markdown code blocks if present
        if test_code.startswith("```java"):
            test_code = test_code[7:]
        elif test_code.startswith("```"):
            test_code = test_code[3:]
        if test_code.endswith("```"):
            test_code = test_code[:-3]

        return test_code.strip(), True

    except Exception as e:
        print(f"Warning: LLM generation failed ({e}), using template fallback", file=sys.stderr)
        return generate_template_test(context, method_name), False


def generate_template_test(context: Dict[str, Any], method_name: Optional[str] = None) -> str:
    """Generate a basic template test when LLM is unavailable."""
    target = context.get('target_class', {})
    class_name = target.get('name', 'Unknown')
    package = target.get('package', 'com.example')
    kind = target.get('kind', 'class')
    schema = context.get('database_schema')
    samples = context.get('existing_test_samples')

    lines = [f"package {package};", ""]

    # Imports
    lines.append("import org.junit.jupiter.api.Test;")
    lines.append("import static org.assertj.core.api.Assertions.assertThat;")

    if samples:
        lines.append(f"import static {package}.{samples.get('class_name')}.*;")

    if kind == 'service':
        lines.append("import org.junit.jupiter.api.extension.ExtendWith;")
        lines.append("import org.mockito.InjectMocks;")
        lines.append("import org.mockito.Mock;")
        lines.append("import org.mockito.junit.jupiter.MockitoExtension;")
        lines.append("import static org.mockito.Mockito.*;")

    lines.append("")

    # Class declaration
    if kind == 'service':
        lines.append("@ExtendWith(MockitoExtension.class)")

    lines.append(f"class {class_name}Test {{")
    lines.append("")

    # Generate basic tests based on kind
    if kind == 'entity':
        # Constructor test
        lines.append("    @Test")
        lines.append("    void shouldCreateInstance() {")
        if samples and samples.get('methods'):
            method = samples['methods'][0]
            lines.append(f"        {class_name} instance = {method.get('name')}();")
        else:
            lines.append(f"        {class_name} instance = new {class_name}();")
        lines.append("        assertThat(instance).isNotNull();")
        lines.append("    }")
        lines.append("")

        # Field tests from schema
        if schema:
            for col in schema.get('columns', [])[:3]:
                field = col.get('java_field', col.get('name'))
                java_type = col.get('java_type', 'Object')

                lines.append("    @Test")
                lines.append(f"    void shouldSetAndGet{field.capitalize()}() {{")
                lines.append(f"        {class_name} instance = new {class_name}();")

                # Generate appropriate test value
                if java_type == 'Long':
                    lines.append(f"        instance.set{field.capitalize()}(1L);")
                    lines.append(f"        assertThat(instance.get{field.capitalize()}()).isEqualTo(1L);")
                elif java_type == 'String':
                    lines.append(f'        instance.set{field.capitalize()}("test");')
                    lines.append(f'        assertThat(instance.get{field.capitalize()}()).isEqualTo("test");')
                elif java_type == 'BigDecimal':
                    lines.append("        instance.set{}(new java.math.BigDecimal(\"100.00\"));".format(field.capitalize()))
                    lines.append("        assertThat(instance.get{}()).isEqualByComparingTo(\"100.00\");".format(field.capitalize()))
                else:
                    lines.append(f"        // TODO: Add test for {field}")

                lines.append("    }")
                lines.append("")

    elif kind == 'service':
        # Mock-based service test template
        deps = context.get('dependencies', {})
        for dep_name, dep_info in list(deps.items())[:2]:
            if dep_info.get('kind') == 'repository':
                lines.append("    @Mock")
                lines.append(f"    private {dep_name} {dep_name[0].lower() + dep_name[1:]};")
                lines.append("")

        lines.append("    @InjectMocks")
        lines.append(f"    private {class_name} {class_name[0].lower() + class_name[1:]};")
        lines.append("")

        lines.append("    @Test")
        lines.append("    void shouldPerformBasicOperation() {")
        lines.append("        // TODO: Implement test")
        lines.append("        assertThat(true).isTrue();")
        lines.append("    }")
        lines.append("")

    else:
        # Generic test
        lines.append("    @Test")
        lines.append("    void shouldCreateInstance() {")
        lines.append(f"        {class_name} instance = new {class_name}();")
        lines.append("        assertThat(instance).isNotNull();")
        lines.append("    }")
        lines.append("")

    lines.append("}")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description='Generate Java unit tests using LLM')
    parser.add_argument('--context', required=True, help='Path to context JSON file from gather_context.py')
    parser.add_argument('--method-name', help='Specific method to test (optional)')
    parser.add_argument('--model', help='LLM model to use (default: from OPENROUTER_MODEL env or claude-sonnet)')
    parser.add_argument('--output', help='Output file path (default: stdout)')

    args = parser.parse_args()

    # Load context
    with open(args.context) as f:
        context = json.load(f)

    if 'error' in context:
        print(f"Error in context: {context['error']}", file=sys.stderr)
        sys.exit(1)

    # Generate test
    test_code, llm_used = generate_test_with_llm(context, args.method_name, args.model)

    if args.output:
        Path(args.output).write_text(test_code)
        source = "LLM" if llm_used else "template"
        print(f"Test generated using {source}, written to {args.output}")
    else:
        print(test_code)


if __name__ == '__main__':
    main()
