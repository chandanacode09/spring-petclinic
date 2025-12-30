"""Parser for Java annotation parameters.

Converts annotation text into structured data:
    Input: '@Column(name = "user_id", nullable = false)'
    Output: {"name": "Column", "params": {"name": "user_id", "nullable": False}}
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class ParsedAnnotation:
    """A parsed Java annotation with structured parameters."""
    name: str  # Simple name (e.g., "Column", "Entity")
    full_name: str  # Full text as it appeared (e.g., "@Column(name = \"id\")")
    params: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a parameter value by key."""
        return self.params.get(key, default)

    def has_param(self, key: str) -> bool:
        """Check if a parameter exists."""
        return key in self.params

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "full_name": self.full_name,
            "params": self.params,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParsedAnnotation":
        return cls(
            name=data["name"],
            full_name=data.get("full_name", f"@{data['name']}"),
            params=data.get("params", {}),
        )


def parse_annotation(annotation_text: str) -> ParsedAnnotation:
    """
    Parse a Java annotation string into structured data.

    Args:
        annotation_text: The annotation text (e.g., '@Column(name = "user_id")')

    Returns:
        ParsedAnnotation with name and params dict

    Examples:
        >>> parse_annotation('@Entity')
        ParsedAnnotation(name='Entity', params={})

        >>> parse_annotation('@Column(name = "user_id", nullable = false)')
        ParsedAnnotation(name='Column', params={'name': 'user_id', 'nullable': False})

        >>> parse_annotation('@Table(name = "users", indexes = {@Index(name = "idx_email")})')
        ParsedAnnotation(name='Table', params={'name': 'users', 'indexes': [...]})
    """
    text = annotation_text.strip()

    # Remove leading @
    if text.startswith('@'):
        text = text[1:]

    # Extract annotation name (handles scoped like @jakarta.persistence.Entity)
    paren_idx = text.find('(')
    if paren_idx == -1:
        # Simple marker annotation without params
        name = text.split('.')[-1] if '.' in text else text
        return ParsedAnnotation(name=name, full_name=annotation_text, params={})

    full_annotation_name = text[:paren_idx]
    name = full_annotation_name.split('.')[-1] if '.' in full_annotation_name else full_annotation_name

    # Extract parameters portion
    params_text = text[paren_idx + 1:-1] if text.endswith(')') else text[paren_idx + 1:]
    params = _parse_params(params_text)

    return ParsedAnnotation(name=name, full_name=annotation_text, params=params)


def _parse_params(params_text: str) -> Dict[str, Any]:
    """Parse the parameters portion of an annotation."""
    params_text = params_text.strip()
    if not params_text:
        return {}

    # Handle single value annotation like @SuppressWarnings("unchecked")
    if '=' not in params_text or _is_single_value(params_text):
        value = _parse_value(params_text)
        return {"value": value}

    # Parse key=value pairs
    params = {}
    pairs = _split_params(params_text)

    for pair in pairs:
        pair = pair.strip()
        if not pair:
            continue

        eq_idx = pair.find('=')
        if eq_idx == -1:
            # Might be a single value without key
            continue

        key = pair[:eq_idx].strip()
        value_str = pair[eq_idx + 1:].strip()
        params[key] = _parse_value(value_str)

    return params


def _is_single_value(text: str) -> bool:
    """Check if the text is a single value (no key=value structure)."""
    # If it starts with a quote, it's a single string value
    if text.startswith('"') or text.startswith("'"):
        return True
    # If it's just an identifier or literal
    if re.match(r'^[\w.]+$', text):
        return True
    # If it starts with { it's an array value
    if text.startswith('{'):
        return True
    return False


def _split_params(params_text: str) -> List[str]:
    """Split parameters by comma, respecting nested structures."""
    parts = []
    current = []
    depth = 0
    in_string = False
    string_char = None

    for char in params_text:
        if in_string:
            current.append(char)
            if char == string_char:
                in_string = False
        elif char in ('"', "'"):
            in_string = True
            string_char = char
            current.append(char)
        elif char == '{':
            depth += 1
            current.append(char)
        elif char == '}':
            depth -= 1
            current.append(char)
        elif char == '(' :
            depth += 1
            current.append(char)
        elif char == ')':
            depth -= 1
            current.append(char)
        elif char == ',' and depth == 0:
            parts.append(''.join(current))
            current = []
        else:
            current.append(char)

    if current:
        parts.append(''.join(current))

    return parts


