import os
import json
import logging
from datetime import datetime, timedelta
from azure.cosmos import CosmosClient
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential


def get_blob_client(storage_account_url, container_name, blob_name):
    """Obtiene cliente de blob con autenticación Managed Identity"""
    try: 
        credential = DefaultAzureCredential()
        blob_service_client = BlobServiceClient(
            account_url=storage_account_url,
            credential=credential
        )
        container_client = blob_service_client.get_container_client(container_name)
        return container_client.get_blob_client(blob_name)
    except Exception as e:
        logging.error(f'Could not get storage information, error: {str(e)}')
        raise



def read_delta_date(storage_account_url, container_name):
    """Lee la fecha delta desde un archivo TXT en Blob Storage"""
    blob_name = "delta_config/last_delta.txt"
    try:
        blob_client = get_blob_client(storage_account_url, container_name, blob_name)
        delta_content = blob_client.download_blob().readall().decode('utf-8')
        return delta_content.strip()
    except Exception as e:
        logging.error(f"Could not read delta file: {str(e)}. Using default date.")
        raise
    

def cosmos_storage(endpoint, storage_account_url, database_name, container_name, blob_container_name, blob_folder_path, query_date):
    try:
    # Conexión a Cosmos DB
        credential = DefaultAzureCredential()
        cosmos_client = CosmosClient(endpoint, credential)
        database = cosmos_client.get_database_client(database_name)
        container = database.get_container_client(container_name)

        # Leer documentos de Cosmos DB
        query = f"SELECT * FROM c WHERE c.createdAt >= '{query_date}'"
        documents = list(container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        # Validación para documentos vacíos
        if not documents or len(documents) == 0:
            logging.info("No new documents were found to transfer. A JSON file will not be created.")
            return True

        # Convertir a JSON
        json_data = json.dumps(documents, ensure_ascii=False)

        # Conexión a Blob Storage
        blob_service_client = BlobServiceClient(
            account_url=storage_account_url,
            credential=credential
        )
        blob_container_client = blob_service_client.get_container_client(blob_container_name)


        # Generar nombre de archivo con timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        blob_name = f"{blob_folder_path}/cosmos_data_{timestamp}.json"  # Incluye la subcarpeta

        # Subir archivo JSON a Blob Storage
        blob_client = blob_container_client.get_blob_client(blob_name)
        blob_client.upload_blob(json_data, overwrite=True)

        logging.info(f'Successfully wrote {len(documents)} documents to Blob Storage as {blob_name}.')
        return True
    except Exception as e:
        logging.error(f'Error occurred: {str(e)}')
        return False

def save_delta_date(storage_account_url, container_name, new_date):
    """Guarda la nueva fecha delta en Blob Storage"""
    blob_name = "delta_config/last_delta.txt"
    try:
        blob_client = get_blob_client(storage_account_url, container_name, blob_name)
        blob_client.upload_blob(new_date.encode('utf-8'), overwrite=True)
        logging.info(f"Updated delta date: {new_date}")
        return True
    except Exception as e:
        logging.error(f"Error saving delta date: {str(e)}")
        return False
