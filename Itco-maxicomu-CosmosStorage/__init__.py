import os
import json
import logging
import azure.functions as func
from datetime import datetime
from . import functionCosmosStorage


def main(timer: func.TimerRequest) -> None:
    logging.info('Python timer trigger function started.')

    # Configuración de conexiones
    storage_account_url = os.environ.get("storage_account_url")
    database_name = os.environ.get("cosmos_db_name")
    container_name = os.environ.get("cosmos_container_name")
    blob_container_name = os.environ.get("storage_container_basecono")
    blob_folder_path = os.environ.get("storage_container_cosmosstorage")
    endpoint = os.environ.get("cosmos_endpoint")
    
    try:
        
        current_delta = functionCosmosStorage.read_delta_date(storage_account_url, blob_container_name)
        logging.info(f"Current delta date: {current_delta}")

        logging.info('The information transfer process begins')
        transfer_success  = functionCosmosStorage.cosmos_storage(endpoint, storage_account_url, database_name, container_name, blob_container_name, blob_folder_path, current_delta)
        if transfer_success:
            new_delta = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0
            ).strftime("%Y-%m-%dT%H:%M:%S")
            
            save_success = functionCosmosStorage.save_delta_date(storage_account_url, blob_container_name,new_delta)

            if not save_success:
                logging.error("The delta date could not be updated.")
                return
        else:
            logging.error("The data transfer failed")
            return  

        logging.info("Process completed successfully!")

    except Exception as e:
        logging.error(f"Error in main execution: {str(e)}", exc_info=True)
        