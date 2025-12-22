# Infrastructure Setup Guide

This guide provides step-by-step instructions for setting up the **FIH Rules Engine** infrastructure from scratch in a new Google Cloud Project.

## 1. Project Initialization

Set your active project and region:
```bash
export PROJECT_ID="fih-rules-engine"
export REGION="europe-west1"

gcloud config set project $PROJECT_ID
gcloud auth application-default set-quota-project $PROJECT_ID
```

## 2. Enable APIs

Enable the required Google Cloud services:
```bash
gcloud services enable \
    run.googleapis.com \
    aiplatform.googleapis.com \
    documentai.googleapis.com \
    sqladmin.googleapis.com \
    storage.googleapis.com \
    artifactregistry.googleapis.com \
    cloudbuild.googleapis.com
```

## 3. Storage & Database Setup

### Create Staging Bucket
This bucket is used for Document AI batch processing.
```bash
gsutil mb -l $REGION gs://fih-rag-staging-$PROJECT_ID
```

### Create Cloud SQL Instance
Create a PostgreSQL 15 instance:
```bash
gcloud sql instances create fih-rag-db \
    --database-version=POSTGRES_15 \
    --tier=db-custom-1-3840 \
    --region=$REGION \
    --storage-type=SSD

# Set the password (avoid special characters that break shell commands, e.g. '!')
gcloud sql users set-password postgres \
    --instance=fih-rag-db \
    --password="<YOUR_DB_PASSWORD>"

# IMPORTANT: Create the application database
gcloud sql databases create hockey_db --instance=fih-rag-db
```

## 4. Document AI Processor

Provision the OCR processor using the automation script:
```bash
python3 scripts/setup_docai_processor.py
```
Copy the `PROCESSOR_ID` from the output for the deployment step below.

## 5. IAM Permissions (Security)

### Create a Service Account for Cloud Run
```bash
gcloud iam service-accounts create fih-rag-sa \
    --display-name="FIH Rules Engine Service Account"
```

### Grant Roles
```bash
# Vertex AI, Document AI, Storage, and Cloud SQL
for ROLE in aiplatform.user documentai.apiUser storage.objectUser cloudsql.client; do
    gcloud projects add-iam-policy-binding $PROJECT_ID \
        --member="serviceAccount:fih-rag-sa@$PROJECT_ID.iam.gserviceaccount.com" \
        --role="roles/$ROLE"
done
```

## 6. Deployment

> [!IMPORTANT]
> Both services require at least **2GiB of memory** and **1 CPU** to handle the heavy Python RAG stack and PDF processing.

### 1. Public API (Standard Dockerfile)
```bash
gcloud run deploy fih-rag-api \
    --source . \
    --region $REGION \
    --memory 2Gi \
    --cpu 1 \
    --service-account="fih-rag-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --allow-unauthenticated \
    --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID,CLOUDSQL_INSTANCE=fih-rag-db,DB_USER=postgres,DB_PASS=YourStrongPassword2025,API_KEY=your-secret,DOCAI_PROCESSOR_ID=your-processor-id,GCS_BUCKET_NAME=fih-rag-staging-$PROJECT_ID"
```

### 2. Admin Dashboard (Custom Dockerfile via Cloud Build)
Because `gcloud run deploy --source` doesn't support custom Dockerfile names, we use Cloud Build:

```bash
# 1. Build the image
gcloud builds submit . --config cloudbuild.admin.yaml

# 2. Deploy from the image
gcloud run deploy fih-rag-admin \
    --image gcr.io/$PROJECT_ID/admin-app:latest \
    --region $REGION \
    --memory 2Gi \
    --cpu 1 \
    --service-account="fih-rag-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --no-allow-unauthenticated \
    --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID,CLOUDSQL_INSTANCE=fih-rag-db,DB_USER=postgres,DB_PASS=<YOUR_DB_PASSWORD>,API_KEY=<YOUR_API_KEY>,DOCAI_PROCESSOR_ID=your-processor-id,GCS_BUCKET_NAME=fih-rag-staging-$PROJECT_ID"
```

---

> [!TIP]
> Use `gcloud run services update --update-env-vars` if you only need to change a single variable without overwriting the entire environment.
