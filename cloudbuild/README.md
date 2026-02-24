# Cloud Build Java Test Generator

Automatically generate grounded Java unit tests on every PR using:
- **Tree-sitter** for accurate AST parsing
- **LLM** (via OpenRouter) for intelligent test generation
- **GCS** for caching the index across builds

## Architecture

```
GitHub PR
    │
    ▼
Cloud Build Trigger
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                    cloudbuild.yaml                       │
├─────────────────────────────────────────────────────────┤
│  1. get-changed-files    │ git diff → changed.txt       │
│  2. load-cached-index    │ GCS → cached-index.json      │
│  3. generate-tests       │ Python + LLM → tests         │
│  4. save-index           │ index → GCS                  │
│  5. validate-tests       │ Maven/Gradle compile         │
│  6. report               │ Summary + artifacts          │
└─────────────────────────────────────────────────────────┘
    │
    ▼
Generated tests in GCS artifacts
```

## Setup Instructions

### 1. Enable Required APIs

```bash
gcloud services enable cloudbuild.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable storage.googleapis.com
```

### 2. Create GCS Bucket for Index Cache

```bash
# Create bucket (choose a unique name)
gsutil mb -l us-central1 gs://YOUR_PROJECT-java-index-cache

# Set lifecycle to delete old indexes after 30 days
cat > /tmp/lifecycle.json << 'EOF'
{
  "rule": [{
    "action": {"type": "Delete"},
    "condition": {"age": 30}
  }]
}
EOF
gsutil lifecycle set /tmp/lifecycle.json gs://YOUR_PROJECT-java-index-cache
```

### 3. Store OpenRouter API Key in Secret Manager

```bash
# Create the secret
echo -n "your-openrouter-api-key" | \
  gcloud secrets create openrouter-api-key \
    --data-file=- \
    --replication-policy="automatic"

# Grant Cloud Build access to the secret
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding openrouter-api-key \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 4. Grant Cloud Build Access to GCS

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')

# Allow Cloud Build to read/write to the index bucket
gsutil iam ch \
  serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com:objectAdmin \
  gs://YOUR_PROJECT-java-index-cache
```

### 5. Create Cloud Build Trigger

**Option A: Via Console**
1. Go to Cloud Build > Triggers
2. Click "Create Trigger"
3. Connect your GitHub repository
4. Configure:
   - Event: Pull Request
   - Branch: `^main$` (or your default branch)
   - Configuration: Cloud Build configuration file
   - Location: `cloudbuild/cloudbuild.yaml`
5. Add substitution variables:
   - `_INDEX_BUCKET`: `YOUR_PROJECT-java-index-cache`

**Option B: Via gcloud**
```bash
gcloud builds triggers create github \
  --name="java-test-generator" \
  --repo-name="YOUR_REPO" \
  --repo-owner="YOUR_ORG" \
  --pull-request-pattern="^main$" \
  --build-config="cloudbuild/cloudbuild.yaml" \
  --substitutions="_INDEX_BUCKET=YOUR_PROJECT-java-index-cache"
```

### 6. Copy Required Files to Your Repo

```bash
# Copy the cloudbuild directory to your Java repo
cp -r cloudbuild/ /path/to/your/java/repo/

# Copy the java_indexer module
cp -r java_indexer/ /path/to/your/java/repo/
```

## Configuration

### Substitution Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `_INDEX_BUCKET` | `java-index-cache` | GCS bucket for cached index |
| `_LLM_MODEL` | `google/gemma-3-4b-it:free` | OpenRouter model ID |
| `_MAX_CLASSES` | `20` | Max classes to generate tests for |

### LLM Models

Free models (via OpenRouter):
- `google/gemma-3-4b-it:free` - Default, good quality
- `meta-llama/llama-3-8b-instruct:free` - Alternative

Paid models (better quality):
- `anthropic/claude-sonnet-4` - Best quality
- `openai/gpt-4o-mini` - Good balance

## Local Testing

```bash
# Test the generator locally
cd /path/to/your/java/repo

# Create a test changed-files.txt
echo "src/main/java/com/example/UserService.java" > changed-files.txt

# Run the generator
export OPENROUTER_API_KEY="your-key"
python cloudbuild/generate_tests.py \
  --repo . \
  --changed-files changed-files.txt \
  --output-dir generated-tests \
  --json-output
```

## Viewing Results

After a build:

1. **Build Logs**: Cloud Build > History > Select build
2. **Generated Tests**: Check the `artifacts` in GCS:
   ```bash
   gsutil ls gs://YOUR_BUCKET/artifacts/BUILD_ID/
   gsutil cat gs://YOUR_BUCKET/artifacts/BUILD_ID/results.json
   ```

## Troubleshooting

### "No module named 'tree_sitter_java'"
The Python step installs dependencies, but if it fails:
```bash
pip install tree-sitter tree-sitter-java
```

### "Secret not found"
Ensure the secret exists and Cloud Build has access:
```bash
gcloud secrets list
gcloud secrets get-iam-policy openrouter-api-key
```

### "Permission denied on GCS bucket"
Grant objectAdmin to Cloud Build service account:
```bash
gsutil iam ch serviceAccount:YOUR_PROJECT_NUMBER@cloudbuild.gserviceaccount.com:objectAdmin gs://YOUR_BUCKET
```

### LLM returns empty/bad response
- Check OpenRouter API key is valid
- Try a different model
- Check the `results.json` for error messages

## Cost Considerations

- **Cloud Build**: ~$0.003/build-minute (E2_MEDIUM)
- **GCS Storage**: ~$0.02/GB/month (minimal for index)
- **OpenRouter**: Free tier available, or ~$0.001-0.01/test with paid models
- **Secrets Manager**: ~$0.06/secret/month

Typical PR build: < $0.05
# Test trigger
