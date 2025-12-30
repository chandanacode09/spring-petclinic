"""Extract database schemas from JPA entity annotations.

Parses @Entity, @Table, @Column, @JoinColumn, relationship annotations
to produce structured database schema information.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import JavaClass, JavaField
from .annotation_parser import (
    parse_annotation,
    find_annotation,
    has_annotation,
    ParsedAnnotation,
    JPA_ENTITY,
    JPA_TABLE,
    JPA_COLUMN,
    JPA_ID,
    JPA_GENERATED_VALUE,
    JPA_JOIN_COLUMN,
    JPA_MANY_TO_ONE,
    JPA_ONE_TO_MANY,
    JPA_ONE_TO_ONE,
    JPA_MANY_TO_MANY,
    JPA_TRANSIENT,
    JPA_EMBEDDED,
)


@dataclass
class ColumnInfo:
    """Information about a database column."""
    name: str  # Column name (from @Column or field name)
    java_type: str  # Java type (Long, String, BigDecimal, etc.)
    java_field: str  # Java field name
    sql_type: Optional[str] = None  # SQL type if specified
    nullable: bool = True
    length: Optional[int] = None
    precision: Optional[int] = None
    scale: Optional[int] = None
    is_pk: bool = False
    is_generated: bool = False
    is_fk: bool = False
    fk_table: Optional[str] = None
    fk_column: Optional[str] = None
    unique: bool = False
    insertable: bool = True
    updatable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "java_type": self.java_type,
            "java_field": self.java_field,
            "sql_type": self.sql_type,
            "nullable": self.nullable,
            "length": self.length,
            "precision": self.precision,
            "scale": self.scale,
            "is_pk": self.is_pk,
            "is_generated": self.is_generated,
            "is_fk": self.is_fk,
            "fk_table": self.fk_table,
            "fk_column": self.fk_column,
            "unique": self.unique,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ColumnInfo":
        return cls(
            name=data["name"],
            java_type=data["java_type"],
            java_field=data.get("java_field", data["name"]),
            sql_type=data.get("sql_type"),
            nullable=data.get("nullable", True),
            length=data.get("length"),
            precision=data.get("precision"),
            scale=data.get("scale"),
            is_pk=data.get("is_pk", False),
            is_generated=data.get("is_generated", False),
            is_fk=data.get("is_fk", False),
            fk_table=data.get("fk_table"),
            fk_column=data.get("fk_column"),
            unique=data.get("unique", False),
        )


@dataclass
class RelationshipInfo:
    """Information about a database relationship."""
    type: str  # MANY_TO_ONE, ONE_TO_MANY, ONE_TO_ONE, MANY_TO_MANY
    target_entity: str  # Target Java class
    target_table: Optional[str] = None  # Target table name if known
    java_field: str = ""  # Java field name
    join_column: Optional[str] = None  # Local join column
    inverse_join_column: Optional[str] = None  # For many-to-many
    mapped_by: Optional[str] = None  # For bidirectional
    fetch_type: str = "LAZY"  # LAZY or EAGER
    cascade: List[str] = field(default_factory=list)
    optional: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "target_entity": self.target_entity,
            "target_table": self.target_table,
            "java_field": self.java_field,
            "join_column": self.join_column,
            "inverse_join_column": self.inverse_join_column,
            "mapped_by": self.mapped_by,
            "fetch_type": self.fetch_type,
            "cascade": self.cascade,
            "optional": self.optional,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RelationshipInfo":
        return cls(
            type=data["type"],
            target_entity=data["target_entity"],
            target_table=data.get("target_table"),
            java_field=data.get("java_field", ""),
            join_column=data.get("join_column"),
            inverse_join_column=data.get("inverse_join_column"),
            mapped_by=data.get("mapped_by"),
            fetch_type=data.get("fetch_type", "LAZY"),
            cascade=data.get("cascade", []),
            optional=data.get("optional", True),
        )


@dataclass
class TableSchema:
    """Complete schema for a JPA entity / database table."""
    table_name: str  # Database table name
    entity_class_fqn: str  # Fully qualified Java class name
    entity_class_name: str  # Simple class name
    schema: Optional[str] = None  # Database schema
    catalog: Optional[str] = None  # Database catalog
    columns: List[ColumnInfo] = field(default_factory=list)
    relationships: List[RelationshipInfo] = field(default_factory=list)
    primary_key_columns: List[str] = field(default_factory=list)
    unique_constraints: List[List[str]] = field(default_factory=list)
    indexes: List[Dict[str, Any]] = field(default_factory=list)
    source_file: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "table_name": self.table_name,
            "entity_class_fqn": self.entity_class_fqn,
            "entity_class_name": self.entity_class_name,
            "schema": self.schema,
            "catalog": self.catalog,
            "columns": [c.to_dict() for c in self.columns],
            "relationships": [r.to_dict() for r in self.relationships],
            "primary_key_columns": self.primary_key_columns,
            "unique_constraints": self.unique_constraints,
            "indexes": self.indexes,
            "source_file": self.source_file,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TableSchema":
        return cls(
            table_name=data["table_name"],
            entity_class_fqn=data["entity_class_fqn"],
            entity_class_name=data.get("entity_class_name", data["table_name"]),
            schema=data.get("schema"),
            catalog=data.get("catalog"),
            columns=[ColumnInfo.from_dict(c) for c in data.get("columns", [])],
            relationships=[RelationshipInfo.from_dict(r) for r in data.get("relationships", [])],
            primary_key_columns=data.get("primary_key_columns", []),
            unique_constraints=data.get("unique_constraints", []),
            indexes=data.get("indexes", []),
            source_file=data.get("source_file", ""),
        )

    def get_column(self, name: str) -> Optional[ColumnInfo]:
        """Get column by name or java field name."""
        for col in self.columns:
            if col.name == name or col.java_field == name:
                return col
        return None

    def get_pk_column(self) -> Optional[ColumnInfo]:
        """Get the primary key column."""
        for col in self.columns:
            if col.is_pk:
                return col
        return None

    def format_for_prompt(self) -> str:
        """Format schema for LLM prompt."""
        lines = [f"Table: {self.table_name} (Entity: {self.entity_class_name})"]

        lines.append("Columns:")
        for col in self.columns:
            flags = []
            if col.is_pk:
                flags.append("PK")
            if col.is_generated:
                flags.append("AUTO")
            if col.is_fk:
                flags.append(f"FK->{col.fk_table}")
            if not col.nullable:
                flags.append("NOT NULL")
            if col.unique:
                flags.append("UNIQUE")

            flag_str = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"  - {col.name}: {col.java_type}{flag_str}")

        if self.relationships:
            lines.append("Relationships:")
            for rel in self.relationships:
                lines.append(f"  - {rel.java_field}: {rel.type} -> {rel.target_entity}")

        return "\n".join(lines)


def is_jpa_entity(java_class: JavaClass) -> bool:
    """Check if a Java class is a JPA entity."""
    return has_annotation(java_class.annotations, *JPA_ENTITY)


def extract_jpa_schema(java_class: JavaClass) -> Optional[TableSchema]:
    """
    Extract table schema from a JPA @Entity class.

    Args:
        java_class: Parsed JavaClass with annotations

    Returns:
        TableSchema if the class is a JPA entity, None otherwise
    """
    if not is_jpa_entity(java_class):
        return None

    # Get table name from @Table or derive from class name
    table_annot = find_annotation(java_class.annotations, *JPA_TABLE)
    if table_annot and table_annot.get("name"):
        table_name = table_annot.get("name")
        schema_name = table_annot.get("schema")
        catalog = table_annot.get("catalog")
    else:
        # Default: convert CamelCase to snake_case
        table_name = _to_snake_case(java_class.name)
        schema_name = None
        catalog = None

    # Extract columns and relationships
    columns = []
    relationships = []
    pk_columns = []

    for field in java_class.fields:
        # Skip transient fields
        if has_annotation(field.annotations, *JPA_TRANSIENT):
            continue
        if "transient" in field.modifiers:
            continue
        if "static" in field.modifiers:
            continue

        # Check for relationships first
        rel = _extract_relationship(field)
        if rel:
            relationships.append(rel)
            # ManyToOne fields also have a join column
            if rel.type in ("MANY_TO_ONE", "ONE_TO_ONE"):
                join_col = _extract_join_column(field, rel)
                if join_col:
                    columns.append(join_col)
        else:
            # Regular column
            col = _extract_column(field)
            if col:
                columns.append(col)
                if col.is_pk:
                    pk_columns.append(col.name)

    # Extract unique constraints and indexes from @Table
    unique_constraints = []
    indexes = []
    if table_annot:
        unique_constraints = _extract_unique_constraints(table_annot)
        indexes = _extract_indexes(table_annot)

    return TableSchema(
        table_name=table_name,
        entity_class_fqn=java_class.fqn,
        entity_class_name=java_class.name,
        schema=schema_name,
        catalog=catalog,
        columns=columns,
        relationships=relationships,
        primary_key_columns=pk_columns,
        unique_constraints=unique_constraints,
        indexes=indexes,
        source_file=java_class.source_file,
    )


def _extract_column(field: JavaField) -> Optional[ColumnInfo]:
    """Extract column info from a field."""
    # Check for @Id
    is_pk = has_annotation(field.annotations, *JPA_ID)
    is_generated = has_annotation(field.annotations, *JPA_GENERATED_VALUE)

    # Get @Column annotation if present
    col_annot = find_annotation(field.annotations, *JPA_COLUMN)

    if col_annot:
        name = col_annot.get("name", _to_snake_case(field.name))
        nullable = col_annot.get("nullable", True) if not is_pk else False
        length = col_annot.get("length")
        precision = col_annot.get("precision")
        scale = col_annot.get("scale")
        unique = col_annot.get("unique", False)
        insertable = col_annot.get("insertable", True)
        updatable = col_annot.get("updatable", True)
        column_definition = col_annot.get("columnDefinition")
    else:
        name = _to_snake_case(field.name)
        nullable = not is_pk
        length = None
        precision = None
        scale = None
        unique = False
        insertable = True
        updatable = True
        column_definition = None

    return ColumnInfo(
        name=name,
        java_type=field.type,
        java_field=field.name,
        sql_type=column_definition,
        nullable=nullable,
        length=length,
        precision=precision,
        scale=scale,
        is_pk=is_pk,
        is_generated=is_generated,
        unique=unique,
        insertable=insertable,
        updatable=updatable,
    )


def _extract_relationship(field: JavaField) -> Optional[RelationshipInfo]:
    """Extract relationship info from a field if it's a relationship."""
    rel_type = None
    rel_annot = None

    if has_annotation(field.annotations, *JPA_MANY_TO_ONE):
        rel_type = "MANY_TO_ONE"
        rel_annot = find_annotation(field.annotations, *JPA_MANY_TO_ONE)
    elif has_annotation(field.annotations, *JPA_ONE_TO_MANY):
        rel_type = "ONE_TO_MANY"
        rel_annot = find_annotation(field.annotations, *JPA_ONE_TO_MANY)
    elif has_annotation(field.annotations, *JPA_ONE_TO_ONE):
        rel_type = "ONE_TO_ONE"
        rel_annot = find_annotation(field.annotations, *JPA_ONE_TO_ONE)
    elif has_annotation(field.annotations, *JPA_MANY_TO_MANY):
        rel_type = "MANY_TO_MANY"
        rel_annot = find_annotation(field.annotations, *JPA_MANY_TO_MANY)

    if not rel_type or not rel_annot:
        return None

    # Get target entity type
    target = rel_annot.get("targetEntity")
    if not target:
        # Infer from field type
        target = _extract_generic_type(field.type) or field.type

    # Get fetch type
    fetch = rel_annot.get("fetch", "LAZY")
    if isinstance(fetch, str) and "." in fetch:
        fetch = fetch.split(".")[-1]

    # Get cascade
    cascade = rel_annot.get("cascade", [])
    if isinstance(cascade, str):
        cascade = [cascade.split(".")[-1] if "." in cascade else cascade]
    elif isinstance(cascade, list):
        cascade = [c.split(".")[-1] if isinstance(c, str) and "." in c else str(c) for c in cascade]

    # Get mapped by (for bidirectional)
    mapped_by = rel_annot.get("mappedBy")

    # Get optional (for ManyToOne/OneToOne)
    optional = rel_annot.get("optional", True)

    # Get join column
    join_col_annot = find_annotation(field.annotations, *JPA_JOIN_COLUMN)
    join_column = join_col_annot.get("name") if join_col_annot else None

    return RelationshipInfo(
        type=rel_type,
        target_entity=target,
        java_field=field.name,
        join_column=join_column,
        mapped_by=mapped_by,
        fetch_type=fetch,
        cascade=cascade,
        optional=optional,
    )


