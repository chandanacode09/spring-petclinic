# Cloud Build PR Test Generation - Next Steps

## Completed
- [x] Integrated `java_test_generator` skill into `cloudbuild/generate_tests.py`
- [x] Added TestSamples discovery and static import injection
- [x] Tested locally - generates tests with rich context

## Next Steps

### 1. Set up Cloud Build Trigger for PRs
```bash
# Create trigger that fires on PRs to your Java repo
gcloud builds triggers create github \
  --name="java-test-generator" \
  --repo-name="YOUR_JAVA_REPO" \
  --repo-owner="YOUR_ORG" \
  --pull-request-pattern="^main$" \
  --build-config="cloudbuild/cloudbuild.yaml"
```

### 2. Store OpenRouter API key in Secret Manager
```bash
echo -n "$OPENROUTER_API_KEY" | gcloud secrets create openrouter-api-key --data-file=-

# Grant Cloud Build access
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding openrouter-api-key \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 3. Copy files to target Java repo
Required files:
- `cloudbuild/cloudbuild.yaml`
- `cloudbuild/generate_tests.py`
- `java_indexer/` module
- `skills/java_test_generator/` skill

### 4. Optional Enhancements

#### Auto-commit generated tests back to PR branch
- Add a Cloud Build step to commit and push generated tests
- Requires GitHub token in Secret Manager

#### Post test suggestions as PR comments
- Use GitHub API to post generated tests as review comments
- More non-invasive than auto-committing

#### Add self-healing (retry on compilation failure)
- If test fails to compile, extract error and ask LLM to fix
- Already implemented in web_ui.py, can port to Cloud Build

## Testing the Pipeline

### Local test command:
```bash
echo "src/main/java/com/example/MyClass.java" > /tmp/changed-files.txt

OPENROUTER_API_KEY="$OPENROUTER_API_KEY" python3 cloudbuild/generate_tests.py \
  --repo /path/to/java/repo \
  --changed-files /tmp/changed-files.txt \
  --output-dir /tmp/generated-tests \
  --json-output
```

### Expected output:
```json
{
  "generated": [
    {
      "class": "MyClass",
      "fqn": "com.example.MyClass",
      "test_file": "/tmp/generated-tests/com/example/MyClassTest.java",
      "llm_used": true,
      "rich_context_used": true,
      "generation_time_ms": 12000
    }
  ],
  "skipped": [],
  "failed": []
}
```
