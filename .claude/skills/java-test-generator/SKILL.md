---
name: java-test-generator
description: Generate JUnit 5 tests for Java classes using AST-grounded context. Automatically loads class signatures, inherited methods, and dependencies from the Java index. Use when creating tests, writing unit tests, or testing Java code.
---

# Java Test Generator Skill

## Purpose

Generate compilable JUnit 5 tests by using **actual class signatures** from the AST index - never invent methods that don't exist.

## When to Use This Skill

Automatically activates when:
- Creating or modifying Java tests
- Working with `*Test.java` files
- User mentions "test", "junit", "unit test" for Java code

---

## CRITICAL RULES

### 1. ALWAYS Load Class Context First

Before generating any test, run:
```bash
python3 scripts/get_class_context.py --class <ClassName>
```

This returns the **actual methods** that exist - use ONLY these.

### 2. NEVER Invent Methods

Common hallucinations to AVOID:
- `setTypeId()` - Does NOT exist. Use `setId()` (from BaseEntity)
- `setTypeName()` - Does NOT exist. Use `setName()` (from NamedEntity)
- `PetType.DOG` - PetType is an ENTITY, not an enum!

### 3. Entity Creation Pattern

All Spring PetClinic entities use **no-arg constructors + setters**:

```java
// CORRECT
PetType type = new PetType();
type.setId(1);        // from BaseEntity
type.setName("dog");  // from NamedEntity

Pet pet = new Pet();
pet.setName("Max");
pet.setBirthDate(LocalDate.now());
pet.setType(type);

// WRONG - DO NOT DO THIS
PetType type = new PetType("dog");  // No such constructor
pet.setType(PetType.DOG);           // PetType is not an enum
petType.setTypeId(1L);              // setTypeId doesn't exist
```

---

## Quick Reference

### Class Hierarchy

```
BaseEntity (id, getId, setId, isNew)
    └── NamedEntity (name, getName, setName, toString)
            ├── PetType (no additional fields)
            ├── Specialty (no additional fields)
            └── Person (firstName, lastName)
                    ├── Owner (address, city, telephone, pets)
                    └── Vet (specialties)
    └── Pet (name, birthDate, type, visits)
    └── Visit (date, description, pet)
```

### Available Methods by Class

Load dynamically with `get_class_context.py`, but common ones:

| Class | Own Methods | Inherited |
|-------|-------------|-----------|
| Pet | setBirthDate, getBirthDate, setType, getType, addVisit, getVisits, getVisitCount | setName, getName, setId, getId, isNew |
| PetType | (none) | setName, getName, setId, getId, isNew, toString |
| Owner | setAddress, getAddress, setCity, getCity, addPet, getPets, getPetCount | setFirstName, setLastName, getName, setId, getId |
| Visit | setDate, getDate, setDescription, getDescription | setId, getId, isNew |

---

## Test Generation Workflow

### Step 1: Get Class Context

```bash
python3 .claude/skills/java-test-generator/scripts/get_class_context.py --class Pet
```

Output shows exact constructors, methods, fields.

### Step 2: Generate Test

Use the context to create tests with ONLY available methods:

```java
package org.springframework.samples.petclinic.owner;

import static org.assertj.core.api.Assertions.*;
import org.junit.jupiter.api.Test;
import java.time.LocalDate;

class PetTest {

    @Test
    void testSetAndGetName() {
        Pet pet = new Pet();
        pet.setName("Max");
        assertThat(pet.getName()).isEqualTo("Max");
    }

    @Test
    void testSetAndGetBirthDate() {
        Pet pet = new Pet();
        LocalDate birthDate = LocalDate.of(2020, 1, 15);
        pet.setBirthDate(birthDate);
        assertThat(pet.getBirthDate()).isEqualTo(birthDate);
    }

    @Test
    void testSetAndGetType() {
        Pet pet = new Pet();
        PetType type = new PetType();
        type.setName("dog");
        pet.setType(type);
        assertThat(pet.getType()).isEqualTo(type);
        assertThat(pet.getType().getName()).isEqualTo("dog");
    }

    @Test
    void testAddVisit() {
        Pet pet = new Pet();
        Visit visit = new Visit();
        visit.setDate(LocalDate.now());
        visit.setDescription("checkup");
        pet.addVisit(visit);
        assertThat(pet.getVisits()).hasSize(1);
    }
}
```

### Step 3: Validate Before Saving

Run validation to catch errors before they become build failures:

```bash
python3 .claude/skills/java-test-generator/scripts/validate_test.py --file PetTest.java
```

---

## Resources

- [class-hierarchy.md](resources/class-hierarchy.md) - Full inheritance tree
- [testing-patterns.md](resources/testing-patterns.md) - AssertJ patterns
- [entity-creation.md](resources/entity-creation.md) - How to create test objects

---

## Troubleshooting

### "cannot find symbol: method setTypeId"
The method doesn't exist. Use `setId()` instead (inherited from BaseEntity).

### "PetType.DOG cannot be resolved"
PetType is a JPA entity, not an enum. Create it with `new PetType()` and `setName()`.

### "incompatible types: Collection cannot be converted to Set"
Check return types in the AST. `getVisits()` returns `Collection<Visit>`, not `Set<Visit>`.
