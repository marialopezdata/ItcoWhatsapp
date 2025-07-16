import os
import io
import logging
import pandas as pd
import requests
import time
from datetime import datetime, timezone
import utils.azure_clients as azure_clients
import utils.utils as utils
import utils.session_cleanup as clean

# Conexión a Whatsapp
# whatsapp_token = "Bearer EAATVIxJamLkBO8zxnPulQAzX6y5M3vHpLSDkeSWNtex3IDDyFrlWrIjj2WjNjSmdsJG5VBXPmHKGXT1DbQYaZAesb2IrDGNWKmTZBjTBv05jcDbqxlaxTQ0ZButKVe65Gf3thHHNsHd95anbdM0UA3HgfaxyoBPy0RF0rgoacPBFW0UB4nAzKvtfhhyCYQAwgZDZD"
whatsapp_token = azure_clients.get_secrets("whatsapp-token")

# Definir tiempo máximo de conversación activa (24 horas)
time_hours = int(os.environ.get("time_hours", 24))


def get_active_phone_numbers():  
    """Obtiene una lista de números de teléfono de contactos activos desde un archivo de Excel en Azure Blob Storage."""
    try:         
        # Obtener una referencia al contenedor
        blob_container = azure_clients.get_blob_container("storage_container_basecono")
        blob_client = blob_container.get_blob_client("comunicados/contactos.xlsx")
        
        # Descargar el contenido del archivo        
        blob_data = blob_client.download_blob()
        
        # Cargar el contenido del blob en un DataFrame de pandas
        excel_bytes = io.BytesIO(blob_data.readall())
        df = pd.read_excel(excel_bytes)        
        
        # Filtrar filas donde ENVIAR sea 'S'
        df_activo = df[df['ENVIAR'].astype(str).str.upper() == 'S']

        # Obtener la lista de números de teléfono
        telefonos = df_activo['TELEFONO'].astype(str).tolist()
        
        return telefonos

    except Exception as e:
        logging.error(f"ERROR - get_active_phone_numbers: {e}")
        raise


def send_whatsapp_message(contacts, texto, img):
    """Envía un mensaje de WhatsApp a varios contactos usando la API de Meta."""
    try:
        now = datetime.now(timezone.utc)
        container = azure_clients.get_cosmos_container()
        na = ["No Aplica"]
        
        clean.clean_old_sessions(container)
        
        headers = {
            "Authorization": whatsapp_token,
            "Content-Type": "application/json",
        }       
        
        logging.info(f"contacts:{contacts}") 
        
        phone_number_id="580789875119451"
        
        url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
        for contact in contacts:
            contact = contact.strip()  # Elimina espacios o saltos de línea

            if not contact:
                logging.info(f"no contact")
                continue  # Evita enviar si el contacto está vacío
            
            conversation = utils.get_conversation(container, contact)

            if conversation:
                conversation_history = conversation["messages"]
                
                if utils.should_close_conversation(conversation, time_hours):
                    logging.info("Conversación cerrada o expirada. Se crea una nueva.")
                    conversation["sessionStatus"] = "closed"
                    utils.save_conversation(container, conversation)    
            
            conversation = utils.initialize_conversation(contact, "user_name")
            
            conversation_history = conversation["messages"]

            data = { 
                "messaging_product": "whatsapp", 
                "to": contact, 
                "type": "template", 
                "template": 
                {
                    "name": "saludocampana", 
                    "language": 
                    { 
                        "code": "es_CO" 
                    },
                    "components": [
                        {
                            "type": "header",
                            "parameters": [
                                {
                                    "type": "image",
                                    "image": {
                                        "link": img
                                    }
                                }
                            ]
                        },
                        {
                            "type": "body",
                            "parameters": [
                                {
                                    "type": "text",
                                    "parameter_name": "nombre",
                                    "text": texto
                                }
                            ]
                        }
                    ]
                } 
            }

            logging.info(f"Enviando mensaje a: {contact}")
            response = requests.post(url, headers=headers, json=data)
            logging.info(f"response content: {response.content}")
            logging.info(f"response status code: {response.status_code}")
            content = f"{texto} - imagen: {img}"
            try:
                content_response = response.json()
                message_id = content_response.get("messages", [{}])[0].get("id", "sin_id")
            except Exception as parse_error:
                logging.error(f"Error parsing response: {parse_error}")
                continue
            utils.add_message(conversation_history, "assistant", content, message_id, "campaña", na, na)
            
            if response.status_code != 200:
                logging.error(f"Falló el envío a {contact}. Status: {response.status_code}. Content: {response.content}")
                continue  # salta al siguiente contacto
            
            utils.save_conversation(container, {
                "id": conversation["id"],
                "userId": conversation["userId"],
                "userName": conversation["userName"],
                "createdAt": now.isoformat(),
                "updatedAt": now.isoformat(),
                "messages": conversation_history,
                "sessionStatus": conversation["sessionStatus"]
            })
            time.sleep(1) 
            response.raise_for_status()
    except Exception as e:
        logging.error(f'ERROR - sending whatsapp message: {e}')