def _parse_value(value_str: str) -> Any:
    """Parse a single annotation value."""
    value_str = value_str.strip()

    if not value_str:
        return None

    # String literal
    if (value_str.startswith('"') and value_str.endswith('"')) or \
       (value_str.startswith("'") and value_str.endswith("'")):
        return value_str[1:-1]

    # Boolean
    if value_str == 'true':
        return True
    if value_str == 'false':
        return False

    # Integer
    if re.match(r'^-?\d+$', value_str):
        return int(value_str)

    # Float/Double
    if re.match(r'^-?\d+\.\d+[fFdD]?$', value_str):
        return float(value_str.rstrip('fFdD'))

    # Long
    if re.match(r'^-?\d+[lL]$', value_str):
        return int(value_str[:-1])

    # Array literal
    if value_str.startswith('{') and value_str.endswith('}'):
        return _parse_array(value_str[1:-1])

    # Nested annotation
    if value_str.startswith('@'):
        return parse_annotation(value_str).to_dict()

    # Class literal (e.g., String.class)
    if value_str.endswith('.class'):
        return value_str[:-6]

    # Enum or constant (e.g., CascadeType.ALL, FetchType.LAZY)
    return value_str


def _parse_array(array_content: str) -> List[Any]:
    """Parse array content like 'value1, value2, @Annotation(...)'."""
    if not array_content.strip():
        return []

    elements = _split_params(array_content)
    return [_parse_value(elem) for elem in elements if elem.strip()]


def parse_annotations(annotations: List[str]) -> List[ParsedAnnotation]:
    """Parse multiple annotation strings."""
    return [parse_annotation(a) for a in annotations]


def find_annotation(annotations: List[str], *names: str) -> Optional[ParsedAnnotation]:
    """
    Find the first annotation matching any of the given names.

    Args:
        annotations: List of annotation strings
        names: Annotation names to look for (without @)

    Returns:
        ParsedAnnotation if found, None otherwise

    Example:
        >>> find_annotation(['@Entity', '@Table(name="users")'], 'Table')
        ParsedAnnotation(name='Table', params={'name': 'users'})
    """
    for annot_str in annotations:
        parsed = parse_annotation(annot_str)
        if parsed.name in names:
            return parsed
    return None


def has_annotation(annotations: List[str], *names: str) -> bool:
    """Check if any annotation matches the given names."""
    return find_annotation(annotations, *names) is not None


# JPA annotation names
JPA_ENTITY = ("Entity",)
JPA_TABLE = ("Table",)
JPA_COLUMN = ("Column",)
JPA_ID = ("Id",)
JPA_GENERATED_VALUE = ("GeneratedValue",)
JPA_JOIN_COLUMN = ("JoinColumn",)
JPA_MANY_TO_ONE = ("ManyToOne",)
JPA_ONE_TO_MANY = ("OneToMany",)
JPA_ONE_TO_ONE = ("OneToOne",)
JPA_MANY_TO_MANY = ("ManyToMany",)
JPA_EMBEDDABLE = ("Embeddable",)
JPA_EMBEDDED = ("Embedded",)
JPA_TRANSIENT = ("Transient",)

# Spring annotation names
SPRING_REST_CONTROLLER = ("RestController",)
SPRING_CONTROLLER = ("Controller",)
SPRING_SERVICE = ("Service",)
SPRING_REPOSITORY = ("Repository",)
SPRING_COMPONENT = ("Component",)
SPRING_REQUEST_MAPPING = ("RequestMapping",)
SPRING_GET_MAPPING = ("GetMapping",)
SPRING_POST_MAPPING = ("PostMapping",)
SPRING_PUT_MAPPING = ("PutMapping",)
SPRING_DELETE_MAPPING = ("DeleteMapping",)
SPRING_PATCH_MAPPING = ("PatchMapping",)
SPRING_PATH_VARIABLE = ("PathVariable",)
SPRING_REQUEST_BODY = ("RequestBody",)
SPRING_REQUEST_PARAM = ("RequestParam",)
SPRING_VALID = ("Valid",)
