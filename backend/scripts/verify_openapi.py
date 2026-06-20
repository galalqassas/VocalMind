import sys
import os
from pathlib import Path

# Setup paths
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(backend_dir.parent / "services"))

# Set mock env vars for app initialization
os.environ["DATABASE_URL"] = "postgresql+asyncpg://vocalmind:vocalmind_dev@localhost:5432/vocalmind"
os.environ["HF_TOKEN"] = "mock_token"
os.environ["GROQ_API_KEY"] = "mock_key"
os.environ["SECRET_KEY"] = "mock_secret"
os.environ["IS_LOCAL"] = "true"
os.environ["AUDIO_FOLDER_WATCHER_ENABLED"] = "false"

from fastapi import FastAPI
from fastapi.routing import APIRoute
from app.main import app
from app.api.deps import get_current_user, get_token

def is_auth_route(route: APIRoute) -> bool:
    if not hasattr(route, "dependant") or route.dependant is None:
        return False
    
    def has_auth_dep(dependant) -> bool:
        if dependant.call in (get_current_user, get_token):
            return True
        for sub_dep in dependant.dependencies:
            if has_auth_dep(sub_dep):
                return True
        return False

    for dep in route.dependencies:
        if dep.dependency in (get_current_user, get_token):
            return True
            
    return has_auth_dep(route.dependant)

def main():
    print("Generating OpenAPI schema...")
    openapi = app.openapi()
    
    violations = []
    
    # R1. Root-Level OpenAPI Metadata & Tags
    info = openapi.get("info", {})
    title = info.get("title")
    version = info.get("version")
    summary = info.get("summary")
    description = info.get("description")
    contact = info.get("contact", {})
    
    print(f"Metadata - Title: {title}, Version: {version}")
    print(f"Metadata - Summary: {summary}")
    print(f"Metadata - Description: {description}")
    print(f"Metadata - Contact: {contact}")
    
    if not title or title == "FastAPI":
        violations.append("R1: App title is missing or default ('FastAPI').")
    if not version:
        violations.append("R1: App version is missing.")
    if not summary:
        violations.append("R1: App summary is missing.")
    if not description:
        violations.append("R1: App description is missing.")
    if not contact or not contact.get("name") or not contact.get("email"):
        violations.append("R1: App contact information (name/email) is missing or incomplete.")
        
    # Tags check
    root_tags = {tag["name"]: tag for tag in openapi.get("tags", [])}
    print(f"Defined root tags: {list(root_tags.keys())}")
    for name, tag in root_tags.items():
        if not tag.get("description"):
            violations.append(f"R1: Tag '{name}' defined in root tags has no description.")

    # R2, R3, R4. Route checks
    total_params = 0
    documented_params = 0
    
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
            
        path = route.path
        # Convert path to OpenAPI path format
        openapi_path = path
        for method in route.methods:
            method_lower = method.lower()
            path_item = openapi.get("paths", {}).get(openapi_path, {})
            op = path_item.get(method_lower)
            if not op:
                continue
                
            route_id = f"{method} {path}"
            
            # R2. Endpoint Docstrings and Descriptions
            op_summary = op.get("summary")
            op_desc = op.get("description")
            
            if not op_desc:
                violations.append(f"R2: Route '{route_id}' has no docstring or description.")
                
            # R3. Parameter and Field Descriptions
            parameters = op.get("parameters", [])
            for param in parameters:
                if param.get("in") in ("path", "query"):
                    total_params += 1
                    if param.get("description"):
                        documented_params += 1
                    else:
                        violations.append(f"R3: Parameter '{param['name']}' in route '{route_id}' has no description.")
            
            # R4. Standardized Response Models & Error Codes
            responses = op.get("responses", {})
            
            # Auth routes must document 401/403
            if is_auth_route(route):
                if "401" not in responses and "403" not in responses:
                    violations.append(f"R4: Auth-protected route '{route_id}' does not document 401 or 403 response.")
            
            # Resource retrieval must document 404
            is_retrieval = method_lower == "get" and any(f"{{{p}}}" in path for p in ("id", "interaction_id", "user_id", "policy_id", "org_id", "job_id", "token"))
            if is_retrieval:
                if "404" not in responses:
                    violations.append(f"R4: Resource retrieval route '{route_id}' does not document 404 response.")

            # Routes with query/path/body params should document 422 (validation error)
            has_input_validation = len(parameters) > 0 or "requestBody" in op
            if has_input_validation and "422" not in responses:
                violations.append(f"R4: Route with input validation '{route_id}' is missing 422 validation response.")
                
            # Check if tag is in root_tags
            route_tags = op.get("tags", [])
            for t in route_tags:
                if t not in root_tags:
                    violations.append(f"R1: Route '{route_id}' references tag '{t}' which is not defined in root tags metadata.")

    # Calculate param coverage
    if total_params > 0:
        coverage = (documented_params / total_params) * 100
        print(f"Parameter description coverage: {coverage:.2f}% ({documented_params}/{total_params})")
        if coverage < 90.0:
            violations.append(f"R3: Parameter description coverage is {coverage:.2f}%, which is below the 90% threshold.")
    else:
        print("No path/query parameters found to validate.")

    # Summary
    if violations:
        print("\n--- OpenAPI Validation Violations Found ---")
        for v in violations:
            print(f"- {v}")
        print(f"\nTotal violations: {len(violations)}")
        sys.exit(1)
    else:
        print("\nAll OpenAPI validation checks passed successfully!")
        sys.exit(0)

if __name__ == "__main__":
    main()
