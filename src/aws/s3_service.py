import boto3
import os


class S3Service:
    def __init__(self):
        self.endpoint_url = os.getenv('AWS_ENDPOINT_URL', 'http://localhost:4566')
        self.region_name = os.getenv('AWS_REGION', 'us-east-1')
        self.access_key = os.getenv('AWS_ACCESS_KEY_ID', 'test')
        self.secret_key = os.getenv('AWS_SECRET_ACCESS_KEY', 'test')
        self.bucket_name = 'habit-tracker'

        self.s3 = boto3.client(
            's3',
            endpoint_url=self.endpoint_url,
            region_name=self.region_name,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key
        )
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """Ensure bucket exists, create if needed"""
        try:
            self.s3.head_bucket(Bucket=self.bucket_name)
        except Exception:
            try:
                self.s3.create_bucket(Bucket=self.bucket_name)
            except Exception:
                pass

    def upload_file(self, file_key: str, file_data: bytes) -> str:
        """Dosya yükle ve URL döndür"""
        try:
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=file_key,
                Body=file_data
            )
            url = f"{self.endpoint_url}/{self.bucket_name}/{file_key}"
            print(f"✅ File uploaded: {file_key}")
            return url
        except Exception as e:
            print(f"❌ Upload error: {e}")
            return None

    def download_file(self, file_key: str) -> bytes:
        """Dosya indir"""
        try:
            response = self.s3.get_object(
                Bucket=self.bucket_name,
                Key=file_key
            )
            file_data = response['Body'].read()
            print(f"✅ File downloaded: {file_key}")
            return file_data
        except Exception as e:
            print(f"❌ Download error: {e}")
            return None

    def delete_file(self, file_key: str) -> bool:
        """Dosya sil"""
        try:
            self.s3.delete_object(
                Bucket=self.bucket_name,
                Key=file_key
            )
            print(f"✅ File deleted: {file_key}")
            return True
        except Exception as e:
            print(f"❌ Delete error: {e}")
            return False
