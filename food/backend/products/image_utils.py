from functools import lru_cache
from pathlib import PurePosixPath

import boto3
from django.conf import settings


@lru_cache(maxsize=1)
def get_s3_client():
    bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
    region = getattr(settings, "AWS_S3_REGION_NAME", "")
    access_key = getattr(settings, "AWS_ACCESS_KEY_ID", "")
    secret_key = getattr(settings, "AWS_SECRET_ACCESS_KEY", "")
    if not all([bucket, region, access_key, secret_key]):
        return None

    return boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


@lru_cache(maxsize=1)
def get_bucket_key_index():
    bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
    s3_client = get_s3_client()
    if not bucket or not s3_client:
        return {}

    paginator = s3_client.get_paginator("list_objects_v2")
    key_index = {}
    for page in paginator.paginate(Bucket=bucket, Prefix="products/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            name = PurePosixPath(key).name
            key_index.setdefault(name, key)
            if "_" in name:
                key_index.setdefault(name.split("_", 1)[1], key)
    return key_index


def resolve_bucket_key(image_path):
    normalized_path = image_path.lstrip("/")
    key_index = get_bucket_key_index()
    if normalized_path in key_index.values():
        return normalized_path

    file_name = PurePosixPath(normalized_path).name
    return key_index.get(file_name, normalized_path)


def build_product_image_url(request, image_path):
    if not image_path:
        return None
    if image_path.startswith(("http://", "https://")):
        return image_path

    image_base_url = getattr(settings, "FOOD_IMAGE_BASE_URL", "").rstrip("/")
    if image_base_url:
        return f"{image_base_url}/{image_path.lstrip('/')}"

    bucket = getattr(settings, "AWS_STORAGE_BUCKET_NAME", "")
    s3_client = get_s3_client()
    if bucket and s3_client:
        bucket_key = resolve_bucket_key(image_path)
        return s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": bucket_key},
            ExpiresIn=3600,
        )

    forwarded_prefix = request.headers.get("X-Forwarded-Prefix", "").rstrip("/")
    media_path = f"{forwarded_prefix}{settings.MEDIA_URL}" if forwarded_prefix else settings.MEDIA_URL
    base = request.build_absolute_uri(media_path)
    return base.rstrip("/") + "/" + image_path.lstrip("/")
