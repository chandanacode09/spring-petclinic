---
name: java-test-generator
description: |
  Generate comprehensive, grounded JUnit 5 unit tests for Java classes using rich AST context,
  database schemas, API endpoints, existing test patterns, and relationship information.
  Use this skill when you need to generate meaningful tests with real test data, proper
  assertions, and correct relationship handling. Keywords: java, junit, test, unit test,
  mockito, assertj, jpa, entity, service, controller, spring boot.
license: Apache-2.0
compatibility: |
  Requires Python 3.9+, tree-sitter, openai package.
  Requires OPENROUTER_API_KEY for LLM test generation.
metadata:
  author: pipeline-context-agent
  version: "1.0"
  category: testing
  platform: java
allowed-tools: Bash(python:*) Read Write Grep
---

# Java Test Generator Skill

## Overview

This skill generates meaningful, compilable JUnit 5 unit tests by gathering comprehensive context:

1. **Class AST Context** - Full class structure from Java index (methods, fields, constructors)
2. **Database Schema** - JPA entity column definitions, constraints, relationships
3. **Dependency Graph** - All classes the target depends on, with their constructors
4. **Existing Test Patterns** - TestSamples classes, test utilities in the repo
5. **API Context** - For controllers, includes endpoint info and request/response types
6. **Relationship Info** - Bidirectional relationships with cascade/fetch behavior

## When to Use This Skill

Invoke this skill when:
- User asks to generate a unit test for a Java class
- User needs test coverage for an entity, service, or controller
- Tests need to handle complex relationships (OneToMany, ManyToOne)
- Tests require realistic sample data

## Test Generation Workflow

### Step 1: Gather Rich Context

Collect all relevant context for test generation:

```bash
python skills/java-test-generator/scripts/gather_context.py \
  --index java_index.json \
  --class-name BankAccount \
  --repo-path repos/jhipster-sample-app \
  --output /tmp/test_context.json
```

This gathers:
- Full class definition with all methods and fields
- Database schema if it's a JPA entity
- All dependencies with their constructors
- Existing TestSamples class if available
- Existing tests for this class
- Related entity test samples

### Step 2: Generate Test with LLM

Generate a comprehensive test using the gathered context:

```bash
python skills/java-test-generator/scripts/generate_test.py \
  --context /tmp/test_context.json \
  --method-name <optional_method> \
  --output /tmp/generated_test.java
```

The LLM receives:
- Exact constructor signatures (to avoid hallucination)
- Realistic sample data patterns from existing tests
- Schema constraints (nullable, length, precision)
- Relationship mappings with proper setup/teardown

### Step 3: Validate and Heal

Compile and run the test, auto-fixing issues:

```bash
python skills/java-test-generator/scripts/validate_test.py \
  --test-file /tmp/generated_test.java \
  --repo-path repos/jhipster-sample-app \
  --max-attempts 3
```

## Context Schema

The `gather_context.py` script produces this JSON structure:

```json
{
  "target_class": {
    "name": "BankAccount",
    "fqn": "io.github.jhipster.sample.domain.BankAccount",
    "kind": "entity",
    "constructors": [...],
    "methods": [...],
    "fields": [...]
  },
  "database_schema": {
    "table_name": "bank_account",
    "columns": [
      {"name": "id", "java_type": "Long", "is_pk": true, "is_generated": true},
      {"name": "name", "java_type": "String", "nullable": false, "length": 255},
      {"name": "balance", "java_type": "BigDecimal", "precision": 21, "scale": 2}
    ],
    "relationships": [
      {"type": "MANY_TO_ONE", "target_entity": "User", "java_field": "user"},
      {"type": "ONE_TO_MANY", "target_entity": "Operation", "java_field": "operations"}
    ]
  },
  "dependencies": {
    "User": {
      "fqn": "io.github.jhipster.sample.domain.User",
      "constructors": ["User()", "User(Long id)"],
      "has_test_samples": true
    },
    "Operation": {
      "fqn": "io.github.jhipster.sample.domain.Operation",
      "constructors": ["Operation()"],
      "has_test_samples": true
    }
  },
  "existing_test_samples": {
    "class_name": "BankAccountTestSamples",
    "methods": [
      "getBankAccountSample1() -> new BankAccount().id(1L).name(\"name1\")",
      "getBankAccountSample2() -> new BankAccount().id(2L).name(\"name2\")",
      "getBankAccountRandomSampleGenerator() -> uses Random/UUID"
    ]
  },
  "test_patterns": {
    "uses_assertj": true,
    "uses_mockito": false,
    "has_equals_verifier": true,
    "has_relationship_tests": true,
    "sample_test_snippets": [
      "@Test void equalsVerifier() { ... }",
      "@Test void operationTest() { ... }"
    ]
  },
  "repo_test_utilities": [
    "TestUtil.equalsVerifier(Class<?>)",
    "TestUtil.createFormattingConversionService()"
  ]
}
```