def _extract_join_column(field: JavaField, rel: RelationshipInfo) -> Optional[ColumnInfo]:
    """Extract the foreign key column for a relationship."""
    join_annot = find_annotation(field.annotations, *JPA_JOIN_COLUMN)

    if join_annot:
        name = join_annot.get("name", _to_snake_case(field.name) + "_id")
        nullable = join_annot.get("nullable", rel.optional)
        insertable = join_annot.get("insertable", True)
        updatable = join_annot.get("updatable", True)
        ref_column = join_annot.get("referencedColumnName", "id")
    else:
        name = _to_snake_case(field.name) + "_id"
        nullable = rel.optional
        insertable = True
        updatable = True
        ref_column = "id"

    return ColumnInfo(
        name=name,
        java_type="Long",  # Usually FK is Long/Integer
        java_field=field.name,
        nullable=nullable,
        is_fk=True,
        fk_table=_to_snake_case(rel.target_entity),
        fk_column=ref_column,
        insertable=insertable,
        updatable=updatable,
    )


def _extract_unique_constraints(table_annot: ParsedAnnotation) -> List[List[str]]:
    """Extract unique constraints from @Table annotation."""
    constraints = []
    unique_constraints = table_annot.get("uniqueConstraints", [])

    for uc in unique_constraints:
        if isinstance(uc, dict):
            columns = uc.get("columnNames", [])
            if columns:
                constraints.append(columns)

    return constraints


