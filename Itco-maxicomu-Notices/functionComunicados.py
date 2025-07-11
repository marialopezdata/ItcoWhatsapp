import os
import io
import logging
import pandas as pd
import requests
import time
from datetime import datetime, timezone
import utils.azure_clients as azure_clients
import utils.utils as utils

# Conexión a Whatsapp
whatsapp_token = "Bearer EAATVIxJamLkBO8zxnPulQAzX6y5M3vHpLSDkeSWNtex3IDDyFrlWrIjj2WjNjSmdsJG5VBXPmHKGXT1DbQYaZAesb2IrDGNWKmTZBjTBv05jcDbqxlaxTQ0ZButKVe65Gf3thHHNsHd95anbdM0UA3HgfaxyoBPy0RF0rgoacPBFW0UB4nAzKvtfhhyCYQAwgZDZD"
# whatsapp_token = os.environ.get("whatsapp_token", "")

# Definir tiempo máximo de conversación activa (24 horas)
time_hours = int(os.environ.get("time_hours", 24))


# def read_announcements():  
#     """Descarga el mensaje para los comunicados desde un archivo de Excel ubicado en Storage Account."""
#     try: 
#         # blob_name = f"comunicados/textoComunicados.xlsx"
        
#         # # Obtener una referencia al contenedor
#         # container_client = blob_service_client.get_container_client(container_name_baseCon)        
        
#         # # Descargar el contenido del archivo
#         # blob_client = container_client.get_blob_client(blob_name)
#         # blob_data = blob_client.download_blob()
        
#         # Obtener una referencia al contenedor
#         blob_container = get_blob_container("storage_container_basecono")
#         blob_client = blob_container.get_blob_client("comunicados/textoComunicados.xlsx")
        
#         # Descargar el contenido del archivo        
#         blob_data = blob_client.download_blob()
        
#         # Cargar el contenido del blob en un DataFrame de pandas
#         excel_bytes = io.BytesIO(blob_data.readall())
#         df = pd.read_excel(excel_bytes)        
        
#         # Filtrar filas donde ENVIAR sea igual a S
#         df_activo = df[df['ENVIAR'].astype(str).str.upper() == 'S']

#         if not df_activo.empty:
#             # Tomar el primer valor del campo TEXTO activo
#             message = df_activo.iloc[0]['TEXTO']
#             img = df_activo.iloc[0]['IMAGEN']
#             return message, img
#         else:
#             return "No hay mensajes activos", None
#     except Exception as e:
#         logging.error(f"ERROR - getting greetings: {e}")
#         raise


def get_active_phone_numbers():  
    """Obtiene una lista de números de teléfono de contactos activos desde un archivo de Excel en Azure Blob Storage."""
    try: 
        # blob_name = f"comunicados/contactos.xlsx"

        # # Obtener referencia al contenedor
        # container_client = blob_service_client.get_container_client(container_name_baseCon)
        
        # # Descargar el contenido del archivo      
        # blob_client = container_client.get_blob_client(blob_name)
        # blob_data = blob_client.download_blob()
        
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
                # conversation_id = conversation["id"]
                conversation_history = conversation["messages"]
                # createdAt = datetime.fromisoformat(conversation["createdAt"])
                # updatedAt = now
                
                # if utils.already_processed(conversation_history, message_id):
                #     logging.info(f"Mensaje con ID {message_id} ya fue procesado.")
                #     return None
                
                if utils.should_close_conversation(conversation, now, time_hours):
                    logging.info("Conversación cerrada o expirada. Se crea una nueva.")
                    conversation["sessionStatus"] = "closed"
                    utils.save_conversation(container, conversation)    
            
            conversation = utils.initialize_conversation(now, contact, "user_name")
            
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
            
            # Cálculo de precio
            # pricing_info = utils.process_webhook_pricing(value)        
            # price = utils.calculate_pricing(user_id, pricing_info["category"])

            logging.info(f"Enviando mensaje a: {contact}")
            response = requests.post(url, headers=headers, json=data)
            logging.info(F"response:{response.content}")
            content = f"{texto} - imagen: {img}"
            content_response = response.json()
            message_id = content_response.get("messages", [{}])[0].get("id", "sin_id")
            utils.add_message(conversation_history, "assistant", content, message_id, now, "campaña", "No Aplica", "No Aplica")
            
            utils.save_conversation(container, {
                "id": conversation["id"],
                "userId": conversation["userId"],
                "userName": conversation["userName"],
                "createdAt": now.isoformat(),
                "updatedAt": now.isoformat(),
                "messages": conversation_history,
                "sessionStatus": conversation["sessionStatus"]
                # "sessionStatus": conversation["sessionStatus"],
                # "whatsappBill": pricing_info["billable"],
                # "whatsappCategory": pricing_info["category"],
                # "whatsappPricingModel": pricing_info["pricing_model"],
                # "whatsappCostUSD": price
            })
            time.sleep(1) 
            response.raise_for_status()
    except Exception as e:
        logging.error(f'ERROR - sending whatsapp message{response.text}: {e}')

