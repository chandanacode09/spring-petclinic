"""Self-healing test generation with static analysis and LLM-based fixing.

This module provides:
1. Static code analysis (no Maven/Gradle required)
2. Error classification (fixable vs unfixable)
3. LLM-based error fixing with context
4. Validation loop with best-attempt tracking
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, List, Tuple

# Load .env file from project root
try:
    from dotenv import load_dotenv
    current = Path(__file__).parent
    for _ in range(3):
        env_file = current / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=True)
            break
        current = current.parent
except ImportError:
    pass

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Categories of compilation/test errors."""
    MISSING_IMPORT = "missing_import"
    MISSING_SYMBOL = "missing_symbol"
    TYPE_MISMATCH = "type_mismatch"
    MISSING_MOCK = "missing_mock"
    NULL_POINTER = "null_pointer"
    ASSERTION_FAILED = "assertion_failed"
    PRIVATE_ACCESS = "private_access"
    EXTERNAL_DEPENDENCY = "external_dependency"
    SYNTAX_ERROR = "syntax_error"
    MISSING_ANNOTATION = "missing_annotation"
    UNKNOWN = "unknown"


class Fixability(Enum):
    """Whether an error can be fixed by LLM."""
    FIXABLE = "fixable"
    MAYBE_FIXABLE = "maybe_fixable"
    UNFIXABLE = "unfixable"


@dataclass
class ClassifiedError:
    """A classified compilation or test error."""
    category: ErrorCategory
    fixability: Fixability
    message: str
    symbol: Optional[str] = None
    line_number: Optional[int] = None
    suggestion: Optional[str] = None


@dataclass
class HealingAttempt:
    """Record of a single healing attempt."""
    attempt_number: int
    test_code: str
    valid: bool
    errors: List[ClassifiedError] = field(default_factory=list)
    fix_applied: bool = False
    fix_description: Optional[str] = None
    is_persistent: bool = False


@dataclass
class HealingResult:
    """Result of the self-healing process."""
    final_code: str
    success: bool
    attempts: List[HealingAttempt]
    best_code: str
    min_error_count: int
    failure_reason: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)


def validate_syntax(test_code: str) -> Tuple[bool, List[str]]:
    """Validate Java test code syntax.

    Args:
        test_code: The Java test code.

    Returns:
        Tuple of (valid: bool, errors: list of str)
    """
    errors = []

    # Check for basic structure
    if "class " not in test_code:
        errors.append("Missing class declaration")

    if "@Test" not in test_code:
        errors.append("Missing @Test annotation - no test methods found")

    # Check for unbalanced braces
    open_braces = test_code.count('{')
    close_braces = test_code.count('}')
    if open_braces != close_braces:
        errors.append(f"Unbalanced braces: {open_braces} open, {close_braces} close")

    # Check for unbalanced parentheses
    open_parens = test_code.count('(')
    close_parens = test_code.count(')')
    if open_parens != close_parens:
        errors.append(f"Unbalanced parentheses: {open_parens} open, {close_parens} close")

    # Check for common syntax issues
    if re.search(r';\s*;', test_code):
        errors.append("Double semicolon detected")

    # Check for missing semicolons after statements
    lines = test_code.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Skip comments, empty lines, annotations, braces
        if not stripped or stripped.startswith('//') or stripped.startswith('*'):
            continue
        if stripped.startswith('@') or stripped.endswith('{') or stripped.endswith('}'):
            continue
        if stripped.startswith('package') or stripped.startswith('import'):
            if not stripped.endswith(';'):
                errors.append(f"Line {i+1}: Missing semicolon after '{stripped[:30]}...'")

    return len(errors) == 0, errors


