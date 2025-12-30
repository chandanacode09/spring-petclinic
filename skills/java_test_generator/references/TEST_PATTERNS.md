# Java Test Patterns Reference

## Entity Tests

### Pattern 1: Using TestSamples for Consistent Data

```java
package io.github.sample.domain;

import static io.github.sample.domain.BankAccountTestSamples.*;
import static io.github.sample.domain.UserTestSamples.*;
import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class BankAccountTest {

    @Test
    void shouldCreateWithSampleData() {
        // Use existing sample generators - never hardcode IDs
        BankAccount account1 = getBankAccountSample1();
        BankAccount account2 = getBankAccountSample2();

        assertThat(account1.getId()).isNotEqualTo(account2.getId());
    }

    @Test
    void shouldCreateRandomSample() {
        // For uniqueness in tests
        BankAccount random = getBankAccountRandomSampleGenerator();
        assertThat(random.getId()).isNotNull();
    }
}
```

### Pattern 2: Equals/HashCode Verification

```java
@Test
void equalsVerifier() throws Exception {
    // Use TestUtil if available in repo
    TestUtil.equalsVerifier(BankAccount.class);

    BankAccount account1 = getBankAccountSample1();
    BankAccount account2 = new BankAccount();

    // Objects with different IDs are not equal
    assertThat(account1).isNotEqualTo(account2);

    // Same ID means equal
    account2.setId(account1.getId());
    assertThat(account1).isEqualTo(account2);
}
```

### Pattern 3: Bidirectional Relationship Testing

```java
@Test
void shouldSyncBidirectionalOneToMany() {
    BankAccount account = getBankAccountRandomSampleGenerator();
    Operation operation = getOperationRandomSampleGenerator();

    // Adding should set back-reference
    account.addOperation(operation);
    assertThat(account.getOperations()).containsOnly(operation);
    assertThat(operation.getBankAccount()).isEqualTo(account);

    // Removing should clear back-reference
    account.removeOperation(operation);
    assertThat(account.getOperations()).doesNotContain(operation);
    assertThat(operation.getBankAccount()).isNull();
}

@Test
void shouldSyncWhenUsingSetOperations() {
    BankAccount account = getBankAccountRandomSampleGenerator();
    Operation operation = getOperationRandomSampleGenerator();

    // Using setter with new set
    account.operations(new HashSet<>(Set.of(operation)));
    assertThat(account.getOperations()).containsOnly(operation);
    assertThat(operation.getBankAccount()).isEqualTo(account);

    // Clear via empty set
    account.setOperations(new HashSet<>());
    assertThat(account.getOperations()).isEmpty();
    assertThat(operation.getBankAccount()).isNull();
}
```

### Pattern 4: Schema Constraint Testing

```java
@Test
void shouldRespectSchemaConstraints() {
    BankAccount account = new BankAccount();

    // Test NOT NULL field - name is required
    account.setName("Valid Name");
    assertThat(account.getName()).isNotNull();

    // Test precision/scale for BigDecimal
    BigDecimal balance = new BigDecimal("12345678901234567890.12"); // 21 precision, 2 scale
    account.setBalance(balance);
    assertThat(account.getBalance()).isEqualByComparingTo(balance);
}

@Test
void shouldHandleNullableFields() {
    BankAccount account = getBankAccountSample1();

    // user is nullable (optional ManyToOne)
    account.setUser(null);
    assertThat(account.getUser()).isNull();
}
```

## Service Tests

### Pattern 5: Service with Mocked Repository

```java
package io.github.sample.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import io.github.sample.domain.BankAccount;
import io.github.sample.repository.BankAccountRepository;
import java.util.Optional;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

@ExtendWith(MockitoExtension.class)
class BankAccountServiceTest {

    @Mock
    private BankAccountRepository bankAccountRepository;

    @InjectMocks
    private BankAccountService bankAccountService;

    @Test
    void shouldFindById() {
        // Arrange
        BankAccount expected = new BankAccount().id(1L).name("Test");
        when(bankAccountRepository.findById(1L)).thenReturn(Optional.of(expected));

        // Act
        Optional<BankAccount> result = bankAccountService.findOne(1L);

        // Assert
        assertThat(result).isPresent();
        assertThat(result.get().getName()).isEqualTo("Test");
        verify(bankAccountRepository).findById(1L);
    }

    @Test
    void shouldReturnEmptyWhenNotFound() {
        // Arrange
        when(bankAccountRepository.findById(999L)).thenReturn(Optional.empty());

        // Act
        Optional<BankAccount> result = bankAccountService.findOne(999L);

        // Assert
        assertThat(result).isEmpty();
    }

    @Test
    void shouldSaveAccount() {
        // Arrange
        BankAccount toSave = new BankAccount().name("New Account");
        BankAccount saved = new BankAccount().id(1L).name("New Account");
        when(bankAccountRepository.save(any(BankAccount.class))).thenReturn(saved);

        // Act
        BankAccount result = bankAccountService.save(toSave);

        // Assert
        assertThat(result.getId()).isEqualTo(1L);
        verify(bankAccountRepository).save(toSave);
    }

    @Test
    void shouldDeleteAccount() {
        // Arrange
        doNothing().when(bankAccountRepository).deleteById(1L);

        // Act
        bankAccountService.delete(1L);

        // Assert
        verify(bankAccountRepository).deleteById(1L);
    }
}
```