def _extract_indexes(table_annot: ParsedAnnotation) -> List[Dict[str, Any]]:
    """Extract indexes from @Table annotation."""
    indexes = []
    index_list = table_annot.get("indexes", [])

    for idx in index_list:
        if isinstance(idx, dict):
            indexes.append({
                "name": idx.get("name"),
                "columnList": idx.get("columnList"),
                "unique": idx.get("unique", False),
            })

    return indexes


def _to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case."""
    result = []
    for i, char in enumerate(name):
        if char.isupper() and i > 0:
            result.append('_')
        result.append(char.lower())
    return ''.join(result)


def _extract_generic_type(type_str: str) -> Optional[str]:
    """Extract the generic type parameter from List<User>, Set<Order>, etc."""
    if '<' in type_str and '>' in type_str:
        start = type_str.index('<') + 1
        end = type_str.rindex('>')
        inner = type_str[start:end].strip()
        # Handle nested generics like Map<String, User>
        if ',' in inner and '<' not in inner:
            # Take the last type for maps
            return inner.split(',')[-1].strip()
        return inner
    return None


def extract_all_schemas(classes: List[JavaClass]) -> List[TableSchema]:
    """Extract schemas from all JPA entities in a list of classes."""
    schemas = []
    for cls in classes:
        schema = extract_jpa_schema(cls)
        if schema:
            schemas.append(schema)
    return schemas
