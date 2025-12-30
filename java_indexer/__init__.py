"""Java AST Indexer - Parse and index Java codebases for grounded context."""

from .models import (
    JavaParameter,
    JavaField,
    JavaMethod,
    JavaConstructor,
    JavaClass,
    JavaFile,
    JavaIndex,
)
from .parser import JavaParser
from .indexer import JavaIndexer
from .resolver import ImportResolver
from .query import ContextQuery
from .test_healer import (
    run_self_healing_loop,
    classify_error,
    analyze_test_code,
    validate_syntax,
    ErrorCategory,
    Fixability,
    HealingResult,
    HealingAttempt,
    ClassifiedError,
)
from .annotation_parser import (
    ParsedAnnotation,
    parse_annotation,
    parse_annotations,
    find_annotation,
    has_annotation,
)
from .schema_extractor import (
    ColumnInfo,
    RelationshipInfo,
    TableSchema,
    extract_jpa_schema,
    extract_all_schemas,
    is_jpa_entity,
)
from .api_extractor import (
    ParamInfo,
    EndpointInfo,
    ControllerInfo,
    extract_spring_endpoints,
    extract_all_endpoints,
    is_spring_controller,
)

__all__ = [
    # Core models
    "JavaParameter",
    "JavaField",
    "JavaMethod",
    "JavaConstructor",
    "JavaClass",
    "JavaFile",
    "JavaIndex",
    "JavaParser",
    "JavaIndexer",
    "ImportResolver",
    "ContextQuery",
    # Test healer
    "run_self_healing_loop",
    "classify_error",
    "analyze_test_code",
    "validate_syntax",
    "ErrorCategory",
    "Fixability",
    "HealingResult",
    "HealingAttempt",
    "ClassifiedError",
    # Annotation parser
    "ParsedAnnotation",
    "parse_annotation",
    "parse_annotations",
    "find_annotation",
    "has_annotation",
    # Schema extractor
    "ColumnInfo",
    "RelationshipInfo",
    "TableSchema",
    "extract_jpa_schema",
    "extract_all_schemas",
    "is_jpa_entity",
    # API extractor
    "ParamInfo",
    "EndpointInfo",
    "ControllerInfo",
    "extract_spring_endpoints",
    "extract_all_endpoints",
    "is_spring_controller",
]