### Pattern 6: Testing Business Logic with Validation

```java
@Test
void shouldRejectNegativeBalance() {
    BankAccount account = new BankAccount()
        .name("Test")
        .balance(new BigDecimal("-100"));

    assertThatThrownBy(() -> bankAccountService.validateAndSave(account))
        .isInstanceOf(IllegalArgumentException.class)
        .hasMessageContaining("negative");
}

@Test
void shouldCalculateInterest() {
    BankAccount account = new BankAccount()
        .balance(new BigDecimal("1000.00"));

    BigDecimal interest = bankAccountService.calculateInterest(account, 0.05);

    assertThat(interest).isEqualByComparingTo("50.00");
}
```

## Controller/Resource Tests

### Pattern 7: REST Controller with MockMvc

```java
package io.github.sample.web.rest;

import static org.hamcrest.Matchers.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.sample.domain.BankAccount;
import io.github.sample.service.BankAccountService;
import java.math.BigDecimal;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

@ExtendWith(MockitoExtension.class)
class BankAccountResourceTest {

    private MockMvc mockMvc;
    private ObjectMapper objectMapper = new ObjectMapper();

    @Mock
    private BankAccountService bankAccountService;

    @InjectMocks
    private BankAccountResource bankAccountResource;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.standaloneSetup(bankAccountResource).build();
    }

    @Test
    void shouldGetBankAccount() throws Exception {
        BankAccount account = new BankAccount().id(1L).name("Test").balance(new BigDecimal("100.00"));
        when(bankAccountService.findOne(1L)).thenReturn(Optional.of(account));

        mockMvc.perform(get("/api/bank-accounts/1"))
            .andExpect(status().isOk())
            .andExpect(content().contentType(MediaType.APPLICATION_JSON))
            .andExpect(jsonPath("$.id").value(1))
            .andExpect(jsonPath("$.name").value("Test"))
            .andExpect(jsonPath("$.balance").value(100.00));
    }

    @Test
    void shouldReturn404WhenNotFound() throws Exception {
        when(bankAccountService.findOne(999L)).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/bank-accounts/999"))
            .andExpect(status().isNotFound());
    }

    @Test
    void shouldCreateBankAccount() throws Exception {
        BankAccount input = new BankAccount().name("New").balance(new BigDecimal("500.00"));
        BankAccount saved = new BankAccount().id(1L).name("New").balance(new BigDecimal("500.00"));
        when(bankAccountService.save(any(BankAccount.class))).thenReturn(saved);

        mockMvc.perform(post("/api/bank-accounts")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(input)))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.id").value(1));
    }

    @Test
    void shouldRejectInvalidInput() throws Exception {
        BankAccount invalid = new BankAccount(); // missing required name

        mockMvc.perform(post("/api/bank-accounts")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(invalid)))
            .andExpect(status().isBadRequest());
    }
}
```

## Realistic Test Data by Type

### String Fields
```java
// Names
"John Doe", "Jane Smith", "Test User"
"Savings Account", "Checking Account", "Investment Portfolio"

// Use UUID for uniqueness
UUID.randomUUID().toString()
"name_" + System.currentTimeMillis()
```

### Numeric Fields
```java
// IDs (Long)
1L, 2L, 100L
longCount.incrementAndGet()  // atomic counter

// Money (BigDecimal) - respect precision/scale
new BigDecimal("1000.00")
new BigDecimal("12345.67")
BigDecimal.ZERO
BigDecimal.valueOf(random.nextDouble() * 10000).setScale(2, RoundingMode.HALF_UP)
```

### Date/Time Fields
```java
// LocalDate
LocalDate.now()
LocalDate.of(2024, 1, 15)

// Instant
Instant.now()
Instant.parse("2024-01-15T10:30:00Z")

// ZonedDateTime
ZonedDateTime.now(ZoneId.of("UTC"))
```

### Collections
```java
// Empty
new HashSet<>()
Collections.emptyList()

// With items
new HashSet<>(Set.of(item1, item2))
List.of(item1, item2, item3)
```

## Common Assertions

### AssertJ (Preferred)
```java
assertThat(actual).isEqualTo(expected);
assertThat(actual).isNotNull();
assertThat(actual).isNull();
assertThat(list).hasSize(3);
assertThat(list).contains(item);
assertThat(list).containsOnly(item1, item2);
assertThat(list).doesNotContain(item);
assertThat(list).isEmpty();
assertThat(decimal).isEqualByComparingTo("100.00");
assertThat(actual).isInstanceOf(ExpectedClass.class);
assertThatThrownBy(() -> methodThatThrows())
    .isInstanceOf(IllegalArgumentException.class)
    .hasMessageContaining("expected message");
```

### JUnit 5
```java
assertEquals(expected, actual);
assertNotNull(actual);
assertNull(actual);
assertTrue(condition);
assertFalse(condition);
assertThrows(IllegalArgumentException.class, () -> methodThatThrows());
```