def classify_error(error_text: str, index=None) -> ClassifiedError:
    """Classify a compilation or test error.

    Args:
        error_text: The error message from compiler or test runner.
        index: Optional JavaIndex to check if symbols exist.

    Returns:
        ClassifiedError with category, fixability, and suggestions.
    """
    error_lower = error_text.lower()

    # Missing import / cannot find symbol
    if "cannot find symbol" in error_lower or "missing import" in error_lower:
        symbol_match = re.search(r"symbol:\s*(?:class|variable|method)\s+(\w+)", error_text)
        if not symbol_match:
            symbol_match = re.search(r"for (\w+)", error_text)
        symbol = symbol_match.group(1) if symbol_match else None

        if index and symbol:
            if hasattr(index, 'class_lookup') and symbol in index.class_lookup:
                return ClassifiedError(
                    category=ErrorCategory.MISSING_IMPORT,
                    fixability=Fixability.FIXABLE,
                    message=error_text,
                    symbol=symbol,
                    suggestion=f"Add import for {symbol} from the index"
                )

        return ClassifiedError(
            category=ErrorCategory.MISSING_IMPORT,
            fixability=Fixability.FIXABLE,
            message=error_text,
            symbol=symbol,
            suggestion="Add missing import statement"
        )

    # Type mismatch
    if "incompatible types" in error_lower or "cannot be converted" in error_lower:
        return ClassifiedError(
            category=ErrorCategory.TYPE_MISMATCH,
            fixability=Fixability.FIXABLE,
            message=error_text,
            suggestion="Fix type conversion or use correct type"
        )

    # Private access
    if "has private access" in error_lower or "is not visible" in error_lower:
        return ClassifiedError(
            category=ErrorCategory.PRIVATE_ACCESS,
            fixability=Fixability.UNFIXABLE,
            message=error_text,
            suggestion="Cannot access private members - test via public methods"
        )

    # Missing mock setup
    if "missing mock" in error_lower or "mock setup" in error_lower:
        return ClassifiedError(
            category=ErrorCategory.MISSING_MOCK,
            fixability=Fixability.FIXABLE,
            message=error_text,
            suggestion="Add when().thenReturn() for mocked dependencies"
        )

    # Missing annotation
    if "missing annotation" in error_lower or "@mock" in error_lower:
        return ClassifiedError(
            category=ErrorCategory.MISSING_ANNOTATION,
            fixability=Fixability.FIXABLE,
            message=error_text,
            suggestion="Add required annotation"
        )

    # Syntax error
    if "unbalanced" in error_lower or "syntax" in error_lower or "semicolon" in error_lower:
        return ClassifiedError(
            category=ErrorCategory.SYNTAX_ERROR,
            fixability=Fixability.FIXABLE,
            message=error_text,
            suggestion="Fix syntax error"
        )

    # Unknown error
    return ClassifiedError(
        category=ErrorCategory.UNKNOWN,
        fixability=Fixability.MAYBE_FIXABLE,
        message=error_text,
        suggestion="Review the error and fix manually"
    )