## LLM Prompt Structure

The LLM receives a carefully structured prompt:

```
CONTEXT: You are generating a JUnit 5 test for a Java class.

TARGET CLASS:
- Name: BankAccount (JPA Entity)
- Package: io.github.jhipster.sample.domain
- Constructors: [BankAccount(), BankAccount(Long id)]

DATABASE SCHEMA:
- Table: bank_account
- Columns:
  - id: Long (PK, auto-generated)
  - name: String (NOT NULL)
  - balance: BigDecimal(21,2) (NOT NULL)
- Relationships:
  - user: ManyToOne -> User (optional, LAZY)
  - operations: OneToMany -> Operation (mapped by bankAccount)

SAMPLE DATA (from existing TestSamples):
- Sample 1: new BankAccount().id(1L).name("name1")
- Sample 2: new BankAccount().id(2L).name("name2")
- Random: new BankAccount().id(longCount.incrementAndGet()).name(UUID.randomUUID().toString())

DEPENDENCY SAMPLES:
- User: getUserSample1(), getUserSample2()
- Operation: getOperationSample1(), getOperationSample2()

EXISTING TEST PATTERNS:
- Uses AssertJ (assertThat)
- Has equals verifier test
- Tests bidirectional relationship sync

GENERATE:
A comprehensive test class that:
1. Uses the EXACT constructors and builder methods shown above
2. Uses realistic sample data matching the schema constraints
3. Tests bidirectional relationship add/remove properly
4. Includes edge cases for nullable fields
5. Uses existing TestSamples when available
```

## Output Format

Generated test follows this structure:

```java
package io.github.jhipster.sample.domain;

import static io.github.jhipster.sample.domain.BankAccountTestSamples.*;
import static io.github.jhipster.sample.domain.OperationTestSamples.*;
import static io.github.jhipster.sample.domain.UserTestSamples.*;
import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;
import java.math.BigDecimal;

class BankAccountTest {

    @Test
    void shouldCreateWithValidData() {
        // Using sample data matching schema constraints
        BankAccount account = new BankAccount()
            .id(1L)
            .name("Savings Account")  // NOT NULL per schema
            .balance(new BigDecimal("1000.50"));  // precision 21, scale 2

        assertThat(account.getName()).isEqualTo("Savings Account");
        assertThat(account.getBalance()).isEqualByComparingTo("1000.50");
    }

    @Test
    void shouldHandleUserRelationship() {
        BankAccount account = getBankAccountSample1();
        User user = getUserSample1();

        account.setUser(user);

        assertThat(account.getUser()).isEqualTo(user);
    }

    @Test
    void shouldSyncBidirectionalOperations() {
        BankAccount account = getBankAccountRandomSampleGenerator();
        Operation operation = getOperationRandomSampleGenerator();

        // Add operation - should set back-reference
        account.addOperation(operation);
        assertThat(account.getOperations()).containsOnly(operation);
        assertThat(operation.getBankAccount()).isEqualTo(account);

        // Remove operation - should clear back-reference
        account.removeOperation(operation);
        assertThat(account.getOperations()).doesNotContain(operation);
        assertThat(operation.getBankAccount()).isNull();
    }

    @Test
    void shouldHandleNullableBalance() {
        BankAccount account = new BankAccount().id(1L).name("Test");
        // balance is NOT NULL per schema, but test default behavior
        assertThat(account.getBalance()).isNull();  // before setting
    }
}
```

## Important Constraints

- **Never invent constructors** - Only use exact signatures from the index
- **Use schema constraints** - Respect NOT NULL, length limits, precision/scale
- **Follow existing patterns** - Match the repo's test style (AssertJ vs JUnit assertions)
- **Test relationships properly** - Handle bidirectional sync, cascade behavior
- **Use TestSamples** - Import and use existing sample generators when available

## Reference Files

See `references/TEST_PATTERNS.md` for common test patterns.
See `references/SAMPLE_DATA.md` for realistic test data examples by type.
