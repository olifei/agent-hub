
# Copyright 2025 Google LLC

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     https://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import datetime
from google.cloud import storage

from mcp_server.pipeline.log import log
from mcp_server.pipeline.config import settings
from mcp_server.pipeline.common_utils import CommonUtils


class GoogleCloudStorage:
    
    def __init__(self, bucket_name):
        self.bucket_name = bucket_name
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)

    def upload_file(self, local_file_path, remote_file_path, replace=False):
        try:
            blob = self.bucket.blob(remote_file_path)
            if not blob.exists() or replace:
                blob.upload_from_filename(local_file_path)
                log.info(f"Upload file successfully to {remote_file_path}")
            else:
                log.info("Remote file exists. Uploading cancelled.")
            return True
        except Exception as e:
            log.error(e)
            return False

    def download_file(self, remote_file_path, local_file_path):
        try:
            blob = self.bucket.blob(remote_file_path)
            blob.download_to_filename(local_file_path)
            return True
        except Exception as e:
            log.error(e)
            return False

    def extract_key_from_full_uri(self, full_uri):
        return full_uri[full_uri.index('/', 5) + 1:]

    def get_gcs_uri_from_key(self, key):
        return f"gs://{settings.GCS_BUCKET_NAME}/{key}"
    
    def get_presigned_url(self, gcs_uri, expiration=1800):
        try:
            gcs_key = self.extract_key_from_full_uri(gcs_uri)
            blob = self.bucket.blob(gcs_key)
            url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(seconds=expiration),
                method="GET",
            )
            return url
        except Exception as e:
            log.error(e)
            return False
        
    def upload_to_gcs(self, identifier, input_file, key_prefix):
        filename = CommonUtils.get_file_name(input_file)
        upload_uri = f"{settings.GCS_PREFIX}/{key_prefix}/{identifier}/{filename}"
        self.upload_file(input_file, upload_uri)
        origin_file_uri = self.get_gcs_uri_from_key(upload_uri)
        return origin_file_uri
    
    def delete_prefix(self, prefix: str):
        """Delete all blobs under a GCS prefix (equivalent to rm -rf).
        
        Args:
            prefix: The GCS prefix to delete all objects under.
        """
        blobs = list(self.bucket.list_blobs(prefix=prefix))
        if not blobs:
            log.info(f"No objects found under prefix: {prefix}")
            return
        for blob in blobs:
            blob.delete()
        log.info(f"Cleaned GCS prefix: {prefix} ({len(blobs)} objects deleted)")

    def download_as_text(self, remote_file_path):
        """Download a GCS blob directly into memory as text.
        
        Args:
            remote_file_path: The GCS key to read.
            
        Returns:
            The file contents as a string, or None if the blob doesn't exist.
        """
        try:
            blob = self.bucket.blob(remote_file_path)
            if not blob.exists():
                return None
            return blob.download_as_text()
        except Exception as e:
            log.error(f"Failed to download {remote_file_path} as text: {e}")
            return None

    def check_file_exists(self, remote_file_path):
        """Check if a file exists in GCS."""
        return self.bucket.blob(remote_file_path).exists()

    def upload_from_string(self, remote_file_path, content: str, content_type: str = "application/json"):
        """Upload string content directly to GCS without writing to local disk.
        
        Args:
            remote_file_path: The GCS key to write to.
            content: String content to upload.
            content_type: MIME type (default: application/json).
        """
        try:
            blob = self.bucket.blob(remote_file_path)
            blob.upload_from_string(content, content_type=content_type)
            log.info(f"Uploaded string content to {remote_file_path}")
            return True
        except Exception as e:
            log.error(f"Failed to upload string to {remote_file_path}: {e}")
            return False

    def list_prefixes(self, prefix: str, delimiter: str = "/") -> list[str]:
        """List 'subdirectory' prefixes under a GCS prefix.
        
        This is analogous to listing subdirectories in a local filesystem.
        For example, listing prefix="pipeline/user/data/" with delimiter="/"
        returns ["pipeline/user/data/category1/", "pipeline/user/data/category2/"].
        
        Args:
            prefix: The GCS prefix to list under (must end with /).
            delimiter: The delimiter for virtual directory hierarchy.
            
        Returns:
            List of sub-prefix strings.
        """
        if not prefix.endswith("/"):
            prefix += "/"
        iterator = self.bucket.list_blobs(prefix=prefix, delimiter=delimiter)
        # Must consume the iterator to populate prefixes
        _ = list(iterator)
        return list(iterator.prefixes)

    def list_blobs_with_prefix(self, prefix: str) -> list[str]:
        """List all blob names under a GCS prefix.
        
        Args:
            prefix: The GCS prefix to list under.
            
        Returns:
            List of blob name strings.
        """
        blobs = self.bucket.list_blobs(prefix=prefix)
        return [blob.name for blob in blobs]

    def download_json(self, remote_file_path) -> dict | None:
        """Download a JSON file from GCS and parse it.
        
        Args:
            remote_file_path: The GCS key to read.
            
        Returns:
            Parsed JSON as dict, or None if not found/invalid.
        """
        text = self.download_as_text(remote_file_path)
        if text is None:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            log.error(f"Failed to parse JSON from {remote_file_path}: {e}")
            return None

    def upload_product_data(self, local_product_dir: str, gcs_data_prefix: str) -> list[str]:
        """Upload a product folder (metadata.json + images) to GCS data store.

        Args:
            local_product_dir: Local product directory (e.g. "data/category/product_id")
            gcs_data_prefix: GCS prefix for data (e.g. "{prefix}/{user_id}/data/category/product_id")

        Returns:
            List of GCS URIs for uploaded image files.
        """
        import os

        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
        uploaded_image_uris = []
        files_seen = sorted(os.listdir(local_product_dir))
        log.info(f"upload_product_data: {local_product_dir} → gs://{self.bucket_name}/{gcs_data_prefix} (files: {files_seen})")

        for filename in files_seen:
            local_path = os.path.join(local_product_dir, filename)
            if not os.path.isfile(local_path):
                continue

            remote_path = f"{gcs_data_prefix}/{filename}"
            ok = self.upload_file(local_path, remote_path, replace=True)
            if ok:
                # Verify the object is actually readable post-upload — upload_file
                # has been observed to log success without the blob being visible.
                blob = self.bucket.blob(remote_path)
                if not blob.exists():
                    log.error(f"upload_product_data: upload_file claimed success but blob is missing: gs://{self.bucket_name}/{remote_path}")

            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext in image_extensions:
                uploaded_image_uris.append(f"gs://{self.bucket_name}/{remote_path}")

        return uploaded_image_uris

    def get_product_image_uris(self, gcs_data_prefix: str) -> list[str]:
        """Get GCS URIs for all product images under a data prefix.
        
        Args:
            gcs_data_prefix: GCS prefix (e.g. "{prefix}/{user_id}/data/category/product_id")
            
        Returns:
            List of GCS URIs for image files.
        """
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
        blobs = self.list_blobs_with_prefix(gcs_data_prefix)
        
        uris = []
        for blob_name in blobs:
            import os
            ext = os.path.splitext(blob_name)[1].lower()
            if ext in image_extensions:
                uris.append(f"gs://{self.bucket_name}/{blob_name}")
        
        return uris


gcs_service = GoogleCloudStorage(settings.GCS_BUCKET_NAME)