def analyze_test_code(test_code: str, cls: dict, deps: dict, index=None) -> List[ClassifiedError]:
    """Analyze test code for potential issues using static analysis.

    Args:
        test_code: The Java test code.
        cls: Class information dict.
        deps: Dependencies dict.
        index: Optional JavaIndex for symbol lookup.

    Returns:
        List of ClassifiedError objects.
    """
    errors = []
    class_name = cls.get('name', '')

    # 1. Validate basic syntax
    valid, syntax_errors = validate_syntax(test_code)
    for err_msg in syntax_errors:
        errors.append(ClassifiedError(
            category=ErrorCategory.SYNTAX_ERROR,
            fixability=Fixability.FIXABLE,
            message=err_msg,
            suggestion="Fix syntax error"
        ))

    # Helper to check if an import is covered (explicit or wildcard)
    def is_import_covered(fqn: str, code: str) -> bool:
        """Check if a fully qualified name is covered by existing imports."""
        if not fqn:
            return True
        # Check explicit import
        if f"import {fqn};" in code:
            return True
        # Check wildcard import (e.g., import io.github.sample.domain.*;)
        if '.' in fqn:
            package = fqn.rsplit('.', 1)[0]  # Get package part
            if f"import {package}.*;" in code:
                return True
        return False

    # 2. Check if class under test is imported
    fqn = cls.get('fqn', '')
    if fqn and not is_import_covered(fqn, test_code) and class_name in test_code:
        errors.append(ClassifiedError(
            category=ErrorCategory.MISSING_IMPORT,
            fixability=Fixability.FIXABLE,
            message=f"Missing import for class under test: {fqn}",
            symbol=class_name,
            suggestion=f"Add: import {fqn};"
        ))

    # 3. Check if dependencies are imported
    for dep_name, dep_info in deps.items():
        # Handle both dict and non-dict dep_info
        if isinstance(dep_info, dict):
            if not dep_info.get('external'):
                dep_fqn = dep_info.get('fqn', '')
                if dep_fqn and dep_name in test_code and not is_import_covered(dep_fqn, test_code):
                    errors.append(ClassifiedError(
                        category=ErrorCategory.MISSING_IMPORT,
                        fixability=Fixability.FIXABLE,
                        message=f"Missing import for dependency: {dep_fqn}",
                        symbol=dep_name,
                        suggestion=f"Add: import {dep_fqn};"
                    ))

    # 4. Check for @Mock without MockitoAnnotations
    if "@Mock" in test_code:
        has_init = ("MockitoAnnotations.openMocks" in test_code or
                   "MockitoAnnotations.initMocks" in test_code or
                   "@ExtendWith(MockitoExtension" in test_code or
                   "@RunWith(MockitoJUnitRunner" in test_code)
        if not has_init:
            errors.append(ClassifiedError(
                category=ErrorCategory.MISSING_ANNOTATION,
                fixability=Fixability.FIXABLE,
                message="@Mock used but no MockitoAnnotations initialization found",
                suggestion="Add @ExtendWith(MockitoExtension.class) or MockitoAnnotations.openMocks(this) in @BeforeEach"
            ))

    # 5. Check for mocked dependencies that might need when().thenReturn()
    mocked_fields = re.findall(r'@Mock\s+(?:private\s+)?(\w+)\s+(\w+);', test_code)
    for type_name, field_name in mocked_fields:
        # Look for method calls on this mock in test methods
        test_method_pattern = r'@Test[^}]+void\s+\w+\([^)]*\)\s*\{([^}]+)\}'
        test_methods = re.findall(test_method_pattern, test_code, re.DOTALL)

        for method_body in test_methods:
            mock_calls = re.findall(rf'{field_name}\.(\w+)\(', method_body)
            for method in mock_calls:
                # Check if there's a when() setup for this
                if f"when({field_name}.{method}" not in test_code:
                    errors.append(ClassifiedError(
                        category=ErrorCategory.MISSING_MOCK,
                        fixability=Fixability.FIXABLE,
                        message=f"Mock {field_name}.{method}() called but no when().thenReturn() setup",
                        symbol=f"{field_name}.{method}",
                        suggestion=f"Add: when({field_name}.{method}(...)).thenReturn(...);"
                    ))

    # 6. Check constructor usage against grounded context
    constructors = cls.get('constructors', [])
    if constructors:
        # Check if any constructor is used
        new_pattern = rf'new\s+{class_name}\s*\(([^)]*)\)'
        constructor_calls = re.findall(new_pattern, test_code)

        for args in constructor_calls:
            arg_count = len([a.strip() for a in args.split(',') if a.strip()]) if args.strip() else 0

            # Check if any constructor matches this arg count
            matching = False
            valid_counts = []
            for ctor in constructors:
                # Handle both dict format and string signature format
                if isinstance(ctor, dict):
                    ctor_params = ctor.get('parameters', [])
                    param_count = len(ctor_params)
                elif isinstance(ctor, str):
                    # Parse signature like "BankAccount(Long id, String name)"
                    match = re.search(r'\(([^)]*)\)', ctor)
                    if match:
                        params_str = match.group(1).strip()
                        param_count = len([p.strip() for p in params_str.split(',') if p.strip()]) if params_str else 0
                    else:
                        param_count = 0
                else:
                    param_count = 0

                valid_counts.append(param_count)
                if param_count == arg_count:
                    matching = True
                    break

            if not matching and constructors:
                errors.append(ClassifiedError(
                    category=ErrorCategory.TYPE_MISMATCH,
                    fixability=Fixability.FIXABLE,
                    message=f"Constructor call with {arg_count} args doesn't match any known constructor",
                    suggestion=f"Use constructor with {valid_counts} parameters"
                ))

    return errors


def ask_llm_to_fix(test_code: str, classified_errors: List[ClassifiedError],
                   cls: dict, deps: dict, attempt_num: int) -> Tuple[str, str]:
    """Ask LLM to fix the test code based on errors.

    Args:
        test_code: Current test code.
        classified_errors: List of ClassifiedError objects.
        cls: Class information dict.
        deps: Dependencies dict.
        attempt_num: Current attempt number.

    Returns:
        Tuple of (fixed_code: str, fix_description: str)
    """
    try:
        from openai import OpenAI
    except ImportError:
        return test_code, "openai package not installed"

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return test_code, "API key not set"

    model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=api_key,
    )

    # Build error context
    error_summary = "\n".join([
        f"- [{e.category.value}] {e.message[:200]}" +
        (f"\n  Suggestion: {e.suggestion}" if e.suggestion else "")
        for e in classified_errors[:5]
    ])

    # Build grounded context
    constructors = cls.get('constructors', [])
    methods = cls.get('methods', [])[:10]

    prompt = f"""Fix the following Java test code that has issues found by static analysis.

ATTEMPT: {attempt_num} of 3

ISSUES FOUND:
{error_summary}

CURRENT TEST CODE:
```java
{test_code}
```

GROUNDED CONTEXT (use ONLY these - do not invent):
- Class: {cls.get('name')}
- Package: {cls.get('package', 'unknown')}
- FQN: {cls.get('fqn', '')}
- Constructors: {json.dumps(constructors)}
- Methods (sample): {json.dumps(methods)}

DEPENDENCIES:
"""
    for dep_name, dep_info in list(deps.items())[:10]:
        # Handle both dict and non-dict dep_info
        if isinstance(dep_info, dict):
            if dep_info.get('external'):
                prompt += f"\n- {dep_name}: EXTERNAL (mock it)"
            else:
                dep_fqn = dep_info.get('fqn', '')
                prompt += f"\n- {dep_name}: {dep_fqn}"
        else:
            prompt += f"\n- {dep_name}: {dep_info}"

    prompt += """

RULES:
1. Fix ONLY the issues mentioned - don't rewrite the whole test
2. Use ONLY constructors/methods from the grounded context
3. Add missing imports with correct FQN
4. Add proper Mockito setup if needed
5. Keep the test logic intact

Output ONLY the fixed Java code, no explanations."""

    try:
        full_prompt = "You are an expert Java developer fixing test code. " + prompt

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": full_prompt}],
            temperature=0.2,
            max_tokens=4000,
        )

        fixed_code = response.choices[0].message.content

        # Clean up markdown
        if "```java" in fixed_code:
            start = fixed_code.find("```java") + 7
            end = fixed_code.find("```", start)
            if end > start:
                fixed_code = fixed_code[start:end]
        elif "```" in fixed_code:
            start = fixed_code.find("```") + 3
            end = fixed_code.find("```", start)
            if end > start:
                fixed_code = fixed_code[start:end]

        fix_description = "LLM fixed: " + ", ".join(
            e.category.value for e in classified_errors[:3]
        )

        return fixed_code.strip(), fix_description

    except Exception as e:
        logger.error(f"LLM fix failed: {e}")
        return test_code, f"LLM fix failed: {e}"


