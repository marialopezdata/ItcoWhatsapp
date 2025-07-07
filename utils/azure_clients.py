import os
import logging
from functools import lru_cache
from azure.identity import DefaultAzureCredential
from azure.cosmos import CosmosClient
from azure.storage.blob import BlobServiceClient
from azure.keyvault.secrets import SecretClient


# URL del Key Vault
key_vault_url = os.environ["key_vault_url"]


@lru_cache
def get_credential():
    """Obtiene una credencial por defecto de Azure (con caché)."""
    return DefaultAzureCredential()


@lru_cache
def get_secrets(secret_name):
    try:
        # Autenticación con la identidad administrada
        credential = get_credential()

        # Cliente para consultar secretos
        client = SecretClient(vault_url=key_vault_url, credential=credential)

        # Obtener un secreto
        retrieved_secret = client.get_secret(secret_name)
        
        return retrieved_secret.value
    except Exception as e:
        logging.error(f"ERROR - getting secret: {e}")
        raise


@lru_cache
def get_cosmos_container():
    """Devuelve el cliente del contenedor de Cosmos DB."""
    try:
        credential = get_credential()
        client = CosmosClient(os.environ["cosmos_endpoint"], credential=credential)
        database = client.get_database_client(os.environ["cosmos_db_name"])
        container = database.get_container_client(os.environ["cosmos_container_name"])
        return container
    except Exception as e:
        logging.error(f"[CosmosDB] Error al conectar: {e}")
        raise


@lru_cache
def get_blob_service_client():
    """Devuelve el cliente principal del Blob Storage."""
    try:
        return BlobServiceClient(
            account_url=os.environ["storage_account_url"],
            credential=get_credential()
        )
    except Exception as e:
        logging.error(f"[BlobStorage] Error al conectar: {e}")
        raise


@lru_cache
def get_blob_container(container_env_var_name: str):
    """Devuelve un contenedor específico usando su variable de entorno."""
    try:
        container_name = os.environ[container_env_var_name]
        return get_blob_service_client().get_container_client(container_name)
    except KeyError:
        raise RuntimeError(f"La variable de entorno '{container_env_var_name}' no está definida.")
    except Exception as e:
        logging.error(f"[BlobStorage] Error al obtener contenedor {container_env_var_name}: {e}")
        raise