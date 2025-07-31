import os
import json
import logging
import azure.functions as func
from datetime import datetime
import utils.azure_clients as azure_clients
import utils.utils as utils
import utils.session_cleanup as clean

def main(timer: func.TimerRequest) -> None:
    logging.info('Python timer trigger function started.')

    # Configuración de conexiones
    container = azure_clients.get_cosmos_container()
    
    try:
        clean.clean_old_sessions(container)
        logging.info("Process completed successfully!")
        return
        
    except Exception as e:
        logging.error(f"Error in main execution: {str(e)}", exc_info=True)
        