"""Extract REST API schemas from Spring controller annotations.

Parses @RestController, @RequestMapping, @GetMapping, etc.
to produce structured API endpoint information.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import JavaClass, JavaMethod, JavaParameter
from .annotation_parser import (
    find_annotation,
    has_annotation,
    ParsedAnnotation,
    SPRING_REST_CONTROLLER,
    SPRING_CONTROLLER,
    SPRING_REQUEST_MAPPING,
    SPRING_GET_MAPPING,
    SPRING_POST_MAPPING,
    SPRING_PUT_MAPPING,
    SPRING_DELETE_MAPPING,
    SPRING_PATCH_MAPPING,
    SPRING_PATH_VARIABLE,
    SPRING_REQUEST_BODY,
    SPRING_REQUEST_PARAM,
    SPRING_VALID,
)


@dataclass
class ParamInfo:
    """Information about an endpoint parameter."""
    name: str
    java_type: str
    source: str  # PATH, QUERY, BODY, HEADER
    required: bool = True
    default_value: Optional[str] = None
    validated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "java_type": self.java_type,
            "source": self.source,
            "required": self.required,
            "default_value": self.default_value,
            "validated": self.validated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParamInfo":
        return cls(
            name=data["name"],
            java_type=data["java_type"],
            source=data.get("source", "QUERY"),
            required=data.get("required", True),
            default_value=data.get("default_value"),
            validated=data.get("validated", False),
        )


@dataclass
class EndpointInfo:
    """Information about a REST API endpoint."""
    path: str  # Full path including base path
    method: str  # GET, POST, PUT, DELETE, PATCH
    handler_method: str  # Java method name
    controller_class: str  # Controller class FQN
    path_params: List[ParamInfo] = field(default_factory=list)
    query_params: List[ParamInfo] = field(default_factory=list)
    request_body: Optional[str] = None  # Request body type
    request_body_validated: bool = False
    response_type: str = "void"  # Return type
    produces: List[str] = field(default_factory=list)  # Content types
    consumes: List[str] = field(default_factory=list)  # Content types
    summary: Optional[str] = None  # From @Operation if present
    source_file: str = ""
    start_line: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "method": self.method,
            "handler_method": self.handler_method,
            "controller_class": self.controller_class,
            "path_params": [p.to_dict() for p in self.path_params],
            "query_params": [p.to_dict() for p in self.query_params],
            "request_body": self.request_body,
            "request_body_validated": self.request_body_validated,
            "response_type": self.response_type,
            "produces": self.produces,
            "consumes": self.consumes,
            "summary": self.summary,
            "source_file": self.source_file,
            "start_line": self.start_line,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EndpointInfo":
        return cls(
            path=data["path"],
            method=data["method"],
            handler_method=data["handler_method"],
            controller_class=data["controller_class"],
            path_params=[ParamInfo.from_dict(p) for p in data.get("path_params", [])],
            query_params=[ParamInfo.from_dict(p) for p in data.get("query_params", [])],
            request_body=data.get("request_body"),
            request_body_validated=data.get("request_body_validated", False),
            response_type=data.get("response_type", "void"),
            produces=data.get("produces", []),
            consumes=data.get("consumes", []),
            summary=data.get("summary"),
            source_file=data.get("source_file", ""),
            start_line=data.get("start_line", 0),
        )

    def format_for_prompt(self) -> str:
        """Format endpoint for LLM prompt."""
        parts = [f"{self.method} {self.path}"]

        if self.path_params:
            params_str = ", ".join(f"{p.name}: {p.java_type}" for p in self.path_params)
            parts.append(f"  Path params: {params_str}")

        if self.query_params:
            params_str = ", ".join(f"{p.name}: {p.java_type}" for p in self.query_params)
            parts.append(f"  Query params: {params_str}")

        if self.request_body:
            validated = " (validated)" if self.request_body_validated else ""
            parts.append(f"  Body: {self.request_body}{validated}")

        parts.append(f"  Returns: {self.response_type}")
        parts.append(f"  Handler: {self.handler_method}()")

        return "\n".join(parts)


@dataclass
class ControllerInfo:
    """Information about a Spring controller."""
    class_fqn: str
    class_name: str
    base_path: str  # From class-level @RequestMapping
    endpoints: List[EndpointInfo] = field(default_factory=list)
    is_rest_controller: bool = True
    source_file: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "class_fqn": self.class_fqn,
            "class_name": self.class_name,
            "base_path": self.base_path,
            "endpoints": [e.to_dict() for e in self.endpoints],
            "is_rest_controller": self.is_rest_controller,
            "source_file": self.source_file,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ControllerInfo":
        return cls(
            class_fqn=data["class_fqn"],
            class_name=data["class_name"],
            base_path=data.get("base_path", ""),
            endpoints=[EndpointInfo.from_dict(e) for e in data.get("endpoints", [])],
            is_rest_controller=data.get("is_rest_controller", True),
            source_file=data.get("source_file", ""),
        )

    def format_for_prompt(self) -> str:
        """Format controller info for LLM prompt."""
        lines = [f"Controller: {self.class_name} (base: {self.base_path or '/'})"]
        lines.append("Endpoints:")
        for endpoint in self.endpoints:
            lines.append(f"  {endpoint.method} {endpoint.path} -> {endpoint.response_type}")
        return "\n".join(lines)


def is_spring_controller(java_class: JavaClass) -> bool:
    """Check if a Java class is a Spring controller."""
    return has_annotation(java_class.annotations, *SPRING_REST_CONTROLLER) or \
           has_annotation(java_class.annotations, *SPRING_CONTROLLER)


def extract_spring_endpoints(java_class: JavaClass) -> Optional[ControllerInfo]:
    """
    Extract REST endpoints from a Spring controller.

    Args:
        java_class: Parsed JavaClass with annotations

    Returns:
        ControllerInfo if the class is a controller, None otherwise
    """
    if not is_spring_controller(java_class):
        return None

    is_rest = has_annotation(java_class.annotations, *SPRING_REST_CONTROLLER)

    # Get base path from class-level @RequestMapping
    base_path = ""
    class_mapping = find_annotation(java_class.annotations, *SPRING_REQUEST_MAPPING)
    if class_mapping:
        base_path = _extract_path(class_mapping)

    # Extract endpoints from methods
    endpoints = []
    for method in java_class.methods:
        endpoint = _extract_endpoint(method, java_class.fqn, base_path, java_class.source_file)
        if endpoint:
            endpoints.append(endpoint)

    if not endpoints:
        return None

    return ControllerInfo(
        class_fqn=java_class.fqn,
        class_name=java_class.name,
        base_path=base_path,
        endpoints=endpoints,
        is_rest_controller=is_rest,
        source_file=java_class.source_file,
    )


def _extract_endpoint(method: JavaMethod, controller_fqn: str,
                      base_path: str, source_file: str) -> Optional[EndpointInfo]:
    """Extract endpoint info from a controller method."""
    # Check for mapping annotations
    http_method = None
    mapping_annot = None

    mapping_types = [
        (SPRING_GET_MAPPING, "GET"),
        (SPRING_POST_MAPPING, "POST"),
        (SPRING_PUT_MAPPING, "PUT"),
        (SPRING_DELETE_MAPPING, "DELETE"),
        (SPRING_PATCH_MAPPING, "PATCH"),
    ]

    for annot_names, method_type in mapping_types:
        annot = find_annotation(method.annotations, *annot_names)
        if annot:
            http_method = method_type
            mapping_annot = annot
            break

    # Check for @RequestMapping with method specified
    if not http_method:
        req_mapping = find_annotation(method.annotations, *SPRING_REQUEST_MAPPING)
        if req_mapping:
            mapping_annot = req_mapping
            method_param = req_mapping.get("method")
            if method_param:
                if isinstance(method_param, str):
                    http_method = method_param.split(".")[-1] if "." in method_param else method_param
                elif isinstance(method_param, list) and method_param:
                    http_method = str(method_param[0]).split(".")[-1]
            else:
                http_method = "GET"  # Default

    if not http_method:
        return None

    # Get path
    method_path = _extract_path(mapping_annot) if mapping_annot else ""
    full_path = _combine_paths(base_path, method_path)

    # Extract parameters
    path_params = []
    query_params = []
    request_body = None
    request_body_validated = False

    for param in method.parameters:
        param_info = _extract_param_info(param)
        if param_info:
            if param_info.source == "PATH":
                path_params.append(param_info)
            elif param_info.source == "QUERY":
                query_params.append(param_info)
            elif param_info.source == "BODY":
                request_body = param_info.java_type
                request_body_validated = param_info.validated

    # Get response type
    response_type = _simplify_response_type(method.return_type)

    # Get produces/consumes
    produces = []
    consumes = []
    if mapping_annot:
        produces = _extract_media_types(mapping_annot.get("produces", []))
        consumes = _extract_media_types(mapping_annot.get("consumes", []))

    return EndpointInfo(
        path=full_path,
        method=http_method,
        handler_method=method.name,
        controller_class=controller_fqn,
        path_params=path_params,
        query_params=query_params,
        request_body=request_body,
        request_body_validated=request_body_validated,
        response_type=response_type,
        produces=produces,
        consumes=consumes,
        source_file=source_file,
        start_line=method.start_line,
    )


def _extract_path(annot: ParsedAnnotation) -> str:
    """Extract path from a mapping annotation."""
    # Try 'value' parameter first
    path = annot.get("value")
    if not path:
        path = annot.get("path")

    if not path:
        return ""

    # Handle array of paths (take first)
    if isinstance(path, list):
        path = path[0] if path else ""

    return str(path)


def _combine_paths(base: str, method_path: str) -> str:
    """Combine base path and method path."""
    if not base:
        base = ""
    if not method_path:
        method_path = ""

    # Ensure base starts with /
    if base and not base.startswith("/"):
        base = "/" + base

    # Remove trailing slash from base
    base = base.rstrip("/")

    # Ensure method path starts with / if not empty
    if method_path and not method_path.startswith("/"):
        method_path = "/" + method_path

    full_path = base + method_path
    return full_path if full_path else "/"


def _extract_param_info(param: JavaParameter) -> Optional[ParamInfo]:
    """Extract parameter info from a method parameter."""
    # Check for @PathVariable
    path_var = find_annotation(param.annotations, *SPRING_PATH_VARIABLE)
    if path_var:
        name = path_var.get("value") or path_var.get("name") or param.name
        required = path_var.get("required", True)
        return ParamInfo(
            name=name,
            java_type=param.type,
            source="PATH",
            required=required,
        )

    # Check for @RequestBody
    req_body = find_annotation(param.annotations, *SPRING_REQUEST_BODY)
    if req_body:
        validated = has_annotation(param.annotations, *SPRING_VALID)
        return ParamInfo(
            name=param.name,
            java_type=param.type,
            source="BODY",
            required=req_body.get("required", True),
            validated=validated,
        )

    # Check for @RequestParam
    req_param = find_annotation(param.annotations, *SPRING_REQUEST_PARAM)
    if req_param:
        name = req_param.get("value") or req_param.get("name") or param.name
        required = req_param.get("required", True)
        default = req_param.get("defaultValue")
        return ParamInfo(
            name=name,
            java_type=param.type,
            source="QUERY",
            required=required,
            default_value=default,
        )

    # No Spring annotation - might be handled by framework conventions
    return None


def _simplify_response_type(return_type: str) -> str:
    """Simplify response type (unwrap ResponseEntity, Mono, etc.)."""
    unwrap_types = [
        "ResponseEntity",
        "Mono",
        "Flux",
        "CompletableFuture",
        "DeferredResult",
    ]

    for wrapper in unwrap_types:
        if return_type.startswith(f"{wrapper}<") and return_type.endswith(">"):
            inner = return_type[len(wrapper) + 1:-1]
            return _simplify_response_type(inner)  # Recursive for nested

    return return_type


def _extract_media_types(value: Any) -> List[str]:
    """Extract media types from produces/consumes."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def extract_all_endpoints(classes: List[JavaClass]) -> List[ControllerInfo]:
    """Extract endpoints from all Spring controllers in a list of classes."""
    controllers = []
    for cls in classes:
        controller = extract_spring_endpoints(cls)
        if controller:
            controllers.append(controller)
    return controllers


def find_endpoints_for_entity(controllers: List[ControllerInfo], entity_name: str) -> List[EndpointInfo]:
    """Find all endpoints that deal with a specific entity."""
    entity_lower = entity_name.lower()
    matching = []

    for controller in controllers:
        # Check controller name
        if entity_lower in controller.class_name.lower():
            matching.extend(controller.endpoints)
        else:
            # Check endpoint paths and types
            for endpoint in controller.endpoints:
                if entity_lower in endpoint.path.lower():
                    matching.append(endpoint)
                elif endpoint.request_body and entity_lower in endpoint.request_body.lower():
                    matching.append(endpoint)
                elif entity_lower in endpoint.response_type.lower():
                    matching.append(endpoint)

    return matching
