import os
import tarfile
import tempfile
from google.cloud import storage

def untar_gzip_to_temp(gzip_file):
    # Create a temporary directory
    temp_dir = tempfile.mkdtemp()
    
    # Extract the gzip file
    with tarfile.open(gzip_file, "r:gz") as tar:
        tar.extractall(path=temp_dir)
    
    return temp_dir

def upload_files_to_gcs(bucket_name, source_folder):
    # Initialize GCS client
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # Upload files
    for filename in os.listdir(source_folder):
        blob = bucket.blob(filename)
        blob.upload_from_filename(os.path.join(source_folder, filename))

def main():
    # Path to your gzip file
    gzip_file = 'path_to_your_gzip_file.tar.gz'

    # GCS bucket name
    bucket_name = 'your_gcs_bucket_name'

    # Untar the file
    temp_dir = untar_gzip_to_temp(gzip_file)

    # Upload to GCS
    upload_files_to_gcs(bucket_name, temp_dir)

    # Cleanup: Optionally delete the temp directory after upload
    # os.rmdir(temp_dir)

if __name__ == "__main__":
    main()
