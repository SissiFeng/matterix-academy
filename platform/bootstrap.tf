# Operator-issued installers contain a machine credential. This bucket has no
# CloudFront origin or application-role access; downloads use short-lived S3 URLs.
resource "aws_s3_bucket" "bootstrap" {
  bucket        = "${local.name}-${local.suffix}-bootstrap"
  force_destroy = false
}
resource "aws_s3_bucket_public_access_block" "bootstrap" {
  bucket                  = aws_s3_bucket.bootstrap.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "bootstrap" {
  bucket = aws_s3_bucket.bootstrap.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_policy" "bootstrap" {
  bucket = aws_s3_bucket.bootstrap.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "TLSOnly", Effect = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.bootstrap.arn, "${aws_s3_bucket.bootstrap.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
resource "aws_s3_bucket_lifecycle_configuration" "bootstrap" {
  bucket = aws_s3_bucket.bootstrap.id
  rule {
    id     = "expire-installers"
    status = "Enabled"
    filter {}
    expiration { days = 1 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}
output "bootstrap_bucket" { value = aws_s3_bucket.bootstrap.id }
