# Infrastructure Setup Guide

This guide provides step-by-step instructions for setting up the **FIH Rules Engine** infrastructure from scratch in a new Google Cloud Project.

## 1. Project Initialization

Set your active project and region:
```bash
export PROJECT_ID="your-project-id"
export REGION="europe-west1"

gcloud config set project $PROJECT_ID
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
Create a PostgreSQL 15 instance (ensure `pgvector` compatibility):
```bash
gcloud sql instances create fih-rag-db \
    --database-version=POSTGRES_15 \
    --tier=db-custom-1-3840 \
    --region=$REGION \
    --storage-type=SSD
```

## 4. Document AI Processor

You must create a **Custom Document Extractor** (or General Processor) in the Google Cloud Console:
1. Go to **Document AI** > **Processors**.
2. Click **Create Processor** and select **Document OCR** (or a specialized one).
3. Copy the **Processor ID** for your `config.py` or environment variables.

## 5. IAM Permissions (Security)

### Create a Service Account for Cloud Run
```bash
gcloud iam service-accounts create fih-rag-sa \
    --display-name="FIH Rules Engine Service Account"
```

### Grant Roles
Assign the necessary permissions to the service account:
```bash
# Vertex AI for Gemini & Embeddings
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:fih-rag-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/aiplatform.user"

# Document AI for parsing
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:fih-rag-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/documentai.apiUser"

# Storage access for ingestion shards
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:fih-rag-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/storage.objectUser"

# Cloud SQL connection
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:fih-rag-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/cloudsql.client"
```

## 6. Deployment

### 1. Public API
```bash
gcloud run deploy fih-rag-api \
    --source . \
    --region $REGION \
    --service-account="fih-rag-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --allow-unauthenticated \
    --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID,CLOUDSQL_INSTANCE=fih-rag-db,DB_USER=postgres,DB_PASS=your-password,API_KEY=your-secret"
```

### 2. Admin Dashboard (Recommended with IAP)
```bash
gcloud run deploy fih-rag-admin \
    --source . \
    --dockerfile Dockerfile.admin \
    --region $REGION \
    --service-account="fih-rag-sa@$PROJECT_ID.iam.gserviceaccount.com" \
    --no-allow-unauthenticated \
    --set-env-vars "GCP_PROJECT_ID=$PROJECT_ID,CLOUDSQL_INSTANCE=fih-rag-db,DB_USER=postgres,DB_PASS=your-password,API_KEY=your-secret"
```

## 7. Manual Build & Deploy (Artifact Registry)

If you prefer to build the image once and deploy it multiple times (or to multiple services), use **Cloud Build** and **Artifact Registry**.

### Create a Repository
```bash
gcloud artifacts repositories create fih-repo \
    --repository-format=docker \
    --location=$REGION
```

### Build the Admin Image
```bash
gcloud builds submit . \
    --tag $REGION-docker.pkg.dev/$PROJECT_ID/fih-repo/admin-app:latest \
    --dockerfile Dockerfile.admin
```

### Deploy from the Image
```bash
gcloud run deploy fih-rag-admin \
    --image $REGION-docker.pkg.dev/$PROJECT_ID/fih-repo/admin-app:latest \
    --region $REGION \
    --service-account="fih-rag-sa@$PROJECT_ID.iam.gserviceaccount.com"
```

> [!TIP]
> This approach is preferred for Production environments as it ensures that the exact same binary is deployed across different stages (staging/prod) without rebuilding from source.
