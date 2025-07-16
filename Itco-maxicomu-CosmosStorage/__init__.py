import os
import json
import logging
import azure.functions as func
from datetime import datetime
from azure.cosmos import CosmosClient
from azure.storage.blob import BlobServiceClient

def CostosStorage(cosmos_connection_string, storage_connection_string, database_name, container_name, blob_container_name, blob_folder_path):
    try:
    # Conexión a Cosmos DB
        cosmos_client = CosmosClient.from_connection_string(cosmos_connection_string)
        database = cosmos_client.get_database_client(database_name)
        container = database.get_container_client(container_name)

        # Leer documentos de Cosmos DB
        documents = list(container.query_items(
            query="SELECT * FROM c WHERE c.createdAt >= '2025-07-14T00:00:00'",
            enable_cross_partition_query=True
        ))

        # Convertir a JSON
        json_data = json.dumps(documents, ensure_ascii=False)

        # Conexión a Blob Storage
        blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
        blob_container_client = blob_service_client.get_container_client(blob_container_name)

        # Crear contenedor si no existe
        try:
            blob_container_client.create_container()
        except Exception as e:
            if "ContainerAlreadyExists" not in str(e):
                raise

        # Generar nombre de archivo con timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        blob_name = f"{blob_folder_path}/cosmos_data_{timestamp}.json"  # Incluye la subcarpeta

        # Subir archivo JSON a Blob Storage
        blob_client = blob_container_client.get_blob_client(blob_name)
        blob_client.upload_blob(json_data, overwrite=True)

        logging.info(f'Successfully wrote {len(documents)} documents to Blob Storage as {blob_name}.')

    except Exception as e:
        logging.error(f'Error occurred: {str(e)}')
        raise


def main(timer: func.TimerRequest) -> None:
    logging.info('Python timer trigger function started.')

    # Configuración de conexiones
    cosmos_connection_string = os.environ.get("CosmosDBConnectionString")
    storage_connection_string = os.environ.get("AzureWebJobsStorage")
    database_name = "conversationitcomaxicomu"
    container_name = "conversationitcomaxicomucont"
    blob_container_name = "base-conocimiento" 
    blob_folder_path = "Cosmos"

    try:
        logging.info('Se inicia el proceso de transferencia de información')
        CostosStorage(cosmos_connection_string, storage_connection_string, database_name, container_name, blob_container_name, blob_folder_path)
    except Exception as e:
        logging.error(f'Error occurred: {str(e)}')
        raise