# def send_whatsapp_message(contacts, message):
#     """Envía un mensaje de WhatsApp a varios contactos usando la API de Meta."""
#     try:        
#         headers = {
#             "Authorization": whatsapp_token,
#             "Content-Type": "application/json",
#         }  
#         contacts = list(set(contacts))  # Elimina duplicados

#         logging.info(f"contacts:{contacts}") 
        
#         phone_number_id="580789875119451"
        
#         url = f"https://graph.facebook.com/v22.0/580789875119451/messages"
#         for contact in contacts:
#             contact = contact.strip()  # Elimina espacios o saltos de línea
            
#             logging.info(f"contact:{type(contact)}")

#             if not contact:
#                 logging.info(f"no contact")
#                 continue  # Evita enviar si el contacto está vacío

#             data = { 
#                 "messaging_product": "whatsapp", 
#                 "to": contact, 
#                 "type": "template", 
#                 "template": 
#                 {
#                     "name": "saludocampana", 
#                     "language": 
#                     { 
#                         "code": "es_CO" 
#                     },
#                     "components": [
#                         {
#                             "type": "header",
#                             "parameters": [
#                                 {
#                                     "type": "image",
#                                     "image": {
#                                         "link": "https://itcodlsprumaxicomu001.blob.core.windows.net/base-conocimiento/comunicados/piezas/imgprueba.png?sp=r&st=2025-05-26T16:39:02Z&se=2025-05-27T00:39:02Z&skoid=95333e26-b965-467b-8e42-5718af4df2b5&sktid=c980e410-0b5c-48bc-bd1a-8b91cabc84bc&skt=2025-05-26T16:39:02Z&ske=2025-05-27T00:39:02Z&sks=b&skv=2024-11-04&spr=https&sv=2024-11-04&sr=b&sig=BuJOYHDbp4hv533ZvK6AMYlwgLSf8UfBGHYd0ydGvDg%3D"
#                                     }
#                                 }
#                             ]
#                         },
#                         {
#                             "type": "body",
#                             "parameters": [
#                                 {
#                                     "type": "text",
#                                     "parameter_name": "nombre",
#                                     "text": "Carlos"
#                                 }
#                             ]
#                         }
#                     ]
#                 } 
#             }
            

#             try:
#                 logging.info(f"Enviando mensaje a: {contact}")
#                 response = requests.post(url, headers=headers, json=data)
#                 logging.info(f"response: {response.status_code} - {response.text}")
#                 response.raise_for_status()
#                 wait_seconds = random.randint(30, 90)
#                 logging.warning(f"Rate limit hit, reintentando en {wait_seconds} segundos...")
#                 time.sleep(wait_seconds)

#             except requests.exceptions.HTTPError as http_err:
#                 logging.error(f"HTTP error occurred: {http_err.response.status_code} - {http_err.response.text}")
#             except Exception as e:
#                 logging.error(f"General error: {str(e)}")
#     except Exception as e:
#         print(f'ERROR - sending whatsapp message{response.text}: {e}')