def run_self_healing_loop(
    test_code: str,
    cls: dict,
    deps: dict,
    method_name: Optional[str] = None,
    repo_path: str = "",
    index=None,
    max_attempts: int = 3
) -> HealingResult:
    """Run the self-healing test generation loop using static analysis.

    No Maven/Gradle required - uses static code analysis to find issues.

    Args:
        test_code: Initial generated test code.
        cls: Class information dict.
        deps: Dependencies dict.
        method_name: Optional specific method being tested (unused, kept for API compat).
        repo_path: Path to the Java repository (unused, kept for API compat).
        index: Optional JavaIndex for symbol lookup.
        max_attempts: Maximum number of fix attempts.

    Returns:
        HealingResult with final code, success status, and attempt history.
    """
    attempts = []
    best_code = test_code
    min_errors = float('inf')
    current_code = test_code
    previous_errors_key = None

    for attempt_num in range(1, max_attempts + 1):
        # Analyze current code
        errors = analyze_test_code(current_code, cls, deps, index)

        attempt = HealingAttempt(
            attempt_number=attempt_num,
            test_code=current_code,
            valid=len(errors) == 0,
            errors=errors
        )

        # Success - no errors found
        if len(errors) == 0:
            attempts.append(attempt)
            return HealingResult(
                final_code=current_code,
                success=True,
                attempts=attempts,
                best_code=current_code,
                min_error_count=0
            )

        # Track best attempt
        if len(errors) < min_errors:
            min_errors = len(errors)
            best_code = current_code

        # Check for persistent errors (same errors as before)
        current_errors_key = tuple(sorted(e.message for e in errors))
        if previous_errors_key and current_errors_key == previous_errors_key:
            attempt.is_persistent = True
            attempts.append(attempt)

            suggestions = list(set(e.suggestion for e in errors if e.suggestion))
            return HealingResult(
                final_code=best_code,
                success=False,
                attempts=attempts,
                best_code=best_code,
                min_error_count=min_errors,
                failure_reason=f"Persistent errors after {attempt_num} attempts",
                suggestions=suggestions or ["Review the errors and fix manually"]
            )

        previous_errors_key = current_errors_key

        # Check if all errors are unfixable
        all_unfixable = all(e.fixability == Fixability.UNFIXABLE for e in errors)
        if all_unfixable:
            attempts.append(attempt)
            return HealingResult(
                final_code=best_code,
                success=False,
                attempts=attempts,
                best_code=best_code,
                min_error_count=min_errors,
                failure_reason="All errors are unfixable",
                suggestions=[e.suggestion for e in errors if e.suggestion]
            )

        # Ask LLM to fix
        if attempt_num < max_attempts:
            fixed_code, fix_desc = ask_llm_to_fix(
                current_code, errors, cls, deps, attempt_num
            )
            attempt.fix_applied = True
            attempt.fix_description = fix_desc
            current_code = fixed_code

        attempts.append(attempt)

    # Max attempts reached
    return HealingResult(
        final_code=best_code,
        success=False,
        attempts=attempts,
        best_code=best_code,
        min_error_count=min_errors,
        failure_reason=f"Max attempts ({max_attempts}) reached",
        suggestions=["Review the remaining errors and fix manually"]
    )
