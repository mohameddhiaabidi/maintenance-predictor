# azure_storage.py
import os
import pandas as pd
import io
from azure.storage.blob import BlobServiceClient

class AzureStorageHelper:
    def __init__(self):
        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not connection_string:
            raise ValueError("❌ AZURE_STORAGE_CONNECTION_STRING environment variable is required")
        
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    
    def save_dataframe(self, df: pd.DataFrame, container_name: str, blob_name: str):
        """Save DataFrame to Azure Blob Storage as Excel"""
        try:
            # Create container if it doesn't exist
            container_client = self.blob_service_client.get_container_client(container_name)
            if not container_client.exists():
                container_client.create_container()
            
            # Convert DataFrame to Excel in memory
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False)
            output.seek(0)
            
            # Upload to blob storage
            blob_client = self.blob_service_client.get_blob_client(
                container=container_name, 
                blob=blob_name
            )
            blob_client.upload_blob(output, overwrite=True)
            
            print(f"✅ DataFrame saved to blob: {container_name}/{blob_name}")
            
        except Exception as e:
            print(f"❌ Failed to save DataFrame to Azure Storage: {str(e)}")
            raise
    
    def upload_file(self, file_path: str, container_name: str, blob_name: str):
        """Upload a file to Azure Blob Storage"""
        try:
            container_client = self.blob_service_client.get_container_client(container_name)
            if not container_client.exists():
                container_client.create_container()
            
            with open(file_path, "rb") as data:
                blob_client = self.blob_service_client.get_blob_client(container_name, blob_name)
                blob_client.upload_blob(data, overwrite=True)
            
            print(f"✅ File uploaded to blob: {container_name}/{blob_name}")
            
        except Exception as e:
            print(f"❌ Failed to upload file to Azure Storage: {str(e)}")
            raise
